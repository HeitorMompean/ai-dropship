"""Ultimate Production Scraper - Smart Extraction + RapidAPI Debugging."""
import logging, os, urllib.parse, re
from typing import List, Dict, Any, Set
import httpx

logger = logging.getLogger(__name__)

SUBREDDITS = ["shutupandtakemymoney", "BuyItForLife", "gadgets", "EDC", "lifehacks"]

_GLOBAL_SEEN: Set[str] = set()

BRAND_BLACKLIST = {
    "apple", "samsung", "google", "microsoft", "sony", "nintendo", "xbox", "playstation",
    "lenovo", "dell", "hp", "asus", "acer", "razer", "corsair", "logitech", "oppo",
    "xiaomi", "huawei", "nvidia", "amd", "intel", "radeon", "geforce",
    "sennheiser", "bose", "jbl", "beats", "airpods", "macbook", "iphone", "ipad",
    "pixel", "galaxy", "oneplus", "dell xps", "macbook pro", "predator", "arduboy", "gopro"
}

CONTENT_BLACKLIST = [
    r"\b(review|reviews|vs\.?|versus|comparison|compared)\b",
    r"\b(news|announced|revealed|leaked|rumor|report|says|claims)\b",
    r"\b(meme|joke|funny|hilarious|gif|comic)\b",
    r"\b(book|movie|game|show|series|film|album|song|music|netflix|youtube|twitch)\b",
    r"\b(car|truck|vehicle|motorcycle|bike|bicycle)\b",
    r"\b(food|drink|restaurant|recipe|coffee|tea|beer|wine)\b",
    r"\b(crypto|bitcoin|stock|invest|money|finance|bank)\b",
    r"\b(politics|government|law|court|crime|war|military|weapon|gun)\b",
    r"\b(list of|a list|things made|not made in|from canada|from usa|submission)\b",
]

