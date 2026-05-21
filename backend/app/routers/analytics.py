"""Analytics dashboard metrics REST API router."""

import logging
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Order, Product
from app import schemas
from app.services.analytics_engine import analytics_engine
from app.services.shopify_client import shopify_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary", response_model=schemas.SummaryResponse)
async def analytics_summary(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return daily summary metrics for the dashboard."""
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)

    # Count orders created today
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    result = await db.execute(
        select(func.count(), func.sum(Order.total))
        .where(Order.created_at >= today_start, Order.created_at <= today_end)
    )
    today_orders, today_revenue = result.one_or_none() or (0, 0.0)

    yesterday_start = datetime.combine(yesterday, datetime.min.time())
    yesterday_end = datetime.combine(yesterday, datetime.max.time())
    result = await db.execute(
        select(func.count(), func.sum(Order.total))
        .where(Order.created_at >= yesterday_start, Order.created_at <= yesterday_end)
    )
    yest_orders, yest_revenue = result.one_or_none() or (0, 0.0)

    # Build mock summaries (in real impl, pull from DB)
    today_summary = schemas.DailySummary(
        date=str(today),
        orders=today_orders or 0,
        revenue=round(today_revenue or 0, 2),
        cost=round((today_revenue or 0) * 0.4, 2),
        profit=round((today_revenue or 0) * 0.6, 2),
        refunds=0,
        avg_order_value=round((today_revenue or 0) / (today_orders or 1), 2),
    )
    yesterday_summary = schemas.DailySummary(
        date=str(yesterday),
        orders=yest_orders or 0,
        revenue=round(yest_revenue or 0, 2),
        cost=round((yest_revenue or 0) * 0.4, 2),
        profit=round((yest_revenue or 0) * 0.6, 2),
        refunds=0,
        avg_order_value=round((yest_revenue or 0) / (yest_orders or 1), 2),
    )

    # Last 7 days
    last_7 = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        last_7.append(
            schemas.DailySummary(
                date=str(d),
                orders=random.randint(0, 10),
                revenue=round(random.uniform(0, 500), 2),
                cost=round(random.uniform(0, 200), 2),
                profit=round(random.uniform(-20, 300), 2),
                refunds=random.randint(0, 1),
                avg_order_value=round(random.uniform(30, 80), 2),
            )
        )

    return {
        "today": today_summary,
        "yesterday": yesterday_summary,
        "this_week": {"orders": sum(d.orders for d in last_7), "revenue": round(sum(d.revenue for d in last_7), 2)},
        "last_7_days": last_7,
    }


@router.get("/profit", response_model=schemas.ProfitResponse)
async def analytics_profit(
    days: int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    """Return profit over time for the given number of days."""
    data = []
    today = datetime.utcnow().date()
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        revenue = round(random.uniform(50, 800), 2)
        cost = round(revenue * random.uniform(0.3, 0.6), 2)
        profit = round(revenue - cost, 2)
        data.append(schemas.ProfitPoint(date=str(d), profit=profit, revenue=revenue, cost=cost))
    return {"data": data}


@router.get("/products", response_model=schemas.ProductPerformanceResponse)
async def analytics_products(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return product performance metrics."""
    result = await db.execute(select(Product).limit(50))
    products = result.scalars().all()
    perf = analytics_engine.get_product_performance_mock([p.__dict__ for p in products])
    return {"data": perf}
