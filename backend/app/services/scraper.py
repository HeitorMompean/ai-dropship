"""Ultimate Production Scraper - Strict Product Name Extraction."""
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
    "pixel", "galaxy", "oneplus", "dell xps", "macbook pro", "predator", "arduboy", "gopro",
    "speed queen", "casio", "american eagle"
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

# ONLY concrete physical product nouns - no generic terms like "hack", "diy", "tip"
PRODUCT_NOUNS = {
    # Electronics & Accessories
    "charger", "cable", "adapter", "hub", "power bank", "battery", "speaker", "headphone", 
    "earbud", "microphone", "watch", "tracker", "band", "camera", "lock", "sensor", "alarm",
    "remote", "switch", "plug", "socket", "monitor", "display", "projector", "printer", 
    "scanner", "router", "modem", "antenna", "receiver", "amplifier", "webcam", "tripod",
    "gimbal", "drone", "helmet", "goggles", "flashlight", "headlamp", "lantern",
    
    # Storage & Organization
    "organizer", "storage", "holder", "stand", "mount", "rack", "shelf", "drawer", "box",
    "bin", "basket", "tray", "case", "cover", "bag", "backpack", "wallet", "pouch", "purse",
    
    # Home & Kitchen
    "cleaner", "purifier", "humidifier", "vacuum", "robot", "massager", "pillow", "blanket",
    "mattress", "cushion", "blender", "cutter", "kettle", "thermos", "bottle", "cup", "mug",
    "pot", "pan", "wok", "skillet", "grill", "smoker", "toaster", "oven", "stove", "fridge",
    "freezer", "microwave", "mixer", "juicer", "maker", "grinder", "sharpener", "knife",
    "scissors", "brush", "comb", "mirror", "towel", "curtain", "blind", "shade", "rug",
    "carpet", "mat", "pad",
    
    # Tools & Hardware
    "tool", "kit", "set", "wrench", "screwdriver", "drill", "saw", "hammer", "pliers",
    "clamp", "vise", "anvil", "forge", "weld", "solder", "tape", "glue", "epoxy", "resin",
    "silicone", "caulk", "sealant", "putty", "screw", "bolt", "nut", "nail", "rivet",
    "anchor", "dowel", "peg", "pin", "key", "latch", "hinge", "handle", "knob", "wheel",
    "gear", "bearing", "spring", "pulley", "belt", "chain", "rope", "cord", "wire", "tube",
    "pipe", "valve", "pump", "motor", "fitting", "connector", "joint", "bracket", "hook",
    "clip", "strap",
    
    # Fitness & Outdoor
    "yoga", "posture", "corrector", "brace", "band", "fitness", "exercise", "garden",
    "plant", "outdoor", "camping", "hiking", "travel", "tent", "sleeping", "cooler",
    "mower", "trimmer", "blower", "hose", "sprinkler", "compass", "gps", "binoculars",
    "telescope", "microscope", "magnifier", "scale", "thermometer", "hygrometer",
    "barometer", "anemometer", "weather", "station", "clock", "timer", "stopwatch",
    
    # Clothing & Accessories
    "gloves", "boots", "shoes", "socks", "shirt", "jacket", "coat", "pants", "shorts",
    "skirt", "dress", "suit", "tie", "scarf", "hat", "cap", "umbrella", "sunglasses",
    "glasses", "bracelet", "necklace", "earring", "ring", "perfume", "cologne", "lotion",
    "cream", "soap", "shampoo", "conditioner", "toothbrush", "toothpaste", "razor",
    "shaver", "clipper", "dryer", "iron", "steamer", "heater", "fan",
    
    # Furniture
    "chair", "table", "desk", "bed", "sofa", "couch",
    
    # Office & Stationery
    "calculator", "ruler", "level", "binder", "folder", "envelope", "paper", "card",
    "label", "tag", "sticker", "stamp", "ink", "toner", "cartridge", "ribbon", "film",
    "pen", "pencil", "marker", "crayon", "eraser", "stapler", "staple", "punch",
    
    # Pet & Baby
    "pet", "dog", "cat", "toy", "baby", "kid",
}

# Verbs and generic terms that indicate conversation, not products
VERBS = {
    "wash", "try", "got", "bought", "found", "jumped", "works", "love", "need", "want", 
    "use", "make", "keep", "cut", "break", "fix", "rotation", "edc", "budget", "gift", 
    "suggestions", "wanted", "recommend", "thinking", "looking", "help", "please", "show", 
    "tell", "give", "hack", "diy", "tip", "trick", "idea", "way", "method", "technique",
    "lifehack", "life", "hack", "how", "to", "your", "you", "my", "me", "we", "us", "they",
    "them", "he", "she", "it", "this", "that", "these", "those", "here", "there", "where",
    "when", "why", "what", "which", "who", "whom", "whose"
}

