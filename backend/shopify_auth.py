"""Shopify Admin API token manager — auto-refreshes via client credentials grant."""

import asyncio
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_cache = {"token": None, "expires_at": 0.0}
_lock = asyncio.Lock()


async def get_shopify_token(force_refresh: bool = False) -> str:
    """Return a valid Admin API access token, refreshing when expired (every ~24h)."""
    now = time.time()
    if not force_refresh and _cache["token"] and now < _cache["expires_at"] - 300:
        return _cache["token"]

    async with _lock:
        now = time.time()
        if not force_refresh and _cache["token"] and now < _cache["expires_at"] - 300:
            return _cache["token"]

        logger.info("Refreshing Shopify access token (client credentials grant)")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://{settings.shopify_shop_name}/admin/oauth/access_token",
                json={
                    "client_id": settings.shopify_client_id,
                    "client_secret": settings.shopify_client_secret,
                    "grant_type": "client_credentials",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        _cache["token"] = data["access_token"]
        _cache["expires_at"] = now + int(data.get("expires_in", 86399))
        logger.info("Shopify token refreshed successfully")
        return _cache["token"]


def invalidate_token() -> None:
    """Force next call to fetch a fresh token (used after a 401)."""
    _cache["token"] = None
    _cache["expires_at"] = 0.0
