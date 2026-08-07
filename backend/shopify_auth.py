import os
import threading
import time

import httpx

_cache = {"token": None, "expires_at": 0.0}
_lock = threading.Lock()


def get_shopify_token() -> str:
    """Return a valid Shopify Admin API token, auto-refreshing every ~24h."""
    now = time.time()
    if _cache["token"] and now < _cache["expires_at"] - 300:
        return _cache["token"]

    with _lock:
        now = time.time()
        if _cache["token"] and now < _cache["expires_at"] - 300:
            return _cache["token"]

        store = os.environ["SHOPIFY_STORE"]
        resp = httpx.post(
            f"https://{store}.myshopify.com/admin/oauth/access_token",
            json={
                "client_id": os.environ["SHOPIFY_CLIENT_ID"],
                "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        _cache["token"] = data["access_token"]
        _cache["expires_at"] = now + int(data.get("expires_in", 86399))
        return _cache["token"]


def shopify_headers() -> dict:
    """Drop-in replacement for your old headers dict."""
    return {
        "X-Shopify-Access-Token": get_shopify_token(),
        "Content-Type": "application/json",
    }
