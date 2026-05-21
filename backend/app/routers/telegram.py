"""Telegram notification REST API router."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.services.telegram_service import telegram_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/telegram", tags=["telegram"])


async def _verify_telegram_token() -> str:
    """Development bypass; production should check Bearer token."""
    return "demo"


@router.post("/send")
async def telegram_send(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a Telegram notification message.

    Request body: {"message": "your text here"}
    """
    message = payload.get("message", "")
    if not message:
        raise HTTPException(status_code=422, detail="Field 'message' is required")

    result = await telegram_service.send_message(message)
    if result.get("status") == "ok":
        return result
    raise HTTPException(status_code=500, detail=result.get("details", "Send failed"))


@router.post("/test")
async def telegram_test() -> Dict[str, Any]:
    """Send a test message to verify Telegram is working."""
    test_msg = (
        "AI Dropship Bot is online! You will receive product approvals "
        "and order alerts here. Reply YES or NO to approve actions."
    )
    result = await telegram_service.send_message(test_msg)
    if result.get("status") == "ok":
        return {"status": "ok", "message": "Test message sent", "result": result}
    return {"status": "error", "result": result}
