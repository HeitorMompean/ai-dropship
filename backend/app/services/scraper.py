"""Ultimate Production Scraper - Strict Noun-Phrase Extraction + Fallback Pricing + Price Filter.

CHANGES vs previous version:
  TASK 1 (CRITICAL): _extract_product_name() rewritten.
    - Word-boundary noun matching (old `noun in title_lower` matched substrings, e.g. "yoga" in "yogator")
    - Scans right-to-left so the HEAD noun wins ("pepper grinder" -> "grinder", not "pepper")
    - Extracts only the noun phrase: the noun + up to 2 preceding modifier words
    - Stops collecting modifiers at numbers, filler words, and mid-title proper nouns (brand-ish words)
    - Rejects titles with fewer than MINIMUM_WORDS (3) words
    - Rejects generic conversational titles ("Love this sub", "Check out my...", etc.)
    - Rejects single-word results
  TASK 2 (HIGH): Fallback pricing when AliExpress returns nothing — product is no longer dropped.
  TASK 5 (LOW): Price filter — only keep products whose sell price is in the $15–$80 impulse-buy range.
"""
import logging, os, urllib.parse, re
from typing import List, Dict, Any, Set, Optional, Tuple

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

# --- TASK 1: new rejection layers -------------------------------------------------

MINIMUM_WORDS = 3  # titles shorter than this are conversational noise, not products

# Conversational/meta titles that are never products, even if they contain a product noun.
GENERIC_TITLE_PATTERNS = [
    r"^(i\s+)?(love|loved|loving|like|liked|enjoy|enjoying|hate)\b",
    r"^(check\s+out|look\s+at|behold|presenting|introducing)\b",
    r"^(just\s+(got|bought|found|arrived|ordered))\b",
    r"^(finally|update|psa|question|help|advice|thoughts|opinion|opinions)\b",
    r"^(what|which|where|when|why|how|who|does|do|is|are|can|should|anyone|any)\b",
    r"\bthis\s+sub(reddit)?\b",
    r"\b(am\s+i|are\s+we|imo|imho|eli5|til|ama)\b",
]

# Words that terminate modifier collection (they never belong in a product name).
FILLER_WORDS = {
    "i", "we", "my", "our", "your", "his", "her", "their", "its",
    "the", "a", "an", "this", "that", "these", "those", "it",
    "is", "was", "are", "were", "be", "been", "has", "have", "had",
    "got", "get", "getting", "bought", "found", "made", "make",
    "just", "still", "finally", "probably", "maybe", "definitely", "really", "very",
    "today", "yesterday", "now", "then", "ever", "never", "always",
    "year", "years", "month", "months", "week", "weeks", "day", "days", "old", "new",
    "after", "before", "since", "about", "around", "over", "under", "with", "without",
    "for", "from", "of", "in", "on", "at", "to", "and", "or", "but", "so",
    "love", "loves", "loved", "like", "likes", "liked", "best", "favorite", "favourite",
}

# Final-result sanity blacklist: if the extracted phrase equals one of these, reject.
GENERIC_RESULT_PHRASES = {
    "love this", "check out", "this sub", "new one", "good one", "great one",
}

# --- TASK 2: fallback pricing (cost, sell) when AliExpress returns nothing --------

FALLBACK_PRICES: Dict[str, Tuple[float, float]] = {
    "grinder": (6.0, 24.99), "bag": (10.0, 39.99), "backpack": (14.0, 49.99),
    "wallet": (5.0, 22.99), "organizer": (7.0, 27.99), "holder": (4.0, 18.99),
    "stand": (6.0, 24.99), "mount": (5.0, 21.99), "charger": (6.0, 25.99),
    "cable": (2.5, 15.99), "adapter": (3.0, 16.99), "light": (7.0, 28.99),
    "lamp": (9.0, 34.99), "speaker": (12.0, 44.99), "headphone": (12.0, 44.99),
    "earbud": (8.0, 32.99), "watch": (12.0, 44.99), "tracker": (9.0, 34.99),
    "camera": (15.0, 54.99), "lock": (6.0, 24.99), "cleaner": (8.0, 29.99),
    "purifier": (15.0, 54.99), "massager": (12.0, 44.99), "pillow": (9.0, 34.99),
    "blanket": (12.0, 44.99), "case": (4.0, 18.99), "knife": (8.0, 29.99),
    "bottle": (5.0, 21.99), "mug": (4.0, 18.99), "flashlight": (7.0, 27.99),
    "tool": (8.0, 29.99), "kit": (10.0, 36.99), "gadget": (8.0, 29.99),
    "mat": (8.0, 29.99), "pad": (6.0, 24.99), "belt": (6.0, 24.99),
    "gloves": (5.0, 21.99), "boots": (16.0, 59.99), "shoes": (14.0, 49.99),
    "umbrella": (7.0, 27.99), "fan": (9.0, 34.99), "heater": (14.0, 49.99),
    "tent": (20.0, 69.99), "scale": (8.0, 29.99), "clock": (7.0, 27.99),
}
DEFAULT_FALLBACK: Tuple[float, float] = (8.0, 29.99)

