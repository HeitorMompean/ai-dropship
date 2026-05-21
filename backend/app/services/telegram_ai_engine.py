"""AI-powered conversation engine for Telegram decision assistant.

This module connects to Ollama to provide intelligent, context-aware
conversations for product approvals, negotiations, and business decisions.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the AI Dropshipping Assistant — a strategic business advisor to the store owner (Heitor). Your role is to help make smart product decisions by analyzing data, asking clarifying questions, and providing recommendations.

PERSONALITY:
- Professional but conversational
- Think like an experienced dropshipping consultant
- Always consider profit margins, competition, and market trends
- Ask questions when information is missing
- Be honest about risks

RULES:
1. When the user asks a question, answer thoughtfully using the product data
2. When uncertain, ALWAYS ask a clarifying question first
3. After 1-2 back-and-forth exchanges, provide a clear recommendation
4. Track the conversation context to avoid repeating yourself
5. If user says "just do it" / "go ahead" / "approved" → finalize as approved
6. If user says "pass" / "skip" / "reject" → finalize as rejected
7. If user wants to negotiate, suggest concrete strategies
8. Format responses with clear sections using bullets and bold text

RESPONSE FORMAT:
Always respond in this JSON format:
{
  "action": "respond" | "ask_question" | "approve" | "reject" | "negotiate" | "needs_clarification",
  "message": "Your natural language response to the user",
  "question_for_user": "If action is 'ask_question', the specific question to ask",
  "confidence": 0.0-1.0,
  "reasoning": "Brief internal reasoning for your decision"
}"""


class TelegramAIEngine:
    """LLM-powered conversation engine for business decisions."""

    def __init__(self) -> None:
        self._ollama_url = getattr(settings, "ollama_base_url", "http://host.docker.internal:11434")
        self._model = getattr(settings, "ollama_model", "dolphin-mistral:7b")
        self._conversations: Dict[str, List[Dict[str, str]]] = {}

    def _get_history(self, decision_id: str) -> List[Dict[str, str]]:
        """Get conversation history for a decision."""
        return self._conversations.get(decision_id, [])

    def _add_to_history(self, decision_id: str, role: str, content: str) -> None:
        """Add a message to conversation history."""
        if decision_id not in self._conversations:
            self._conversations[decision_id] = []
        self._conversations[decision_id].append({"role": role, "content": content})
        # Keep last 10 messages to manage context
        self._conversations[decision_id] = self._conversations[decision_id][-10:]

    async def process_message(
        self,
        decision_id: str,
        user_message: str,
        product_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Process user message through LLM and return structured response."""

        # Add user message to history
        self._add_to_history(decision_id, "user", user_message)

        # Build the prompt with context
        history = self._get_history(decision_id)
        product_json = json.dumps(product_context, indent=2, default=str)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": f"CURRENT PRODUCT CONTEXT:\n{product_json}\n\nCONVERSATION HISTORY:\n{json.dumps(history[-5:], indent=2)}",
            },
            {"role": "user", "content": user_message},
        ]

        # Call Ollama
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._ollama_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": messages,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.7, "num_predict": 500},
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                # Parse LLM response
                llm_content = data.get("message", {}).get("content", "{}")

                # Try to parse JSON, fallback to text response
                try:
                    result = json.loads(llm_content)
                except json.JSONDecodeError:
                    # LLM didn't return valid JSON, wrap it
                    result = {
                        "action": "respond",
                        "message": llm_content[:1000],
                        "question_for_user": None,
                        "confidence": 0.5,
                        "reasoning": "LLM returned non-JSON response",
                    }

                # Validate required fields
                result.setdefault("action", "respond")
                result.setdefault("message", "I'm analyzing this for you...")
                result.setdefault("question_for_user", None)
                result.setdefault("confidence", 0.5)
                result.setdefault("reasoning", "")

                # Add assistant response to history
                self._add_to_history(decision_id, "assistant", result["message"])

                return result

        except httpx.HTTPStatusError as e:
            logger.error("Ollama HTTP error: %s", e)
            return self._fallback_response("Ollama server error. Is it running? Try: ollama run dolphin-mistral:7b")
        except httpx.ConnectError:
            logger.error("Cannot connect to Ollama at %s", self._ollama_url)
            return self._fallback_response(
                "I can't reach the AI brain (Ollama). Please:\n"
                "1. Open a new PowerShell\n"
                "2. Run: ollama run dolphin-mistral:7b\n"
                "3. Then try again here"
            )
        except Exception as e:
            logger.error("AI engine error: %s", e)
            return self._fallback_response(f"AI engine error: {str(e)[:200]}")

    def _fallback_response(self, message: str) -> Dict[str, Any]:
        """Return a safe fallback response when LLM fails."""
        return {
            "action": "respond",
            "message": message,
            "question_for_user": None,
            "confidence": 0.0,
            "reasoning": "Fallback due to LLM error",
        }

    async def generate_initial_message(self, product_context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate the rich initial approval message with analysis."""
        title = product_context.get("title", "Unknown Product")
        price = float(product_context.get("price", 0))
        cost = float(product_context.get("cost", 0))
        margin_pct = product_context.get("margin", "N/A")
        supplier = product_context.get("supplier", "N/A")
        category = product_context.get("category", "General")
        scores = product_context.get("scores", {})
        total_score = product_context.get("total_score", 0)

        profit = price - cost
        daily_10 = profit * 10
        monthly_10 = daily_10 * 30

        # Build score bars
        score_lines = ""
        if scores:
            for label, value in scores.items():
                filled = min(int(value), 10)
                empty = 10 - filled
                bar = "█" * filled + "░" * empty
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
            f"  • Ask me anything about this product\n"
            f"  • Tell me your concerns"
        )

        return {
            "message": message,
            "action": "ask_question",
            "question_for_user": "What's your call on this product? Or do you want me to dig deeper into anything?",
            "confidence": 0.7,
        }


# Singleton instance
ai_engine = TelegramAIEngine()