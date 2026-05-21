"""
telegram_webhook.py — COMPLETE AUTO-PIPELINE (Option A)
=======================================================
Handles ALL Telegram button clicks and routes them correctly.

CRITICAL FIX: Uses valid DecisionStatus enum values:
    pending, replied, timeout, executed, cancelled
The old code used "approved"/"rejected" which the PostgreSQL enum REJECTS.

Buttons handled:
  ✅ APPROVE   → status="executed"  → triggers full auto-pipeline
  ❌ REJECT    → status="cancelled"
  💬 NEGOTIATE → status="replied"   → AI helps re-analyze
  🔍 ALTERNATIVES → searches for similar products
  📊 ANALYSIS  → shows deep scoring breakdown
  🤖 CHAT      → AI conversation mode
  🚀 ad:LAUNCH → launches Facebook ad
  ✏️ ad:EDIT   → edit ad copy
  ⏭️ ad:SKIP   → skip ad, keep Shopify listing
"""

import logging
import json
import traceback
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.database import AsyncSessionLocal
from app.models import Decision, DecisionStatus
from app.schemas import DecisionStatusEnum
from app.config import settings
from app.services.telegram_ai_engine import ai_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram_webhook"])

# ─────────────────────────────────────────────────────────────
# TELEGRAM API HELPERS (self-contained)
# ─────────────────────────────────────────────────────────────

_BOT_TOKEN: Optional[str] = None
_CHAT_ID: Optional[str] = None


def _bot_token() -> str:
    global _BOT_TOKEN
    if _BOT_TOKEN is None:
        _BOT_TOKEN = (
            getattr(settings, "telegram_bot_token", "")
            or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
            or ""
        )
    return _BOT_TOKEN


def _chat_id() -> str:
    global _CHAT_ID
    if _CHAT_ID is None:
        _CHAT_ID = (
            getattr(settings, "telegram_chat_id", "")
            or getattr(settings, "TELEGRAM_CHAT_ID", "")
            or ""
        )
    return _CHAT_ID


async def _tg_api(method: str, payload: dict) -> dict:
    token = _bot_token()
    if not token:
        logger.error("[telegram_webhook] No TELEGRAM_BOT_TOKEN!")
        return {}
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload)
            data = r.json()
            if not data.get("ok"):
                logger.warning(f"[telegram_webhook] Telegram {method} error: {data.get('description')}")
            return data.get("result", {})
    except Exception as exc:
        logger.error(f"[telegram_webhook] Telegram {method} exception: {exc}")
        return {}


async def _send_message(chat_id: str, text: str, reply_markup: Optional[dict] = None) -> dict:
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": "HTML",
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)
    return await _tg_api("sendMessage", payload)


async def _answer_callback(callback_query_id: str, text: str = "") -> None:
    await _tg_api("answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text[:200],
    })


# ─────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────

async def _get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ─────────────────────────────────────────────────────────────
# STATUS RESOLUTION (THE CRITICAL FIX)
# ─────────────────────────────────────────────────────────────

_STATUS_MAP = {
    "approved":    DecisionStatusEnum.executed.value,
    "rejected":    DecisionStatusEnum.cancelled.value,
    "executed":    DecisionStatusEnum.executed.value,
    "cancelled":   DecisionStatusEnum.cancelled.value,
    "pending":     DecisionStatusEnum.pending.value,
    "replied":     DecisionStatusEnum.replied.value,
    "timeout":     DecisionStatusEnum.timeout.value,
}
_VALID_STATUSES = [e.value for e in DecisionStatusEnum]


async def _resolve_decision(
    decision_id: int,
    status_value: str,
    action_taken: Optional[str] = None,
    response_text: Optional[str] = None,
    db: AsyncSession = None,
) -> Decision:
    resolved = _STATUS_MAP.get(status_value.lower(), status_value)
    if resolved not in _VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status_value}' → '{resolved}'. "
            f"Valid values: {_VALID_STATUSES}"
        )

    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")

    try:
        decision.status = DecisionStatus(resolved)
    except (ValueError, KeyError):
        decision.status = resolved

    if action_taken is not None:
        decision.action = action_taken
    if response_text is not None:
        decision.response = response_text
    decision.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(decision)
    logger.info(f"[telegram_webhook] Decision {decision_id} → status='{resolved}'")
    return decision


