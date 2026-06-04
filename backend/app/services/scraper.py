"""Simple scraper - returns products with minimal filtering."""
import logging, os, urllib.parse, re
from typing import List, Dict, Any
import httpx

logger = logging.getLogger(__name__)

SUBREDDITS = ["shutupandtakemymoney", "BuyItForLife", "gadgets", "EDC", "lifehacks"]

# Only filter out OBVIOUS non-products
BLACKLIST = {"news", "announced", "revealed", "leaked", "rumor", "report", "meme", "joke", "funny"}

# Product categories with pricing (cost, sell)
CATEGORIES = {
    "organizer": (8, 24.99), "storage": (6, 19.99), "holder": (5, 17.99),
    "stand": (7, 22.99), "mount": (8, 26.99), "rack": (10, 34.99),
    "charger": (9, 29.99), "cable": (4, 14.99), "adapter": (6, 19.99),
    "light": (8, 27.99), "lamp": (10, 32.99), "led": (6, 21.99),
    "speaker": (12, 39.99), "headphone": (15, 49.99), "earbud": (10, 34.99),
    "watch": (12, 39.99), "tracker": (15, 49.99), "sensor": (8, 26.99),
    "camera": (20, 59.99), "lock": (12, 39.99),
    "cleaner": (10, 34.99), "purifier": (15, 49.99),
    "massager": (15, 49.99), "pillow": (10, 34.99), "blanket": (12, 39.99),
    "bag": (12, 39.99), "backpack": (15, 49.99), "wallet": (8, 26.99),
    "case": (6, 19.99), "cover": (5, 17.99),
    "tool": (10, 34.99), "kit": (12, 39.99), "set": (15, 49.99),
    "gadget": (8, 26.99), "device": (10, 34.99), "accessory": (6, 19.99),
    "kitchen": (10, 34.99), "blender": (15, 49.99),
    "bottle": (6, 19.99), "cup": (5, 17.99), "mug": (6, 19.99),
    "fitness": (12, 39.99), "yoga": (10, 34.99),
    "posture": (12, 39.99), "corrector": (10, 34.99),
    "pet": (8, 26.99), "toy": (10, 34.99),
    "garden": (12, 39.99), "plant": (8, 26.99), "outdoor": (15, 49.99),
    "camping": (12, 39.99), "hiking": (15, 49.99), "travel": (10, 34.99),
}


class ScraperService:
    async def scrape_trending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Simple scraper that just works."""
        logger.info("[SCRAPER] Starting")
        
        scrapingbee_key = os.getenv("SCRAPINGBEE_API_KEY")
        if not scrapingbee_key:
            logger.error("[SCRAPER] SCRAPINGBEE_API_KEY not set")
            return []
        
        # Get Reddit posts
        posts = []
        for sub in SUBREDDITS:
            try:
                reddit_url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
                proxy_url = f"https://app.scrapingbee.com/api/v1/?api_key={scrapingbee_key}&url={urllib.parse.quote(reddit_url)}&render_js=false&premium_proxy=true"
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(proxy_url, headers={"User-Agent": "Mozilla/5.0"})
                    response.raise_for_status()
                    data = response.json()
                    
                    for child in data.get("data", {}).get("children", []):
                        post = child.get("data", {})
                        if post.get("score", 0) >= 100:
                            posts.append({
                                "title": post.get("title", ""),
                                "score": post.get("score", 0),
                                "subreddit": sub
                            })
            except Exception as e:
                logger.warning(f"[SCRAPER] Error on r/{sub}: {e}")
        
        logger.info(f"[SCRAPER] Got {len(posts)} posts")
        
        # Extract products (VERY permissive)
        products = []
        seen = set()
        
        for post in posts:
            title = post["title"]
            title_lower = title.lower()
            
            # Skip if blacklist word found
            if any(word in title_lower for word in BLACKLIST):
                continue
            
            # Clean up title
            name = re.sub(r"[^\w\s]", "", title)
            name = re.sub(r"\s+", " ", name).strip()
            
            # Skip if too long or too short
            if len(name) < 5 or len(name) > 80:
                continue
            
            # Skip duplicates
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            
            # Find category (or use default)
            found_cat = "gadget"
            for cat in CATEGORIES.keys():
                if cat in title_lower:
                    found_cat = cat
                    break
            
            cost, sell = CATEGORIES[found_cat]
            
            # Calculate score
            scores = {
                "Problem/Solution": 7, "Passionate Audience": 7, "Profit Margin": 7,
                "Perceived Value": 7, "Impulse": 7, "Availability": 8,
                "Trending": 7, "Shipping": 7, "Legal/Safe": 9,
                "Repeat Purchase": 6, "Visual Appeal": 7, "Price Point": 7,
                "Competition": 6
            }
            
            # Boost based on upvotes
            if post["score"] > 1000:
                scores["Trending"] = 10
                scores["Passionate Audience"] = 9
            elif post["score"] > 500:
                scores["Trending"] = 9
            elif post["score"] > 200:
                scores["Trending"] = 8
            
            total = sum(scores.values())
            
            products.append({
                "title": name,
                "description": f"Trending on r/{post['subreddit']} ({post['score']} upvotes)",
                "supplier_url": f"https://aliexpress.com/wholesale?SearchText={urllib.parse.quote(name)}",
                "cost_price": cost,
                "suggested_sell_price": sell,
                "margin": round(sell - cost, 2),
                "scores": scores,
                "total_score": total,
                "source_data": {
                    "reddit": {"subreddit": post["subreddit"], "upvotes": post["score"]},
                    "google_trends": {"interest_score": 70}
                }
            })
            
            # Stop if we have enough
            if len(products) >= limit * 2:
                break
        
        # Sort by score and return
        products.sort(key=lambda x: x["total_score"], reverse=True)
        logger.info(f"[SCRAPER] Found {len(products)} products")
        
        return products[:limit]
    
    async def analyze_google_trends(self, keyword: str):
        return {"keyword": keyword, "interest_score": 65}
    
    async def check_facebook_ads(self, keyword: str):
        return {"keyword": keyword, "competition": "medium"}

scraper = ScraperService()
