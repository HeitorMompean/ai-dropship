"""Price tracking and monitoring service."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)


class PriceMonitorService:
    """Track competitor prices and detect significant changes."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client

    async def fetch_price(self, url: str, selector: Optional[str] = None) -> Optional[float]:
        """Fetch a competitor price from a URL.

        In a real implementation this would parse HTML (BeautifulSoup/Playwright).
        For MVP, returns None so the system degrades gracefully.
        """
        logger.info("Fetching price from %s", url)
        # Placeholder for real scraping
        return None

    async def check_price_change(
        self, old_price: float, new_price: Optional[float], threshold_pct: float = 10.0
    ) -> Dict[str, Any]:
        """Determine if a price change crosses the alert threshold."""
        if new_price is None:
            return {"changed": False, "reason": "unable_to_fetch"}

        diff = new_price - old_price
        pct = (diff / old_price) * 100 if old_price else 0.0
        changed = abs(pct) >= threshold_pct
        return {
            "changed": changed,
            "old_price": old_price,
            "new_price": new_price,
            "diff": diff,
            "pct": round(pct, 2),
            "threshold_pct": threshold_pct,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


price_monitor = PriceMonitorService()
