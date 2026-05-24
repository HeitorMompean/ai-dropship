"""
telegram_webhook.py - Fixed enum bug
APPROVE -> executed, REJECT -> cancelled, NEGOTIATE -> replied
"""

import logging
import json
import traceback
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.database import AsyncSessionLocal
from app.models import Decision, DecisionStatus
from app.schemas import DecisionStatusEnum
from app.config import settings
from app.services.telegram_ai_engine import ai_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram_webhook"])

_BOT_TOKEN: Optional[str] = None
_CHAT_ID: Optional[str] = None


def _bot_token() -> str:
    global _BOT_TOKEN
    if _BOT_TOKEN is None:
        _BOT_TOKEN = getattr(settings, "telegram_bot_token", "") or ""
    return _BOT_TOKEN


def _chat_id() -> str:
    global _CHAT_ID
    if _CHAT_ID is None:
        _CHAT_ID = getattr(settings, "telegram_chat_id", "") or ""
    return _CHAT_ID


async def _tg_api(method: str, payload: dict) -> dict:
    token = _bot_token()
    if not token:
        return {}
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload)
            data = r.json()
            return data.get("result", {})
    except Exception:
        return {}


async def _send_message(chat_id: str, text: str, reply_markup: Optional[dict] = None) -> dict:
    payload = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)
    return await _tg_api("sendMessage", payload)


