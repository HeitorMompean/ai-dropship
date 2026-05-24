"""telegram_webhook - handles Telegram buttons"""
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

BOT_TOKEN = getattr(settings, "telegram_bot_token", "") or ""
CHAT_ID = getattr(settings, "telegram_chat_id", "") or ""

async def tg_api(method: str, payload: dict) -> dict:
    if not BOT_TOKEN: return {}
    try:
        async with AsyncClient(timeout=30) as c:
            r = await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload)
            return r.json().get("result", {})
    except: return {}

async def send_msg(chat_id: str, text: str, markup: Optional[dict] = None):
    p = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML"}
    if markup: p["reply_markup"] = json.dumps(markup)
    return await tg_api("sendMessage", p)

async def answer_cb(cb_id: str, text: str = ""):
    await tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:200]})

async def get_db():
    async with AsyncSessionLocal() as s: yield s

VALID = [e.value for e in DecisionStatusEnum]

async def resolve_decision(did: int, status: str, db: AsyncSession) -> Decision:
    MAP = {"approve": "executed", "reject": "cancelled", "negotiate": "replied",
           "executed": "executed", "cancelled": "cancelled", "pending": "pending",
           "replied": "replied", "timeout": "timeout"}
    r = MAP.get(status.lower(), status)
    if r not in VALID: raise ValueError(f"Bad status '{status}' -> '{r}'. Valid: {VALID}")
    res = await db.execute(select(Decision).where(Decision.id == did))
    d = res.scalar_one_or_none()
    if not d: raise ValueError(f"Decision {did} not found")
    try: d.status = DecisionStatus(r)
    except: d.status = r
    d.updated_at = datetime.utcnow()
    await db.commit(); await db.refresh(d)
    logger.info(f"Decision {did} -> {r}")
    return d

async def trigger_pipeline(decision: Decision, db: AsyncSession):
    ctx = decision.context_json or {}
    title = ctx.get("product_title", "Product")
    cost = float(ctx.get("cost", 0) or 0)
    sell = float(ctx.get("price", 0) or ctx.get("sell_price", 0) or 0)
    supplier = ctx.get("supplier", "") or ctx.get("supplier_url", "") or ""
    desc = ctx.get("description", "") or ctx.get("ai_description", "") or title
    margin = ((sell - cost) / cost * 100) if cost > 0 else 0
    if not CHAT_ID: return
    await send_msg(CHAT_ID, f"<b>Auto-Pipeline Started</b>\n\n<b>{title}</b>\nCost: ${cost:.2f} -> Sell: ${sell:.2f}\nMargin: {margin:.1f}%\n\n<i>Listing on Shopify...</i>")
    sid = None
    try:
        from app.agents.agent_storekeeper import AgentStorekeeper
        r = await AgentStorekeeper().list_product(title=title, description=desc, cost_price=cost, sell_price=sell, supplier_url=supplier, request_approval=False)
        sid = str(r.get("product_id", "unknown")) if isinstance(r, dict) else str(r)
        await send_msg(CHAT_ID, f"<b>Listed on Shopify</b>\nID: {sid}")
    except Exception as e:
        sid = "failed"
        await send_msg(CHAT_ID, f"<b>Shopify failed</b>\n{str(e)[:300]}")
    await send_msg(CHAT_ID, "<b>Generating Facebook ad copy...</b>")
    ad = {"headline": title[:40], "primary_text": desc[:125] if desc else f"Get {title} now!", "cta": "Shop Now", "targeting": "25-54, All Genders, Online Shopping", "budget": "$20/day"}
    try:
        ai_prompt = f"Create a Facebook ad for this dropshipping product.\n\nProduct: {title}\nDescription: {desc}\nPrice: ${sell:.2f}\nMargin: {margin:.1f}%\n\nRespond with ONLY a JSON object containing:\n{{'headline': '...', 'primary_text': '...', 'cta': '...', 'targeting': '...', 'budget': '...'}}"
        result = await ai_engine.process_message(ai_prompt, chat_id=CHAT_ID)
        msg = result.get("message", "") if isinstance(result, dict) else str(result)
        j1, j2 = msg.find("{"), msg.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            parsed = json.loads(msg[j1:j2])
            for k in ad:
                if k in parsed and parsed[k]: ad[k] = str(parsed[k])
    except Exception as e: logger.error(f"AI ad failed: {e}")
    sid = sid or "unknown"
    kb = {"inline_keyboard": [[{"text": "Launch Ad on Facebook", "callback_data": f"ad:{sid}:launch"}],
                               [{"text": "Edit Copy", "callback_data": f"ad:{sid}:edit"}],
                               [{"text": "Skip Ad", "callback_data": f"ad:{sid}:skip"}]]}
    await send_msg(CHAT_ID, f"<b>Facebook Ad Ready</b>\n\n<b>{ad['headline']}</b>\n\n{ad['primary_text']}\n\nCTA: <b>{ad['cta']}</b>\nTargeting: {ad['targeting']}\nBudget: {ad['budget']}\n\nShopify ID: {sid}", markup=kb)