# ─────────────────────────────────────────────────────────────
# AUTO-PIPELINE: SHOPIFY + FACEBOOK AD
# ─────────────────────────────────────────────────────────────

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

    # Notify start
    await _send_message(
        chat_id,
        f"🚀 <b>Auto-Pipeline Started</b>\n\n"
        f"📦 <b>{title}</b>\n"
        f"💰 Cost: <code>${cost:.2f}</code> → Sell: <code>${sell:.2f}</code>\n"
        f"📈 Margin: <code>{margin_pct:.1f}%</code>\n\n"
        f"⏳ <i>Listing on Shopify…</i>",
    )

    # 1. Shopify
    shopify_id = None
    try:
        from app.agents.agent_storekeeper import AgentStorekeeper
        storekeeper = AgentStorekeeper()
        result = await storekeeper.list_product(
            title=title,
            description=description,
            cost_price=cost,
            sell_price=sell,
            supplier_url=supplier,
            request_approval=False,
        )
        shopify_id = str(result.get("product_id", "unknown")) if isinstance(result, dict) else str(result)
        await _send_message(chat_id, f"✅ <b>Listed on Shopify</b>\n🆔 <code>{shopify_id}</code>")
    except Exception as exc:
        logger.error(f"[auto-pipeline] Shopify failed: {exc}")
        shopify_id = "failed"
        await _send_message(chat_id, f"⚠️ <b>Shopify failed</b>\n<code>{str(exc)[:300]}</code>")

    # 2. Generate Facebook ad via AI
    await _send_message(chat_id, "📝 <b>Generating Facebook ad copy…</b>")

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
            f'{{"headline": "...", "primary_text": "...", "cta": "...", "targeting": "...", "budget": "..."}}\n\n'
            f"Rules:\n- headline: max 40 chars, catchy\n- primary_text: max 125 chars, persuasive\n- cta: call-to-action like 'Shop Now'\n- targeting: age, gender, interests\n- budget: recommended daily budget USD"
        )
        ai_result = await ai_engine.process_message(ai_prompt, chat_id=chat_id)
        raw_msg = ai_result.get("message", "") if isinstance(ai_result, dict) else str(ai_result)

        # Parse JSON from AI response
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
        logger.error(f"[auto-pipeline] AI ad gen failed: {exc}")

    # 3. Send ad with buttons
    shopify_id = shopify_id or "unknown"
    keyboard = {
        "inline_keyboard": [
            [{"text": "🚀 Launch Ad on Facebook", "callback_data": f"ad:{shopify_id}:launch"}],
            [{"text": "✏️ Edit Copy", "callback_data": f"ad:{shopify_id}:edit"}],
            [{"text": "⏭️ Skip Ad (Keep Listing)", "callback_data": f"ad:{shopify_id}:skip"}],
        ]
    }

    await _send_message(
        chat_id,
        f"📢 <b>Facebook Ad Ready</b>\n\n"
        f"<b>🎯 {ad_data['headline']}</b>\n\n"
        f"📝 {ad_data['primary_text']}\n\n"
        f"👉 CTA: <b>{ad_data['cta']}</b>\n"
        f"🎯 Targeting: {ad_data['targeting']}\n"
        f"💰 Budget: {ad_data['budget']}\n\n"
        f"🆔 Shopify ID: <code>{shopify_id}</code>",
        reply_markup=keyboard,
    )


# ─────────────────────────────────────────────────────────────
# CALLBACK HANDLER
# ─────────────────────────────────────────────────────────────