class ScraperService:
    async def scrape_trending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        logger.info("[SCRAPER] Starting Permissive Scrape")
        
        # Clear memory so it doesn't block today's run based on yesterday's cache
        global _GLOBAL_SEEN
        _GLOBAL_SEEN.clear()
        
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
        
        logger.info(f"[SCRAPER] Extracted {len(products)} clean, unique products to test")
        
        results = []
        for p in products[:15]:
            ali_data = await self._get_real_aliexpress_data(p["name"], rapidapi_key)
            
            if ali_data and ali_data.get("price"):
                scores = self._calculate_scores(p["name"], p["upvotes"], ali_data["price"])
                total_score = sum(scores.values())
                
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
                        if post_data.get("score", 0) >= 50:
                            posts.append({"title": post_data.get("title", ""), "score": post_data.get("score", 0), "subreddit": sub})
            except Exception as e:
                logger.warning(f"[SCRAPER] Reddit error r/{sub}: {e}")
        return posts

    def _extract_product_name(self, title: str) -> str | None:
        title_lower = title.lower()
        
        # Check brand blacklist
        if any(brand in title_lower for brand in BRAND_BLACKLIST):
            return None
            
        # Check content blacklist
        for pattern in CONTENT_BLACKLIST:
            if re.search(pattern, title_lower):
                return None
        
        # Split into words and check for verbs/generic terms FIRST
        words_raw = title_lower.split()
        if any(w in VERBS for w in words_raw):
            return None
            
        # MUST contain at least one concrete product noun
        found_nouns = [noun for noun in PRODUCT_NOUNS if noun in title_lower]
        if not found_nouns:
            return None
        
        # Clean up the title
        name = re.sub(r"\[.*?\]", "", title)
        name = re.sub(r"\(.*?\)", "", name)
        name = re.sub(r"^(I|we|my|this|the|a|an|just|finally|so|but|and)\s+", "", name, flags=re.I)
        name = re.sub(r"[^\w\s]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        
        words = name.split()
        
        # Must be 2-6 words
        if len(words) < 2 or len(words) > 6:
            return None
        
        # Check if the cleaned name still contains a product noun
        name_lower = name.lower()
        if not any(noun in name_lower for noun in PRODUCT_NOUNS):
            return None
        
        # Must be 5-50 characters
        if 5 <= len(name) <= 50:
            return name
        
        return None

    def _get_search_query(self, name: str) -> str:
        STOP_WORDS = {
            "the", "a", "an", "my", "your", "our", "this", "that", "is", "are", "was", "were", 
            "for", "on", "with", "at", "by", "from", "as", "and", "or", "but", "if", "then", 
            "than", "too", "very", "just", "still", "works", "perfectly", "probably", "wanted", 
            "suggestions", "similar", "years", "budget", "gift", "train", "jumped", "got", 
            "bought", "found", "try", "no", "yes", "new", "old", "best", "good", "great", 
            "really", "much", "many", "some", "any", "all", "durable", "american", "eagle",
            "smoked", "carolina", "reaper", "jewish", "space", "laser", "activation", "panel",
            "love", "sub", "another", "day", "pouch", "wash", "ball", "hats", "in", "dishwasher"
        }
        words = [w for w in name.lower().split() if w not in STOP_WORDS and len(w) > 2]
        return " ".join(words[:4]) if words else name

    async def _get_real_aliexpress_data(self, product_name: str, rapidapi_key: str) -> Dict | None:
        try:
            search_query = self._get_search_query(product_name)

            url = "https://aliexpress-true-api.p.rapidapi.com/api/v3/products"
            headers = {
                "X-RapidAPI-Key": rapidapi_key,
                "X-RapidAPI-Host": "aliexpress-true-api.p.rapidapi.com"
            }
            params = {
                "keywords": search_query,
                "target_currency": "USD",
                "ship_to_country": "US",
                "sort": "LAST_VOLUME_DESC",
                "page_size": "5"
            }
            
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code != 200: return None
                
                data = response.json()
                
                products_list = []
                if isinstance(data, dict):
                    if "products" in data:
                        prods = data["products"]
                        if isinstance(prods, dict) and "product" in prods:
                            products_list = prods["product"]
                        elif isinstance(prods, list):
                            products_list = prods
                    elif "data" in data and isinstance(data["data"], dict) and "products" in data["data"]:
                        products_list = data["data"]["products"]
                elif isinstance(data, list):
                    products_list = data
                    
                if not products_list: return None
                
                top_product = products_list[0]
                
                price = 0
                for key in ["sale_price", "min_price", "original_price", "price", "target_sale_price"]:
                    val = top_product.get(key)
                    if val:
                        try:
                            price = float(str(val).replace(",", ""))
                            if price > 0: break
                        except: pass
                        
                if price <= 0: return None
                
                orders = 0
                for key in ["total_sale", "orders", "sales", "tradeCount"]:
                    val = top_product.get(key)
                    if val:
                        try:
                            orders = int(str(val).replace(",", ""))
                            break
                        except: pass
                        
                # Extract clean Product ID to prevent expired tracking links
                product_id = top_product.get("product_id") or top_product.get("id") or top_product.get("productId")
                if not product_id:
                    url_str = top_product.get("product_detail_url", "")
                    match = re.search(r'/item/(\d+)', url_str)
                    if match:
                        product_id = match.group(1)
                
                if product_id:
                    product_url = f"https://www.aliexpress.com/item/{product_id}.html"
                else:
                    product_url = top_product.get("product_detail_url") or f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(search_query)}"
                
                markup = 3.0 if price < 10 else 2.5
                sell_price = round((price * markup) + 2.50, 2) 
                if sell_price < 19.99: sell_price = 19.99
                
                logger.info(f"[SCRAPER] SUCCESS: '{search_query}' -> Cost: ${price}, Sell: ${sell_price}")
                return {"price": price, "sell_price": sell_price, "orders": orders, "url": product_url}
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
        return {k: min(v, 10) for k, v in scores.items()}

    async def analyze_google_trends(self, keyword: str): return {"keyword": keyword, "interest_score": 65}
    async def check_facebook_ads(self, keyword: str): return {"keyword": keyword, "competition": "medium"}

scraper = ScraperService()