async def handle_cb(data: str, chat_id: str, db: AsyncSession) -> Optional[str]:
    logger.info(f"CB: {data}")
    parts = data.split(":")
    if len(parts) < 3: return "Invalid callback"
    prefix, eid, action = parts[0], parts[1], parts[2]
    if prefix == "decision":
        try: did = int(eid)
        except: return f"Bad ID: {eid}"
        if action == "approve":
            try: d = await resolve_decision(did, "executed", db)
            except ValueError as e: return f"Error: {e}"
            ctx = d.context_json or {}
            await trigger_pipeline(d, db)
            return f"<b>APPROVED</b>: {ctx.get('product_title', 'Product')}\n\nAuto-pipeline triggered (Shopify -> Facebook Ad)!"
        elif action == "reject":
            try: d = await resolve_decision(did, "cancelled", db)
            except ValueError as e: return f"Error: {e}"
            ctx = d.context_json or {}
            return f"<b>REJECTED</b>: {ctx.get('product_title', 'Product')}"
        elif action == "negotiate":
            try: d = await resolve_decision(did, "replied", db)
            except ValueError as e: return f"Error: {e}"
            ctx = d.context_json or {}
            cost = float(ctx.get("cost", 0) or 0)
            sell = float(ctx.get("price", 0) or ctx.get("sell_price", 0) or 0)
            m = ((sell - cost) / cost * 100) if cost > 0 else 0
            return f"<b>Negotiate Mode</b>\n\n{ctx.get('product_title', 'Product')}\nCost ${cost:.2f} -> Sell ${sell:.2f}\nMargin: {m:.1f}%\n\nReply with your target price."
        elif action == "alternatives": return "<b>Finding Alternatives</b>\n\nSearching AliExpress for similar products."
        elif action == "analysis":
            res = await db.execute(select(Decision).where(Decision.id == did))
            d = res.scalar_one_or_none()
            if not d: return f"Decision {did} not found"
            ctx = d.context_json or {}
            sc = ctx.get("scores", {})
            sl = "\n".join(f"  {k}: {v}/100" for k, v in sc.items()) if sc else f"  Overall: {ctx.get('overall_score', 'N/A')}/100"
            cost = float(ctx.get("cost", 0) or 0)
            sell = float(ctx.get("price", 0) or ctx.get("sell_price", 0) or 0)
            return f"<b>Deep Analysis</b>\n\n<b>{ctx.get('product_title', 'Product')}</b>\n\nScores:\n{sl}\n\nCost: ${cost:.2f} -> Sell: ${sell:.2f}\nMargin: {((sell - cost) / cost * 100) if cost > 0 else 0:.1f}%"
        elif action == "chat":
            res = await db.execute(select(Decision).where(Decision.id == did))
            d = res.scalar_one_or_none()
            if not d: return f"Decision {did} not found"
            ctx = d.context_json or {}
            return f"<b>AI Chat Mode</b> - {ctx.get('product_title', 'this product')}\n\nAsk me anything:\n- What's the profit margin?\n- Who's the target audience?\n- Write me an ad headline\n\nJust reply normally!"
        else: return f"Unknown action: {action}"
    elif prefix == "ad":
        if action == "launch": return f"<b>Launching Facebook Ad</b>\nID: {eid}\n\nConnect Facebook Marketing API to proceed."
        elif action == "edit": return f"<b>Edit Ad Copy</b>\nID: {eid}\n\nReply with improved ad text."
        elif action == "skip": return f"<b>Ad Skipped</b>\nID: {eid}\nProduct remains on Shopify."
        else: return f"Unknown ad action: {action}"
    else: return f"Unknown prefix: {prefix}"

async def handle_msg(text: str, chat_id: str, db: AsyncSession) -> str:
    try:
        r = await ai_engine.process_message(text, chat_id=chat_id)
        return r.get("message", "Processing...") if isinstance(r, dict) else str(r)
    except Exception as e: return f"AI error: {str(e)[:200]}"

@router.post("/webhook")
async def telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        data = await request.json()
        if "callback_query" in data:
            cbq = data["callback_query"]
            qd = cbq.get("data", "")
            cid = str(cbq.get("message", {}).get("chat", {}).get("id", CHAT_ID))
            cbid = cbq.get("id", "")
            resp = await handle_cb(qd, cid, db)
            await answer_cb(cbid, "Done!")
            if resp: await send_msg(cid, resp)
            return {"ok": True}
        if "message" in data:
            msg = data["message"]
            cid = str(msg.get("chat", {}).get("id", CHAT_ID))
            text = msg.get("text", "")
            if not text: return {"ok": True}
            resp = await handle_msg(text, cid, db)
            await send_msg(cid, resp)
            return {"ok": True}
        return {"ok": True}
    except HTTPException: raise
    except Exception: raise HTTPException(status_code=500, detail="Webhook error")
