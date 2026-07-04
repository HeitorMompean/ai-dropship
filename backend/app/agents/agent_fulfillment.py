"""Order Fulfillment Manager agent implementation."""

import json
import logging
from typing import Any, Dict, List, Optional

from crewai import Agent

from app.agents.crew_setup import create_agent, wrap_async_tool
from app.agents.tools import (
    create_get_shopify_orders_tool,
    create_forward_to_supplier_tool,
    create_update_tracking_tool,
    create_request_human_decision_tool,
)
from app.agents.memory import conversation_memory
from app.services.shopify_client import shopify_client

logger = logging.getLogger(__name__)


class AgentFulfillment:
    """Process orders from receipt to delivery with zero errors.

    For high-value (> $200) or suspicious orders, requests human approval.
    """

    HIGH_VALUE_THRESHOLD = 200.0
    FRAUD_SCORE_THRESHOLD = 0.6

    def __init__(self) -> None:
        self.agent = self._build_agent()

    def _build_tools(self) -> List[Any]:
        tools = [
            create_get_shopify_orders_tool(),
            create_forward_to_supplier_tool(),
            create_update_tracking_tool(),
            create_request_human_decision_tool(),
        ]
        for t in tools:
            if hasattr(t["func"], "__call__"):
                t["func"] = wrap_async_tool(t["func"])
        return tools

    def _build_agent(self) -> Agent:
        return create_agent(
            role="Order Fulfillment Manager",
            goal=(
                "Process orders from receipt to delivery with zero errors. "
                "For high-value or suspicious orders, request human approval before fulfilling."
            ),
            backstory=(
                "You are a meticulous fulfillment specialist with deep experience in dropshipping logistics. "
                "You verify order details, detect fraud patterns, and coordinate with suppliers for seamless delivery. "
                "You never fulfill an order that looks risky without owner confirmation."
            ),
            tools=self._build_tools(),
            allow_delegation=False,
            verbose=True,
        )

    async def check_pending_orders(self) -> Dict[str, Any]:
        """Fetch pending Shopify orders, evaluate them, and either fulfill or request approval."""
        logger.info("[AgentFulfillment] Checking pending orders...")
        conversation_memory.update_agent_state("fulfillment", {"state": "running", "action": "check_pending_orders"})

        orders = await shopify_client.get_orders(status="any", limit=50)
        processed = []

        for order in orders:
            total = float(order.get("total_price", "0"))
            fraud_score = self._calculate_fraud_score(order)
            needs_approval = total > self.HIGH_VALUE_THRESHOLD or fraud_score > self.FRAUD_SCORE_THRESHOLD

            record = {
                "shopify_order_id": str(order.get("id")),
                "name": order.get("name"),
                "total": total,
                "fraud_score": fraud_score,
                "customer": order.get("customer", {}),
            }

            if needs_approval:
                context = {
                    "agent_name": "fulfillment",
                    "decision_type": "approve_fulfillment",
                    "order": record,
                }
                sms_text = (
                    f"ORDER ALERT: {order.get('name')} ${total:.2f}. "
                    f"Risk score {fraud_score:.1f}/1.0. "
                    f"Reply 'YES' to fulfill, 'NO' to cancel/review."
                )
                tool = create_request_human_decision_tool()
                await tool["func"](json.dumps(context), sms_text)
                record["action"] = "waiting_approval"
            else:
                # HONEST STATUS: this agent does NOT fulfill orders. Real
                # fulfillment happens via the orders/create webhook (Telegram
                # card -> DSers/manual, or CJ auto-order). The old code marked
                # orders "auto_fulfilled" while shipping nothing — with a real
                # store that means angry customers and chargebacks. Removed.
                already_fulfilled = (order.get("fulfillment_status") or "") == "fulfilled"
                record["action"] = "fulfilled" if already_fulfilled else "pending_fulfillment"
                if not already_fulfilled:
                    logger.info(
                        "[AgentFulfillment] Order %s ($%s) awaiting fulfillment "
                        "(handled via webhook -> DSers/CJ)", order.get("name"), total
                    )

            processed.append(record)

        conversation_memory.update_agent_state("fulfillment", {"state": "idle", "orders_checked": len(processed)})
        logger.info("[AgentFulfillment] Checked %s orders.", len(processed))
        return {"orders": processed, "waiting_approval": [o for o in processed if o["action"] == "waiting_approval"]}

    def _calculate_fraud_score(self, order: Dict[str, Any]) -> float:
        """Calculate a simple heuristic fraud score (0.0 - 1.0)."""
        score = 0.0
        total = float(order.get("total_price", "0"))
        if total > 300:
            score += 0.3
        if total > 500:
            score += 0.2
        customer = order.get("customer", {})
        if not customer.get("orders_count"):
            score += 0.2
        shipping = order.get("shipping_address", {})
        if shipping.get("country") and shipping["country"].upper() not in ("US", "CA", "GB", "AU"):
            score += 0.15
        if not shipping.get("phone"):
            score += 0.1
        return min(score, 1.0)

    async def run(self) -> Dict[str, Any]:
        """Default run delegates to check_pending_orders."""
        return await self.check_pending_orders()
