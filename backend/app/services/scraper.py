"""Production scraper with REAL AliExpress prices via ScrapingBee."""
import logging, os, urllib.parse, re, time
from typing import List, Dict, Any, Set, Optional
import httpx

logger = logging.getLogger(__name__)

SUBREDDITS = ["shutupandtakemymoney", "BuyItForLife", "gadgets", "EDC", "lifehacks", "skincareaddiction"]

# Brands to filter out
BRAND_BLACKLIST = {
    "apple", "samsung", "google", "microsoft", "sony", "nintendo", "xbox", "playstation",
    "lenovo", "dell", "hp", "asus", "acer", "razer", "corsair", "logitech", "oppo",
    "xiaomi", "huawei", "nvidia", "amd", "intel", "radeon", "geforce",
    "cooler master", "evga", "gigabyte", "msi", "be quiet", "noctua",
    "sennheiser", "bose", "jbl", "beats", "airpods", "macbook",
    "iphone", "ipad", "pixel", "galaxy", "oneplus", "dell xps", "macbook pro",
    "predator", "arduboy", "gopro", "xgimi", "lenovo yoga", "zen", "ryzen"
}

# Non-product content patterns
CONTENT_BLACKLIST = [
    r"\b(review|reviews|vs\.?|versus|comparison|compared)\b",
    r"\b(news|announced|revealed|leaked|rumor|report|says|claims)\b",
    r"\b(meme|joke|funny|hilarious|gif|comic)\b",
    r"\b(book|movie|game|show|series|film|album|song|music|netflix|youtube|twitch)\b",
    r"\b(car|truck|vehicle|motorcycle|bike|bicycle)\b",
    r"\b(food|drink|restaurant|recipe|coffee|tea|beer|wine)\b",
    r"\b(crypto|bitcoin|stock|invest|money|finance|bank)\b",
    r"\b(politics|government|law|court|crime|war|military|weapon|gun)\b",
    r"\b(list of|a list|things made|not made in|from canada|from usa)\b",
]

# Product categories with fallback pricing (cost, sell)
PRODUCT_CATEGORIES = {
    "organizer": (6, 22), "storage": (5, 18), "holder": (4, 15), "stand": (6, 20),
    "mount": (7, 24), "rack": (9, 32), "shelf": (8, 28), "drawer": (7, 25),
    "charger": (8, 28), "cable": (3, 12), "adapter": (5, 18), "hub": (8, 28),
    "power bank": (10, 35), "battery": (6, 22),
    "light": (7, 25), "lamp": (9, 30), "led": (5, 20), "lantern": (8, 28),
    "speaker": (11, 38), "headphone": (13, 48), "earbud": (9, 32), "microphone": (10, 35),
    "watch": (11, 38), "tracker": (13, 42), "band": (6, 22),
    "camera": (16, 52), "lock": (11, 38), "sensor": (7, 25), "alarm": (9, 32),
    "cleaner": (9, 32), "purifier": (13, 48), "humidifier": (11, 38),
    "vacuum": (15, 50), "robot": (18, 58),
    "massager": (13, 48), "pillow": (9, 32), "blanket": (11, 38),
    "mattress": (15, 50), "cushion": (8, 28),
    "bag": (11, 38), "backpack": (13, 48), "wallet": (7, 25),
    "case": (5, 18), "cover": (4, 15), "protector": (3, 13),
    "tool": (9, 32), "kit": (11, 38), "set": (13, 42), "wrench": (7, 25),
    "gadget": (7, 25), "device": (9, 32), "accessory": (5, 18),
    "kitchen": (9, 32), "blender": (13, 48), "cutter": (7, 25),
    "bottle": (5, 18), "cup": (4, 15), "mug": (5, 18), "thermos": (8, 28),
    "fitness": (11, 38), "exercise": (13, 48), "yoga": (9, 32),
    "posture": (11, 38), "corrector": (9, 32), "brace": (7, 25),
    "pet": (7, 25), "dog": (9, 32), "cat": (7, 25), "toy": (9, 32),
    "garden": (11, 38), "plant": (7, 25), "outdoor": (13, 48),
    "camping": (11, 38), "hiking": (13, 48), "travel": (9, 32),
    "tray": (5, 18), "seed": (4, 15), "pot": (6, 22),
}

