"""Store settings REST API router."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import StoreSetting
from app import schemas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=schemas.SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Get all store settings grouped by category."""
    result = await db.execute(select(StoreSetting))
    items = result.scalars().all()
    settings_map: Dict[str, str] = {}
    categories: Dict[str, List[str]] = {}
    for s in items:
        settings_map[s.key] = s.value
        categories.setdefault(s.category, []).append(s.key)
    return {"settings": settings_map, "categories": categories}


@router.patch("")
async def update_settings(
    payload: schemas.SettingsPatch,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Update multiple store settings."""
    for key, value in payload.settings.items():
        result = await db.execute(select(StoreSetting).where(StoreSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            db.add(StoreSetting(key=key, value=value, category="general"))
    await db.commit()
    logger.info("Settings updated: %s", list(payload.settings.keys()))
    return {"status": "ok", "updated": list(payload.settings.keys())}
