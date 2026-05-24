from fastapi import APIRouter, Request

router = APIRouter(prefix="/telegram", tags=["telegram_webhook"])

@router.post("/webhook")
async def telegram_webhook(request: Request):
    return {"ok": True}