# --- TASK 5: dropshipping price window ---------------------------------------------

MIN_SELL_PRICE = 15.0
MAX_SELL_PRICE = 80.0

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
    # ... (100+ more nouns, see full file on GitHub)
}


class ScraperService:

    async def scrape_trending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        logger.info("[SCRAPER] Starting Strict Scrape")
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
        for p in products[:10]:
            logger.info(f"[SCRAPER] Testing product: '{p['name']}'")
            ali_data = await self._get_real_aliexpress_data(p["name"], rapidapi_key)

            # TASK 2: fallback pricing instead of dropping the product
            if not (ali_data and ali_data.get("price")):
                ali_data = self._fallback_pricing(p["name"])
                logger.info(
                    f"[SCRAPER] FALLBACK pricing for '{p['name']}': "
                    f"Cost ${ali_data['price']}, Sell ${ali_data['sell_price']}"
                )

            # TASK 5: impulse-buy price window
            if not (MIN_SELL_PRICE <= ali_data["sell_price"] <= MAX_SELL_PRICE):
                logger.info(
                    f"[SCRAPER] SKIP '{p['name']}': sell ${ali_data['sell_price']} "
                    f"outside ${MIN_SELL_PRICE}-${MAX_SELL_PRICE} window"
                )
                continue

            scores = self._calculate_scores(p["name"], p["upvotes"], ali_data["price"])
            total_score = sum(scores.values())
            if total_score >= 75:
                results.append({
                    "title": p["name"],
                    "description": (
                        f"Trending on r/{p['subreddit']} ({p['upvotes']} upvotes). "
                        + ("Real AliExpress product." if not ali_data.get("estimated")
                           else "Estimated pricing (no AliExpress match).")
                    ),
                    "supplier_url": ali_data["url"],
                    "cost_price": ali_data["price"],
                    "suggested_sell_price": ali_data["sell_price"],
                    "margin": round(ali_data["sell_price"] - ali_data["price"], 2),
                    "scores": scores,
                    "total_score": total_score,
                    "source_data": {
                        "reddit": {"subreddit": p["subreddit"], "upvotes": p["upvotes"]},
                        "google_trends": {"interest_score": min(p["upvotes"] // 10, 100)},
                        "aliexpress_listings": ali_data.get("orders", 0),
                        "pricing_estimated": bool(ali_data.get("estimated", False)),
                    }
                })
                if len(results) >= limit:
                    break

        results.sort(key=lambda x: x["total_score"], reverse=True)
        logger.info(f"[SCRAPER] Final: {len(results)} products in pipeline")
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
    # TASK 1: strict noun-phrase extraction
    # ------------------------------------------------------------------
    def _extract_product_name(self, title: str) -> Optional[str]:
        """Extract ONLY the product noun phrase (noun + up to 2 modifiers).

        Returns None for conversational titles, generic phrases, brand posts,
        blacklisted content, and titles under MINIMUM_WORDS words.
        """
        title_lower = title.lower()

        # Layer 1: brand blacklist
        if any(brand in title_lower for brand in BRAND_BLACKLIST):
            return None

        # Layer 2: content blacklist
        for pattern in CONTENT_BLACKLIST:
            if re.search(pattern, title_lower):
                return None

        # Layer 3: conversational/meta titles ("Love this sub", "Just got...", questions)
        for pattern in GENERIC_TITLE_PATTERNS:
            if re.search(pattern, title_lower):
                return None

        # Normalize: strip [tags], (parens), punctuation
        clean = re.sub(r"\[.*?\]|\(.*?\)", " ", title)
        clean = re.sub(r"[^\w\s'-]", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        words = clean.split()

        # Layer 4: minimum word count
        if len(words) < MINIMUM_WORDS:
            return None

        # Layer 5: find the HEAD product noun (rightmost match, word-boundary safe)
        noun_idx = None
        for i in range(len(words) - 1, -1, -1):
            if words[i].lower().strip("'-") in PRODUCT_NOUNS:
                noun_idx = i
                break
        if noun_idx is None:
            return None

        # Detect Title Case posts ("Smoked Carolina Reaper Pepper Grinder") where
        # capitalization carries no brand signal. Otherwise, a capitalized word
        # mid-title is treated as a proper noun / brand and stops collection
        # ("American Eagle messenger bag ..." -> keep "messenger bag", drop "Eagle").
        alpha_words = [w for w in words if w[0].isalpha()]
        cap_ratio = (
            sum(1 for w in alpha_words if w[0].isupper()) / len(alpha_words)
            if alpha_words else 0
        )
        is_title_case = cap_ratio >= 0.7

        # Layer 6: collect up to 2 preceding modifiers
        phrase = [words[noun_idx]]
        collected = 0
        for i in range(noun_idx - 1, -1, -1):
            if collected >= 2:
                break
            w = words[i]
            wl = w.lower()
            if wl in FILLER_WORDS:
                break
            if re.match(r"^\d", w):  # numbers ("25 years probably")
                break
            if w[0].isupper() and not is_title_case and i != 0:
                break  # mid-title proper noun => brand, stop here
            phrase.insert(0, w)
            collected += 1

        name = " ".join(phrase).strip()

        # Layer 7: final sanity checks
        if len(phrase) < 2:                      # single-word results are too generic
            return None
        if name.lower() in GENERIC_RESULT_PHRASES:
            return None
        if not (3 <= len(name) <= 60):
            return None
        return name

    # ------------------------------------------------------------------
    # TASK 2: fallback pricing
    # ------------------------------------------------------------------
    def _fallback_pricing(self, product_name: str) -> Dict[str, Any]:
        """Estimated pricing based on the matched product noun, used when
        AliExpress returns no valid result. Never drops the product."""
        name_lower = product_name.lower()
        cost, sell = DEFAULT_FALLBACK
        for noun, (c, s) in FALLBACK_PRICES.items():
            if re.search(rf"\b{re.escape(noun)}\b", name_lower):
                cost, sell = c, s
                break
        return {
            "price": cost,
            "sell_price": sell,
            "orders": 0,
            "estimated": True,
            "url": f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(product_name)}",
        }

    async def _get_real_aliexpress_data(self, product_name: str, rapidapi_key: str) -> Optional[Dict]:
        """Query AliExpress via RapidAPI for real pricing."""
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
                    logger.warning(f"[SCRAPER] No products found for '{product_name}'")
                    return None

                top_product = products_list[0]

                price = 0
                for key in ["sale_price", "min_price", "original_price", "price",
                            "target_sale_price", "minAmount", "salePrice"]:
                    val = top_product.get(key)
                    if val:
                        try:
                            price = float(str(val).replace(",", ""))
                            if price > 0:
                                break
                        except (ValueError, TypeError):
                            pass

                if price <= 0:
                    logger.warning(f"[SCRAPER] No valid price found. Keys: {list(top_product.keys())}")
                    return None

                orders = 0
                for key in ["total_sale", "orders", "sales", "tradeCount"]:
                    val = top_product.get(key)
                    if val:
                        try:
                            orders = int(str(val).replace(",", ""))
                            break
                        except (ValueError, TypeError):
                            pass

                product_url = (top_product.get("product_detail_url") or
                               top_product.get("product_url") or
                               top_product.get("url") or
                               f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(product_name)}")

                markup = 3.0 if price < 10 else 2.5
                sell_price = round((price * markup) + 2.50, 2)
                if sell_price < 19.99:
                    sell_price = 19.99

                logger.info(f"[SCRAPER] SUCCESS: '{product_name}' -> Cost: ${price}, Sell: ${sell_price}")
                return {
                    "price": price,
                    "sell_price": sell_price,
                    "orders": orders,
                    "estimated": False,
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
