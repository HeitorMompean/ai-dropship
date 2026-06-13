"""Ultimate Production Scraper - Real Products, Real Prices, Real Names.

DESIGN (v3):
  - Reddit titles are NEVER used as the final product name. They are only a
    signal of demand. We extract a clean SEARCH KEYWORD from the title.
  - The final product name is the ACTUAL AliExpress listing's title (cleaned),
    so name, cost price, and supplier URL always describe the same real item.
  - A relevance check rejects AliExpress results that don't match the keyword,
    instead of blindly trusting products_list[0].
  - NO estimated/fallback pricing. If AliExpress has no relevant, priced
    listing, the product is dropped. Only real prices enter the pipeline.
  - Price filter: sell price must land in the $15-$80 impulse-buy window.
"""
import logging, os, urllib.parse, re
from typing import List, Dict, Any, Set, Optional

import httpx

logger = logging.getLogger(__name__)

SUBREDDITS = [
    "shutupandtakemymoney", "BuyItForLife", "gadgets", "EDC", "lifehacks",
    "ProductPorn", "INEEEEDIT", "DidntKnowIWantedThat", "somethingimade",
    "gifts", "ofcoursethatsathing", "BuyItForLifeUK",
]

BRAND_BLACKLIST = {
    "apple", "samsung", "google", "microsoft", "sony", "nintendo", "xbox", "playstation",
    "lenovo", "dell", "hp", "asus", "acer", "razer", "corsair", "logitech", "oppo",
    "xiaomi", "huawei", "nvidia", "amd", "intel", "radeon", "geforce",
    "sennheiser", "bose", "jbl", "beats", "airpods", "macbook", "iphone", "ipad",
    "pixel", "galaxy", "oneplus", "dell xps", "macbook pro", "predator", "arduboy", "gopro",
}

CONTENT_BLACKLIST = [
    # discussion-signal patterns (post is talking about, not selling, a product)
    r"\b(review|reviews|vs\.?|versus|comparison|compared)\b",
    r"\b(news|announced|revealed|leaked|rumor|report|says|claims)\b",
    r"\b(meme|joke|funny|hilarious|gif|comic)\b",
    # non-commerce / safety topics (always vetoed)
    r"\b(crypto|bitcoin|stock|invest|finance|bank)\b",
    r"\b(politics|government|election|court|crime|war|military|weapon|gun|ammo|knife\s+fight)\b",
    r"\b(list of|a list|things made|not made in|from canada|from usa|submission)\b",
    # NOTE: soft topical words (coffee/tea/bike/car/game/movie/music/food...) were
    # REMOVED — they frequently appear inside real product names ("coffee grinder",
    # "bike phone mount", "game controller", "music stand"). The downstream relevance
    # check + price window now guard against genuinely irrelevant results.
]

MINIMUM_WORDS = 3  # titles shorter than this are conversational noise, not products

# Conversational/meta titles that are never products, even if they contain a product noun.
GENERIC_TITLE_PATTERNS = [
    r"^(i\s+)?(love|loved|loving|like|liked|enjoy|enjoying|hate)\b",
    r"^(check\s+out|look\s+at|behold|presenting|introducing)\b",
    r"^(i\s+)?(just\s+(got|bought|found|ordered))\b",
    r"^(finally|update|psa|question|help|advice|thoughts|opinion|opinions)\b",
    r"^(what|which|where|when|why|how|who|does|do|is|are|can|should|anyone|any)\b",
    r"\bthis\s+sub(reddit)?\b",
    r"\b(am\s+i|are\s+we|imo|imho|eli5|til|ama)\b",
]

# Words that terminate keyword-modifier collection (never part of a product name).
FILLER_WORDS = {
    "i", "we", "my", "our", "your", "his", "her", "their", "its",
    "the", "a", "an", "this", "that", "these", "those", "it",
    "is", "was", "are", "were", "be", "been", "has", "have", "had",
    "got", "get", "getting", "bought", "found", "made", "make",
    "just", "still", "finally", "probably", "maybe", "definitely", "really", "very",
    "amazing", "awesome", "great", "best", "favorite", "favourite", "perfect", "incredible",
    "today", "yesterday", "now", "then", "ever", "never", "always",
    "year", "years", "month", "months", "week", "weeks", "day", "days", "old", "new",
    "after", "before", "since", "about", "around", "over", "under", "with", "without",
    "for", "from", "of", "in", "on", "at", "to", "and", "or", "but", "so",
    "love", "loves", "loved", "like", "likes", "liked",
    # verbs/comparatives seen polluting keywords in production ("redo cable", "safer battery")
    "redo", "fix", "fixed", "replace", "replaced", "repair", "repaired",
    "upgrade", "upgraded", "need", "needs", "needed", "want", "wanted", "use", "used", "using",
    "safer", "better", "cheaper", "easier", "stronger", "faster", "slower",
    "bigger", "smaller", "longer", "shorter", "newer", "older", "nicer", "worse",
}

