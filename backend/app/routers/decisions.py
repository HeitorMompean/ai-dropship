"""Decision queue (human-in-the-loop) REST API router."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Decision, Conversation
from app import schemas
from app.agents.memory import conversation_memory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.get("", response_model=schemas.DecisionListResponse)
async def list_decisions(
    status: Optional[str] = Query(None),
    agent_name: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """List decisions with optional filters."""
    query = select(Decision)
    if status:
        query = query.where(Decision.status == status)
    if agent_name:
        query = query.where(Decision.agent_name == agent_name)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.order_by(Decision.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"items": items, "total": total}


@router.get("/{decision_id}", response_model=schemas.DecisionOut)
async def get_decision(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
) -> Decision:
    """Get a single decision by ID."""
    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision


@router.post("/{decision_id}/resolve", response_model=schemas.DecisionOut)
async def resolve_decision(
    decision_id: int,
    payload: schemas.DecisionResolveRequest,
    db: AsyncSession = Depends(get_db),
) -> Decision:
    """Manually resolve a pending decision."""
    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    if decision.status.value not in ("pending", "replied"):
        raise HTTPException(status_code=400, detail="Decision already resolved")

    from datetime import datetime
    decision.owner_reply = payload.action
    decision.reply_parsed_action = payload.action
    decision.status = "executed"
    decision.resolved_at = datetime.utcnow()
    await db.commit()
    await db.refresh(decision)
    logger.info("Decision %s manually resolved to: %s", decision_id, payload.action)
    return decision


@router.get("/{decision_id}/conversation", response_model=schemas.ConversationListResponse)
async def decision_conversation(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get SMS conversation thread for a decision."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.decision_id == decision_id)
        .order_by(Conversation.timestamp.asc())
    )
    items = result.scalars().all()
    return {"items": items, "total": len(items)}

@router.post("", response_model=schemas.DecisionOut, status_code=201)
async def create_decision(
    payload: schemas.DecisionCreate,
    db: AsyncSession = Depends(get_db),
) -> Decision:
    """Create a new decision requiring owner approval."""
    decision = Decision(
        agent_name=payload.agent_name,
        decision_type=payload.decision_type,
        context_json=payload.context_json,
        sms_text_sent=payload.sms_text_sent,
        timeout_at=payload.timeout_at,
        status="pending",
    )
    db.add(decision)
    await db.commit()
    await db.refresh(decision)

    try:
        from app.services.telegram_service import telegram_service
        await telegram_service.send_approval_request(
            decision_id=decision.id,
            agent_name=decision.agent_name,
            decision_type=decision.decision_type,
            sms_text=decision.sms_text_sent,
            context=decision.context_json,
        )
    except Exception as e:
        logger.warning("Telegram approval request failed: %s", e)

    return decision