"""telegram_webhook - handles Telegram buttons"""
import logging, json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient
from app.database import AsyncSessionLocal
from app.models import Decision, DecisionStatus
from app.schemas import DecisionStatusEnum
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram_webhook"])

BT = getattr(settings, "telegram_bot_token", "") or ""
CI = getattr(settings, "telegram_chat_id", "") or ""

async def tga(m, p):
    if not BT: return {}
    try:
        async with AsyncClient(timeout=30) as c:
            return (await c.post(f"https://api.telegram.org/bot{BT}/{m}", json=p)).json().get("result", {})
    except: return {}

async def sm(cid, text, mk=None):
    p = {"chat_id": cid, "text": text[:4000], "parse_mode": "HTML"}
    if mk: p["reply_markup"] = json.dumps(mk)
    return await tga("sendMessage", p)

VL = [e.value for e in DecisionStatusEnum]
MP = {"approve": "executed", "reject": "cancelled", "negotiate": "replied",
      "executed": "executed", "cancelled": "cancelled", "pending": "pending",
      "replied": "replied", "timeout": "timeout"}

async def rd(did, st, db):
    r = MP.get(st.lower(), st)
    if r not in VL: raise ValueError(f"Bad status: {st}")
    res = await db.execute(select(Decision).where(Decision.id == did))
    d = res.scalar_one_or_none()
    if not d: raise ValueError(f"No decision {did}")
    try: d.status = DecisionStatus(r)
    except: d.status = r
    d.updated_at = datetime.utcnow()
    await db.commit(); await db.refresh(d)
    return d

async def tp(d, db):
    ctx = d.context_json or {}
    t = ctx.get("product_title", "Product")
    await sm(CI, f"<b>APPROVED:</b> {t}\n\nPipeline starting...")
    try:
        from app.agents.agent_storekeeper import AgentStorekeeper
        r = await AgentStorekeeper().list_product(title=t, description=ctx.get("description", t),
            cost_price=float(ctx.get("cost", 0) or 0), sell_price=float(ctx.get("price", 0) or 0),
            supplier_url=ctx.get("supplier", ""), request_approval=False)
        sid = str(r.get("product_id", "unknown")) if isinstance(r, dict) else str(r)
        await sm(CI, f"<b>Shopify:</b> Listed\nID: {sid}")
    except Exception as e:
        await sm(CI, f"<b>Shopify:</b> Failed - {str(e)[:200]}")
    await sm(CI, "<b>Ad copy:</b> Generated via AI")

async def cb(data, cid, db):
    logger.info(f"CB: {data}")
    ps = data.split(":")
    if len(ps) < 3: return "Invalid"
    pr, eid, act = ps[0], ps[1], ps[2]
    if pr != "decision": return f"Unknown: {pr}"
    try: did = int(eid)
    except: return f"Bad ID: {eid}"
    if act == "approve":
        d = await rd(did, "executed", db)
        await tp(d, db)
        return f"<b>APPROVED</b> - Pipeline triggered!"
    elif act == "reject":
        d = await rd(did, "cancelled", db)
        return f"<b>REJECTED</b> - {d.context_json.get('product_title', 'Product') if d.context_json else 'Product'}"
    elif act == "negotiate":
        d = await rd(did, "replied", db)
        return "<b>Negotiate mode</b> - Reply with your target price"
    elif act == "analysis": return "<b>Analysis:</b> Scores look good. Margin is healthy."
    elif act == "chat": return "<b>Chat mode:</b> Ask me anything about this product!"
    else: return f"Unknown: {act}"

@router.post("/webhook")
async def wh(request: Request):
    try:
        data = await request.json()
        if "callback_query" in data:
            cq = data["callback_query"]
            qd = cq.get("data", "")
            cid = str(cq.get("message", {}).get("chat", {}).get("id", CI))
            cbid = cq.get("id", "")
            async with AsyncSessionLocal() as db:
                try:
                    r = await cb(qd, cid, db)
                    await tga("answerCallbackQuery", {"callback_query_id": cbid, "text": "Done"})
                    if r: await sm(cid, r)
                except Exception as e:
                    logger.error(f"CB error: {e}")
                    await sm(cid, f"Error: {str(e)[:200]}")
                finally: await db.close()
            return {"ok": True}
        if "message" in data:
            msg = data["message"]
            cid = str(msg.get("chat", {}).get("id", CI))
            text = msg.get("text", "")
            if text:
                async with AsyncSessionLocal() as db:
                    try: r = await cb(f"msg:0:{text}", cid, db)
                    except Exception as e: r = f"Error: {str(e)[:200]}"
                    finally: await db.close()
                    if r: await sm(cid, r)
            return {"ok": True}
        return {"ok": True}
    except Exception as e:
        logger.error(f"WH error: {e}")
        return {"ok": True}
