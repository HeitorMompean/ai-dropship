"""Shopify Store Manager agent implementation."""

import json
import logging
from typing import Any, Dict, List, Optional

from crewai import Agent

from app.agents.crew_setup import create_agent, wrap_async_tool
from app.agents.tools import (
    create_create_shopify_product_tool,
    create_update_shopify_product_tool,
    create_request_human_decision_tool,
)
from app.agents.memory import conversation_memory
from app.services.shopify_client import shopify_client

logger = logging.getLogger(__name__)


class AgentStorekeeper:
    """Create and optimize Shopify product listings for maximum conversion.

    Calls human approval when pricing or copy is uncertain.
    """

    def __init__(self) -> None:
        self.agent = self._build_agent()

    def _build_tools(self) -> List[Any]:
        tools = [
            create_create_shopify_product_tool(),
            create_update_shopify_product_tool(),
            create_request_human_decision_tool(),
        ]
        for t in tools:
            if hasattr(t["func"], "__call__"):
                t["func"] = wrap_async_tool(t["func"])
        return tools

    def _build_agent(self) -> Agent:
        return create_agent(
            role="Shopify Store Manager",
            goal=(
                "Create and optimize Shopify product listings for maximum conversion. "
                "Request human approval when pricing or listing copy is uncertain."
            ),
            backstory=(
                "You are a seasoned e-commerce merchandiser with a track record of building "
                "high-converting product pages. You understand persuasive copywriting, pricing psychology, "
                "and Shopify SEO. You always validate important pricing decisions with the store owner."
            ),
            tools=self._build_tools(),
            allow_delegation=False,
            verbose=True,
        )

    async def list_product(
        self,
        title: str,
        description: str,
        cost_price: float,
        sell_price: float,
        supplier_url: str,
        request_approval: bool = True,
    ) -> Dict[str, Any]:
        """Create a Shopify product listing.

        If request_approval is True, send SMS first and wait for human response.
        """
        logger.info("[AgentStorekeeper] Listing product: %s", title)
        conversation_memory.update_agent_state("storekeeper", {"state": "running", "action": "list_product", "product": title})

        if request_approval:
            context = {
                "agent_name": "storekeeper",
                "decision_type": "approve_listing",
                "product": {
                    "title": title,
                    "cost_price": cost_price,
                    "sell_price": sell_price,
                    "margin": round(sell_price - cost_price, 2),
                    "margin_pct": round(((sell_price - cost_price) / sell_price) * 100, 1) if sell_price else 0,
                },
            }
            margin_pct = round(((sell_price - cost_price) / sell_price) * 100, 1) if sell_price else 0
            sms_text = (
                f"LISTING REQUEST: {title[:30]}... "
                f"Cost ${cost_price:.2f} -> Sell ${sell_price:.2f} ({margin_pct}% margin). "
                f"Reply 'YES' to publish, 'NO' to reject, 'EDIT price X' to change price."
            )
            tool = create_request_human_decision_tool()
            await tool["func"](json.dumps(context), sms_text)
            conversation_memory.update_agent_state("storekeeper", {"state": "waiting_human"})
            return {"status": "waiting_approval", "product_title": title}

        # Direct publish (no approval)
        payload = {
            "title": title,
            "body_html": description,
            "product_type": "Dropship",
            "tags": "dropship,ai-curated",
            "variants": [
                {
                    "price": str(sell_price),
                    "sku": f"DS-{hash(title) % 100000:05d}",
                    "inventory_management": None,
                }
            ],
        }
        result = await shopify_client.create_product(payload)
        shopify_id = str(result.get("id", ""))
        conversation_memory.update_agent_state("storekeeper", {"state": "idle", "last_listing_id": shopify_id})
        logger.info("[AgentStorekeeper] Listed %s -> Shopify ID %s", title, shopify_id)
        return {"status": "published", "shopify_product_id": shopify_id, "title": title}

    async def update_listing(self, shopify_product_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing Shopify product."""
        result = await shopify_client.update_product(int(shopify_product_id), updates)
        return {"status": "updated", "shopify_product_id": shopify_product_id, "result": result}

    async def run(self) -> Dict[str, Any]:
        """Default run: check for products awaiting listing and process them."""
        conversation_memory.update_agent_state("storekeeper", {"state": "idle"})
        return {"status": "idle", "message": "Storekeeper is idle. Use list_product() to create listings."}
