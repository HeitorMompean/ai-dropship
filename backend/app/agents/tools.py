"""Shared tools for all AI agents (scrape, Shopify API, SMS, etc.)."""

import logging
from typing import Any, Dict, List, Optional, Callable
import asyncio

from app.services.shopify_client import shopify_client
from app.services.scraper import scraper
from app.services.sms_service import sms_service
from app.services.price_monitor import price_monitor
from app.services.analytics_engine import analytics_engine

logger = logging.getLogger(__name__)


def create_scrape_trending_products_tool() -> Dict[str, Any]:
    """Factory for the scrape_trending_products tool definition.

    Returns a dict compatible with CrewAI tool registration.
    """
    async def _run(limit: int = 10) -> str:
        products = await scraper.scrape_trending_products(limit=limit)
        return str(products)

    return {
        "name": "scrape_trending_products",
        "description": "Scrape the web for trending dropshipping product ideas. Returns a list of product dicts with title, description, cost_price, suggested_sell_price, and scores.",
        "func": _run,
    }


def create_analyze_google_trends_tool() -> Dict[str, Any]:
    """Factory for the analyze_google_trends tool."""
    async def _run(keyword: str) -> str:
        data = await scraper.analyze_google_trends(keyword)
        return str(data)

    return {
        "name": "analyze_google_trends",
        "description": "Check Google Trends for a keyword. Returns interest_score, trend_direction, and forecast.",
        "func": _run,
    }


def create_check_facebook_ads_tool() -> Dict[str, Any]:
    """Factory for the check_facebook_ads tool."""
    async def _run(keyword: str) -> str:
        data = await scraper.check_facebook_ads(keyword)
        return str(data)

    return {
        "name": "check_facebook_ads",
        "description": "Check Facebook Ad Library for a keyword. Returns active_ad_count, saturation level, and avg engagement.",
        "func": _run,
    }


def create_create_shopify_product_tool() -> Dict[str, Any]:
    """Factory for the create_shopify_product tool."""
    async def _run(payload_json: str) -> str:
        import json
        payload = json.loads(payload_json)
        result = await shopify_client.create_product(payload)
        return str(result)

    return {
        "name": "create_shopify_product",
        "description": "Create a product on Shopify. Input is a JSON string with Shopify product fields.",
        "func": _run,
    }


def create_update_shopify_product_tool() -> Dict[str, Any]:
    """Factory for the update_shopify_product tool."""
    async def _run(product_id: str, payload_json: str) -> str:
        import json
        payload = json.loads(payload_json)
        result = await shopify_client.update_product(int(product_id), payload)
        return str(result)

    return {
        "name": "update_shopify_product",
        "description": "Update a Shopify product. Input: product_id (string) and JSON payload.",
        "func": _run,
    }


def create_get_shopify_orders_tool() -> Dict[str, Any]:
    """Factory for the get_shopify_orders tool."""
    async def _run(status: str = "any", limit: int = 50) -> str:
        orders = await shopify_client.get_orders(status=status, limit=limit)
        return str(orders)

    return {
        "name": "get_shopify_orders",
        "description": "Fetch Shopify orders. Optional status filter and limit.",
        "func": _run,
    }


def create_forward_to_supplier_tool() -> Dict[str, Any]:
    """Factory for the forward_to_supplier tool (mock in MVP)."""
    async def _run(order_json: str, supplier_url: str) -> str:
        import json
        order = json.loads(order_json)
        logger.info("[MOCK] Forwarded order %s to supplier %s", order.get("id"), supplier_url)
        return f"Order forwarded to {supplier_url}: {order.get('id')}"

    return {
        "name": "forward_to_supplier",
        "description": "Forward an order to the supplier for fulfillment. Input: order JSON and supplier URL.",
        "func": _run,
    }


def create_update_tracking_tool() -> Dict[str, Any]:
    """Factory for the update_tracking tool."""
    async def _run(order_id: str, tracking_number: str, carrier: str = "UPS") -> str:
        logger.info("[MOCK] Updated tracking for order %s: %s (%s)", order_id, tracking_number, carrier)
        return f"Tracking updated for order {order_id}: {tracking_number} ({carrier})"

    return {
        "name": "update_tracking",
        "description": "Update tracking information for an order.",
        "func": _run,
    }