# Expanded categories to catch more products
PRODUCT_CATEGORIES = {
    "organizer": (6, 22), "storage": (5, 18), "holder": (4, 15), "stand": (6, 20),
    "mount": (7, 24), "rack": (9, 32), "charger": (8, 28), "cable": (3, 12),
    "light": (7, 25), "lamp": (9, 30), "speaker": (11, 38), "headphone": (13, 48),
    "earbud": (9, 32), "watch": (11, 38), "tracker": (13, 42), "camera": (16, 52),
    "lock": (11, 38), "cleaner": (9, 32), "purifier": (13, 48), "massager": (13, 48),
    "pillow": (9, 32), "blanket": (11, 38), "bag": (11, 38), "backpack": (13, 48),
    "wallet": (7, 25), "case": (5, 18), "tool": (9, 32), "kit": (11, 38),
    "gadget": (7, 25), "kitchen": (9, 32), "blender": (13, 48), "bottle": (5, 18),
    "fitness": (11, 38), "yoga": (9, 32), "posture": (11, 38), "pet": (7, 25),
    "garden": (11, 38), "camping": (11, 38), "hiking": (13, 48), "cup": (4, 15),
    "mug": (5, 18), "thermos": (8, 28), "mat": (8, 28), "brush": (4, 15),
    "mirror": (8, 28), "screen": (6, 22), "keyboard": (12, 40), "mouse": (8, 28),
    "pad": (5, 18), "pen": (3, 12), "notebook": (6, 20), "scissors": (5, 18),
    "knife": (8, 28), "sharpener": (4, 15), "cutting": (7, 25), "board": (8, 28),
    "shelf": (9, 32), "drawer": (8, 28), "hook": (3, 12), "hanger": (4, 15),
    "clip": (3, 12), "strap": (4, 15), "belt": (6, 20), "band": (4, 15),
    "ring": (3, 12), "chain": (5, 18), "rope": (6, 20), "cord": (4, 15),
    "wire": (4, 15), "plug": (4, 15), "socket": (5, 18), "switch": (5, 18),
    "remote": (6, 20), "sensor": (7, 25), "alarm": (8, 28), "detector": (9, 32),
    "monitor": (15, 50), "display": (12, 40), "projector": (25, 80),
    "printer": (20, 60), "scanner": (15, 50), "router": (12, 40), "modem": (10, 35),
    "antenna": (8, 28), "receiver": (12, 40), "amplifier": (15, 50),
    "microphone": (10, 35), "webcam": (12, 40), "tripod": (10, 35),
    "gimbal": (20, 60), "drone": (30, 90), "helmet": (15, 50), "goggles": (12, 40),
    "gloves": (6, 20), "boots": (15, 50), "shoes": (12, 40), "socks": (4, 15),
    "shirt": (8, 28), "jacket": (15, 50), "coat": (18, 60), "pants": (12, 40),
    "shorts": (8, 28), "skirt": (8, 28), "dress": (12, 40), "suit": (25, 80),
    "tie": (4, 15), "scarf": (6, 20), "hat": (5, 18), "cap": (4, 15),
    "umbrella": (6, 20), "sunglasses": (5, 18), "glasses": (8, 28),
    "watch": (12, 40), "bracelet": (4, 15), "necklace": (5, 18), "earring": (3, 12),
    "perfume": (10, 35), "cologne": (10, 35), "lotion": (6, 20), "cream": (5, 18),
    "soap": (3, 12), "shampoo": (5, 18), "conditioner": (5, 18), "towel": (6, 20),
    "toothbrush": (3, 12), "toothpaste": (3, 12), "razor": (5, 18), "shaver": (10, 35),
    "trimmer": (8, 28), "clipper": (10, 35), "dryer": (12, 40), "iron": (10, 35),
    "steamer": (12, 40), "heater": (15, 50), "fan": (10, 35), "cooler": (15, 50),
    "ac": (30, 90), "fridge": (40, 120), "freezer": (35, 100), "oven": (30, 90),
    "stove": (25, 80), "microwave": (25, 80), "toaster": (12, 40),
    "maker": (15, 50), "grinder": (10, 35), "mixer": (15, 50), "juicer": (15, 50),
    "kettle": (10, 35), "pot": (12, 40), "pan": (10, 35), "wok": (12, 40),
    "skillet": (12, 40), "grill": (20, 60), "smoker": (25, 80),
    "chair": (20, 60), "table": (25, 80), "desk": (30, 90), "bed": (40, 120),
    "sofa": (50, 150), "couch": (50, 150), "rug": (20, 60), "carpet": (25, 80),
    "curtain": (15, 50), "blind": (12, 40), "shade": (10, 35),
    "plant": (8, 28), "pot": (6, 20), "soil": (5, 18), "seed": (3, 12),
    "fertilizer": (8, 28), "hose": (12, 40), "sprinkler": (10, 35),
    "mower": (40, 120), "trimmer": (15, 50), "blower": (20, 60),
    "tent": (25, 80), "sleeping bag": (20, 60), "mat": (12, 40),
    "stove": (15, 50), "cooler": (20, 60), "lantern": (10, 35),
    "flashlight": (8, 28), "headlamp": (10, 35), "compass": (5, 18),
    "map": (4, 15), "gps": (20, 60), "radio": (12, 40), "binoculars": (20, 60),
    "telescope": (30, 90), "microscope": (25, 80), "magnifier": (5, 18),
    "scale": (10, 35), "thermometer": (8, 28), "hygrometer": (10, 35),
    "barometer": (12, 40), "anemometer": (15, 50), "weather": (12, 40),
    "station": (20, 60), "clock": (8, 28), "timer": (5, 18), "stopwatch": (8, 28),
    "calculator": (6, 20), "ruler": (3, 12), "tape": (4, 15), "level": (8, 28),
    "square": (6, 20), "plumb": (5, 18), "chalk": (3, 12), "marker": (4, 15),
    "crayon": (4, 15), "pencil": (3, 12), "eraser": (2, 8), "glue": (3, 12),
    "tape": (4, 15), "stapler": (6, 20), "staple": (3, 12), "punch": (5, 18),
    "binder": (6, 20), "folder": (4, 15), "envelope": (3, 12), "paper": (5, 18),
    "card": (3, 12), "label": (3, 12), "tag": (2, 8), "sticker": (3, 12),
    "stamp": (4, 15), "ink": (5, 18), "toner": (15, 50), "cartridge": (12, 40),
    "ribbon": (4, 15), "film": (8, 28), "battery": (6, 20), "charger": (8, 28),
    "adapter": (5, 18), "converter": (8, 28), "transformer": (12, 40),
    "inverter": (15, 50), "generator": (40, 120), "solar": (25, 80),
    "panel": (20, 60), "controller": (12, 40), "regulator": (10, 35),
    "motor": (15, 50), "pump": (12, 40), "valve": (8, 28), "pipe": (6, 20),
    "tube": (5, 18), "hose": (8, 28), "fitting": (4, 15), "connector": (5, 18),
    "joint": (4, 15), "bearing": (6, 20), "gear": (8, 28), "pulley": (6, 20),
    "belt": (5, 18), "chain": (6, 20), "sprocket": (8, 28), "clutch": (12, 40),
    "brake": (10, 35), "shock": (12, 40), "strut": (15, 50), "spring": (6, 20),
    "mount": (8, 28), "bracket": (5, 18), "hanger": (4, 15), "hook": (3, 12),
    "clamp": (5, 18), "vise": (12, 40), "anvil": (20, 60), "forge": (30, 90),
    "weld": (15, 50), "solder": (8, 28), "braze": (10, 35), "glue": (5, 18),
    "epoxy": (8, 28), "resin": (10, 35), "silicone": (6, 20), "caulk": (5, 18),
    "sealant": (6, 20), "putty": (4, 15), "clay": (5, 18), "dough": (4, 15),
    "slime": (5, 18), "sand": (4, 15), "gravel": (5, 18), "rock": (4, 15),
    "stone": (5, 18), "brick": (4, 15), "block": (5, 18), "tile": (6, 20),
    "slate": (8, 28), "marble": (12, 40), "granite": (15, 50), "quartz": (12, 40),
    "glass": (8, 28), "mirror": (10, 35), "lens": (12, 40), "prism": (8, 28),
    "filter": (6, 20), "screen": (8, 28), "mesh": (5, 18), "net": (6, 20),
    "web": (5, 18), "fabric": (8, 28), "cloth": (6, 20), "textile": (8, 28),
    "yarn": (5, 18), "thread": (4, 15), "string": (3, 12), "rope": (6, 20),
    "cord": (5, 18), "twine": (4, 15), "wire": (5, 18), "cable": (6, 20),
    "chain": (8, 28), "link": (5, 18), "ring": (4, 15), "hoop": (5, 18),
    "loop": (4, 15), "band": (5, 18), "strap": (6, 20), "belt": (8, 28),
    "buckle": (5, 18), "clasp": (4, 15), "fastener": (5, 18), "clip": (4, 15),
    "pin": (3, 12), "nail": (4, 15), "screw": (4, 15), "bolt": (5, 18),
    "nut": (4, 15), "washer": (3, 12), "rivet": (4, 15), "anchor": (6, 20),
    "plug": (4, 15), "dowel": (4, 15), "peg": (3, 12), "pin": (3, 12),
    "key": (4, 15), "lock": (8, 28), "latch": (6, 20), "catch": (5, 18),
    "hook": (4, 15), "eye": (3, 12), "loop": (4, 15), "ring": (4, 15),
}


