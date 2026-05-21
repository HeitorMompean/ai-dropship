"""Facebook Ads Service for Vital Elements."""

import json
import logging
from typing import Any, Dict

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://graph.facebook.com/v18.0"


class FacebookAdsService:
    def __init__(self):
        self.access_token = getattr(settings, "facebook_access_token", "")
        self.account_id = getattr(settings, "facebook_ad_account_id", "").replace("act_", "")
        self.page_id = getattr(settings, "facebook_page_id", "")
        self._enabled = all([self.access_token, self.account_id, self.page_id])

    def is_configured(self):
        return self._enabled

    async def launch_full_ad(self, product_title, headline, body, cta="SHOP_NOW", daily_budget=20.0, link_url=""):
        if not self.is_configured():
            return {"status": "error", "error": "Not configured. Check .env file."}

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Campaign — token in URL, data= (form), special_ad_categories as JSON string
            r = await client.post(
                f"{BASE_URL}/act_{self.account_id}/campaigns?access_token={self.access_token}",
                data={
                    "name": f"VE - {product_title[:40]}",
                    "objective": "LINK_CLICKS",
                    "status": "PAUSED",
                    "special_ad_categories": json.dumps([]),
                },
            )
            d = r.json()
            if "error" in d:
                return {"status": "error", "error": d["error"].get("message", str(d["error"]))), "stage": "campaign"}
            campaign_id = d["id"]

            # 2. AdSet — targeting as JSON string
            targeting = {"geo_locations": {"countries": ["US"]}, "age_min": 18, "age_max": 65, "publisher_platforms": ["facebook", "instagram"]}
            r = await client.post(
                f"{BASE_URL}/act_{self.account_id}/adsets?access_token={self.access_token}",
                data={
                    "name": f"VE AdSet - {product_title[:40]}",
                    "campaign_id": campaign_id,
                    "status": "PAUSED",
                    "targeting": json.dumps(targeting),
                    "optimization_goal": "LINK_CLICKS",
                    "billing_event": "IMPRESSIONS",
                    "daily_budget": int(daily_budget * 100),
                },
            )
            d = r.json()
            if "error" in d:
                return {"status": "error", "error": d["error"].get("message", str(d["error"]))), "stage": "adset"}
            adset_id = d["id"]

            # 3. Creative — object_story_spec as JSON string
            story = {"page_id": self.page_id, "link_data": {"message": body, "name": headline, "call_to_action": {"type": cta}}}
            if link_url:
                story["link_data"]["link"] = link_url
            r = await client.post(
                f"{BASE_URL}/act_{self.account_id}/adcreatives?access_token={self.access_token}",
                data={
                    "name": f"VE Creative - {product_title[:40]}",
                    "object_story_spec": json.dumps(story),
                },
            )
            d = r.json()
            if "error" in d:
                return {"status": "error", "error": d["error"].get("message", str(d["error"]))), "stage": "creative"}
            creative_id = d["id"]

            # 4. Ad — creative as JSON string
            r = await client.post(
                f"{BASE_URL}/act_{self.account_id}/ads?access_token={self.access_token}",
                data={
                    "name": f"VE Ad - {product_title[:50]}",
                    "adset_id": adset_id,
                    "creative": json.dumps({"creative_id": creative_id}),
                    "status": "PAUSED",
                },
            )
            d = r.json()
            if "error" in d:
                return {"status": "error", "error": d["error"].get("message", str(d["error"]))), "stage": "ad"}

            return {"status": "launched", "campaign_id": campaign_id, "adset_id": adset_id, "ad_id": d["id"]}


facebook_ads = FacebookAdsService()