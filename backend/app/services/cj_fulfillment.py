"""CJ Dropshipping fulfillment service.

Uses CJ's REAL current API (verified against developers.cjdropshipping.com docs):
  - Auth:   POST /api2.0/v1/authentication/getAccessToken  {"apiKey": "..."}
            -> accessToken (15-day life; server caches the same token for 24h)
  - Order:  POST /api2.0/v1/shopping/order/createOrderV2   (CJ-Access-Token header)
  - Status: GET  /api2.0/v1/shopping/order/getOrderDetail?orderId=...
  - Rate limit: ~1 request/second -> a lock + minimum interval is enforced here.

NOTE: an older base URL (api.cjdropshipping.com/api/order/createOrderV2) floats
around in guides; it is stale. Do not switch to it.

Env vars (all read directly so config.py needs no changes):
  CJ_ENABLED         "true" to allow auto-ordering (default: off -> manual mode)
  CJ_API_KEY         from CJ dashboard: My CJ -> Authorization -> API
  CJ_DEFAULT_LOGISTIC  e.g. "CJPacket Ordinary" (default) or "USPS+"
  CJ_FROM_COUNTRY    default "CN" (use "US" if sourcing from CJ US warehouse)
  CJ_SKU_MAP         JSON mapping Shopify SKU (or variant id as string) -> CJ
                     variant id, e.g. {"GRINDER-01": "92511400-C758-4474-...."}

Auto-ordering only fires for line items that have a mapping in CJ_SKU_MAP.
Unmapped items fall back to the manual Telegram card — safe by default.
"""

import os
import json
import time
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

CJ_BASE = "https://developers.cjdropshipping.com/api2.0/v1"


def cj_enabled() -> bool:
    return os.getenv("CJ_ENABLED", "").strip().lower() in ("1", "true", "yes") and bool(
        os.getenv("CJ_API_KEY", "").strip()
    )


def cj_research_enabled() -> bool:
    """Research lookups (US-warehouse checks) need only the API key —
    they run even while auto-ORDERING (CJ_ENABLED) is still off."""
    return bool(os.getenv("CJ_API_KEY", "").strip())


