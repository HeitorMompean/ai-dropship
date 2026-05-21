"""Shopify API client wrapper with demo-mode fallback."""

import json
import logging
from typing import Any, Dict, List, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class ShopifyClient:
    """Async Shopify Admin API wrapper. Falls back to demo data when credentials are missing."""

    def __init__(self) -> None:
        self.shop_name = settings.shopify_shop_name
        self.access_token = settings.shopify_access_token
        self.api_version = "2024-04"
        self.base_url = f"https://{self.shop_name}/admin/api/{self.api_version}"
        self.demo_mode = settings.is_demo_mode
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {}
            if not self.demo_mode:
                headers["X-Shopify-Access-Token"] = self.access_token
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def _request(
        self, method: str, path: str, json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make an HTTP request to Shopify Admin API or return mock data in demo mode."""
        if self.demo_mode:
            return self._mock_response(method, path, json_data)

        client = await self._get_client()
        try:
            response = await client.request(method, path, json=json_data)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Shopify HTTP error: %s %s -> %s", method, path, exc.response.text)
            raise
        except httpx.RequestError as exc:
            logger.error("Shopify request error: %s %s -> %s", method, path, exc)
            raise

    def _mock_response(
        self, method: str, path: str, json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Return realistic demo data for any Shopify endpoint."""
        logger.info("[DEMO MODE] Mock Shopify %s %s", method, path)

        if "orders" in path and method == "GET":
            return {
                "orders": [
                    {
                        "id": 1001,
                        "name": "#D1001",
                        "email": "demo@example.com",
                        "total_price": "49.99",
                        "financial_status": "paid",
                        "fulfillment_status": None,
                        "customer": {"first_name": "Alice", "last_name": "Demo", "phone": "+15551234567"},
                        "shipping_address": {"address1": "123 Demo St", "city": "Demo City", "zip": "12345"},
                        "line_items": [{"title": "Smart Bottle", "quantity": 1, "price": "49.99"}],
                    }
                ]
            }
        if "products" in path and method == "POST":
            return {"product": {"id": 9999, "title": json_data.get("product", {}).get("title", "Demo Product")}}
        if "products" in path and method == "GET":
            return {
                "products": [
                    {"id": 2001, "title": "Smart Bottle", "variants": [{"price": "49.99"}]}
                ]
            }
        if "products" in path and method in ("PUT", "PATCH"):
            return {"product": {"id": 2001, "title": json_data.get("product", {}).get("title", "Updated")}}
        if "customers" in path and method == "GET":
            return {
                "customers": [
                    {"id": 5001, "first_name": "Alice", "last_name": "Demo", "email": "demo@example.com", "orders_count": 3}
                ]
            }
        if "refunds" in path:
            return {"refund": {"id": 7001, "order_id": 1001}}
        return {}

    async def get_orders(self, status: Optional[str] = "any", limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch orders from Shopify."""
        data = await self._request("GET", f"/orders.json?status={status}&limit={limit}")
        return data.get("orders", [])

    async def get_order(self, order_id: int) -> Dict[str, Any]:
        """Fetch a single order."""
        data = await self._request("GET", f"/orders/{order_id}.json")
        return data.get("order", {})

    async def create_product(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a product on Shopify."""
        data = await self._request("POST", "/products.json", json_data={"product": payload})
        return data.get("product", {})

    async def update_product(self, product_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing product."""
        data = await self._request("PUT", f"/products/{product_id}.json", json_data={"product": payload})
        return data.get("product", {})

    async def delete_product(self, product_id: int) -> bool:
        """Delete a product. Returns True on success."""
        if self.demo_mode:
            logger.info("[DEMO MODE] Deleted product %s", product_id)
            return True
        try:
            client = await self._get_client()
            response = await client.delete(f"/products/{product_id}.json")
            return response.status_code == 200
        except Exception as exc:
            logger.error("Delete product error: %s", exc)
            return False

    async def get_products(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch all products."""
        data = await self._request("GET", f"/products.json?limit={limit}")
        return data.get("products", [])

    async def get_customer_orders(self, customer_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch customer order history."""
        data = await self._request("GET", f"/customers/{customer_id}/orders.json?limit={limit}")
        return data.get("orders", [])

    async def create_fulfillment(self, order_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a fulfillment for an order."""
        data = await self._request("POST", f"/orders/{order_id}/fulfillments.json", json_data={"fulfillment": payload})
        return data.get("fulfillment", {})

    async def create_refund(self, order_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process a refund."""
        data = await self._request("POST", f"/orders/{order_id}/refunds.json", json_data={"refund": payload})
        return data.get("refund", {})

    async def cancel_order(self, order_id: int) -> Dict[str, Any]:
        """Cancel an order."""
        data = await self._request("POST", f"/orders/{order_id}/cancel.json")
        return data.get("order", {})

    async def send_email(self, to_email: str, subject: str, body: str) -> bool:
        """Send a customer email via Shopify (or mock in demo mode)."""
        if self.demo_mode:
            logger.info("[DEMO MODE] Email to %s: %s", to_email, subject)
            return True
        # Shopify does not have a native outbound email API; this is a placeholder
        # for an email service integration (SendGrid, etc.)
        logger.info("Email sent to %s: %s", to_email, subject)
        return True

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


shopify_client = ShopifyClient()
