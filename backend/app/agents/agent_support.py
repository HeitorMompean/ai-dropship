"""Customer Service Representative agent implementation."""

import json
import logging
from typing import Any, Dict, List, Optional

from crewai import Agent

from app.agents.crew_setup import create_agent, wrap_async_tool
from app.agents.tools import (
    create_get_customer_history_tool,
    create_send_shopify_email_tool,
    create_process_refund_tool,
    create_request_human_decision_tool,
)
from app.agents.memory import conversation_memory

logger = logging.getLogger(__name__)


class AgentSupport:
    """Resolve customer inquiries and maintain satisfaction.

    For refunds > $50 or repeat complainers, request human approval.
    """

    REFUND_THRESHOLD = 50.0
    COMPLAINT_THRESHOLD = 2

    def __init__(self) -> None:
        self.agent = self._build_agent()

    def _build_tools(self) -> List[Any]:
        tools = [
            create_get_customer_history_tool(),
            create_send_shopify_email_tool(),
            create_process_refund_tool(),
            create_request_human_decision_tool(),
        ]
        for t in tools:
            if hasattr(t["func"], "__call__"):
                t["func"] = wrap_async_tool(t["func"])
        return tools

    def _build_agent(self) -> Agent:
        return create_agent(
            role="Customer Service Representative",
            goal=(
                "Resolve customer inquiries and maintain satisfaction. "
                "For refunds over $50 or repeat complainers, request human approval."
            ),
            backstory=(
                "You are a compassionate and efficient customer support agent. You have access to order history, "
                "refund tools, and email. You prioritize customer happiness while protecting the store's profitability. "
                "You escalate high-stakes refund requests to the owner."
            ),
            tools=self._build_tools(),
            allow_delegation=False,
            verbose=True,
        )

    async def scan_reviews(self) -> Dict[str, Any]:
        """Mock scan of reviews/complaints.

        In a real implementation, this would pull from Shopify reviews, Zendesk, or email.
        """
        logger.info("[AgentSupport] Scanning reviews...")
        conversation_memory.update_agent_state("support", {"state": "running", "action": "scan_reviews"})
        # Mock data
        complaints = [
            {"customer_id": "c101", "email": "angry@example.com", "issue": "wrong_item", "refund_amount": 29.99, "complaint_count": 1},
            {"customer_id": "c102", "email": "repeat@example.com", "issue": "late_delivery", "refund_amount": 65.00, "complaint_count": 3},
        ]
        escalated = []
        for c in complaints:
            if c["refund_amount"] > self.REFUND_THRESHOLD or c["complaint_count"] > self.COMPLAINT_THRESHOLD:
                context = {
                    "agent_name": "support",
                    "decision_type": "approve_refund",
                    "complaint": c,
                }
                sms_text = (
                    f"REFUND REQUEST: {c['email']} ${c['refund_amount']:.2f} "
                    f"(complaints: {c['complaint_count']}). "
                    f"Reply 'YES' to approve refund, 'NO' to deny, 'PARTIAL X' for partial."
                )
                tool = create_request_human_decision_tool()
                await tool["func"](json.dumps(context), sms_text)
                c["action"] = "waiting_approval"
                escalated.append(c)
            else:
                c["action"] = "auto_resolved"

        conversation_memory.update_agent_state("support", {"state": "idle", "complaints": len(complaints)})
        return {"complaints": complaints, "escalated": escalated}

    async def run(self) -> Dict[str, Any]:
        """Default run delegates to scan_reviews."""
        return await self.scan_reviews()
