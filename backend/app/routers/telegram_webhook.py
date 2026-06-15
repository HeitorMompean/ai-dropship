"""telegram_webhook.py — FIXED with correct enum values."""
import logging, json, traceback
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
    if not token: return {}
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload)
            return r.json().get("result", {})
    except: return {}

async def _send_message(chat_id: str, text: str, reply_markup: Optional[dict] = None) -> dict:
    payload = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
    return await _tg_api("sendMessage", payload)

async def _answer_callback(callback_query_id: str, text: str = "") -> None:
    await _tg_api("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text[:200]})

async def _resolve_decision(decision_id: int, status_value: str, action_taken: Optional[str] = None, db: AsyncSession = None) -> Decision:
    STATUS_MAP = {"approved": "executed", "rejected": "cancelled", "executed": "executed", "cancelled": "cancelled", "pending": "pending", "replied": "replied", "timeout": "timeout"}
    VALID = ["pending", "replied", "timeout", "executed", "cancelled"]
    resolved = STATUS_MAP.get(status_value.lower(), status_value)
    if resolved not in VALID:
        raise ValueError(f"Invalid status '{status_value}'. Valid: {VALID}")
    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if decision is None: raise ValueError(f"Decision {decision_id} not found")
    try: decision.status = DecisionStatus(resolved)
    except: decision.status = resolved
    if action_taken: decision.action = action_taken
    decision.updated_at = datetime.utcnow()
    await db.commit(); await db.refresh(decision)
    return decision

async def _get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def _trigger_storekeeper_and_ad(decision: Decision, db: AsyncSession) -> None:
    ctx = decision.context_json or {}
    title = ctx.get("product_title", "Untitled")
    cost = float(ctx.get("cost", 0) or 0)
    sell = float(ctx.get("price", 0) or 0)
    supplier = ctx.get("supplier", "") or ""
    description = ctx.get("description", "") or title
    margin_pct = ((sell - cost) / cost * 100) if cost > 0 else 0
    chat_id = _chat_id()
    if not chat_id: return
    
    await _send_message(chat_id, f"🚀 <b>Auto-Pipeline Started</b>\n\n📦 <b>{title}</b>\n💰 ${cost:.2f} → ${sell:.2f} | 📈 {margin_pct:.1f}%\n\n⏳ <i>Listing on Shopify…</i>")
    
    shopify_id = None
    try:
        from app.agents.agent_storekeeper import AgentStorekeeper
        storekeeper = AgentStorekeeper()
        result = await storekeeper.list_product(title=title, description=description, cost_price=cost, sell_price=sell, supplier_url=supplier, request_approval=False)
        shopify_id = str(result.get("shopify_product_id", "unknown")) if isinstance(result, dict) else str(result)
        await _send_message(chat_id, f"✅ <b>Listed on Shopify</b>\n🆔 <code>{shopify_id}</code>")
    except Exception as exc:
        shopify_id = "failed"
        await _send_message(chat_id, f"⚠️ Shopify failed: <code>{str(exc)[:300]}</code>")
    
    await _send_message(chat_id, "📝 <b>Generating Facebook ad copy…</b>")
    ad_data = {"headline": title[:40], "primary_text": description[:125] or f"Get {title} now!", "cta": "Shop Now", "targeting": "25-54, All Genders, Online Shopping", "budget": "$20/day"}
    
    try:
        ai_prompt = f"Create a Facebook ad for this dropshipping product.\n\nProduct: {title}\nDescription: {description}\nPrice: ${sell:.2f}\nMargin: {margin_pct:.1f}%\n\nRespond with ONLY a JSON object containing:\n{{'headline': '...', 'primary_text': '...', 'cta': '...', 'targeting': '...', 'budget': '...'}}\n\nRules:\n- headline: max 40 chars, catchy\n- primary_text: max 125 chars, persuasive\n- cta: call-to-action like 'Shop Now'\n- targeting: age, gender, interests\n- budget: recommended daily budget USD"
        ai_result = await ai_engine.process_message(ai_prompt, chat_id=chat_id)
        raw_msg = ai_result.get("message", "") if isinstance(ai_result, dict) else str(ai_result)
        j1 = raw_msg.find("{"); j2 = raw_msg.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            try:
                parsed = json.loads(raw_msg[j1:j2])
                for k in ad_data:
                    if k in parsed and parsed[k]: ad_data[k] = str(parsed[k])
            except: pass
    except Exception as exc: logger.error("AI ad gen failed: %s", exc)
    
    shopify_id = shopify_id or "unknown"
    keyboard = {"inline_keyboard": [[{"text": "🚀 Launch Ad on Facebook", "callback_data": f"ad:{shopify_id}:launch"}], [{"text": "✏️ Edit Copy", "callback_data": f"ad:{shopify_id}:edit"}], [{"text": "⏭️ Skip Ad", "callback_data": f"ad:{shopify_id}:skip"}]]}
    await _send_message(chat_id, f"📢 <b>Facebook Ad Ready</b>\n\n<b>🎯 {ad_data['headline']}</b>\n\n📝 {ad_data['primary_text']}\n\n👉 CTA: <b>{ad_data['cta']}</b>\n🎯 Targeting: {ad_data['targeting']}\n💰 Budget: {ad_data['budget']}\n\n🆔 Shopify ID: <code>{shopify_id}</code>", reply_markup=keyboard)

async def _handle_callback(query_data: str, chat_id: str, db: AsyncSession) -> Optional[str]:
    parts = query_data.split(":")
    if len(parts) < 3: return "❌ Invalid callback data"
    prefix, entity_id, action = parts[0], parts[1], parts[2]

    if prefix == "decision":
        decision_id = int(entity_id)
        if action == "approve":
            decision = await _resolve_decision(decision_id, "executed", "approved_via_telegram", db)
            ctx = decision.context_json or {}
            await _trigger_storekeeper_and_ad(decision, db)
            return f"✅ <b>APPROVED</b>: {ctx.get('product_title', 'Product')}\n\n🚀 Auto-pipeline triggered (Shopify → Facebook Ad)!"
        elif action == "reject":
            decision = await _resolve_decision(decision_id, "cancelled", "rejected_via_telegram", db)
            return f"❌ <b>REJECTED</b>: {decision.context_json.get('product_title', 'Product')}"
        elif action == "negotiate":
            decision = await _resolve_decision(decision_id, "replied", "negotiate_requested", db)
            ctx = decision.context_json or {}; cost = float(ctx.get("cost", 0)); sell = float(ctx.get("price", 0))
            margin = ((sell - cost) / cost * 100) if cost > 0 else 0
            return f"💬 <b>Negotiate Mode</b>\n\n📦 {ctx.get('product_title', 'Product')}\n💰 ${cost:.2f} → ${sell:.2f} | 📈 {margin:.1f}%\n\nReply with your target price."
        elif action == "alternatives": return "🔍 Searching for alternatives..."
        elif action == "analysis":
            result = await db.execute(select(Decision).where(Decision.id == decision_id))
            d = result.scalar_one_or_none()
            if not d: return f"❌ Decision {decision_id} not found"
            ctx = d.context_json or {}; scores = ctx.get("scores", {})
            score_lines = "\n".join(f"  {'🟢' if v >= 7 else '🟡' if v >= 4 else '🔴'} {k}: <b>{v}</b>/10" for k, v in scores.items()) if scores else f"  Total: <b>{ctx.get('total_score', 'N/A')}</b>/130"
            cost = float(ctx.get("cost", 0)); sell = float(ctx.get("price", 0))
            return f"📊 <b>Deep Analysis</b>\n\n📦 <b>{ctx.get('product_title', 'Product')}</b>\n\n🎯 Scores:\n{score_lines}\n\n💰 ${cost:.2f} → ${sell:.2f} | 📈 {((sell - cost) / cost * 100) if cost > 0 else 0:.1f}%"
        elif action == "chat":
            return f"🤖 <b>AI Chat Mode</b>\n\nAsk me anything about this product.\nJust reply normally!"
        elif action == "risk": return "⚠️ Risk analysis coming soon..."
        elif action == "scores": return "📊 Analysis: Use the 📊 Deep Analysis button!"
        else: return f"❓ Unknown: {action}"
    elif prefix == "ad":
        shopify_id = entity_id
        if action == "launch": return f"🚀 Launching Facebook Ad\n🆔 <code>{shopify_id}</code>\n\nConnect Facebook Marketing API to complete."
        elif action == "edit": return f"✏️ Edit Ad Copy\n🆔 <code>{shopify_id}</code>\n\nReply with improved ad text."
        elif action == "skip": return f"⏭️ Ad Skipped\n🆔 <code>{shopify_id}</code>\nProduct remains on Shopify."
        else: return f"❓ Unknown ad action: {action}"
    else: return f"❓ Unknown prefix: {prefix}"

async def _handle_message(message_text: str, chat_id: str, db: AsyncSession) -> str:
    try:
        result = await ai_engine.process_message(message_text, chat_id=chat_id)
        return result.get("message", "🤖 Processing...") if isinstance(result, dict) else str(result)
    except Exception as exc:
        logger.error("AI error: %s", exc)
        return f"⚠️ AI error: {str(exc)[:200]}"

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
            if response_text: await _send_message(chat_id, response_text)
            return {"ok": True}
        if "message" in data:
            msg = data["message"]
            chat_id = str(msg.get("chat", {}).get("id", _chat_id()))
            text = msg.get("text", "")
            if not text: return {"ok": True}
            response = await _handle_message(text, chat_id, db)
            await _send_message(chat_id, response)
            return {"ok": True}
        return {"ok": True}
    except HTTPException: raise
    except Exception as exc:
        logger.error("Webhook error: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc)[:200])
