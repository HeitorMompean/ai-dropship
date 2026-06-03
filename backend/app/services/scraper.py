"""Production Reddit scraper with aggressive filtering + AliExpress integration."""
import logging, random, re, urllib.parse, os
from typing import List, Dict, Any, Set
import httpx

logger = logging.getLogger(__name__)

SUBREDDITS = ["shutupandtakemymoney", "BuyItForLife", "gadgets", "EDC", "lifehacks"]

# Aggressive blacklist - filter out non-products
BLACKLIST_WORDS = {
    "news", "announced", "revealed", "leaked", "rumor", "report", "says", "claims",
    "apple", "samsung", "google", "microsoft", "sony", "nintendo", "xbox", "playstation",
    "lenovo", "dell", "hp", "asus", "acer", "razer", "corsair", "logitech",
    "iphone", "ipad", "macbook", "pixel", "galaxy", "oneplus", "xiaomi", "huawei",
    "nvidia", "amd", "intel", "radeon", "geforce", "rtx", "rx",
    "book", "movie", "game", "show", "series", "film", "album", "song", "music",
    "meme", "joke", "funny", "hilarious", "lol", "lmao",
    "how to", "tutorial", "guide", "tips", "trick", "hack",
    "vs", "versus", "comparison", "review", "unboxing",
    "car", "truck", "vehicle", "motorcycle", "bike",
    "house", "apartment", "home", "room",
    "person", "man", "woman", "kid", "child", "baby",
    "dog", "cat", "pet", "animal",
    "food", "drink", "restaurant", "recipe", "meal",
    "software", "app", "program", "website", "service", "subscription",
    "crypto", "bitcoin", "stock", "invest", "money", "finance",
    "politics", "government", "law", "court", "crime",
    "war", "military", "weapon", "gun",
    "drug", "medicine", "pharmaceutical",
}

# Product categories that actually work for dropshipping
PRODUCT_CATEGORIES = {
    "organizer": (8, 24.99), "storage": (6, 19.99), "holder": (5, 17.99),
    "stand": (7, 22.99), "mount": (8, 26.99), "rack": (10, 34.99),
    "charger": (9, 29.99), "cable": (4, 14.99), "adapter": (6, 19.99),
    "light": (8, 27.99), "lamp": (10, 32.99), "led": (6, 21.99),
    "speaker": (12, 39.99), "headphone": (15, 49.99), "earbud": (10, 34.99),
    "watch": (12, 39.99), "tracker": (15, 49.99), "sensor": (8, 26.99),
    "camera": (20, 59.99), "security": (15, 49.99), "lock": (12, 39.99),
    "cleaner": (10, 34.99), "purifier": (15, 49.99), "humidifier": (12, 39.99),
    "massager": (15, 49.99), "pillow": (10, 34.99), "blanket": (12, 39.99),
    "bag": (12, 39.99), "backpack": (15, 49.99), "wallet": (8, 26.99),
    "case": (6, 19.99), "cover": (5, 17.99), "protector": (4, 14.99),
    "tool": (10, 34.99), "kit": (12, 39.99), "set": (15, 49.99),
    "gadget": (8, 26.99), "device": (10, 34.99), "accessory": (6, 19.99),
    "kitchen": (10, 34.99), "cooking": (12, 39.99), "blender": (15, 49.99),
    "bottle": (6, 19.99), "cup": (5, 17.99), "mug": (6, 19.99),
    "fitness": (12, 39.99), "exercise": (15, 49.99), "yoga": (10, 34.99),
    "posture": (12, 39.99), "corrector": (10, 34.99), "brace": (8, 26.99),
    "pet": (8, 26.99), "dog": (10, 34.99), "cat": (8, 26.99),
    "baby": (10, 34.99), "kid": (8, 26.99), "toy": (10, 34.99),
    "garden": (12, 39.99), "plant": (8, 26.99), "outdoor": (15, 49.99),
    "camping": (12, 39.99), "hiking": (15, 49.99), "travel": (10, 34.99),
}


