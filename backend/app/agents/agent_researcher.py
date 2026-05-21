"""Product Research Specialist — auto-creates Telegram decisions."""
import logging
from typing import Any, Dict
import httpx
from app.agents.crew_setup import create_agent, wrap_async_tool
from app.agents.tools import create_scrape_trending_products_tool, create_analyze_google_trends_tool, create_check_facebook_ads_tool, create_request_human_decision_tool
from app.agents.memory import conversation_memory
from app.services.scraper import scraper

logger = logging.getLogger(__name__)

class AgentResearcher:
    def __init__(self): self.agent = self._build_agent()

    def _build_tools(self):
        tools = [create_scrape_trending_products_tool(), create_analyze_google_trends_tool(), create_check_facebook_ads_tool(), create_request_human_decision_tool()]
        for t in tools:
            if hasattr(t["func"],"__call__"): t["func"] = wrap_async_tool(t["func"])
        return tools

    def _build_agent(self):
        return create_agent(role="Product Research Specialist", goal="Find winning products. Score > 75 = auto-create Telegram approval.", backstory="Expert e-commerce researcher using 13-factor scoring.", tools=self._build_tools(), allow_delegation=False, verbose=True)

    async def run(self, limit=10):
        logger.info("[Researcher] Starting limit=%s", limit)
        conversation_memory.update_agent_state("researcher", {"state":"running"})
        raw = await scraper.scrape_trending_products(limit=limit)
        products = []; decisions = 0

        for p in raw:
            scores = p.get("scores",{}); total = sum(scores.values())
            rec = {"title":p["title"],"description":p["description"],"supplier_url":p["supplier_url"],"cost_price":p["cost_price"],"suggested_sell_price":p["suggested_sell_price"],"margin":p.get("margin",round(p["suggested_sell_price"]-p["cost_price"],2)),"scores":scores,"total_score":total}
            products.append(rec)

            if total > 75:
                try:
                    from datetime import datetime, timedelta, timezone
                    src = p.get("source_data",{}); reddit = src.get("reddit",{}); trends = src.get("google_trends",{})
                    context = {"product_title":p["title"],"price":p["suggested_sell_price"],"cost":p["cost_price"],"margin":f"{int((p['suggested_sell_price']-p['cost_price'])/p['suggested_sell_price']*100)}%" if p["suggested_sell_price"]>0 else "N/A","supplier":p["supplier_url"],"category":"Trending Products","scores":scores,"total_score":total,"source":reddit.get("subreddit","Reddit"),"upvotes":reddit.get("upvotes",0),"trend_interest":trends.get("interest_score",0),"aliexpress_listings":src.get("aliexpress_listings",0)}
                    sms = f"Found '{p['title'][:40]}' on {reddit.get('subreddit','Reddit')} ({reddit.get('upvotes',0)} upvotes). Sell: ${p['suggested_sell_price']:.2f} | Cost: ${p['cost_price']:.2f}. Score: {total}/130."
                    timeout = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post("http://localhost:8000/api/decisions", json={"agent_name":"researcher","decision_type":"product_approval","context_json":context,"sms_text_sent":sms,"timeout_at":timeout}, headers={"Authorization":"Bearer change_this_to_a_random_32_char_string"})
                        if resp.status_code == 201: decisions += 1; logger.info("[Researcher] Decision for '%s'", p["title"])
                        else: logger.warning("[Researcher] API: %s", resp.status_code)
                except Exception as e: logger.error("[Researcher] Decision error: %s", e)

        conversation_memory.update_agent_state("researcher", {"state":"idle","products_found":len(products),"decisions_created":decisions})
        logger.info("[Researcher] Done: %s products, %s decisions", len(products), decisions)
        return {"products":products,"high_scorers":[p for p in products if p["total_score"]>75],"decisions_created":decisions}

    async def analyze_keyword(self, keyword):
        trends = await scraper.analyze_google_trends(keyword)
        ads = await scraper.check_facebook_ads(keyword)
        return {"keyword":keyword,"trends":trends,"ads":ads}