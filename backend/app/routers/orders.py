"""Order CRUD and action REST API router."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Order
from app import schemas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=schemas.OrderListResponse)
async def list_orders(
    status: Optional[str] = Query(None),
    fulfillment: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """List orders with optional filters."""
    query = select(Order)
    if status:
        query = query.where(Order.status == status)
    if fulfillment:
        query = query.where(Order.fulfillment_status == fulfillment)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"items": items, "total": total}


@router.get("/{order_id}", response_model=schemas.OrderOut)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Get a single order by ID."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/{order_id}/action", response_model=schemas.OrderOut)
async def order_action(
    order_id: int,
    payload: schemas.OrderActionRequest,
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Apply a manual action to an order: fulfill, cancel, refund, approve."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    action = payload.action
    if action == "fulfill":
        order.fulfillment_status = "fulfilled"
        order.agent_decision = "manual_fulfill"
    elif action == "cancel":
        order.fulfillment_status = "cancelled"
        order.agent_decision = "manual_cancel"
    elif action == "refund":
        order.fulfillment_status = "refunded"
        order.agent_decision = "manual_refund"
    elif action == "approve":
        order.fulfillment_status = "approved"
        order.agent_decision = "manual_approve"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    order.human_override = True
    await db.commit()
    await db.refresh(order)
    logger.info("Order %s action: %s", order_id, action)
    return order
