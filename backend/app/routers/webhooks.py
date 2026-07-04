"""Shopify webhook handlers (orders, products) + fulfillment kickoff.

CHANGES vs previous version:
  - SECURITY FIX: HMAC verification now (a) uses BASE64 comparison — Shopify's
    X-Shopify-Hmac-Sha256 header is base64, not hex, so the old hexdigest
    comparison rejected every genuine webhook — and (b) rejects requests with a
    MISSING header instead of silently skipping verification.
  - FULFILLMENT LOOP: orders/create now (1) saves the order, (2) sends a rich
    Telegram card with customer, address, items, and each item's AliExpress
    supplier link (everything needed to place the order manually or in DSers),
    and (3) if CJ auto-fulfillment is enabled AND the SKUs are mapped, places
    the CJ order automatically and reports the CJ order id.
"""

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, HTTPException, Header, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Order, Product
from app.services.shopify_client import shopify_client
from app.services.cj_fulfillment import cj_service, cj_enabled, load_sku_map

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/shopify", tags=["webhooks"])


def verify_shopify_hmac(body: bytes, hmac_header: Optional[str]) -> bool:
    """Verify Shopify webhook signature (base64 HMAC-SHA256)."""
    if settings.is_demo_mode:
        return True
    if not hmac_header:
        return False  # missing header = unauthenticated; never skip verification
    secret = settings.shopify_webhook_secret.encode("utf-8")
    digest = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(digest, hmac_header)


async def _supplier_links_for(line_items: List[Dict[str, Any]],
                              db: AsyncSession) -> Dict[str, str]:
    """Map line-item product_id -> supplier URL from our Product table (if stored)."""
    links: Dict[str, str] = {}
    for li in line_items:
        pid = str(li.get("product_id") or "")
        if not pid or pid in links:
            continue
        try:
            result = await db.execute(
                select(Product).where(Product.shopify_product_id == pid)
            )
            product = result.scalar_one_or_none()
            url = getattr(product, "supplier_url", None) if product else None
            if url:
                links[pid] = url
        except Exception as e:
            logger.warning("Supplier lookup failed for product %s: %s", pid, e)
    return links


async def _notify_new_order(payload: Dict[str, Any], db: AsyncSession,
                            cj_result: Optional[str], unmapped: List[Dict[str, Any]]) -> None:
    """Send the fulfillment card to Telegram."""
    try:
        from app.services.telegram_service import telegram_service
    except Exception as e:
        logger.error("Telegram service unavailable for order notify: %s", e)
        return

    ship = payload.get("shipping_address") or {}
    line_items = payload.get("line_items", [])
    links = await _supplier_links_for(line_items, db)

    lines = []
    for li in line_items:
        pid = str(li.get("product_id") or "")
        item = (f"  • {li.get('quantity', 1)}x <b>{li.get('title', 'Item')}</b>"
                f" — ${li.get('price', '?')}")
        if li.get("sku"):
            item += f" (SKU <code>{li['sku']}</code>)"
        if pid in links:
            item += f"\n    ↳ Supplier: {links[pid]}"
        lines.append(item)

    address = ", ".join(x for x in [
        ship.get("address1"), ship.get("address2"), ship.get("city"),
        ship.get("province"), ship.get("zip"), ship.get("country"),
    ] if x)

    if cj_result:
        status_line = f"🤖 <b>CJ auto-order placed</b> — CJ ID <code>{cj_result}</code>"
    elif cj_enabled() and unmapped:
        status_line = ("⚠️ CJ enabled but some SKUs are unmapped — "
                       "<b>place this order manually</b> (or add them to CJ_SKU_MAP).")
    else:
        status_line = "👉 <b>Action needed:</b> place this order with the supplier (DSers or the links above)."

    msg = (
        f"🛒 <b>NEW PAID ORDER {payload.get('name', '')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 {ship.get('name') or 'Customer'} | 💰 ${payload.get('total_price', '?')}\n"
        f"📍 {address or 'No shipping address'}\n"
        f"📞 {ship.get('phone') or (payload.get('customer') or {}).get('phone') or '—'}\n\n"
        f"<b>Items:</b>\n" + "\n".join(lines) + f"\n\n{status_line}"
    )
    await telegram_service.send_message(msg)


@router.post("/order-created")
async def shopify_order_created(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Handle Shopify 'orders/create' (register the webhook for orders/paid ideally)."""
    body = await request.body()
    if not verify_shopify_hmac(body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Invalid HMAC")

    payload = json.loads(body)
    shopify_order_id = str(payload.get("id"))
    customer = payload.get("customer", {}) or {}
    shipping = payload.get("shipping_address", {}) or {}
    line_items = payload.get("line_items", [])

    # Idempotency: Shopify retries webhooks; never double-process an order.
    result = await db.execute(select(Order).where(Order.shopify_order_id == shopify_order_id))
    existing = result.scalar_one_or_none()
    if existing:
        logger.info("Order %s already exists. Skipping.", shopify_order_id)
        return {"status": "skipped", "reason": "exists"}

    # Optional CJ auto-order — only for mapped SKUs, only if explicitly enabled.
    cj_order_id: Optional[str] = None
    unmapped: List[Dict[str, Any]] = line_items
    if cj_enabled():
        mapped, unmapped = cj_service.map_line_items(line_items, load_sku_map())
        if mapped and not unmapped:
            cj_order_id = await cj_service.create_order(payload, mapped)
            if not cj_order_id:
                logger.error("CJ auto-order FAILED for %s — falling back to manual", payload.get("name"))
        elif mapped and unmapped:
            logger.warning("Order %s partially mapped (%d/%d items) — manual fulfillment",
                           payload.get("name"), len(mapped), len(line_items))

    order = Order(
        shopify_order_id=shopify_order_id,
        customer_name=f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip() or "Unknown",
        customer_phone=customer.get("phone") or shipping.get("phone"),
        customer_email=customer.get("email"),
        total=float(payload.get("total_price", "0")),
        status=payload.get("financial_status", "unknown"),
        fraud_score=0.0,
        fulfillment_status="cj_ordered" if cj_order_id else "pending",
        shipping_address_json=shipping,
        items_json={"line_items": line_items, "cj_order_id": cj_order_id},
    )
    db.add(order)
    await db.commit()
    logger.info("Order %s created (Shopify ID %s, CJ %s).", order.id, shopify_order_id, cj_order_id)

    await _notify_new_order(payload, db, cj_order_id, unmapped)
    return {"status": "ok"}


@router.post("/order-updated")
async def shopify_order_updated(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Handle Shopify 'orders/updated' webhook."""
    body = await request.body()
    if not verify_shopify_hmac(body, x_shopify_hmac_sha256):
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
    prior = order.items_json or {}
    order.items_json = {"line_items": payload.get("line_items", []),
                        "cj_order_id": prior.get("cj_order_id")}
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
    if not verify_shopify_hmac(body, x_shopify_hmac_sha256):
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