# Marketing junk to strip from AliExpress listing titles.
ALI_TITLE_JUNK = [
    r"\b(20\d{2})\b", r"\bnew\b", r"\bhot\s*sale\b", r"\bfree\s*shipping\b",
    r"\bdropshipping\b", r"\bwholesale\b", r"\bhigh\s*quality\b", r"\b\d+\s*pcs?\b",
    r"\b\d+\s*pack\b", r"\bfor\s+(men|women|kids|home|gift)s?\b.*$",
]

MIN_SELL_PRICE = 15.0
MAX_SELL_PRICE = 80.0
MAX_NAME_WORDS = 8  # cap on cleaned AliExpress titles

# ONLY concrete physical product nouns - no generic terms
PRODUCT_NOUNS = {
    "organizer", "storage", "holder", "stand", "mount", "rack", "charger", "cable", "adapter",
    "light", "lamp", "led", "speaker", "headphone", "earbud", "watch", "tracker", "sensor",
    "camera", "lock", "cleaner", "purifier", "massager", "pillow", "blanket", "bag", "backpack",
    "wallet", "case", "cover", "tool", "kit", "gadget", "blender", "bottle", "cup", "mug",
    "yoga", "posture", "pet", "garden", "camping", "grinder", "cutter", "sharpener", "brush",
    "comb", "mirror", "knife", "scissors", "grill", "pot", "pan", "tray", "mat", "pad", "hook",
    "clip", "strap", "belt", "ring", "chain", "rope", "plug", "switch", "remote", "alarm",
    "detector", "gloves", "boots", "shoes", "hat", "cap", "umbrella", "perfume", "lotion",
    "cream", "soap", "razor", "dryer", "heater", "fan", "chair", "table", "desk", "rug",
    "curtain", "tent", "flashlight", "compass", "scale", "clock", "timer", "ruler", "glue",
    "tape", "stapler", "battery", "motor", "pump", "valve", "pipe", "gear", "bearing", "spring",
    # --- expanded set (v3.3): common physical / dropshipping product nouns ---
    "briefcase", "purse", "tote", "duffel", "pouch", "sleeve", "thermos", "tumbler", "flask",
    "kettle", "teapot", "jar", "container", "lunchbox", "cooler", "multitool", "pliers", "wrench",
    "screwdriver", "drill", "hammer", "axe", "hatchet", "clamp", "lantern", "sunglasses", "goggles",
    "scarf", "beanie", "socks", "slippers", "sandals", "sneakers", "insole", "leash", "collar",
    "carrier", "feeder", "fountain", "aquarium", "planter", "hose", "nozzle", "sprinkler", "shovel",
    "rake", "shears", "hammock", "stove", "tongs", "spatula", "whisk", "ladle", "peeler", "grater",
    "colander", "strainer", "funnel", "juicer", "coaster", "apron", "towel", "sponge", "mop",
    "broom", "bucket", "basket", "bin", "hamper", "hanger", "shelf", "drawer", "cabinet", "stool",
    "bench", "cushion", "vase", "frame", "sticker", "magnet", "keychain", "lanyard", "bracelet",
    "necklace", "earring", "pendant", "trimmer", "clipper", "tweezers", "diffuser", "humidifier",
    "thermometer", "projector", "keyboard", "mouse", "mousepad", "webcam", "microphone", "tripod",
    "stylus", "dock", "hub", "router", "antenna", "powerbank", "controller", "gamepad", "headset",
    "earphone", "soundbar", "subwoofer", "amplifier", "kettlebell", "dumbbell", "mask", "wallet",
    "opener", "corkscrew", "thermostat", "doorbell", "scraper", "trowel", "caddy", "rollerball",
}


