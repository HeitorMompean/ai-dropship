"""Agent status, trigger, and logs REST API router."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AgentLog
from app import schemas
from app.agents.memory import conversation_memory
from app.agents.agent_researcher import AgentResearcher
from app.agents.agent_storekeeper import AgentStorekeeper
from app.agents.agent_fulfillment import AgentFulfillment
from app.agents.agent_support import AgentSupport
from app.agents.agent_marketer import AgentMarketer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])

_AGENT_MAP = {
    "researcher": AgentResearcher,
    "storekeeper": AgentStorekeeper,
    "fulfillment": AgentFulfillment,
    "support": AgentSupport,
    "marketer": AgentMarketer,
}


@router.get("/status", response_model=schemas.AgentStatusResponse)
async def agent_status() -> Dict[str, Any]:
    """Return current runtime status of all agents."""
    states = conversation_memory.get_all_agent_states()
    agents = []
    for name in ["researcher", "storekeeper", "fulfillment", "support", "marketer", "orchestrator"]:
        st = states.get(name, {})
        agents.append(
            schemas.AgentStatus(
                name=name,
                state=st.get("state", "idle"),
                last_run=st.get("updated_at"),
                next_run=None,
                recent_error=st.get("error"),
            )
        )
    return {"agents": agents}


@router.post("/{name}/trigger")
async def trigger_agent(
    name: str,
    payload: schemas.AgentTriggerRequest,
) -> Dict[str, Any]:
    """Manually trigger an agent run."""
    if name not in _AGENT_MAP:
        raise HTTPException(status_code=404, detail="Unknown agent name")

    agent_cls = _AGENT_MAP[name]
    agent = agent_cls()
    try:
        result = await agent.run()
        return {"status": "ok", "agent": name, "result": result}
    except Exception as exc:
        logger.error("Agent %s trigger failed: %s", name, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/logs", response_model=schemas.AgentLogListResponse)
async def agent_logs(
    agent_name: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get recent agent activity logs."""
    query = select(AgentLog).order_by(AgentLog.created_at.desc())
    if agent_name:
        query = query.where(AgentLog.agent_name == agent_name)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"items": items, "total": total}
