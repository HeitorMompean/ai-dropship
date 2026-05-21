"""Product CRUD REST API router."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Product
from app import schemas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=schemas.ProductListResponse)
async def list_products(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None, ge=0, le=130),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """List products with optional filters."""
    query = select(Product)
    if status:
        query = query.where(Product.status == status)
    if search:
        query = query.where(Product.title.ilike(f"%{search}%"))
    if min_score is not None:
        query = query.where(Product.total_score >= min_score)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return {"items": items, "total": total}


@router.post("", response_model=schemas.ProductOut, status_code=201)
async def create_product(
    payload: schemas.ProductCreate,
    db: AsyncSession = Depends(get_db),
) -> Product:
    """Create a new product from research data."""
    product = Product(
        title=payload.title,
        description=payload.description,
        supplier_url=payload.supplier_url,
        cost_price=payload.cost_price,
        suggested_sell_price=payload.suggested_sell_price,
        actual_sell_price=payload.actual_sell_price,
        margin=payload.margin,
        score_problem_solution=payload.score_problem_solution,
        score_passionate_audience=payload.score_passionate_audience,
        score_profit_margin=payload.score_profit_margin,
        score_perceived_value=payload.score_perceived_value,
        score_impulse_potential=payload.score_impulse_potential,
        score_availability=payload.score_availability,
        score_trending=payload.score_trending,
        score_shipping=payload.score_shipping,
        score_legal=payload.score_legal,
        score_repeat_purchase=payload.score_repeat_purchase,
        score_visual_appeal=payload.score_visual_appeal,
        score_price_point=payload.score_price_point,
        score_competitive_landscape=payload.score_competitive_landscape,
        total_score=payload.total_score,
        ai_analysis_json=payload.ai_analysis_json,
        status=payload.status.value,
        shopify_product_id=payload.shopify_product_id,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    logger.info("Product created: %s (ID %s)", product.title, product.id)
    return product


@router.get("/{product_id}", response_model=schemas.ProductOut)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> Product:
    """Get a single product by ID."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.patch("/{product_id}", response_model=schemas.ProductOut)
async def update_product(
    product_id: int,
    payload: schemas.ProductUpdate,
    db: AsyncSession = Depends(get_db),
) -> Product:
    """Update a product by ID."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "status" and value is not None:
            value = value.value
        setattr(product, key, value)

    await db.commit()
    await db.refresh(product)
    logger.info("Product %s updated.", product_id)
    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Delete a product by ID."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.delete(product)
    await db.commit()
    logger.info("Product %s deleted.", product_id)
    return {"status": "deleted", "id": product_id}
