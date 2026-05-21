"""APScheduler configuration for periodic agent tasks."""

import logging
from typing import Any, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.agents.agent_researcher import AgentResearcher
from app.agents.agent_fulfillment import AgentFulfillment
from app.agents.agent_marketer import AgentMarketer
from app.agents.agent_support import AgentSupport
from app.agents.memory import conversation_memory

logger = logging.getLogger(__name__)


class AgentScheduler:
    """Manages APScheduler jobs for all AI agents."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self._researcher = AgentResearcher()
        self._fulfillment = AgentFulfillment()
        self._marketer = AgentMarketer()
        self._support = AgentSupport()

    def _log_agent_start(self, name: str) -> None:
        logger.info("[Scheduler] Starting job: %s", name)
        conversation_memory.update_agent_state(name, {"state": "running", "trigger": "scheduled"})

    def _log_agent_end(self, name: str, result: Any) -> None:
        logger.info("[Scheduler] Finished job: %s -> %s", name, result)

    async def _run_researcher(self) -> None:
        """Periodic product research job (every 6 hours)."""
        self._log_agent_start("researcher")
        try:
            result = await self._researcher.run(limit=10)
            self._log_agent_end("researcher", result)
        except Exception as exc:
            logger.error("[Scheduler] Researcher job failed: %s", exc)
            conversation_memory.update_agent_state("researcher", {"state": "error", "error": str(exc)})

    async def _run_fulfillment(self) -> None:
        """Periodic fulfillment check job (every 1 hour)."""
        self._log_agent_start("fulfillment")
        try:
            result = await self._fulfillment.check_pending_orders()
            self._log_agent_end("fulfillment", result)
        except Exception as exc:
            logger.error("[Scheduler] Fulfillment job failed: %s", exc)
            conversation_memory.update_agent_state("fulfillment", {"state": "error", "error": str(exc)})

    async def _run_marketer_metrics(self) -> None:
        """Periodic metrics check job (every 30 minutes)."""
        self._log_agent_start("marketer")
        try:
            result = await self._marketer.check_metrics()
            self._log_agent_end("marketer", result)
        except Exception as exc:
            logger.error("[Scheduler] Marketer metrics job failed: %s", exc)
            conversation_memory.update_agent_state("marketer", {"state": "error", "error": str(exc)})

    async def _run_marketer_daily_report(self) -> None:
        """Daily report job (at 9:00 AM)."""
        self._log_agent_start("marketer_daily_report")
        try:
            result = await self._marketer.daily_report()
            self._log_agent_end("marketer_daily_report", result)
        except Exception as exc:
            logger.error("[Scheduler] Marketer daily report job failed: %s", exc)

    async def _run_support_scan(self) -> None:
        """Periodic support scan job (every 2 hours)."""
        self._log_agent_start("support")
        try:
            result = await self._support.scan_reviews()
            self._log_agent_end("support", result)
        except Exception as exc:
            logger.error("[Scheduler] Support scan job failed: %s", exc)
            conversation_memory.update_agent_state("support", {"state": "error", "error": str(exc)})

    def setup_jobs(self) -> None:
        """Register all periodic jobs with the scheduler."""
        self.scheduler.add_job(
            self._run_researcher,
            trigger=IntervalTrigger(hours=6),
            id="researcher_6h",
            name="Product Research (6h)",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_fulfillment,
            trigger=IntervalTrigger(hours=1),
            id="fulfillment_1h",
            name="Order Fulfillment Check (1h)",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_marketer_metrics,
            trigger=IntervalTrigger(minutes=30),
            id="marketer_30m",
            name="Metrics Check (30m)",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_marketer_daily_report,
            trigger=CronTrigger(hour=9, minute=0),
            id="marketer_daily_9am",
            name="Daily Report (9am)",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_support_scan,
            trigger=IntervalTrigger(hours=2),
            id="support_2h",
            name="Support Scan (2h)",
            replace_existing=True,
        )
        logger.info("All scheduler jobs registered.")

    def start(self) -> None:
        """Start the scheduler."""
        self.setup_jobs()
        self.scheduler.start()
        logger.info("Scheduler started.")

    def shutdown(self) -> None:
        """Gracefully shut down the scheduler."""
        self.scheduler.shutdown(wait=True)
        logger.info("Scheduler shut down.")


# Singleton instance
agent_scheduler = AgentScheduler()