def create_get_customer_history_tool() -> Dict[str, Any]:
    """Factory for the get_customer_history tool."""
    async def _run(customer_id: str) -> str:
        orders = await shopify_client.get_customer_orders(int(customer_id), limit=50)
        return str(orders)

    return {
        "name": "get_customer_history",
        "description": "Fetch order history for a customer by Shopify customer ID.",
        "func": _run,
    }


def create_send_shopify_email_tool() -> Dict[str, Any]:
    """Factory for the send_shopify_email tool."""
    async def _run(to_email: str, subject: str, body: str) -> str:
        ok = await shopify_client.send_email(to_email, subject, body)
        return "Email sent" if ok else "Email failed"

    return {
        "name": "send_shopify_email",
        "description": "Send an email to a customer.",
        "func": _run,
    }


def create_process_refund_tool() -> Dict[str, Any]:
    """Factory for the process_refund tool."""
    async def _run(order_id: str, amount: float, reason: str = "Customer request") -> str:
        import json
        payload = {"refund_line_items": [], "transactions": [{"kind": "refund", "amount": amount}]}
        result = await shopify_client.create_refund(int(order_id), payload)
        logger.info("Refund processed for order %s: $%s (%s)", order_id, amount, reason)
        return str(result)

    return {
        "name": "process_refund",
        "description": "Process a refund for a Shopify order. Input: order_id, amount, reason.",
        "func": _run,
    }


def create_get_daily_metrics_tool() -> Dict[str, Any]:
    """Factory for the get_daily_metrics tool."""
    async def _run() -> str:
        data = analytics_engine.get_daily_metrics_mock()
        return str(data)

    return {
        "name": "get_daily_metrics",
        "description": "Get daily store metrics: visitors, orders, revenue, profit, conversion rate.",
        "func": _run,
    }


def create_calculate_true_profit_tool() -> Dict[str, Any]:
    """Factory for the calculate_true_profit tool."""
    async def _run(revenue: float, cost_price: float, shipping: float = 5.0, ad_spend: float = 0.0) -> str:
        result = analytics_engine.calculate_order_profit(revenue, cost_price, shipping, ad_spend)
        return str(result)

    return {
        "name": "calculate_true_profit",
        "description": "Calculate true net profit for an order. Input: revenue, cost_price, shipping, ad_spend.",
        "func": _run,
    }


def create_get_ad_performance_tool() -> Dict[str, Any]:
    """Factory for the get_ad_performance tool."""
    async def _run(days: int = 7) -> str:
        data = analytics_engine.get_ad_performance_mock(days=days)
        return str(data)

    return {
        "name": "get_ad_performance",
        "description": "Get ad performance for the last N days. Returns spend, impressions, clicks, conversions, ROAS.",
        "func": _run,
    }


def create_request_human_decision_tool() -> Dict[str, Any]:
    """Factory for the request_human_decision tool.

    This is the critical gateway tool that all agents use to pause and ask the owner.
    """
    from app.agents.memory import conversation_memory
    from app.services.sms_service import sms_service
    from datetime import datetime, timedelta
    import json

    async def _run(context_json: str, sms_text: str) -> str:
        """Send a human decision request.

        Args:
            context_json: JSON string with all decision context.
            sms_text: Concise SMS text to send to the owner.
        """
        try:
            context = json.loads(context_json)
        except Exception:
            context = {"raw": context_json}

        agent_name = context.get("agent_name", "unknown")
        decision_type = context.get("decision_type", "unknown")

        # Log to memory
        conversation_memory.add_decision_context(
            agent_name=agent_name,
            decision_type=decision_type,
            context=context,
            sms_text=sms_text,
        )

        # Send SMS
        result = await sms_service.send_to_owner(sms_text)

        logger.info(
            "Human decision requested by %s (%s): %s",
            agent_name,
            decision_type,
            sms_text,
        )
        return f"Decision request sent. SMS result: {result}"

    return {
        "name": "request_human_decision",
        "description": "Request a human decision from the store owner. Input: context_json (string) and sms_text (string). This pauses the agent workflow until the owner replies.",
        "func": _run,
    }
