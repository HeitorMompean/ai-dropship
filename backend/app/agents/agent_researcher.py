"""Product Research Specialist — auto-creates Telegram decisions with notifications."""
import os
import logging
from typing import Any, Dict, Set
import httpx
from datetime import datetime, timedelta, timezone

from app.agents.crew_setup import create_agent, wrap_async_tool
from app.agents.tools import (
    create_scrape_trending_products_tool,
    create_analyze_google_trends_tool,
    create_check_facebook_ads_tool,
    create_request_human_decision_tool,
)
from app.agents.memory import conversation_memory
from app.services.scraper import scraper
from app.services.telegram_service import telegram_service

logger = logging.getLogger(__name__)

# Module-level set to prevent duplicate Telegram messages across app reloads/instances
_GLOBAL_SENT_NOTIFICATIONS: Set[str] = set()


class AgentResearcher:
    def __init__(self):
        self.agent = self._build_agent()

    def _build_tools(self):
        tools = [
            create_scrape_trending_products_tool(),
            create_analyze_google_trends_tool(),
            create_check_facebook_ads_tool(),
            create_request_human_decision_tool(),
        ]
        for t in tools:
            if hasattr(t["func"], "__call__"):
                t["func"] = wrap_async_tool(t["func"])
        return tools

    def _build_agent(self):
        return create_agent(
            role="Product Research Specialist",
            goal="Find winning products. Score > 75 = auto-create Telegram approval.",
            backstory="Expert e-commerce researcher using 13-factor scoring.",
            tools=self._build_tools(),
            allow_delegation=False,
            verbose=True,
        )

    async def run(self, limit=10):
        logger.info("[Researcher] Starting limit=%s", limit)
        conversation_memory.update_agent_state("researcher", {"state": "running"})
        raw = await scraper.scrape_trending_products(limit=limit)
        products = []
        decisions = 0

        for p in raw:
            scores = p.get("scores", {})
            total = sum(scores.values())
            rec = {
                "title": p["title"],
                "description": p["description"],
                "supplier_url": p["supplier_url"],
                "cost_price": p["cost_price"],
                "suggested_sell_price": p["suggested_sell_price"],
                "margin": p.get("margin", round(p["suggested_sell_price"] - p["cost_price"], 2)),
                "scores": scores,
                "total_score": total,
            }
            products.append(rec)

            if total > 75:
                try:
                    src = p.get("source_data", {})
                    reddit = src.get("reddit", {})
                    trends = src.get("google_trends", {})
                    
                    context = {
                        "product_title": p["title"],
                        "price": p["suggested_sell_price"],
                        "cost": p["cost_price"],
                        "margin": f"{int((p['suggested_sell_price'] - p['cost_price']) / p['suggested_sell_price'] * 100)}%" if p["suggested_sell_price"] > 0 else "N/A",
                        "supplier": p["supplier_url"],
                        "category": "Trending Products",
                        "scores": scores,
                        "total_score": total,
                        "source": reddit.get("subreddit", "Reddit"),
                        "upvotes": reddit.get("upvotes", 0),
                        "trend_interest": trends.get("interest_score", 0),
                        "aliexpress_listings": src.get("aliexpress_listings", 0),
                    }
                    
                    sms = (
                        f"Found '{p['title'][:40]}' on {reddit.get('subreddit', 'Reddit')} "
                        f"({reddit.get('upvotes', 0)} upvotes). Sell: ${p['suggested_sell_price']:.2f} | "
                        f"Cost: ${p['cost_price']:.2f}. Score: {total}/130."
                    )
                    timeout = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

                    # Use dynamic port (Railway assigns PORT env var, defaults to 8080)
                    port = os.getenv("PORT", "8080")

                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            f"http://127.0.0.1:{port}/api/decisions",
                            json={
                                "agent_name": "researcher",
                                "decision_type": "product_approval",
                                "context_json": context,
                                "sms_text_sent": sms,
                                "timeout_at": timeout,
                            },
                            headers={"Authorization": "Bearer change_this_to_a_random_32_char_string"},
                        )
                        
                        if resp.status_code == 201:
                            decision_data = resp.json()
                            decision_id = decision_data.get("id")
                            logger.info("[Researcher] Decision %s created for '%s'", decision_id, p["title"])

                            # DEDUPLICATION: Prevent sending the same product to Telegram twice
                            product_title = context.get("product_title", "")
                            notification_key = f"{product_title}_{datetime.now(timezone.utc).date()}"

                            if notification_key not in _GLOBAL_SENT_NOTIFICATIONS:
                                _GLOBAL_SENT_NOTIFICATIONS.add(notification_key)

                                if decision_id:
                                    try:
                                        await telegram_service.send_approval_request(
                                            decision_id=decision_id,
                                            agent_name="researcher",
                                            decision_type="product_approval",
                                            sms_text=sms,
                                            context=context,
                                        )
                                        logger.info("[Researcher] Telegram notification sent for decision %s", decision_id)
                                    except Exception as te:
                                        logger.error("[Researcher] Telegram send failed: %s", te)

                            decisions += 1
                        else:
                            logger.warning("[Researcher] API status: %s body: %s", resp.status_code, resp.text[:200])
                except Exception as e:
                    logger.error("[Researcher] Decision error: %s", e)

        conversation_memory.update_agent_state(
            "researcher",
            {"state": "idle", "products_found": len(products), "decisions_created": decisions},
        )
        logger.info("[Researcher] Done: %s products, %s decisions", len(products), decisions)
        return {
            "products": products,
            "high_scorers": [p for p in products if p["total_score"] > 75],
            "decisions_created": decisions,
        }

    async def analyze_keyword(self, keyword):
        trends = await scraper.analyze_google_trends(keyword)
        ads = await scraper.check_facebook_ads(keyword)
        return {"keyword": keyword, "trends": trends, "ads": ads}