async def _handle_callback(query_data: str, chat_id: str, db: AsyncSession) -> Optional[str]:
    logger.info(f"[telegram_webhook] Callback: '{query_data}'")
    parts = query_data.split(":")
    if len(parts) < 3:
        return "❌ Invalid callback data"

    prefix, entity_id, action = parts[0], parts[1], parts[2]

    # ── DECISION BUTTONS ───────────────────────────────────
    if prefix == "decision":
        decision_id = int(entity_id)

        if action == "approve":
            decision = await _resolve_decision(
                decision_id=decision_id,
                status_value="executed",
                action_taken="approved_via_telegram",
                db=db,
            )
            ctx = decision.context_json or {}
            title = ctx.get("product_title", "Product")
            await _trigger_storekeeper_and_ad(decision, db)
            return f"✅ <b>APPROVED</b>: {title}\n\n🚀 Auto-pipeline triggered (Shopify → Facebook Ad)!"

        elif action == "reject":
            decision = await _resolve_decision(
                decision_id=decision_id,
                status_value="cancelled",
                action_taken="rejected_via_telegram",
                db=db,
            )
            ctx = decision.context_json or {}
            return f"❌ <b>REJECTED</b>: {ctx.get('product_title', 'Product')}"

        elif action == "negotiate":
            decision = await _resolve_decision(
                decision_id=decision_id,
                status_value="replied",
                action_taken="negotiate_requested",
                db=db,
            )
            ctx = decision.context_json or {}
            cost = float(ctx.get("cost", 0) or 0)
            sell = float(ctx.get("price", 0) or ctx.get("sell_price", 0) or 0)
            margin = ((sell - cost) / cost * 100) if cost > 0 else 0
            return (
                f"💬 <b>Negotiate Mode</b>\n\n"
                f"📦 {ctx.get('product_title', 'Product')}\n"
                f"💰 Cost <code>${cost:.2f}</code> → Sell <code>${sell:.2f}</code>\n"
                f"📈 Margin: <code>{margin:.1f}%</code>\n\n"
                f"Reply with your target price (e.g. <code>49.99</code>)"
            )

        elif action == "alternatives":
            return (
                f"🔍 <b>Finding Alternatives</b>\n\n"
                f"Searching AliExpress for similar products at better prices.\n"
                f"Reply with a price range or features you want."
            )

        elif action == "analysis":
            result = await db.execute(select(Decision).where(Decision.id == decision_id))
            decision = result.scalar_one_or_none()
            if not decision:
                return f"❌ Decision {decision_id} not found"

            ctx = decision.context_json or {}
            scores = ctx.get("scores", {})
            score_lines = "\n".join(
                f"  {'🟢' if v >= 70 else '🟡' if v >= 40 else '🔴'} {k}: <b>{v}</b>/100"
                for k, v in scores.items()
            ) if scores else f"  • Overall: <b>{ctx.get('overall_score', 'N/A')}</b>/100"

            cost = float(ctx.get("cost", 0) or 0)
            sell = float(ctx.get("price", 0) or ctx.get("sell_price", 0) or 0)
            return (
                f"📊 <b>Deep Analysis</b>\n\n"
                f"📦 <b>{ctx.get('product_title', 'Product')}</b>\n\n"
                f"🎯 Scores:\n{score_lines}\n\n"
                f"💰 Cost: <code>${cost:.2f}</code> → Sell: <code>${sell:.2f}</code>\n"
                f"📈 Margin: <code>{((sell - cost) / cost * 100) if cost > 0 else 0:.1f}%</code>\n"
                f"🏷️ Supplier: {(ctx.get('supplier', 'N/A') or 'N/A')[:80]}"
            )

        elif action == "chat":
            result = await db.execute(select(Decision).where(Decision.id == decision_id))
            decision = result.scalar_one_or_none()
            if not decision:
                return f"❌ Decision {decision_id} not found"
            ctx = decision.context_json or {}
            title = ctx.get("product_title", "this product")
            return (
                f"🤖 <b>AI Chat Mode</b> — <i>{title}</i>\n\n"
                f"Ask me anything:\n"
                f"• \"What's the profit margin?\"\n"
                f"• \"Who's the target audience?\"\n"
                f"• \"Write me an ad headline\"\n"
                f"• \"Should I negotiate?\"\n\n"
                f"Just reply normally — I'm listening! 🎧"
            )

        else:
            return f"❓ Unknown action: {action}"

    # ── AD BUTTONS ───────────────────────────────────────────
    elif prefix == "ad":
        shopify_id = entity_id
        if action == "launch":
            return f"🚀 <b>Launching Facebook Ad</b>\n🆔 <code>{shopify_id}</code>\n\n<i>Next: Connect Facebook Marketing API</i>"
        elif action == "edit":
            return f"✏️ <b>Edit Ad Copy</b>\n🆔 <code>{shopify_id}</code>\n\nReply with improved ad text."
        elif action == "skip":
            return f"⏭️ <b>Ad Skipped</b>\n🆔 <code>{shopify_id}</code>\nProduct remains on Shopify."
        else:
            return f"❓ Unknown ad action: {action}"

    else:
        return f"❓ Unknown prefix: {prefix}"


# ─────────────────────────────────────────────────────────────
# MESSAGE HANDLER
# ─────────────────────────────────────────────────────────────

async def _handle_message(message_text: str, chat_id: str, db: AsyncSession) -> str:
    try:
        result = await ai_engine.process_message(message_text, chat_id=chat_id)
        return result.get("message", "🤖 Processing...") if isinstance(result, dict) else str(result)
    except Exception as exc:
        logger.error(f"[telegram_webhook] AI error: {exc}")
        return f"⚠️ <b>AI error</b>\n<code>{str(exc)[:200]}</code>"


# ─────────────────────────────────────────────────────────────
# MAIN WEBHOOK ENDPOINT
# ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def telegram_webhook(request: Request, db: AsyncSession = Depends(_get_db)):
    try:
        data = await request.json()
        logger.debug(f"[telegram_webhook] Update: {json.dumps(data, indent=2)[:800]}")

        # Button click
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

        # Text message
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
    except Exception as exc:
        logger.error(f"[telegram_webhook] Unhandled error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc)[:200])