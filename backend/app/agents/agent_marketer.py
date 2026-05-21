"""Performance Marketing Analyst agent implementation."""

import json
import logging
from typing import Any, Dict, List, Optional

from crewai import Agent

from app.agents.crew_setup import create_agent, wrap_async_tool
from app.agents.tools import (
    create_get_daily_metrics_tool,
    create_calculate_true_profit_tool,
    create_get_ad_performance_tool,
    create_request_human_decision_tool,
)
from app.agents.memory import conversation_memory
from app.services.analytics_engine import analytics_engine

logger = logging.getLogger(__name__)


class AgentMarketer:
    """Monitor metrics and optimize store profitability.

    When metrics are outside bounds for 3+ days, requests human decision.
    """

    PROFIT_WARNING_DAYS = 3
    PROFIT_WARNING_THRESHOLD = -20.0  # cumulative profit over N days

    def __init__(self) -> None:
        self.agent = self._build_agent()
        self._profit_history: List[float] = []

    def _build_tools(self) -> List[Any]:
        tools = [
            create_get_daily_metrics_tool(),
            create_calculate_true_profit_tool(),
            create_get_ad_performance_tool(),
            create_request_human_decision_tool(),
        ]
        for t in tools:
            if hasattr(t["func"], "__call__"):
                t["func"] = wrap_async_tool(t["func"])
        return tools

    def _build_agent(self) -> Agent:
        return create_agent(
            role="Performance Marketing Analyst",
            goal=(
                "Monitor store metrics and optimize profitability. "
                "When metrics are outside safe bounds for 3+ days, request human intervention."
            ),
            backstory=(
                "You are a data-driven marketing analyst who lives by numbers. You track ROAS, conversion rates, "
                "and profit margins daily. You spot trends before they become problems and recommend budget shifts "
                "or ad pauses when performance drops. You always alert the owner when the store is losing money consistently."
            ),
            tools=self._build_tools(),
            allow_delegation=False,
            verbose=True,
        )

    async def check_metrics(self) -> Dict[str, Any]:
        """Fetch daily metrics and check for sustained underperformance."""
        logger.info("[AgentMarketer] Checking metrics...")
        conversation_memory.update_agent_state("marketer", {"state": "running", "action": "check_metrics"})

        metrics = analytics_engine.get_daily_metrics_mock()
        profit = metrics.get("profit", 0)
        self._profit_history.append(profit)
        if len(self._profit_history) > 7:
            self._profit_history.pop(0)

        warning_triggered = False
        if len(self._profit_history) >= self.PROFIT_WARNING_DAYS:
            recent_profit = sum(self._profit_history[-self.PROFIT_WARNING_DAYS:])
            if recent_profit < self.PROFIT_WARNING_THRESHOLD:
                warning_triggered = True
                context = {
                    "agent_name": "marketer",
                    "decision_type": "metrics_alert",
                    "recent_profit": recent_profit,
                    "days": self.PROFIT_WARNING_DAYS,
                    "metrics": metrics,
                }
                sms_text = (
                    f"STORE ALERT: Profit ${recent_profit:.2f} last {self.PROFIT_WARNING_DAYS} days. "
                    f"Visitors {metrics.get('visitors')}, Orders {metrics.get('orders')}. "
                    f"Reply 'PAUSE ADS' to pause, 'INCREASE BUDGET' to boost, 'CHECK' to review."
                )
                tool = create_request_human_decision_tool()
                await tool["func"](json.dumps(context), sms_text)

        conversation_memory.update_agent_state(
            "marketer",
            {"state": "idle", "profit": profit, "warning": warning_triggered},
        )
        return {"metrics": metrics, "warning_triggered": warning_triggered, "profit_history": self._profit_history}

    async def daily_report(self) -> Dict[str, Any]:
        """Generate a daily summary report."""
        metrics = analytics_engine.get_daily_metrics_mock()
        ads = analytics_engine.get_ad_performance_mock(days=1)
        report = {
            "date": metrics.get("date"),
            "revenue": metrics.get("revenue"),
            "profit": metrics.get("profit"),
            "orders": metrics.get("orders"),
            "visitors": metrics.get("visitors"),
            "conversion_rate": metrics.get("conversion_rate"),
            "ad_spend": ads.get("spend"),
            "roas": ads.get("roas"),
        }
        logger.info("[AgentMarketer] Daily report: %s", report)
        conversation_memory.update_agent_state("marketer", {"state": "idle", "last_report": report})
        return report

    async def run(self) -> Dict[str, Any]:
        """Default run delegates to check_metrics."""
        return await self.check_metrics()