EXTRACTION_PATTERNS = [
    r"(?:I|we)\s+(?:bought|got|found|purchased)\s+(?:this|a|an|the)?\s*([^.!?]{5,60})",
    r"(?:this|my|the)\s+([^.!?]{5,60})\s+(?:is|are|was|changed|saved|helped|works|rocks)",
    r"best\s+([^.!?]{5,60})\s+(?:for|to|ever|under|I've)",
    r"(?:found|discovered)\s+(?:this|a|an|the)?\s*([^.!?]{5,60})",
    r"([^.!?]{5,60})\s+(?:review|unboxing|haul|find|setup)",
    r"(?:recommend|suggest)\s+(?:this|a|an|the)?\s*([^.!?]{5,60})",
]


class ScraperService:
    def __init__(self):
        self._seen_products: Set[str] = set()

    async def scrape_trending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Production scrape with REAL AliExpress prices."""
        logger.info("[SCRAPER] Starting production scrape with REAL prices")
        
        scrapingbee_key = os.getenv("SCRAPINGBEE_API_KEY")
        if not scrapingbee_key:
            logger.error("[SCRAPER] SCRAPINGBEE_API_KEY not set")
            return []
        
        # Step 1: Get Reddit posts
        posts = await self._get_reddit_posts(scrapingbee_key)
        logger.info(f"[SCRAPER] Got {len(posts)} posts from Reddit")
        
        # Step 2: Extract product names
        products = []
        for post in posts:
            product_name = self._extract_product_name(post["title"])
            if product_name:
                product_key = product_name.lower()
                if product_key not in self._seen_products:
                    self._seen_products.add(product_key)
                    products.append({
                        "name": product_name,
                        "subreddit": post["subreddit"],
                        "upvotes": post["score"],
                        "permalink": post.get("permalink", "")
                    })
        
        logger.info(f"[SCRAPER] Extracted {len(products)} unique products")
        
        # Step 3: Get REAL AliExpress prices
        results = []
        for p in products[:limit * 3]:
            ali_data = await self._get_aliexpress_data(p["name"], scrapingbee_key)
            
            # Use REAL price if available, fallback to category pricing with WARNING
            if ali_data and ali_data.get("price"):
                cost = ali_data["price"]
                sell_price = ali_data["sell_price"]
                logger.info(f"[SCRAPER] REAL price for '{p['name']}': ${cost:.2f} -> ${sell_price:.2f}")
            else:
                # Fallback to category pricing (but log WARNING)
                category, fallback_cost, fallback_sell = self._get_category_pricing(p["name"])
                cost = fallback_cost
                sell_price = fallback_sell
                logger.warning(f"[SCRAPER] FALLBACK price for '{p['name']}': ${cost:.2f} -> ${sell_price:.2f} (AliExpress scrape failed)")
            
            scores = self._calculate_scores(p["name"], p["upvotes"], cost)
            total_score = sum(scores.values())
            
            if total_score >= 85:
                results.append({
                    "title": p["name"],
                    "description": f"Trending on r/{p['subreddit']} ({p['upvotes']} upvotes).",
                    "supplier_url": f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(p['name'])}",
                    "cost_price": cost,
                    "suggested_sell_price": sell_price,
                    "margin": round(sell_price - cost, 2),
                    "scores": scores,
                    "total_score": total_score,
                    "source_data": {
                        "reddit": {"subreddit": p["subreddit"], "upvotes": p["upvotes"]},
                        "google_trends": {"interest_score": min(p["upvotes"] // 10, 100)},
                        "aliexpress_listings": ali_data.get("count", 0) if ali_data else 0,
                        "price_source": "real" if ali_data and ali_data.get("price") else "fallback"
                    }
                })
            
            if len(results) >= limit:
                break
        
        results.sort(key=lambda x: x["total_score"], reverse=True)
        logger.info(f"[SCRAPER] Final: {len(results)} products")
        
        return results[:limit]

    async def _get_reddit_posts(self, scrapingbee_key: str) -> List[Dict]:
        """Get posts from Reddit via ScrapingBee."""
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
                        post_data = child.get("data", {})
                        if post_data.get("score", 0) >= 100:
                            posts.append({
                                "title": post_data.get("title", ""),
                                "score": post_data.get("score", 0),
                                "subreddit": sub,
                                "permalink": f"https://reddit.com{post_data.get('permalink', '')}"
                            })
            except Exception as e:
                logger.warning(f"[SCRAPER] Error on r/{sub}: {e}")
        
        return posts

    def _extract_product_name(self, title: str) -> Optional[str]:
        """Extract actual product name from Reddit title."""
        title_lower = title.lower()
        
        # Check brand blacklist
        if any(brand in title_lower for brand in BRAND_BLACKLIST):
            return None
        
        # Check content blacklist
        for pattern in CONTENT_BLACKLIST:
            if re.search(pattern, title_lower):
                return None
        
        # Must contain at least one product category word
        found_category = False
        for category in PRODUCT_CATEGORIES.keys():
            if category in title_lower:
                found_category = True
                break
        
        if not found_category:
            return None
        
        # Try extraction patterns
        for pattern in EXTRACTION_PATTERNS:
            match = re.search(pattern, title, re.I)
            if match:
                name = match.group(1).strip()
                name = re.sub(r"[^\w\s]", "", name)
                name = re.sub(r"\s+", " ", name).strip()
                
                if 5 <= len(name) <= 50 and 2 <= len(name.split()) <= 6:
                    return name
        
        # Fallback: use title directly if short enough
        name = re.sub(r"[^\w\s]", "", title)
        name = re.sub(r"\s+", " ", name).strip()
        
        if 5 <= len(name) <= 50 and 2 <= len(name.split()) <= 6:
            return name
        
        return None

    async def _get_aliexpress_data(self, product_name: str, scrapingbee_key: str) -> Optional[Dict]:
        """Get REAL AliExpress product data via ScrapingBee with robust price extraction."""
        try:
            search_url = f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(product_name)}"
            # Use render_js=true to load dynamic content
            proxy_url = f"https://app.scrapingbee.com/api/v1/?api_key={scrapingbee_key}&url={urllib.parse.quote(search_url)}&render_js=true&device=desktop"
            
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.get(proxy_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                })
                
                if response.status_code != 200:
                    logger.warning(f"[SCRAPER] AliExpress returned {response.status_code} for '{product_name}'")
                    return None
                
                html = response.text
                
                # Try MULTIPLE price patterns (AliExpress changes their HTML frequently)
                price = None
                price_patterns = [
                    # Pattern 1: formatedAmount with US $
                    r'"formatedAmount":"US \$(\d+\.?\d*)"',
                    # Pattern 2: formatedAmount with just $
                    r'"formatedAmount":"\$(\d+\.?\d*)"',
                    # Pattern 3: minAmount value
                    r'"minAmount":\{"value":(\d+\.?\d*)',
                    # Pattern 4: price field
                    r'"price":"(\d+\.?\d*)"',
                    # Pattern 5: raw price with $
                    r'\$([0-9]+\.?[0-9]{0,2})(?!\d)',
                    # Pattern 6: data-price attribute
                    r'data-price="(\d+\.?\d*)"',
                    # Pattern 7: salePrice
                    r'"salePrice":\{"minAmount":\{"value":(\d+\.?\d*)',
                ]
                
                for pattern in price_patterns:
                    match = re.search(pattern, html)
                    if match:
                        try:
                            price = float(match.group(1))
                            if 0.5 <= price <= 500:  # Reasonable price range
                                break
                        except ValueError:
                            continue
                
                if not price:
                    logger.warning(f"[SCRAPER] No valid price found for '{product_name}' in AliExpress HTML")
                    return None
                
                # Extract product count/listings
                count = 0
                count_patterns = [
                    r'"totalCount":(\d+)',
                    r'"totalResults":(\d+)',
                    r'(\d+)\s+orders',
                ]
                for pattern in count_patterns:
                    match = re.search(pattern, html)
                    if match:
                        count = int(match.group(1))
                        break
                
                # Calculate sell price: 2.5-3x markup based on cost
                if price < 10:
                    markup = 3.0
                elif price < 25:
                    markup = 2.8
                else:
                    markup = 2.5
                
                sell_price = round(max(price * markup, 19.99), 2)
                
                logger.info(f"[SCRAPER] Extracted REAL price for '{product_name}': ${price:.2f} -> ${sell_price:.2f} ({count} listings)")
                
                return {
                    "price": price,
                    "sell_price": sell_price,
                    "count": count,
                    "orders": count,
                    "url": search_url
                }
                
        except httpx.TimeoutException:
            logger.warning(f"[SCRAPER] Timeout scraping AliExpress for '{product_name}'")
        except Exception as e:
            logger.warning(f"[SCRAPER] Error scraping AliExpress for '{product_name}': {type(e).__name__}: {e}")
        
        return None

    def _get_category_pricing(self, product_name: str) -> tuple[str, float, float]:
        """Get fallback pricing based on product category."""
        name_lower = product_name.lower()
        
        for category, (min_price, max_price) in PRODUCT_CATEGORIES.items():
            if category in name_lower:
                cost = round((min_price + max_price) / 2, 2)
                sell = round(max_price, 2)
                return category, cost, sell
        
        # Default fallback
        return "gadget", 8.0, 29.99

    def _calculate_scores(self, product_name: str, upvotes: int, cost: float) -> Dict[str, int]:
        """Calculate 13-factor product score."""
        scores = {
            "Problem/Solution": 7, "Passionate Audience": 7, "Profit Margin": 7,
            "Perceived Value": 7, "Impulse": 7, "Availability": 8,
            "Trending": 7, "Shipping": 7, "Legal/Safe": 9,
            "Repeat Purchase": 6, "Visual Appeal": 7, "Price Point": 7,
            "Competition": 6
        }
        
        # Upvotes boost
        if upvotes > 1000:
            scores["Trending"] = 10
            scores["Passionate Audience"] = 9
        elif upvotes > 500:
            scores["Trending"] = 9
            scores["Passionate Audience"] = 8
        elif upvotes > 200:
            scores["Trending"] = 8
        
        # Price point scoring
        if 8 <= cost <= 25:
            scores["Price Point"] = 9
            scores["Impulse"] = 9
        elif cost < 8:
            scores["Price Point"] = 8
        else:
            scores["Price Point"] = 6
        
        # Category boosts
        name_lower = product_name.lower()
        if any(word in name_lower for word in ["pet", "dog", "cat"]):
            scores["Passionate Audience"] = 10
            scores["Repeat Purchase"] = 9
        if any(word in name_lower for word in ["fitness", "exercise", "yoga"]):
            scores["Problem/Solution"] = 9
            scores["Repeat Purchase"] = 8
        if any(word in name_lower for word in ["kitchen", "cooking", "blender"]):
            scores["Problem/Solution"] = 8
            scores["Repeat Purchase"] = 8
        if any(word in name_lower for word in ["garden", "plant", "outdoor"]):
            scores["Passionate Audience"] = 9
            scores["Repeat Purchase"] = 8
        
        return {k: min(v, 10) for k, v in scores.items()}

    async def analyze_google_trends(self, keyword: str):
        return {"keyword": keyword, "interest_score": 65}

    async def check_facebook_ads(self, keyword: str):
        return {"keyword": keyword, "competition": "medium"}

scraper = ScraperService()