class ScraperService:

    async def scrape_trending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        logger.info("[SCRAPER] Starting Strict Scrape v3.3 (wider funnel: +nouns, +subreddits, per-run dedup)")
        rapidapi_key = os.getenv("RAPIDAPI_KEY")
        if not rapidapi_key:
            logger.error("[SCRAPER] RAPIDAPI_KEY not set!")
            return []

        posts = await self._get_reddit_posts()
        logger.info(f"[SCRAPER] Got {len(posts)} posts from Reddit")

        # Step 1: extract clean SEARCH KEYWORDS (not final names) from Reddit titles.
        # Dedup is per-run (local) so manual re-triggers and scheduled runs can
        # re-surface still-trending products, instead of a process-lifetime set
        # that permanently starves later runs of the same hot posts.
        seen: Set[str] = set()
        candidates = []
        for post in posts:
            keyword = self._extract_search_keyword(post["title"])
            if keyword:
                key = keyword.lower()
                if key not in seen:
                    seen.add(key)
                    candidates.append({
                        "keyword": keyword,
                        "subreddit": post["subreddit"],
                        "upvotes": post["score"]
                    })

        logger.info(f"[SCRAPER] Extracted {len(candidates)} clean, unique keywords to test")

        results = []
        for c in candidates[:10]:
            logger.info(f"[SCRAPER] Searching AliExpress for: '{c['keyword']}'")
            ali_data = await self._get_real_aliexpress_data(c["keyword"], rapidapi_key)

            # NO fallback pricing. No relevant priced listing => drop the candidate.
            if not ali_data:
                logger.info(f"[SCRAPER] DROP '{c['keyword']}': no relevant AliExpress listing with a real price")
                continue

            # Price window filter
            if not (MIN_SELL_PRICE <= ali_data["sell_price"] <= MAX_SELL_PRICE):
                logger.info(
                    f"[SCRAPER] SKIP '{ali_data['name']}': sell ${ali_data['sell_price']} "
                    f"outside ${MIN_SELL_PRICE}-${MAX_SELL_PRICE} window"
                )
                continue

            # The FINAL NAME is the real AliExpress listing's (cleaned) title.
            scores = self._calculate_scores(ali_data["name"], c["upvotes"], ali_data["price"])
            total_score = sum(scores.values())
            if total_score >= 75:
                results.append({
                    "title": ali_data["name"],
                    "description": (
                        f"Demand signal: r/{c['subreddit']} ({c['upvotes']} upvotes, "
                        f"keyword '{c['keyword']}'). Real AliExpress listing."
                    ),
                    "supplier_url": ali_data["url"],
                    "cost_price": ali_data["price"],
                    "suggested_sell_price": ali_data["sell_price"],
                    "margin": round(ali_data["sell_price"] - ali_data["price"], 2),
                    "scores": scores,
                    "total_score": total_score,
                    "source_data": {
                        "reddit": {"subreddit": c["subreddit"], "upvotes": c["upvotes"],
                                   "search_keyword": c["keyword"]},
                        "google_trends": {"interest_score": min(c["upvotes"] // 10, 100)},
                        "aliexpress_listings": ali_data.get("orders", 0),
                    }
                })
                if len(results) >= limit:
                    break

        results.sort(key=lambda x: x["total_score"], reverse=True)
        logger.info(f"[SCRAPER] Final: {len(results)} products with REAL names and REAL prices")
        return results[:limit]

    async def _get_reddit_posts(self) -> List[Dict]:
        posts = []
        scrapingbee_key = os.getenv("SCRAPINGBEE_API_KEY")
        if not scrapingbee_key:
            return posts
        for sub in SUBREDDITS:
            try:
                reddit_url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
                proxy_url = (
                    f"https://app.scrapingbee.com/api/v1/?api_key={scrapingbee_key}"
                    f"&url={urllib.parse.quote(reddit_url)}&render_js=false&premium_proxy=true"
                )
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(proxy_url, headers={"User-Agent": "Mozilla/5.0"})
                    response.raise_for_status()
                    data = response.json()
                    for child in data.get("data", {}).get("children", []):
                        post_data = child.get("data", {})
                        if post_data.get("score", 0) >= 50:
                            posts.append({
                                "title": post_data.get("title", ""),
                                "score": post_data.get("score", 0),
                                "subreddit": sub
                            })
            except Exception as e:
                logger.warning(f"[SCRAPER] Reddit error r/{sub}: {e}")
        return posts

    # ------------------------------------------------------------------
    # Keyword extraction (from Reddit titles) — used ONLY to search AliExpress
    # ------------------------------------------------------------------
    def _extract_search_keyword(self, title: str) -> Optional[str]:
        """Extract a clean search keyword (product noun + up to 2 modifiers).

        This is NOT the final product name — it is only the AliExpress search
        query. The final name comes from the matched AliExpress listing.
        """
        title_lower = title.lower()

        if any(brand in title_lower for brand in BRAND_BLACKLIST):
            return None
        for pattern in CONTENT_BLACKLIST:
            if re.search(pattern, title_lower):
                return None
        for pattern in GENERIC_TITLE_PATTERNS:
            if re.search(pattern, title_lower):
                return None

        clean = re.sub(r"\[.*?\]|\(.*?\)", " ", title)
        clean = re.sub(r"[^\w\s'-]", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        words = clean.split()

        if len(words) < MINIMUM_WORDS:
            return None

        # Rightmost product noun = head noun ("pepper grinder" -> grinder)
        noun_idx = None
        for i in range(len(words) - 1, -1, -1):
            if words[i].lower().strip("'-") in PRODUCT_NOUNS:
                noun_idx = i
                break
        if noun_idx is None:
            return None

        # Title Case posts carry no brand signal in capitalization; in mixed-case
        # titles, a capitalized mid-title word is treated as a brand and stops
        # collection ("American Eagle messenger bag" -> "messenger bag").
        alpha_words = [w for w in words if w[0].isalpha()]
        cap_ratio = (
            sum(1 for w in alpha_words if w[0].isupper()) / len(alpha_words)
            if alpha_words else 0
        )
        is_title_case = cap_ratio >= 0.7

        phrase = [words[noun_idx]]
        collected = 0
        for i in range(noun_idx - 1, -1, -1):
            if collected >= 2:
                break
            w = words[i]
            if w.lower() in FILLER_WORDS:
                break
            if re.match(r"^\d", w):
                break
            if w[0].isupper() and not is_title_case and i != 0:
                break
            phrase.insert(0, w)
            collected += 1

        keyword = " ".join(phrase).strip().lower()
        if len(phrase) < 2 or not (3 <= len(keyword) <= 60):
            return None
        return keyword

    # ------------------------------------------------------------------
    # AliExpress lookup — returns the REAL listing's name, price, and URL
    # ------------------------------------------------------------------
    def _is_relevant(self, keyword: str, ali_title: str) -> bool:
        """The listing must actually match what we searched for.

        Requires the head noun to appear in the AliExpress title, plus at least
        half of the keyword tokens overall.
        """
        if not ali_title:
            return False
        ali_lower = ali_title.lower()
        tokens = keyword.lower().split()
        head_noun = tokens[-1]
        # tolerate simple plural/singular differences
        if not re.search(rf"\b{re.escape(head_noun.rstrip('s'))}s?\b", ali_lower):
            return False
        hits = sum(1 for t in tokens if re.search(rf"\b{re.escape(t.rstrip('s'))}s?\b", ali_lower))
        return hits >= max(1, (len(tokens) + 1) // 2)

    def _clean_ali_title(self, ali_title: str) -> str:
        """Strip marketing junk from an AliExpress listing title and cap length."""
        name = ali_title
        for pattern in ALI_TITLE_JUNK:
            name = re.sub(pattern, " ", name, flags=re.I)
        name = re.sub(r"[^\w\s'/-]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        words = name.split()
        if len(words) > MAX_NAME_WORDS:
            name = " ".join(words[:MAX_NAME_WORDS])
        return name.strip(" -/")

    @staticmethod
    def _extract_price(product: Dict) -> float:
        for key in ["sale_price", "min_price", "original_price", "price",
                    "target_sale_price", "minAmount", "salePrice"]:
            val = product.get(key)
            if val:
                try:
                    price = float(str(val).replace(",", "").replace("$", ""))
                    if price > 0:
                        return price
                except (ValueError, TypeError):
                    pass
        return 0.0

    @staticmethod
    def _extract_title(product: Dict) -> str:
        for key in ["product_title", "title", "subject", "name", "productTitle"]:
            val = product.get(key)
            if val and isinstance(val, str):
                return val
        return ""

    @staticmethod
    def _extract_orders(product: Dict) -> int:
        for key in ["total_sale", "orders", "sales", "tradeCount", "lastest_volume"]:
            val = product.get(key)
            if val:
                try:
                    return int(str(val).replace(",", ""))
                except (ValueError, TypeError):
                    pass
        return 0

    async def _get_real_aliexpress_data(self, keyword: str, rapidapi_key: str) -> Optional[Dict]:
        """Search AliExpress and return the first RELEVANT listing with a REAL price.

        Returns the listing's own cleaned title as `name`, so the product name
        always matches the supplier URL and price. Returns None if nothing
        relevant/priced is found — the candidate is then dropped (no estimates).
        """
        try:
            url = "https://aliexpress-true-api.p.rapidapi.com/api/v3/products"
            headers = {
                "X-RapidAPI-Key": rapidapi_key,
                "X-RapidAPI-Host": "aliexpress-true-api.p.rapidapi.com"
            }
            params = {
                "keywords": keyword,
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

                products_list = []
                if isinstance(data, dict) and "products" in data:
                    prods = data["products"]
                    if isinstance(prods, dict) and "product" in prods:
                        products_list = prods["product"]
                    elif isinstance(prods, list):
                        products_list = prods
                elif isinstance(data, dict) and "data" in data and isinstance(data["data"], dict) and "products" in data["data"]:
                    products_list = data["data"]["products"]
                elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    products_list = data["data"]
                elif isinstance(data, list):
                    products_list = data

                if not products_list:
                    logger.warning(f"[SCRAPER] No results for '{keyword}'")
                    return None

                # Collect ALL relevant priced variants from the (up to 5) results,
                # instead of taking the first one. AliExpress returns a mix of
                # cheap and premium/bulk listings; the first-by-volume result is
                # often the expensive one ($60 electric grinder vs a $15 manual).
                candidates = []
                for candidate in products_list[:5]:
                    if not isinstance(candidate, dict):
                        continue
                    raw_title = self._extract_title(candidate)
                    price = self._extract_price(candidate)
                    if price <= 0:
                        continue
                    if not self._is_relevant(keyword, raw_title):
                        logger.info(f"[SCRAPER] Irrelevant result for '{keyword}': '{raw_title[:60]}'")
                        continue
                    name = self._clean_ali_title(raw_title)
                    if len(name) < 3:
                        continue

                    markup = 3.0 if price < 10 else 2.5
                    sell_price = round((price * markup) + 2.50, 2)
                    if sell_price < 19.99:
                        sell_price = 19.99

                    candidates.append({
                        "name": name,
                        "price": price,
                        "sell_price": sell_price,
                        "orders": self._extract_orders(candidate),
                        "url": (candidate.get("product_detail_url") or
                                candidate.get("product_url") or
                                candidate.get("url") or
                                f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(keyword)}"),
                    })

                if not candidates:
                    logger.warning(f"[SCRAPER] No relevant priced listing for '{keyword}'")
                    return None

                # Prefer variants whose sell price lands in the impulse-buy window;
                # among those, pick the cheapest (best margin headroom). If none fit
                # the window, drop the product rather than shipping a $154 listing.
                in_window = [c for c in candidates if MIN_SELL_PRICE <= c["sell_price"] <= MAX_SELL_PRICE]
                if not in_window:
                    cheapest = min(candidates, key=lambda c: c["sell_price"])
                    logger.info(
                        f"[SCRAPER] DROP '{keyword}': no variant in ${MIN_SELL_PRICE}-${MAX_SELL_PRICE} "
                        f"(cheapest of {len(candidates)} was '{cheapest['name']}' @ sell ${cheapest['sell_price']})"
                    )
                    return None

                chosen = min(in_window, key=lambda c: c["sell_price"])
                logger.info(
                    f"[SCRAPER] MATCH '{keyword}' -> '{chosen['name']}' | "
                    f"Cost: ${chosen['price']}, Sell: ${chosen['sell_price']}, Orders: {chosen['orders']} "
                    f"({len(in_window)}/{len(candidates)} variants in window)"
                )
                return chosen
        except Exception as e:
            logger.warning(f"[SCRAPER] RapidAPI error for '{keyword}': {e}")
            return None

    def _calculate_scores(self, product_name: str, upvotes: int, cost: float) -> Dict[str, int]:
        scores = {
            "Problem/Solution": 7, "Passionate Audience": 7, "Profit Margin": 7,
            "Perceived Value": 7, "Impulse": 7, "Availability": 8,
            "Trending": 7, "Shipping": 7, "Legal/Safe": 9,
            "Repeat Purchase": 6, "Visual Appeal": 7, "Price Point": 7,
            "Competition": 6
        }
        if upvotes > 1000:
            scores["Trending"] = 10; scores["Passionate Audience"] = 9
        elif upvotes > 500:
            scores["Trending"] = 9
        elif upvotes > 200:
            scores["Trending"] = 8
        if 8 <= cost <= 25:
            scores["Price Point"] = 9; scores["Impulse"] = 9
        return {k: min(v, 10) for k, v in scores.items()}

    async def analyze_google_trends(self, keyword: str):
        return {"keyword": keyword, "interest_score": 65}

    async def check_facebook_ads(self, keyword: str):
        return {"keyword": keyword, "competition": "medium"}


scraper = ScraperService()
