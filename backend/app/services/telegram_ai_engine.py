"""AI-powered conversation engine for the Telegram decision assistant.

Migrated from Ollama (localhost — unreachable on Railway) to Groq's cloud API
(OpenAI-compatible, free tier ~14,400 req/day). Set GROQ_API_KEY in the
environment; optionally GROQ_MODEL to override the default.

IMPORTANT: process_message() now matches how telegram_webhook.py actually calls
it — process_message(message, chat_id=...) — instead of the old
(decision_id, user_message, product_context) signature, which raised
TypeError on every call and made the webhook silently fall back to templates.
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Light system prompt that works for BOTH free-text chat and the JSON ad-copy
# prompt the webhook sends. We don't force a rigid JSON schema here, because the
# ad-gen call supplies its own "respond with ONLY JSON" instruction.
SYSTEM_PROMPT = (
    "You are the AI Dropshipping Assistant for the store owner. "
    "Be concise, practical, and honest about margins, competition, and risk. "
    "If the user's message explicitly asks for a JSON object, reply with ONLY "
    "valid JSON and nothing else. Otherwise reply in short, clear plain text "
    "suitable for a Telegram message."
)


class TelegramAIEngine:
    """LLM-powered conversation engine for business decisions (Groq backend)."""

    def __init__(self) -> None:
        # Prefer an explicit env var; fall back to a settings field if present.
        self._api_key: str = os.getenv("GROQ_API_KEY", getattr(settings, "groq_api_key", "") or "")
        self._model: str = os.getenv("GROQ_MODEL", getattr(settings, "groq_model", "") or "llama-3.3-70b-versatile")
        self._conversations: Dict[str, List[Dict[str, str]]] = {}

    # ------------------------------------------------------------------ history
    def _get_history(self, key: str) -> List[Dict[str, str]]:
        return self._conversations.get(key, [])

    def _add_to_history(self, key: str, role: str, content: str) -> None:
        self._conversations.setdefault(key, []).append({"role": role, "content": content})
        # keep last 10 to bound context
        self._conversations[key] = self._conversations[key][-10:]

    # ------------------------------------------------------------------ main API
    async def process_message(
        self,
        message: str,
        chat_id: Optional[str] = None,
        product_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process a user/system message through Groq and return a structured dict.

        Returns {"message": <text>, "action": "respond", "confidence": float}.
        Callers (telegram_webhook) only read ["message"], so this stays compatible
        whether the model returns prose or JSON.
        """
        key = str(chat_id or "default")
        self._add_to_history(key, "user", message)

        if not self._api_key:
            return self._fallback_response(
                "⚠️ AI isn't configured yet. Set GROQ_API_KEY in the environment "
                "to enable AI replies (free key at console.groq.com)."
            )

        messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if product_context:
            ctx = json.dumps(product_context, default=str)[:2000]
            messages.append({"role": "system", "content": f"PRODUCT CONTEXT:\n{ctx}"})
        # history already ends with the current user message
        messages.extend(self._get_history(key)[-8:])

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 600,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if not content:
                return self._fallback_response("I didn't get a usable response from the AI. Try again?")

            self._add_to_history(key, "assistant", content)
            return {"message": content, "action": "respond", "confidence": 0.6, "reasoning": ""}

        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:300]
            except Exception:
                pass
            logger.error("Groq HTTP error: %s %s", e, body)
            # 401 = bad/missing key, 429 = rate limited, 400 = often a bad model name
            return self._fallback_response(
                f"AI service error ({e.response.status_code}). "
                "Check GROQ_API_KEY and GROQ_MODEL. Details logged."
            )
        except httpx.ConnectError:
            logger.error("Cannot reach Groq API")
            return self._fallback_response("I can't reach the AI service right now. Please try again shortly.")
        except Exception as e:
            logger.error("AI engine error: %s", e)
            return self._fallback_response(f"AI engine error: {str(e)[:200]}")

    def _fallback_response(self, message: str) -> Dict[str, Any]:
        return {
            "action": "respond",
            "message": message,
            "question_for_user": None,
            "confidence": 0.0,
            "reasoning": "Fallback (AI unavailable)",
        }

    # ----------------------------------------------------- rich initial message
    async def generate_initial_message(self, product_context: Dict[str, Any]) -> Dict[str, Any]:
        """Format the rich initial approval message (no LLM call — pure formatting)."""
        title = product_context.get("title", "Unknown Product")
        price = float(product_context.get("price", 0))
        cost = float(product_context.get("cost", 0))
        margin_pct = product_context.get("margin", "N/A")
        supplier = product_context.get("supplier", "N/A")
        category = product_context.get("category", "General")
        scores = product_context.get("scores", {})
        total_score = product_context.get("total_score", 0)

        profit = price - cost
        monthly_10 = profit * 10 * 30

        score_lines = ""
        if scores:
            for label, value in scores.items():
                filled = min(int(value), 10)
                bar = "█" * filled + "░" * (10 - filled)
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
            f"<i>I'm your AI assistant. You can:</i>\n"
            f"  • Approve this product\n"
            f"  • Ask me to negotiate cost\n"
            f"  • Request alternative suppliers\n"
            f"  • Ask me anything about this product"
        )
        return {
            "message": message,
            "action": "ask_question",
            "question_for_user": "What's your call on this product?",
            "confidence": 0.7,
        }


# Singleton instance
ai_engine = TelegramAIEngine()