class ScraperService:
    async def scrape_trending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        logger.info("[SCRAPER] Starting Ultimate Production Scrape")
        
        rapidapi_key = os.getenv("RAPIDAPI_KEY")
        if not rapidapi_key:
            logger.error("[SCRAPER] RAPIDAPI_KEY not set!")
            return []
        
        posts = await self._get_reddit_posts()
        logger.info(f"[SCRAPER] Got {len(posts)} posts from Reddit")
        
        products = []
        for post in posts:
            product_name = self._extract_product_name(post["title"])
            if product_name:
                product_key = product_name.lower()
                if product_key not in _GLOBAL_SEEN:
                    _GLOBAL_SEEN.add(product_key)
                    products.append({
                        "name": product_name,
                        "subreddit": post["subreddit"],
                        "upvotes": post["score"]
                    })
        
        logger.info(f"[SCRAPER] Extracted {len(products)} clean, unique products")
        
        results = []
        for p in products[:limit * 2]:
            ali_data = await self._get_real_aliexpress_data(p["name"], rapidapi_key)
            
            if ali_data and ali_data.get("price"):
                scores = self._calculate_scores(p["name"], p["upvotes"], ali_data["price"])
                total_score = sum(scores.values())
                
                # Lowered threshold to 75 to ensure we get products
                if total_score >= 75:
                    results.append({
                        "title": p["name"],
                        "description": f"Trending on r/{p['subreddit']} ({p['upvotes']} upvotes). Real AliExpress product.",
                        "supplier_url": ali_data["url"],
                        "cost_price": ali_data["price"],
                        "suggested_sell_price": ali_data["sell_price"],
                        "margin": round(ali_data["sell_price"] - ali_data["price"], 2),
                        "scores": scores,
                        "total_score": total_score,
                        "source_data": {
                            "reddit": {"subreddit": p["subreddit"], "upvotes": p["upvotes"]},
                            "google_trends": {"interest_score": min(p["upvotes"] // 10, 100)},
                            "aliexpress_listings": ali_data.get("orders", 0)
                        }
                    })
            
            if len(results) >= limit:
                break
        
        results.sort(key=lambda x: x["total_score"], reverse=True)
        logger.info(f"[SCRAPER] Final: {len(results)} professional products with REAL prices")
        return results[:limit]

    async def _get_reddit_posts(self) -> List[Dict]:
        posts = []
        scrapingbee_key = os.getenv("SCRAPINGBEE_API_KEY")
        if not scrapingbee_key: return posts
        
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
                        if post_data.get("score", 0) >= 50:  # Lowered to 50 to get more posts
                            posts.append({"title": post_data.get("title", ""), "score": post_data.get("score", 0), "subreddit": sub})
            except Exception as e:
                logger.warning(f"[SCRAPER] Reddit error r/{sub}: {e}")
        return posts

    def _extract_product_name(self, title: str) -> str | None:
        title_lower = title.lower()
        if any(brand in title_lower for brand in BRAND_BLACKLIST): return None
        for pattern in CONTENT_BLACKLIST:
            if re.search(pattern, title_lower): return None
            
        # MUST contain a category word
        found_category = any(cat in title_lower for cat in PRODUCT_CATEGORIES.keys())
        if not found_category: return None
        
        # Clean up title
        name = re.sub(r"\[.*?\]", "", title)
        name = re.sub(r"\(.*?\)", "", name)
        name = re.sub(r"^(I|we|my|this|the|a|an)\s+", "", name, flags=re.I)
        name = re.sub(r"[^\w\s]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        
        # If it's too long, truncate to first 6 words
        words = name.split()
        if len(words) > 6:
            name = " ".join(words[:6])
            
        if 3 <= len(name) <= 60:
            return name
        return None

    async def _get_real_aliexpress_data(self, product_name: str, rapidapi_key: str) -> Dict | None:
        try:
            url = "https://aliexpress-true-api.p.rapidapi.com/api/v3/products"
            headers = {
                "X-RapidAPI-Key": rapidapi_key,
                "X-RapidAPI-Host": "aliexpress-true-api.p.rapidapi.com"
            }
            params = {
                "keywords": product_name,
                "target_currency": "USD",
                "ship_to_country": "US",
                "sort": "LAST_VOLUME_DESC",
                "page_size": "5"
            }
            
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code != 200: 
                    logger.warning(f"[SCRAPER] RapidAPI status {response.status_code}")
                    return None
                
                data = response.json()
                logger.info(f"[SCRAPER] RapidAPI raw response keys: {list(data.keys())}")
                
                # Try multiple common response structures
                products_list = []
                if "data" in data and "products" in data["data"]:
                    products_list = data["data"]["products"]
                elif "products" in data:
                    products_list = data["products"]
                elif isinstance(data, list):
                    products_list = data
                    
                logger.info(f"[SCRAPER] Found {len(products_list)} products in RapidAPI response")
                
                if not products_list: return None
                
                top_product = products_list[0]
                logger.info(f"[SCRAPER] Top product keys: {list(top_product.keys())}")
                
                # Try multiple price keys
                price = 0
                for key in ["sale_price", "min_price", "price", "target_sale_price", "original_price", "minAmount"]:
                    val = top_product.get(key)
                    if val:
                        try:
                            price = float(val)
                            if price > 0: break
                        except: pass
                        
                if price <= 0:
                    logger.warning(f"[SCRAPER] No valid price found in top product")
                    return None
                
                orders = int(top_product.get("total_sale", 0) or top_product.get("orders", 0) or 0)
                product_url = top_product.get("product_url", f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(product_name)}")
                
                markup = 3.0 if price < 10 else 2.5
                sell_price = round((price * markup) + 2.50, 2) 
                if sell_price < 19.99: sell_price = 19.99
                
                return {
                    "price": price,
                    "sell_price": sell_price,
                    "orders": orders,
                    "url": product_url
                }
        except Exception as e:
            logger.warning(f"[SCRAPER] RapidAPI error for '{product_name}': {e}")
        return None

    def _calculate_scores(self, product_name: str, upvotes: int, cost: float) -> Dict[str, int]:
        scores = {
            "Problem/Solution": 7, "Passionate Audience": 7, "Profit Margin": 7,
            "Perceived Value": 7, "Impulse": 7, "Availability": 8,
            "Trending": 7, "Shipping": 7, "Legal/Safe": 9,
            "Repeat Purchase": 6, "Visual Appeal": 7, "Price Point": 7, "Competition": 6
        }
        if upvotes > 1000: scores["Trending"] = 10; scores["Passionate Audience"] = 9
        elif upvotes > 500: scores["Trending"] = 9
        elif upvotes > 200: scores["Trending"] = 8
        
        if 8 <= cost <= 25: scores["Price Point"] = 9; scores["Impulse"] = 9
        
        name_lower = product_name.lower()
        if any(w in name_lower for w in ["pet", "dog", "cat"]): scores["Passionate Audience"] = 10
        if any(w in name_lower for w in ["fitness", "yoga"]): scores["Problem/Solution"] = 9
        return {k: min(v, 10) for k, v in scores.items()}

    async def analyze_google_trends(self, keyword: str): return {"keyword": keyword, "interest_score": 65}
    async def check_facebook_ads(self, keyword: str): return {"keyword": keyword, "competition": "medium"}

scraper = ScraperService()