async def _answer_callback(callback_query_id: str, text: str = "") -> None:
    await _tg_api("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text[:200]})


async def _get_db():
    async with AsyncSessionLocal() as session:
        yield session


_STATUS_MAP = {
    "approve":     DecisionStatusEnum.executed.value,
    "reject":      DecisionStatusEnum.cancelled.value,
    "negotiate":   DecisionStatusEnum.replied.value,
    "executed":    DecisionStatusEnum.executed.value,
    "cancelled":   DecisionStatusEnum.cancelled.value,
    "pending":     DecisionStatusEnum.pending.value,
    "replied":     DecisionStatusEnum.replied.value,
    "timeout":     DecisionStatusEnum.timeout.value,
}
_VALID_STATUSES = [e.value for e in DecisionStatusEnum]


async def _resolve_decision(decision_id: int, status_value: str, db: AsyncSession) -> Decision:
    resolved = _STATUS_MAP.get(status_value.lower(), status_value)
    if resolved not in _VALID_STATUSES:
        raise ValueError(f"Invalid status '{status_value}' -> '{resolved}'. Valid: {_VALID_STATUSES}")

    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")

    try:
        decision.status = DecisionStatus(resolved)
    except (ValueError, KeyError):
        decision.status = resolved

    decision.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(decision)
    return decision


async def _trigger_storekeeper_and_ad(decision: Decision, db: AsyncSession) -> None:
    ctx = decision.context_json or {}
    title = ctx.get("product_title", "Untitled Product")
    cost = float(ctx.get("cost", 0) or 0)
    sell = float(ctx.get("price", 0) or ctx.get("sell_price", 0) or 0)
    supplier = ctx.get("supplier", "") or ctx.get("supplier_url", "") or ""
    description = ctx.get("description", "") or ctx.get("ai_description", "") or title
    margin_pct = ((sell - cost) / cost * 100) if cost > 0 else 0

    chat_id = _chat_id()
    if not chat_id:
        return

    await _send_message(chat_id, f"<b>Auto-Pipeline Started</b>\n\n<b>{title}</b>\nCost: ${cost:.2f} -> Sell: ${sell:.2f}\nMargin: {margin_pct:.1f}%\n\n<i>Listing on Shopify...</i>")

    shopify_id = None
    try:
        from app.agents.agent_storekeeper import AgentStorekeeper
        storekeeper = AgentStorekeeper()
        result = await storekeeper.list_product(
            title=title, description=description, cost_price=cost,
            sell_price=sell, supplier_url=supplier, request_approval=False,
        )
        shopify_id = str(result.get("product_id", "unknown")) if isinstance(result, dict) else str(result)
        await _send_message(chat_id, f"<b>Listed on Shopify</b>\nID: {shopify_id}")
    except Exception as exc:
        shopify_id = "failed"
        await _send_message(chat_id, f"<b>Shopify listing failed</b>\n{str(exc)[:300]}")

    await _send_message(chat_id, "<b>Generating Facebook ad copy...</b>")

    ad_data = {
        "headline": title[:40],
        "primary_text": description[:125] if description else f"Get {title} now! Limited time offer.",
        "cta": "Shop Now",
        "targeting": "25-54, All Genders, Online Shopping",
        "budget": "$20/day",
    }

    try:
        ai_prompt = (
            f"Create a Facebook ad for this dropshipping product.\n\n"
            f"Product: {title}\nDescription: {description}\nPrice: ${sell:.2f}\nMargin: {margin_pct:.1f}%\n\n"
            f"Respond with ONLY a JSON object containing:\n"
            f'{{"headline": "...", "primary_text": "...", "cta": "...", "targeting": "...", "budget": "..."}}'
        )
        ai_result = await ai_engine.process_message(ai_prompt, chat_id=chat_id)
        raw_msg = ai_result.get("message", "") if isinstance(ai_result, dict) else str(ai_result)
        json_start = raw_msg.find("{")
        json_end = raw_msg.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            try:
                parsed = json.loads(raw_msg[json_start:json_end])
                for key in ad_data:
                    if key in parsed and parsed[key]:
                        ad_data[key] = str(parsed[key])
            except json.JSONDecodeError:
                pass
    except Exception as exc:
        logger.error(f"AI ad gen failed: {exc}")

    shopify_id = shopify_id or "unknown"
    keyboard = {
        "inline_keyboard": [
            [{"text": "Launch Ad on Facebook", "callback_data": f"ad:{shopify_id}:launch"}],
            [{"text": "Edit Copy", "callback_data": f"ad:{shopify_id}:edit"}],
            [{"text": "Skip Ad", "callback_data": f"ad:{shopify_id}:skip"}],
        ]
    }

    await _send_message(
        chat_id,
        f"<b>Facebook Ad Ready</b>\n\n<b>{ad_data['headline']}</b>\n\n{ad_data['primary_text']}\n\nCTA: <b>{ad_data['cta']}</b>\nTargeting: {ad_data['targeting']}\nBudget: {ad_data['budget']}\n\nShopify ID: {shopify_id}",
        reply_markup=keyboard,
    )


async def _handle_callback(query_data: str, chat_id: str, db: AsyncSession) -> Optional[str]:
    logger.info(f"Callback: '{query_data}'")
    parts = query_data.split(":")
    if len(parts) < 3:
        return "Invalid callback data"

    prefix, entity_id, action = parts[0], parts[1], parts[2]

    if prefix == "decision":
        try:
            decision_id = int(entity_id)
        except ValueError:
            return f"Invalid decision ID: {entity_id}"

        if action == "approve":
            try:
                decision = await _resolve_decision(decision_id, "executed", db)
            except ValueError as exc:
                return f"Error: {exc}"
            ctx = decision.context_json or {}
            title = ctx.get("product_title", "Product")
            await _trigger_storekeeper_and_ad(decision, db)
            return f"<b>APPROVED</b>: {title}\n\nAuto-pipeline triggered (Shopify -> Facebook Ad)!"

        elif action == "reject":
            try:
                decision = await _resolve_decision(decision_id, "cancelled", db)
            except ValueError as exc:
                return f"Error: {exc}"
            ctx = decision.context_json or {}
            return f"<b>REJECTED</b>: {ctx.get('product_title', 'Product')}"

        elif action == "negotiate":
            try:
                decision = await _resolve_decision(decision_id, "replied", db)
            except ValueError as exc:
                return f"Error: {exc}"
            ctx = decision.context_json or {}
            cost = float(ctx.get("cost", 0) or 0)
            sell = float(ctx.get("price", 0) or ctx.get("sell_price", 0) or 0)
            margin = ((sell - cost) / cost * 100) if cost > 0 else 0
            return f"<b>Negotiate Mode</b>\n\n{ctx.get('product_title', 'Product')}\nCost ${cost:.2f} -> Sell ${sell:.2f}\nMargin: {margin:.1f}%\n\nReply with your target price."

        elif action == "alternatives":
            return "<b>Finding Alternatives</b>\n\nSearching AliExpress for similar products at better prices."

        elif action == "analysis":
            result = await db.execute(select(Decision).where(Decision.id == decision_id))
            decision = result.scalar_one_or_none()
            if not decision:
                return f"Decision {decision_id} not found"
            ctx = decision.context_json or {}
            scores = ctx.get("scores", {})
            score_lines = "\n".join(f"  {k}: {v}/100" for k, v in scores.items()) if scores else f"  Overall: {ctx.get('overall_score', 'N/A')}/100"
            cost = float(ctx.get("cost", 0) or 0)
            sell = float(ctx.get("price", 0) or ctx.get("sell_price", 0) or 0)
            return f"<b>Deep Analysis</b>\n\n<b>{ctx.get('product_title', 'Product')}</b>\n\nScores:\n{score_lines}\n\nCost: ${cost:.2f} -> Sell: ${sell:.2f}\nMargin: {margin:.1f}%"

        elif action == "chat":
            result = await db.execute(select(Decision).where(Decision.id == decision_id))
            decision = result.scalar_one_or_none()
            if not decision:
                return f"Decision {decision_id} not found"
            ctx = decision.context_json or {}
            title = ctx.get("product_title", "this product")
            return f"<b>AI Chat Mode</b> - {title}\n\nAsk me anything about this product:\n- What's the profit margin?\n- Who's the target audience?\n- Write me an ad headline\n\nJust reply normally!"

        else:
            return f"Unknown action: {action}"

    elif prefix == "ad":
        shopify_id = entity_id
        if action == "launch":
            return f"<b>Launching Facebook Ad</b>\nID: {shopify_id}\n\nConnect Facebook Marketing API to proceed."
        elif action == "edit":
            return f"<b>Edit Ad Copy</b>\nID: {shopify_id}\n\nReply with improved ad text."
        elif action == "skip":
            return f"<b>Ad Skipped</b>\nID: {shopify_id}\nProduct remains on Shopify."
        else:
            return f"Unknown ad action: {action}"

    else:
        return f"Unknown prefix: {prefix}"


async def _handle_message(message_text: str, chat_id: str, db: AsyncSession) -> str:
    try:
        result = await ai_engine.process_message(message_text, chat_id=chat_id)
        return result.get("message", "Processing...") if isinstance(result, dict) else str(result)
    except Exception as exc:
        return f"AI error: {str(exc)[:200]}"


@router.post("/webhook")
async def telegram_webhook(request: Request, db: AsyncSession = Depends(_get_db)):
    try:
        data = await request.json()

        if "callback_query" in data:
            cbq = data["callback_query"]
            query_data = cbq.get("data", "")
            chat_id = str(cbq.get("message", {}).get("chat", {}).get("id", _chat_id()))
            callback_id = cbq.get("id", "")

            response_text = await _handle_callback(query_data, chat_id, db)
            await _answer_callback(callback_id, "Done!")
            if response_text:
                await _send_message(chat_id, response_text)
            return {"ok": True}

        if "message" in data:
            msg = data["message"]
            chat_id = str(msg.get("chat", {}).get("id", _chat_id()))
            text = msg.get("text", "")
            if not text:
                return {"ok": True}
            response = await _handle_message(text, chat_id, db)
            await _send_message(chat_id, response)
            return {"ok": True}

        return {"ok": True}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Webhook error")
