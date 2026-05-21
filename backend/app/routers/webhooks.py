"""Shopify webhook handlers (orders, products)."""

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException, Header, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Order, Product
from app.services.shopify_client import shopify_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/shopify", tags=["webhooks"])


def verify_shopify_hmac(body: bytes, hmac_header: str) -> bool:
    """Verify Shopify webhook HMAC signature."""
    if settings.is_demo_mode:
        return True
    secret = settings.shopify_webhook_secret.encode("utf-8")
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, hmac_header)


@router.post("/order-created")
async def shopify_order_created(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Handle Shopify 'orders/create' webhook."""
    body = await request.body()
    if x_shopify_hmac_sha256 and not verify_shopify_hmac(body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Invalid HMAC")

    payload = json.loads(body)
    shopify_order_id = str(payload.get("id"))
    customer = payload.get("customer", {})
    shipping = payload.get("shipping_address", {})
    line_items = payload.get("line_items", [])

    # Check for existing order
    result = await db.execute(select(Order).where(Order.shopify_order_id == shopify_order_id))
    existing = result.scalar_one_or_none()
    if existing:
        logger.info("Order %s already exists. Skipping.", shopify_order_id)
        return {"status": "skipped", "reason": "exists"}

    order = Order(
        shopify_order_id=shopify_order_id,
        customer_name=f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip() or "Unknown",
        customer_phone=customer.get("phone") or shipping.get("phone"),
        customer_email=customer.get("email"),
        total=float(payload.get("total_price", "0")),
        status=payload.get("financial_status", "unknown"),
        fraud_score=0.0,
        fulfillment_status="pending",
        shipping_address_json=shipping,
        items_json={"line_items": line_items},
    )
    db.add(order)
    await db.commit()
    logger.info("Order %s created (Shopify ID %s).", order.id, shopify_order_id)
    return {"status": "ok"}


@router.post("/order-updated")
async def shopify_order_updated(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Handle Shopify 'orders/updated' webhook."""
    body = await request.body()
    if x_shopify_hmac_sha256 and not verify_shopify_hmac(body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Invalid HMAC")

    payload = json.loads(body)
    shopify_order_id = str(payload.get("id"))
    result = await db.execute(select(Order).where(Order.shopify_order_id == shopify_order_id))
    order = result.scalar_one_or_none()
    if not order:
        logger.warning("Order update received for unknown order %s", shopify_order_id)
        return {"status": "ignored", "reason": "not_found"}

    order.status = payload.get("financial_status", order.status)
    order.total = float(payload.get("total_price", order.total))
    order.shipping_address_json = payload.get("shipping_address", order.shipping_address_json)
    order.items_json = {"line_items": payload.get("line_items", [])}
    await db.commit()
    logger.info("Order %s updated.", shopify_order_id)
    return {"status": "ok"}


@router.post("/product-updated")
async def shopify_product_updated(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Handle Shopify 'products/update' webhook."""
    body = await request.body()
    if x_shopify_hmac_sha256 and not verify_shopify_hmac(body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Invalid HMAC")

    payload = json.loads(body)
    shopify_product_id = str(payload.get("id"))
    result = await db.execute(select(Product).where(Product.shopify_product_id == shopify_product_id))
    product = result.scalar_one_or_none()
    if not product:
        return {"status": "ignored", "reason": "not_found"}

    product.title = payload.get("title", product.title)
    product.description = payload.get("body_html", product.description)
    variants = payload.get("variants", [])
    if variants:
        try:
            product.actual_sell_price = float(variants[0].get("price", 0))
        except Exception:
            pass
    await db.commit()
    logger.info("Product %s updated.", shopify_product_id)
    return {"status": "ok"}
