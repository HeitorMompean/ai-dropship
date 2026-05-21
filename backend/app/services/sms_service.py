"""SMS service wrapper around the android-sms-gateway REST API."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class SMSService:
    """Send and receive SMS via the android-sms-gateway REST API."""

    def __init__(self) -> None:
        self.base_url = settings.sms_gateway_base_url.rstrip("/")
        self.device_id = settings.sms_gateway_device_id
        self.owner_phone = settings.owner_phone_number
        self.demo_mode = settings.is_demo_mode
        self._client: Optional[httpx.AsyncClient] = None
        self.auth = httpx.BasicAuth("sms", "12345678")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                auth=self.auth,
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def send_sms(self, to: str, message: str) -> Dict[str, Any]:
        """Send an SMS message through the gateway.

        In demo mode, the message is logged but not actually sent.
        """
        if self.demo_mode:
            logger.info("[DEMO SMS] To %s: %s", to, message)
            return {
                "id": f"demo-{datetime.utcnow().timestamp()}",
                "status": "sent",
                "to": to,
                "message": message,
                "demo": True,
            }

        client = await self._get_client()
        payload = {
            "deviceId": self.device_id,
            "message": message,
            "phoneNumbers": [to],
        }
        try:
            response = await client.post("/api/v1/messages", json=payload)
            response.raise_for_status()
            data = response.json()
            logger.info("SMS sent to %s, id=%s", to, data.get("id"))
            return data
        except httpx.HTTPStatusError as exc:
            logger.error("SMS gateway HTTP error: %s", exc.response.text)
            return {"error": "http_error", "details": exc.response.text}
        except httpx.RequestError as exc:
            logger.error("SMS gateway request error: %s", exc)
            return {"error": "request_error", "details": str(exc)}

    async def send_to_owner(self, message: str) -> Dict[str, Any]:
        """Convenience method to send SMS to the store owner."""
        return await self.send_sms(self.owner_phone, message)

    def process_inbound_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process an inbound SMS webhook payload.

        Expected payload keys: message, phoneNumber, timestamp, messageId
        Returns a normalized dict for the API layer.
        """
        normalized = {
            "from": payload.get("phoneNumber", "").strip(),
            "body": payload.get("message", "").strip(),
            "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
            "message_id": payload.get("messageId", ""),
        }
        logger.info("Inbound SMS from %s: %s", normalized["from"], normalized["body"])
        return normalized

    async def get_messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent messages from the gateway (if supported)."""
        if self.demo_mode:
            return []
        client = await self._get_client()
        try:
            response = await client.get(f"/api/v1/messages?limit={limit}")
            response.raise_for_status()
            return response.json().get("data", [])
        except Exception as exc:
            logger.error("Failed to fetch messages: %s", exc)
            return []

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


sms_service = SMSService()

