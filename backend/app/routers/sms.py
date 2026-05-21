"""SMS inbound webhook and conversation history REST API router."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Conversation, Decision
from app import schemas
from app.services.sms_service import sms_service
from app.agents.agent_orchestrator import orchestrator
from app.agents.memory import conversation_memory
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sms", tags=["sms"])


security = HTTPBearer(auto_error=False)

async def _verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    if settings.app_env == "development" and settings.app_secret_key == "demo_secret_key_change_me":
        return "demo"
    if not credentials or credentials.credentials != settings.app_secret_key:
        raise HTTPException(status_code=401, detail="Invalid or missing Bearer token")
    return credentials.credentials


@router.post("/inbound")
async def sms_inbound(payload: schemas.SmsInboundPayload, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Webhook from android-sms-gateway when the owner replies.

    Processes the inbound message, attempts to match it to a pending decision,
    records the conversation, and returns the parsed action.
    """
    normalized = sms_service.process_inbound_webhook(payload.model_dump())
    from_number = normalized["from"]
    body = normalized["body"]

    # Record conversation in DB
    conversation = Conversation(
        direction="inbound",
        message_body=body,
        timestamp=payload.timestamp or datetime.utcnow(),
        message_id=payload.messageId,
    )

    # Try to match to most recent pending decision by phone + recency
    result = await db.execute(
        select(Decision)
        .where(Decision.status == "pending")
        .order_by(Decision.created_at.desc())
        .limit(1)
    )
    pending_decision = result.scalar_one_or_none()
    if pending_decision:
        conversation.decision_id = pending_decision.id
        # Update decision record
        pending_decision.owner_reply = body
        pending_decision.status = "replied"
        pending_decision.reply_parsed_action = orchestrator.parse_reply(body, pending_decision.decision_type)

    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    # Also process through orchestrator for memory state
    processed = await orchestrator.process_inbound_reply(from_number, body)

    logger.info("Inbound SMS processed from %s: %s", from_number, body)
    return {
        "status": "ok",
        "parsed_action": processed.get("parsed_action") if processed else None,
        "conversation_id": conversation.id,
        "decision_id": conversation.decision_id,
    }


@router.get("/conversations", response_model=schemas.ConversationListResponse, dependencies=[Depends(_verify_token)])
async def list_conversations(
    decision_id: Optional[int] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get all SMS conversation history."""
    query = select(Conversation).order_by(Conversation.timestamp.desc())
    if decision_id is not None:
        query = query.where(Conversation.decision_id == decision_id)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"items": items, "total": total}


@router.post("/send")
async def send_sms_endpoint(payload: schemas.SmsSendPayload, credentials: str = Depends(_verify_token)) -> Dict[str, Any]:
    result = await sms_service.send_sms(payload.to, payload.message)
    return {"status": "ok", "result": result}