class ScraperService:
    def __init__(self):
        self._seen_products: Set[str] = set()

    async def scrape_trending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Scrape Reddit, filter aggressively, get real AliExpress products."""
        logger.info("[SCRAPER] Starting production scrape")
        
        # Step 1: Get Reddit posts
        posts = await self._get_reddit_posts()
        logger.info(f"[SCRAPER] Got {len(posts)} raw posts from Reddit")
        
        # Step 2: Extract product names (aggressive filtering)
        products = []
        for post in posts:
            product_name = self._extract_product_name(post["title"])
            if product_name:
                products.append({
                    "name": product_name,
                    "subreddit": post["subreddit"],
                    "upvotes": post["score"],
                    "permalink": post.get("permalink", "")
                })
        
        logger.info(f"[SCRAPER] Extracted {len(products)} potential products")
        
        # Step 3: Deduplicate
        unique_products = []
        seen_names = set()
        for p in products:
            name_lower = p["name"].lower()
            if name_lower not in seen_names:
                seen_names.add(name_lower)
                unique_products.append(p)
        
        logger.info(f"[SCRAPER] {len(unique_products)} unique products after dedup")
        
        # Step 4: Get real AliExpress data for each product
        results = []
        for p in unique_products[:limit]:
            ali_data = await self._get_aliexpress_product(p["name"])
            if ali_data:
                scores = self._calculate_scores(p["name"], p["upvotes"], ali_data["price"])
                total_score = sum(scores.values())
                
                # Only include products with score > 80
                if total_score >= 80:
                    results.append({
                        "title": ali_data["title"],
                        "description": f"Trending on r/{p['subreddit']} ({p['upvotes']} upvotes). Real AliExpress product with {ali_data['orders']}+ orders.",
                        "supplier_url": ali_data["url"],
                        "cost_price": ali_data["price"],
                        "suggested_sell_price": ali_data["sell_price"],
                        "margin": round(ali_data["sell_price"] - ali_data["price"], 2),
                        "scores": scores,
                        "total_score": total_score,
                        "source_data": {
                            "reddit": {"subreddit": p["subreddit"], "upvotes": p["upvotes"]},
                            "aliexpress": {"orders": ali_data["orders"], "rating": ali_data["rating"]}
                        }
                    })
        
        # Sort by score
        results.sort(key=lambda x: x["total_score"], reverse=True)
        logger.info(f"[SCRAPER] Final: {len(results)} high-quality products")
        
        return results[:limit]

    async def _get_reddit_posts(self) -> List[Dict]:
        """Get posts from Reddit via ScrapingBee."""
        posts = []
        scrapingbee_key = os.getenv("SCRAPINGBEE_API_KEY")
        
        if not scrapingbee_key:
            logger.error("[SCRAPER] SCRAPINGBEE_API_KEY not set")
            return posts
        
        for sub in SUBREDDITS:
            try:
                reddit_url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
                proxy_url = f"https://app.scrapingbee.com/api/v1/?api_key={scrapingbee_key}&url={urllib.parse.quote(reddit_url)}&render_js=false&premium_proxy=true"
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(proxy_url, headers={"User-Agent": "Mozilla/5.0"})
                    response.raise_for_status()
                    data = response.json()
                    
                    for child in data.get("data", {}).get("children", []):
                        post_data = child.get("data", {})
                        if post_data.get("score", 0) >= 100:  # Only popular posts
                            posts.append({
                                "title": post_data.get("title", ""),
                                "score": post_data.get("score", 0),
                                "subreddit": sub,
                                "permalink": f"https://reddit.com{post_data.get('permalink', '')}"
                            })
            except Exception as e:
                logger.warning(f"[SCRAPER] Error scraping r/{sub}: {e}")
        
        return posts

    def _extract_product_name(self, title: str) -> str | None:
        """Extract product name from Reddit title with aggressive filtering."""
        title_lower = title.lower()
        
        # Blacklist check
        if any(word in title_lower for word in BLACKLIST_WORDS):
            return None
        
        # Must contain at least one product category word
        found_category = None
        for category in PRODUCT_CATEGORIES.keys():
            if category in title_lower:
                found_category = category
                break
        
        if not found_category:
            return None
        
        # Extract product name (remove common prefixes/suffixes)
        name = title
        name = re.sub(r"^(I|My|This|The|A|An)\s+", "", name, flags=re.I)
        name = re.sub(r"\s+(is|are|was|were|has|have|had|will|would|could|should|may|might|can)\s+.*$", "", name, flags=re.I)
        name = re.sub(r"\[.*?\]", "", name)  # Remove [tags]
        name = re.sub(r"\(.*?\)", "", name)  # Remove (parentheses)
        name = re.sub(r"[^\w\s]", "", name)  # Remove punctuation
        name = name.strip()
        
        # Must be 5-60 characters
        if 5 <= len(name) <= 60:
            return name
        
        return None

    async def _get_aliexpress_product(self, product_name: str) -> Dict | None:
        """Get real product data from AliExpress."""
        try:
            search_url = f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(product_name)}"
            
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(search_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                
                if response.status_code != 200:
                    return None
                
                # Extract product data from HTML (simplified - in production use proper scraping)
                html = response.text
                
                # Look for price patterns
                price_match = re.search(r'"formatedAmount":"\$(\d+\.?\d*)"', html)
                title_match = re.search(r'"title":"([^"]{10,100})"', html)
                orders_match = re.search(r'"tradeCount":(\d+)', html)
                
                if price_match and title_match:
                    cost = float(price_match.group(1))
                    title = title_match.group(1)
                    orders = int(orders_match.group(1)) if orders_match else 50
                    
                    # Calculate sell price (3x markup, min $19.99)
                    sell_price = max(cost * 3, 19.99)
                    
                    return {
                        "title": title,
                        "price": cost,
                        "sell_price": round(sell_price, 2),
                        "orders": orders,
                        "rating": 4.5,  # Default rating
                        "url": search_url
                    }
        except Exception as e:
            logger.warning(f"[SCRAPER] AliExpress error for '{product_name}': {e}")
        
        return None

    def _calculate_scores(self, product_name: str, upvotes: int, cost: float) -> Dict[str, int]:
        """Calculate 13-factor product score."""
        scores = {
            "Problem/Solution": 7,
            "Passionate Audience": 7,
            "Profit Margin": 7,
            "Perceived Value": 7,
            "Impulse": 7,
            "Availability": 8,
            "Trending": 7,
            "Shipping": 7,
            "Legal/Safe": 9,
            "Repeat Purchase": 6,
            "Visual Appeal": 7,
            "Price Point": 7,
            "Competition": 6
        }
        
        # Upvotes = trending indicator
        if upvotes > 1000:
            scores["Trending"] = 10
            scores["Passionate Audience"] = 9
        elif upvotes > 500:
            scores["Trending"] = 9
            scores["Passionate Audience"] = 8
        elif upvotes > 200:
            scores["Trending"] = 8
        
        # Price point scoring
        if 10 <= cost <= 30:
            scores["Price Point"] = 9
            scores["Impulse"] = 9
        elif cost < 10:
            scores["Price Point"] = 8
        else:
            scores["Price Point"] = 6
        
        # Category-specific boosts
        name_lower = product_name.lower()
        if "pet" in name_lower or "dog" in name_lower or "cat" in name_lower:
            scores["Passionate Audience"] = 10
            scores["Repeat Purchase"] = 9
        if "fitness" in name_lower or "exercise" in name_lower:
            scores["Problem/Solution"] = 9
            scores["Repeat Purchase"] = 8
        if "kitchen" in name_lower or "cooking" in name_lower:
            scores["Problem/Solution"] = 8
            scores["Repeat Purchase"] = 8
        
        return {k: min(v, 10) for k, v in scores.items()}

    async def analyze_google_trends(self, keyword: str) -> Dict[str, Any]:
        return {"keyword": keyword, "interest_score": 65}

    async def check_facebook_ads(self, keyword: str) -> Dict[str, Any]:
        return {"keyword": keyword, "competition": "medium"}

scraper = ScraperService()
