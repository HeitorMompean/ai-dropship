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

# Intellectual-property / right-of-publicity risk patterns. Listings whose TITLE
# matches any of these are dropped before reaching Telegram: unlicensed character,
# franchise, league, brand, or real-person merch is the #1 cause of Shopify /
# Stripe / PayPal account suspensions for dropshippers. This is a high-confidence
# baseline, NOT exhaustive — celebrity coverage in particular can't be complete,
# so the supplier-link check before APPROVE still matters.
IP_BLACKLIST = [
    # film / TV / animation studios & franchises
    r"\b(disney|pixar|marvel|avengers|spider[- ]?man|iron man|star wars|mandalorian|"
    r"harry potter|hogwarts|wizarding|lord of the rings|game of thrones|"
    r"dc comics|batman|superman|wonder woman|justice league|"
    r"minions|despicable me|shrek|frozen|elsa|moana|encanto|stitch|mickey|minnie)\b",
    # anime / manga franchises & characters
    r"\b(pokemon|pok[eé]mon|pikachu|nintendo|mario|luigi|zelda|kirby|sonic|"
    r"naruto|sasuke|dragon ball|goku|vegeta|one piece|luffy|demon slayer|"
    r"jujutsu kaisen|attack on titan|my hero academia|sailor moon|gundam|"
    r"hello kitty|sanrio|kuromi|cinnamoroll|studio ghibli|totoro)\b",
    # gaming IP
    r"\b(minecraft|fortnite|roblox|among us|league of legends|overwatch|"
    r"call of duty|grand theft auto|gta|pubg|valorant|genshin)\b",
    # sports leagues / clubs
    r"\b(nfl|nba|mlb|nhl|fifa|uefa|premier league|la liga|"
    r"real madrid|barcelona|man united|manchester city|lakers|warriors)\b",
    # real people / celebrity / public-figure signals
    r"\b(taylor swift|drake|beyonce|kanye|rihanna|ariana grande|billie eilish|"
    r"ice spice|nicki minaj|travis scott|bad bunny|messi|ronaldo|lebron|"
    r"princess diana|royal family|kate middleton|elon musk|trump|biden)\b",
    r"\b(singer|rapper|celebrity|popstar|footballer)\b.*\b(card|poster|shirt|mug|sticker|keychain|portrait)\b",
    # generic counterfeit / unlicensed signals
    r"\b(cosplay|replica|bootleg|fan art|fanart|inspired by|official licensed|"
    r"licensed merch|knockoff)\b",
]

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
    "useful", "handy", "clever", "genius", "neat", "cool", "coolest", "nice", "sleek", "fancy",
    "ultimate", "essential", "must", "have", "favorite",
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
        logger.info("[SCRAPER] Starting Strict Scrape v3.7 (IP filter + real 13-factor scoring)")
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
            scores = self._calculate_scores(
                ali_data["name"], c["upvotes"], ali_data["price"],
                sell_price=ali_data["sell_price"], orders=ali_data.get("orders", 0),
            )
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
        # Don't even search AliExpress for obviously IP/celebrity titles.
        if self._is_ip_risky(title_lower):
            return None

        # Normalize smart quotes to straight, fold possessives/contractions so
        # "dad's" -> "dads" (not a stray "s" token), then drop remaining punctuation.
        clean = title.replace("\u2019", "'").replace("\u2018", "'")
        clean = re.sub(r"\[.*?\]|\(.*?\)", " ", clean)
        clean = re.sub(r"'s\b", "s", clean, flags=re.I)
        clean = re.sub(r"[^\w\s-]", " ", clean)
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
    def _is_ip_risky(text: str) -> Optional[str]:
        """Return the matched IP/celebrity term if `text` looks like unlicensed
        IP / real-person merch, else None. Used to reject account-risk listings."""
        if not text:
            return None
        low = text.lower()
        for pattern in IP_BLACKLIST:
            m = re.search(pattern, low)
            if m:
                return m.group(0)[:40]
        return None

    @staticmethod
    def _price_from_url(url: str) -> float:
        """Extract the cheapest variant price from an AliExpress supplier URL.

        The pdp_npi query param (URL-decoded) looks like:
            ...!USD!<min_orig>!<min_sale>!!<max_orig>!<max_sale>!@<tokens>...
        i.e. it carries the FULL price range. We read only the price block
        between 'USD' and the next '@' (so we don't pick up the product-id or
        trailing flags), and return the smallest positive number = the cheapest
        variant's price. Returns 0.0 if the URL has no parseable price block
        (e.g. the wholesale-search fallback URL).
        """
        if not url:
            return 0.0
        try:
            decoded = urllib.parse.unquote(url)
            m = re.search(r"USD([!0-9.]*?)@", decoded)
            if not m:
                return 0.0
            nums = [float(x) for x in re.findall(r"\d+\.\d+|\d+", m.group(1))]
            nums = [n for n in nums if n > 0]
            return min(nums) if nums else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _extract_price(product: Dict, debug_name: str = "") -> float:
        """Return the cheapest positive price across the candidate fields.

        AliExpress listings span a price RANGE across variants (1pc, packs,
        colours). The API can return both ends (e.g. min_price 1.62 and
        sale_price/original_price 5.45+). Taking the FIRST present field grabbed
        whichever happened to be listed first — often the high end — which made
        the cost look wrong. We now take the MIN positive value, i.e. the
        single-unit sourcing cost a dropshipper actually pays.
        """
        found: Dict[str, float] = {}
        # Standard listing price fields only — NOT app-exclusive flash prices
        # (app_sale_price etc.), which you may not actually be able to source at.
        for key in ["sale_price", "min_price", "min_sale_price", "original_price",
                    "price", "target_sale_price", "minAmount", "salePrice"]:
            val = product.get(key)
            if val in (None, "", 0, "0"):
                continue
            try:
                price = float(str(val).replace(",", "").replace("$", "").strip())
                if price > 0:
                    found[key] = price
            except (ValueError, TypeError):
                pass
        if not found:
            return 0.0
        chosen = min(found.values())
        if debug_name:
            logger.info("[SCRAPER] PRICE FIELDS for '%s': %s -> using min $%.2f",
                        debug_name, {k: f"${v:.2f}" for k, v in found.items()}, chosen)
        return chosen

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
                "page_size": "10"
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
                for candidate in products_list[:10]:
                    if not isinstance(candidate, dict):
                        continue
                    raw_title = self._extract_title(candidate)
                    ip_hit = self._is_ip_risky(raw_title)
                    if ip_hit:
                        logger.info(f"[SCRAPER] IP-RISK skip for '{keyword}': '{raw_title[:55]}' (matched '{ip_hit}')")
                        continue
                    if not self._is_relevant(keyword, raw_title):
                        logger.info(f"[SCRAPER] Irrelevant result for '{keyword}': '{raw_title[:60]}'")
                        continue
                    name = self._clean_ali_title(raw_title)
                    if len(name) < 3:
                        continue

                    product_url = (candidate.get("product_detail_url") or
                                   candidate.get("product_url") or
                                   candidate.get("url") or
                                   f"https://www.aliexpress.com/wholesale?SearchText={urllib.parse.quote(keyword)}")

                    # CHEAPEST VARIANT: the structured API field often reports the
                    # TOP of a listing's price range. The supplier URL's pdp_npi
                    # string carries the full range, so we also parse the cheapest
                    # price from it and take the lower of the two sources.
                    field_price = self._extract_price(candidate, debug_name=keyword)
                    url_price = self._price_from_url(product_url)
                    sources = [p for p in (field_price, url_price) if p > 0]
                    if not sources:
                        continue
                    price = min(sources)
                    if url_price > 0 and url_price < field_price:
                        logger.info("[SCRAPER] CHEAPEST VARIANT for '%s': field $%.2f vs url $%.2f -> using $%.2f",
                                    keyword, field_price, url_price, price)

                    markup = 3.0 if price < 10 else 2.5
                    sell_price = round((price * markup) + 2.50, 2)
                    if sell_price < 19.99:
                        sell_price = 19.99

                    candidates.append({
                        "name": name,
                        "price": price,
                        "sell_price": sell_price,
                        "orders": self._extract_orders(candidate),
                        "url": product_url,
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

    # Category hints used by scoring (kept small + honest).
    _CONSUMABLE_HINTS = ("filter", "refill", "cartridge", "blade", "strip", "pad",
                         "wipe", "bag", "disposable", "replacement", "battery")
    _LEGAL_RISK_HINTS = ("supplement", "vitamin", "pill", "detox", "slimming", "weight loss",
                         "serum", "cream", "lotion", "medical", "therapy", "cure", "treatment",
                         "vape", "e-cig", "nicotine", "taser", "pepper spray", "baby", "infant",
                         "toddler", "lithium")

    def _calculate_scores(self, product_name: str, upvotes: int, cost: float,
                          sell_price: float = 0.0, orders: int = 0) -> Dict[str, int]:
        """13-factor score driven by REAL signals where they exist.

        Real (computed from data): Profit Margin, Price Point, Impulse, Trending,
        Passionate Audience, Availability, Competition, Repeat Purchase, Legal/Safe,
        Perceived Value. Honest neutral defaults (can't assess from API data):
        Problem/Solution, Shipping, Visual Appeal — these need a human/image and are
        left at 7 rather than faked.
        """
        name_l = product_name.lower()
        margin_pct = ((sell_price - cost) / sell_price * 100) if sell_price > 0 else 0.0
        s: Dict[str, int] = {}

        # Profit Margin — from real margin %
        s["Profit Margin"] = (10 if margin_pct >= 85 else 9 if margin_pct >= 75 else
                              8 if margin_pct >= 65 else 7 if margin_pct >= 55 else
                              6 if margin_pct >= 45 else 4)

        # Price Point & Impulse — impulse-buy sweet spot is ~$15-30
        s["Price Point"] = (10 if 15 <= sell_price <= 30 else 8 if sell_price <= 45 else
                            6 if sell_price <= 60 else 5 if sell_price <= 80 else 3)
        s["Impulse"] = (10 if sell_price <= 25 else 8 if sell_price <= 40 else
                        6 if sell_price <= 60 else 4)

        # Trending & Passionate Audience — from Reddit upvotes
        s["Trending"] = (10 if upvotes >= 2000 else 9 if upvotes >= 1000 else
                         8 if upvotes >= 500 else 7 if upvotes >= 200 else
                         6 if upvotes >= 100 else 5)
        s["Passionate Audience"] = max(5, min(10, 5 + upvotes // 150))

        # Availability & Competition — from real AliExpress order volume.
        # Few orders = low competition but less proven; huge orders = saturated.
        if orders <= 0:
            s["Availability"], s["Competition"] = 6, 6
        elif orders < 50:
            s["Availability"], s["Competition"] = 8, 8
        elif orders < 500:
            s["Availability"], s["Competition"] = 9, 7
        elif orders < 5000:
            s["Availability"], s["Competition"] = 9, 6
        else:
            s["Availability"], s["Competition"] = 10, 4

        # Repeat Purchase — consumables get reordered, gadgets don't
        s["Repeat Purchase"] = 8 if any(h in name_l for h in self._CONSUMABLE_HINTS) else 5

        # Legal/Safe — real category risk (IP merch is already filtered out upstream)
        s["Legal/Safe"] = 5 if any(h in name_l for h in self._LEGAL_RISK_HINTS) else 9

        # Perceived Value — strong margin AND a reasonable price reads as good value
        s["Perceived Value"] = 8 if (margin_pct >= 60 and sell_price <= 50) else 6

        # Not assessable from API data — honest neutral defaults, not faked highs
        s["Problem/Solution"] = 7
        s["Shipping"] = 7
        s["Visual Appeal"] = 7

        return {k: max(1, min(10, v)) for k, v in s.items()}

    async def analyze_google_trends(self, keyword: str):
        return {"keyword": keyword, "interest_score": 65}

    async def check_facebook_ads(self, keyword: str):
        return {"keyword": keyword, "competition": "medium"}



scraper = ScraperService()
