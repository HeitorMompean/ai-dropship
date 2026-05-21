"""Telegram notification service — AI-powered business assistant."""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    """Send notifications via Telegram Bot API with rich formatting."""

    def __init__(self) -> None:
        self._token: Optional[str] = getattr(settings, "telegram_bot_token", None)
        self._chat_id: Optional[str] = getattr(settings, "telegram_chat_id", None)
        self._base_url: Optional[str] = (
            f"https://api.telegram.org/bot{self._token}" if self._token else None
        )

    def _bar(self, score: int, max_val: int = 10) -> str:
        """Create a visual progress bar."""
        filled = min(score, max_val)
        empty = max_val - filled
        return "█" * filled + "░" * empty

    async def send_message(
        self,
        message: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a text message to the configured chat."""
        if not self._token or not self._chat_id:
            logger.warning("Telegram not configured - skipping notification")
            return {"status": "skipped", "reason": "not_configured"}

        url = f"{self._base_url}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": message[:4096],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if data.get("ok"):
                    logger.info(
                        "Telegram message sent, msg_id=%s",
                        data["result"]["message_id"],
                    )
                    return {"status": "ok", "message_id": data["result"]["message_id"]}
                logger.error("Telegram API error: %s", data.get("description"))
                return {"status": "error", "details": data}
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            return {"status": "error", "details": str(e)}

    async def send_approval_request(
        self,
        decision_id: int,
        agent_name: str,
        decision_type: str,
        sms_text: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send a rich product approval request with inline keyboard."""
        title = context.get("product_title", "Unknown Product")
        price = float(context.get("price", 0))
        cost = float(context.get("cost", 0))
        margin_pct = context.get("margin", "N/A")
        supplier = context.get("supplier", "N/A")
        category = context.get("category", "General")
        scores = context.get("scores", {})
        total_score = context.get("total_score", 0)

        profit = price - cost
        daily_10 = profit * 10
        monthly_10 = daily_10 * 30

        score_lines = ""
        if scores:
            for label, value in scores.items():
                bar = self._bar(int(value))
                score_lines += f"\n  {label}: {bar} {value}/10"

        message = (
            f"<b>⚡ NEW PRODUCT — AI ANALYSIS</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"📦 <b>{title}</b>\n"
            f"💰 Sell: <b>${price:.2f}</b> | Cost: <b>${cost:.2f}</b> | Margin: <b>{margin_pct}</b>\n"
            f"🌍 Supplier: {supplier} | 📂 {category}\n\n"
            f"<b>💵 PROFIT FORECAST</b>\n"
            f"  Per unit: <b>${profit:.2f}</b>\n"
            f"  10/day × 30 days = <b>${monthly_10:,.2f}/month</b>\n\n"
            f"<b>📊 PRODUCT SCORES</b>{score_lines}\n"
            f"\n  🏆 <b>TOTAL: {total_score}/130</b>\n\n"
            f"📋 <i>{sms_text}</i>\n\n"
            f"<i>💡 Tip: Reply with text or tap a button below.</i>"
        )

        # Rich inline keyboard
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ APPROVE", "callback_data": f"decision:{decision_id}:approve"},
                    {"text": "❌ REJECT", "callback_data": f"decision:{decision_id}:reject"},
                ],
                [
                    {"text": "💰 Negotiate Cost", "callback_data": f"decision:{decision_id}:negotiate"},
                    {"text": "🔍 Alternatives", "callback_data": f"decision:{decision_id}:alternatives"},
                ],
                [
                    {"text": "📊 Deep Analysis", "callback_data": f"decision:{decision_id}:analysis"},
                    {"text": "⚠️ Risk Check", "callback_data": f"decision:{decision_id}:risk"},
                ],
                [
                    {"text": "🤔 Ask AI a Question", "callback_data": f"decision:{decision_id}:chat"},
                ],
            ]
        }

        return await self.send_message(message, reply_markup=keyboard)

    async def send_ai_response(
        self,
        response_text: str,
        decision_id: int,
        show_actions: bool = True,
    ) -> Dict[str, Any]:
        """Send an AI response with follow-up action buttons."""
        keyboard = None
        if show_actions:
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Approve", "callback_data": f"decision:{decision_id}:approve"},
                        {"text": "❌ Reject", "callback_data": f"decision:{decision_id}:reject"},
                    ],
                    [
                        {"text": "💬 Continue Chat", "callback_data": f"decision:{decision_id}:chat"},
                        {"text": "📊 View Scores", "callback_data": f"decision:{decision_id}:scores"},
                    ],
                ]
            }

        return await self.send_message(response_text, reply_markup=keyboard)

    async def send_order_notification(
        self,
        order_id: str,
        customer: str,
        items: List[Dict[str, Any]],
        total: float,
        status: str = "new",
    ) -> Dict[str, Any]:
        """Send order notification."""
        emoji = "🛒" if status == "new" else "✅"
        message = f"<b>{emoji} ORDER {status.upper()}</b>\n\n"
        message += f"<b>Order:</b> #{order_id}\n"
        message += f"<b>Customer:</b> {customer}\n"
        message += f"<b>Total:</b> ${total:.2f}\n\n"
        message += "<b>Items:</b>\n"
        for item in items:
            message += f"  • {item['name']} x{item.get('qty', 1)}\n"

        if status == "new":
            message += "\n<i>Payment confirmed. Ready for fulfillment.</i>"

        return await self.send_message(message)

    async def send_daily_summary(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Send daily business summary."""
        message = (
            f"<b>📊 DAILY BUSINESS SUMMARY</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"📈 <b>Sales</b>\n"
            f"  Orders: {stats.get('orders', 0)}\n"
            f"  Revenue: ${stats.get('revenue', 0):.2f}\n"
            f"  Profit: ${stats.get('profit', 0):.2f}\n\n"
            f"📦 <b>Products</b>\n"
            f"  Active: {stats.get('active_products', 0)}\n"
            f"  Pending: {stats.get('pending_decisions', 0)}\n\n"
            f"🤖 <b>Agent Status</b>\n"
            f"  Researcher: {stats.get('researcher_status', 'idle')}\n"
            f"  Storekeeper: {stats.get('storekeeper_status', 'idle')}\n"
            f"  Fulfillment: {stats.get('fulfillment_status', 'idle')}\n\n"
            f"💡 <b>AI Insight</b>\n"
            f"<i>{stats.get('ai_insight', 'No insights today.')}</i>"
        )
        return await self.send_message(message)


# Singleton instance
telegram_service = TelegramService()