def load_sku_map() -> Dict[str, str]:
    """Shopify SKU / variant-id -> CJ variant id (vid). Empty dict if unset/invalid."""
    raw = os.getenv("CJ_SKU_MAP", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as e:
        logger.error("[CJ] CJ_SKU_MAP is not valid JSON: %s", e)
    return {}


class CJFulfillmentService:
    def __init__(self) -> None:
        self._api_key = os.getenv("CJ_API_KEY", "")
        self._token: Optional[str] = None
        self._token_fetched_at: float = 0.0
        self._lock = asyncio.Lock()          # serialize calls (CJ QPS = 1)
        self._last_call: float = 0.0

    # ------------------------------------------------------------- rate limit
    async def _throttle(self) -> None:
        wait = 1.1 - (time.monotonic() - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.monotonic()

    # ------------------------------------------------------------------ auth
    async def _get_token(self, client: httpx.AsyncClient) -> Optional[str]:
        # CJ caches the token server-side for 24h; token itself lives 15 days.
        # Refresh ours every 12h to stay well inside both windows.
        if self._token and (time.monotonic() - self._token_fetched_at) < 12 * 3600:
            return self._token
        await self._throttle()
        try:
            resp = await client.post(
                f"{CJ_BASE}/authentication/getAccessToken",
                json={"apiKey": self._api_key},
                timeout=30.0,
            )
            data = resp.json()
            if data.get("code") == 200 and data.get("data", {}).get("accessToken"):
                self._token = data["data"]["accessToken"]
                self._token_fetched_at = time.monotonic()
                logger.info("[CJ] Access token obtained")
                return self._token
            logger.error("[CJ] Auth failed: %s", str(data)[:300])
        except Exception as e:
            logger.error("[CJ] Auth error: %s", e)
        return None

    async def _call(self, method: str, path: str,
                    json_body: Optional[dict] = None,
                    params: Optional[dict] = None) -> Optional[dict]:
        async with self._lock:
            async with httpx.AsyncClient(timeout=40.0) as client:
                token = await self._get_token(client)
                if not token:
                    return None
                await self._throttle()
                try:
                    resp = await client.request(
                        method, f"{CJ_BASE}{path}",
                        headers={"CJ-Access-Token": token,
                                 "Content-Type": "application/json"},
                        json=json_body, params=params,
                    )
                    data = resp.json()
                    if data.get("code") != 200:
                        logger.error("[CJ] %s %s -> %s", method, path, str(data)[:300])
                        return None
                    return data.get("data")
                except Exception as e:
                    logger.error("[CJ] %s %s error: %s", method, path, e)
                    return None

    # -------------------------------------------------------------- order API
    async def find_us_stock(self, keyword: str) -> Optional[Dict[str, Any]]:
        """Search CJ's catalog for `keyword` filtered to US-warehouse inventory.

        Uses the verified /product/listV2 endpoint, which accepts a countryCode
        filter ("filter products with inventory in specified countries") — one
        call answers "is this product TikTok-Shop-eligible (US stock)?".
        Returns {pid, sku, name, sell_price, us_inventory} for the best match,
        or None when nothing with US stock is found.
        """
        data = await self._call(
            "GET", "/product/listV2",
            params={"keyWord": keyword[:200], "countryCode": "US",
                    "page": 1, "size": 5, "orderBy": 4, "sort": "desc"},
        )
        try:
            content = (data or {}).get("content") or []
            products = content[0].get("productList") or [] if content else []
            for p in products:
                inv = int(p.get("warehouseInventoryNum") or 0)
                if inv > 0:
                    return {
                        "pid": p.get("id"),
                        "sku": p.get("sku"),
                        "name": p.get("nameEn"),
                        "sell_price": p.get("sellPrice"),
                        "us_inventory": inv,
                    }
        except Exception as e:
            logger.warning("[CJ] find_us_stock parse error for '%s': %s", keyword, e)
        return None

    @staticmethod
    def build_order_payload(shopify_order: Dict[str, Any],
                            mapped_products: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build a createOrderV2 payload from a Shopify order dict."""
        ship = shopify_order.get("shipping_address") or {}
        return {
            "orderNumber": str(shopify_order.get("name") or shopify_order.get("id")),
            "shippingCustomerName": ship.get("name")
                or f"{ship.get('first_name','')} {ship.get('last_name','')}".strip(),
            "shippingAddress": ship.get("address1", ""),
            "shippingAddress2": ship.get("address2") or "",
            "shippingCity": ship.get("city", ""),
            "shippingProvince": ship.get("province", ""),
            "shippingZip": ship.get("zip", ""),
            "shippingCountry": ship.get("country", ""),
            "shippingCountryCode": ship.get("country_code", "US"),
            "shippingPhone": ship.get("phone")
                or (shopify_order.get("customer") or {}).get("phone") or "",
            "email": shopify_order.get("email") or "",
            "remark": "auto-order from ai-dropship",
            "platform": "shopify",
            "logisticName": os.getenv("CJ_DEFAULT_LOGISTIC", "CJPacket Ordinary"),
            "fromCountryCode": os.getenv("CJ_FROM_COUNTRY", "CN"),
            "payType": 2,  # 2 = pay from CJ wallet balance
            "products": mapped_products,  # [{"vid": "...", "quantity": n}]
        }

    @staticmethod
    def map_line_items(line_items: List[Dict[str, Any]],
                       sku_map: Dict[str, str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Split Shopify line items into (mapped-for-CJ, unmapped)."""
        mapped, unmapped = [], []
        for li in line_items:
            key = str(li.get("sku") or "") or str(li.get("variant_id") or "")
            vid = sku_map.get(key)
            if vid:
                mapped.append({"vid": vid, "quantity": int(li.get("quantity", 1)),
                               "storeLineItemId": str(li.get("id", ""))})
            else:
                unmapped.append(li)
        return mapped, unmapped

    async def create_order(self, shopify_order: Dict[str, Any],
                           mapped_products: List[Dict[str, Any]]) -> Optional[str]:
        """Place the CJ order. Returns CJ orderId or None."""
        payload = self.build_order_payload(shopify_order, mapped_products)
        data = await self._call("POST", "/shopping/order/createOrderV2", json_body=payload)
        if data:
            order_id = data.get("orderId") or (data if isinstance(data, str) else None)
            logger.info("[CJ] Order created: %s for Shopify %s", order_id, payload["orderNumber"])
            return str(order_id) if order_id else None
        return None

    async def get_order_detail(self, cj_order_id: str) -> Optional[Dict[str, Any]]:
        """Order detail; includes trackNumber once shipped."""
        return await self._call("GET", "/shopping/order/getOrderDetail",
                                params={"orderId": cj_order_id})

    async def sync_tracking_to_shopify(self, shopify_order_id: int,
                                       tracking_number: str,
                                       tracking_company: str = "CJPacket") -> bool:
        """Mark the Shopify order fulfilled with tracking (emails the customer)."""
        try:
            from app.services.shopify_client import shopify_client
            payload = {
                "fulfillment": {
                    "notify_customer": True,
                    "tracking_info": {"number": tracking_number,
                                      "company": tracking_company},
                }
            }
            result = await shopify_client.create_fulfillment(int(shopify_order_id), payload)
            return bool(result)
        except Exception as e:
            logger.error("[CJ] Shopify tracking sync failed: %s", e)
            return False


cj_service = CJFulfillmentService()
