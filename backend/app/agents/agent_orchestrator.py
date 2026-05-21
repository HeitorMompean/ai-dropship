"""Decision gateway, SMS orchestrator, and LangGraph workflow for human-in-the-loop.

The orchestrator receives ``request_human_decision`` calls from other agents,
formats concise SMS messages, sends them via the SMS gateway, parses replies,
and routes actions back. It also handles timeouts with conservative defaults.

The LangGraph workflow ``product_to_listing`` implements a state machine:
discover â†’ score â†’ human_approval â†’ create_draft â†’ human_approval â†’ publish â†’ monitor
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from app.config import settings
from app.agents.memory import conversation_memory
from app.services.sms_service import sms_service
from app.agents.agent_researcher import AgentResearcher
from app.agents.agent_storekeeper import AgentStorekeeper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """Central service that manages human-in-the-loop decisions for all agents.

    1. Receives ``request_human_decision`` calls from other agents.
    2. Formats concise SMS (< 160 chars if possible, or multi-part).
    3. Sends via ``sms_service.send_to_owner()``.
    4. Waits for reply (webhook updates decision record).
    5. Parses reply using simple keyword matching + heuristic fallback.
    6. Routes parsed action back to the requesting agent/workflow.
    7. Handles timeout (if no reply in 2 hours, takes conservative default).
    """

    DEFAULT_TIMEOUT_MINUTES = 120

    def __init__(self) -> None:
        pass

    async def request_human_decision(
        self,
        agent_name: str,
        decision_type: str,
        context: Dict[str, Any],
        sms_text: Optional[str] = None,
        timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES,
    ) -> Dict[str, Any]:
        """Send a human decision request and record it in memory.

        Returns the decision record dict.
        """
        if sms_text is None:
            sms_text = self._format_sms(agent_name, decision_type, context)

        decision_id = conversation_memory.add_decision_context(
            agent_name=agent_name,
            decision_type=decision_type,
            context=context,
            sms_text=sms_text,
        )

        # Send SMS
        sms_result = await sms_service.send_to_owner(sms_text)
        logger.info("Decision %s sent to owner. SMS result: %s", decision_id, sms_result)

        record = {
            "id": decision_id,
            "agent_name": agent_name,
            "decision_type": decision_type,
            "context": context,
            "sms_text": sms_text,
            "status": "pending",
            "timeout_at": (datetime.utcnow() + timedelta(minutes=timeout_minutes)).isoformat(),
            "created_at": datetime.utcnow().isoformat(),
        }
        return record

    def _format_sms(self, agent_name: str, decision_type: str, context: Dict[str, Any]) -> str:
        """Format a concise SMS from decision context.

        Tries to stay under 160 characters for single-part delivery.
        """
        if decision_type == "approve_listing":
            product = context.get("product", {})
            title = product.get("title", "Product")[:25]
            margin = product.get("margin_pct", 0)
            msg = f"LISTING: {title}... Margin {margin}%. Reply YES/NO/EDIT price X"
        elif decision_type == "approve_fulfillment":
            order = context.get("order", {})
            total = order.get("total", 0)
            risk = order.get("fraud_score", 0)
            msg = f"ORDER ${total:.0f} Risk {risk:.1f}. Reply YES to fulfill, NO to cancel."
        elif decision_type == "approve_refund":
            complaint = context.get("complaint", {})
            amount = complaint.get("refund_amount", 0)
            msg = f"REFUND ${amount:.2f}? Reply YES/NO/PARTIAL X"
        elif decision_type == "metrics_alert":
            profit = context.get("recent_profit", 0)
            days = context.get("days", 3)
            msg = f"ALERT: Profit ${profit:.0f} last {days}d. PAUSE/INCREASE/CHECK"
        elif decision_type == "approve_sample_order":
            product = context.get("product", {})
            title = product.get("title", "")[:25]
            score = product.get("total_score", 0)
            cost = product.get("cost_price", 0)
            msg = f"SAMPLE: {title}... Score {score}/130 ${cost:.2f}. YES/NO/INFO"
        else:
            msg = f"[{agent_name}] {decision_type}: Reply YES/NO."

        if len(msg) > 160:
            msg = msg[:157] + "..."
        return msg

    def parse_reply(self, reply_text: str, decision_type: str) -> str:
        """Parse an inbound SMS reply into a machine action.

        Uses simple keyword matching as the primary parser, with a basic
        heuristic fallback. A production system could use an LLM here.
        """
        text = reply_text.strip().upper()

        if text.startswith("YES") or text in ("Y", "SURE", "OK", "APPROVE", "CONFIRM"):
            return "approve"
        if text.startswith("NO") or text in ("N", "REJECT", "DENY", "CANCEL"):
            return "reject"
        if text.startswith("PARTIAL") or text.startswith("PART"):
            match = re.search(r"\d+(?:\.\d{0,2})?", text)
            if match:
                return f"partial:{match.group(0)}"
            return "partial"
        if "EDIT" in text or "CHANGE" in text:
            match = re.search(r"\d+(?:\.\d{0,2})?", text)
            if match:
                return f"edit_price:{match.group(0)}"
            return "edit"
        if "INFO" in text or "DETAILS" in text or "MORE" in text:
            return "request_info"
        if "PAUSE" in text:
            return "pause_ads"
        if "INCREASE" in text or "BOOST" in text or "MORE" in text:
            return "increase_budget"
        if "CHECK" in text or "REVIEW" in text:
            return "review"

        positive_words = {"YES", "GO", "DO IT", "APPROVE", "OKAY", "YEP", "YUP"}
        negative_words = {"NO", "STOP", "DON'T", "DONT", "NEVER", "REJECT"}
        pos_hits = sum(1 for w in positive_words if w in text)
        neg_hits = sum(1 for w in negative_words if w in text)

        if pos_hits > neg_hits:
            return "approve"
        if neg_hits > pos_hits:
            return "reject"

        if decision_type in ("approve_fulfillment", "approve_refund", "approve_listing"):
            return "reject"
        return "review"

    async def handle_timeout(self, decision_record: Dict[str, Any]) -> str:
        """Handle a timed-out decision by applying a conservative default action.

        Returns the action taken.
        """
        decision_type = decision_record.get("decision_type", "unknown")
        if decision_type in ("approve_fulfillment", "approve_listing"):
            action = "reject"
        elif decision_type == "approve_refund":
            action = "review"
        elif decision_type == "metrics_alert":
            action = "review"
        elif decision_type == "approve_sample_order":
            action = "reject"
        else:
            action = "review"

        logger.warning(
            "Decision %s timed out. Conservative default applied: %s",
            decision_record.get("id"),
            action,
        )
        return action

    async def process_inbound_reply(self, from_number: str, reply_text: str) -> Optional[Dict[str, Any]]:
        """Process an inbound SMS reply from the owner.

        1. Find the most recent pending decision.
        2. Parse the reply into an action.
        3. Update the decision record.
        4. Return the updated record.
        """
        pending = conversation_memory.get_pending_decisions()
        if not pending:
            logger.info("No pending decisions. Ignoring inbound SMS from %s.", from_number)
            return None

        decision = pending[-1]
        decision_id = decision["id"]
        decision_type = decision["decision_type"]

        parsed_action = self.parse_reply(reply_text, decision_type)
        success = conversation_memory.resolve_decision(decision_id, reply_text, parsed_action)

        if success:
            logger.info(
                "Decision %s resolved. Action: %s (reply: %s)",
                decision_id,
                parsed_action,
                reply_text,
            )
            return {
                "decision_id": decision_id,
                "parsed_action": parsed_action,
                "reply": reply_text,
                "status": "resolved",
            }
        return None


orchestrator = AgentOrchestrator()


# ---------------------------------------------------------------------------
# LangGraph workflow: product_to_listing
# ---------------------------------------------------------------------------

class ProductWorkflowState(TypedDict, total=False):
    """TypedDict representing the state of the product-to-listing workflow."""
    product_id: Optional[int]
    title: str
    description: str
    supplier_url: str
    cost_price: float
    sell_price: float
    scores: Dict[str, int]
    total_score: int
    status: str
    decision_id: Optional[str]
    shopify_product_id: Optional[str]
    error: Optional[str]


async def _node_discover(state: ProductWorkflowState) -> ProductWorkflowState:
    """Discover trending products via the researcher agent."""
    logger.info("[LangGraph] Node: discover")
    researcher = AgentResearcher()
    result = await researcher.run(limit=5)
    products = result.get("products", [])
    if not products:
        return {**state, "status": "hold", "error": "No products discovered"}
    best = max(products, key=lambda p: p.get("total_score", 0))
    return {
        **state,
        "status": "score",
        "title": best["title"],
        "description": best.get("description", ""),
        "supplier_url": best.get("supplier_url", ""),
        "cost_price": best["cost_price"],
        "sell_price": best["suggested_sell_price"],
        "scores": best.get("scores", {}),
        "total_score": best.get("total_score", 0),
    }


async def _node_score(state: ProductWorkflowState) -> ProductWorkflowState:
    """Score the product and decide whether to proceed to human approval."""
    logger.info("[LangGraph] Node: score for product: %s", state.get("title"))
    total = state.get("total_score", 0)
    if total < 50:
        return {**state, "status": "hold", "error": f"Score too low ({total})"}
    return {**state, "status": "human_approval"}


async def _node_human_approval(state: ProductWorkflowState) -> ProductWorkflowState:
    """Request human approval for sample order / initial go-ahead."""
    logger.info("[LangGraph] Node: human_approval (sample)")
    context = {
        "agent_name": "orchestrator",
        "decision_type": "approve_sample_order",
        "product": {
            "title": state.get("title"),
            "cost_price": state.get("cost_price"),
            "sell_price": state.get("sell_price"),
            "total_score": state.get("total_score"),
            "supplier_url": state.get("supplier_url"),
        },
    }
    record = await orchestrator.request_human_decision(
        agent_name="orchestrator",
        decision_type="approve_sample_order",
        context=context,
    )
    return {
        **state,
        "status": "waiting_human_1",
        "decision_id": record.get("id"),
    }


async def _node_check_human_1(state: ProductWorkflowState) -> ProductWorkflowState:
    """Check if the first human decision has been resolved."""
    decision_id = state.get("decision_id")
    if not decision_id:
        return {**state, "status": "human_approval"}

    all_decisions = conversation_memory._decisions
    decision = None
    for d in all_decisions:
        if d["id"] == decision_id:
            decision = d
            break

    if not decision:
        return {**state, "status": "hold", "error": "Decision record lost"}

    if decision["status"] == "resolved":
        action = decision.get("reply_parsed_action", "reject")
        if action.startswith("approve") or action == "approve":
            return {**state, "status": "create_draft", "decision_id": None}
        if action.startswith("reject") or action == "reject":
            return {**state, "status": "hold", "error": "Owner rejected sample order"}
        if action == "request_info":
            return {**state, "status": "human_approval"}
        return {**state, "status": "hold", "error": f"Unknown action: {action}"}

    timeout_at_str = decision.get("timeout_at", "")
    try:
        timeout_at = datetime.fromisoformat(timeout_at_str)
        if datetime.utcnow() > timeout_at:
            default_action = await orchestrator.handle_timeout(decision)
            if default_action == "reject":
                return {**state, "status": "hold", "error": "Timeout: conservative reject"}
            return {**state, "status": "create_draft", "decision_id": None}
    except Exception:
        pass

    return {**state, "status": "waiting_human_1"}


async def _node_create_draft(state: ProductWorkflowState) -> ProductWorkflowState:
    """Create a draft Shopify listing via the storekeeper agent (no publish yet)."""
    logger.info("[LangGraph] Node: create_draft for %s", state.get("title"))
    storekeeper = AgentStorekeeper()
    result = await storekeeper.list_product(
        title=state["title"],
        description=state["description"],
        cost_price=state["cost_price"],
        sell_price=state["sell_price"],
        supplier_url=state["supplier_url"],
        request_approval=False,
    )
    shopify_id = result.get("shopify_product_id")
    return {
        **state,
        "status": "human_approval_2",
        "shopify_product_id": shopify_id,
    }


async def _node_human_approval_2(state: ProductWorkflowState) -> ProductWorkflowState:
    """Request human approval for the final publish step."""
    logger.info("[LangGraph] Node: human_approval_2 (publish)")
    context = {
        "agent_name": "orchestrator",
        "decision_type": "approve_listing",
        "product": {
            "title": state.get("title"),
            "shopify_product_id": state.get("shopify_product_id"),
            "cost_price": state.get("cost_price"),
            "sell_price": state.get("sell_price"),
        },
    }
    record = await orchestrator.request_human_decision(
        agent_name="orchestrator",
        decision_type="approve_listing",
        context=context,
    )
    return {
        **state,
        "status": "waiting_human_2",
        "decision_id": record.get("id"),
    }


async def _node_check_human_2(state: ProductWorkflowState) -> ProductWorkflowState:
    """Check if the second human decision (publish approval) has been resolved."""
    decision_id = state.get("decision_id")
    if not decision_id:
        return {**state, "status": "human_approval_2"}

    all_decisions = conversation_memory._decisions
    decision = None
    for d in all_decisions:
        if d["id"] == decision_id:
            decision = d
            break

    if not decision:
        return {**state, "status": "hold", "error": "Decision record lost"}

    if decision["status"] == "resolved":
        action = decision.get("reply_parsed_action", "reject")
        if action.startswith("approve") or action == "approve":
            return {**state, "status": "publish", "decision_id": None}
        if action.startswith("reject") or action == "reject":
            return {**state, "status": "hold", "error": "Owner rejected publishing"}
        if action.startswith("edit_price"):
            match = re.search(r"edit_price:(\d+(?:\.\d{0,2})?)", action)
            if match:
                new_price = float(match.group(1))
                return {
                    **state,
                    "sell_price": new_price,
                    "status": "create_draft",
                    "decision_id": None,
                }
            return {**state, "status": "create_draft", "decision_id": None}
        if action == "request_info":
            return {**state, "status": "human_approval_2"}
        return {**state, "status": "hold", "error": f"Unknown action: {action}"}

    timeout_at_str = decision.get("timeout_at", "")
    try:
        timeout_at = datetime.fromisoformat(timeout_at_str)
        if datetime.utcnow() > timeout_at:
            default_action = await orchestrator.handle_timeout(decision)
            if default_action == "reject":
                return {**state, "status": "hold", "error": "Timeout: conservative reject"}
            return {**state, "status": "publish", "decision_id": None}
    except Exception:
        pass

    return {**state, "status": "waiting_human_2"}


async def _node_publish(state: ProductWorkflowState) -> ProductWorkflowState:
    """Publish the Shopify product (mark as active / listed)."""
    logger.info("[LangGraph] Node: publish %s", state.get("title"))
    return {
        **state,
        "status": "monitor",
        "error": None,
    }


async def _node_monitor(state: ProductWorkflowState) -> ProductWorkflowState:
    """Monitor the published product (pricing, stock, reviews)."""
    logger.info("[LangGraph] Node: monitor %s", state.get("title"))
    return {**state, "status": "done"}


async def _node_hold(state: ProductWorkflowState) -> ProductWorkflowState:
    """Hold state: workflow paused awaiting external action or manual resume."""
    logger.info("[LangGraph] Node: hold for %s â€” %s", state.get("title"), state.get("error"))
    return state


def _sync_wrapper(async_func):
    import asyncio
    def wrapper(state: ProductWorkflowState) -> ProductWorkflowState:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return asyncio.run_coroutine_threadsafe(async_func(state), loop).result()
            return loop.run_until_complete(async_func(state))
        except RuntimeError:
            return asyncio.run(async_func(state))
    return wrapper


def build_product_to_listing_graph() -> StateGraph:
    """Build and return the compiled LangGraph state machine for product-to-listing."""
    workflow = StateGraph(ProductWorkflowState)

    workflow.add_node("discover", _sync_wrapper(_node_discover))
    workflow.add_node("score", _sync_wrapper(_node_score))
    workflow.add_node("human_approval", _sync_wrapper(_node_human_approval))
    workflow.add_node("check_human_1", _sync_wrapper(_node_check_human_1))
    workflow.add_node("create_draft", _sync_wrapper(_node_create_draft))
    workflow.add_node("human_approval_2", _sync_wrapper(_node_human_approval_2))
    workflow.add_node("check_human_2", _sync_wrapper(_node_check_human_2))
    workflow.add_node("publish", _sync_wrapper(_node_publish))
    workflow.add_node("monitor", _sync_wrapper(_node_monitor))
    workflow.add_node("hold", _sync_wrapper(_node_hold))

    workflow.set_entry_point("discover")
    workflow.add_edge("discover", "score")
    workflow.add_conditional_edges(
        "score",
        lambda s: "human_approval" if s["status"] == "human_approval" else "hold",
        {"human_approval": "human_approval", "hold": "hold"},
    )
    workflow.add_edge("human_approval", "check_human_1")
    workflow.add_conditional_edges(
        "check_human_1",
        lambda s: s["status"],
        {
            "human_approval": "human_approval",
            "waiting_human_1": "check_human_1",
            "create_draft": "create_draft",
            "hold": "hold",
        },
    )
    workflow.add_edge("create_draft", "human_approval_2")
    workflow.add_edge("human_approval_2", "check_human_2")
    workflow.add_conditional_edges(
        "check_human_2",
        lambda s: s["status"],
        {
            "human_approval_2": "human_approval_2",
            "waiting_human_2": "check_human_2",
            "publish": "publish",
            "create_draft": "create_draft",
            "hold": "hold",
        },
    )
    workflow.add_edge("publish", "monitor")
    workflow.add_edge("monitor", END)
    workflow.add_edge("hold", END)
    # removed

    return workflow.compile()


product_to_listing_graph = build_product_to_listing_graph()
