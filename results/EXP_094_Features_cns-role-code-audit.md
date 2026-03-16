2026-03-15 16:21:29,819 - llm_consortium.orchestrator - ERROR - Automatic response error for glm-5: Error code: 429 - {'detail': 'Infrastructure is at maximum capacity, try again later'}
2026-03-15 16:25:04,250 - llm_consortium.orchestrator - ERROR - Automatic response error for glm-5: Error code: 429 - {'detail': 'Infrastructure is at maximum capacity, try again later'}
2026-03-15 16:28:56,488 - llm_consortium.orchestrator - ERROR - Automatic response error for glm-5: Error code: 429 - {'detail': 'Infrastructure is at maximum capacity, try again later'}
```python
### FILE: researcher.py ###
import os
import requests
from dotenv import load_dotenv
from logger import get_logger

# Optional dependency for RSS feeds.
# If missing, RSS functionality degrades gracefully without crashing.
try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False

load_dotenv()
log = get_logger("Researcher")

MAX_QUERY_LENGTH = 100  # Tavily 400s on overly long queries
RSS_TIMEOUT = 5  # Seconds per feed to prevent hanging
MAX_RSS_RESULTS = 5  # Cap total RSS items to avoid context bloat
MAX_ENTRIES_PER_FEED = 15  # Limit entries checked per feed
RELEVANCE_THRESHOLD = 3  # Minimum keyword matches for relevance

# Curated RSS feeds organized by category for relevance matching.
# Tuples used at module level for immutability; instance copies are mutable.
_RSS_FEEDS_DEFAULT = {
    "general": (
        "https://feeds.reuters.com/reuters/topNews",
        "https://rsshub.app/apnews/topics/apf-topnews",
        "http://feeds.bbci.co.uk/news/world/rss.xml"
    ),
    "financial": (
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://www.ft.com/?format=rss"
    ),
    "crypto": (
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed"
    ),
    "politics": (
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
        "https://feeds.foxnews.com/foxnews/politics"
    )
}

# Keywords for category detection
CATEGORY_KEYWORDS = {
    "crypto": ("bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "defi", "nft", "token", "mining", "web3"),
    "financial": ("stock", "market", "economy", "fed", "interest rate", "inflation", "gdp", "investment", "trade", "bonds"),
    "politics": ("election", "president", "vote", "congress", "senate", "democrat", "republican", "biden", "trump", "policy"),
    "general": ()  # Always included as fallback
}


class PolyResearcher:
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")
        self.use_rss = os.getenv("ENABLE_RSS_FEEDS", "true").lower() == "true"

        # Instance-level mutable copy prevents cross-instance contamination
        self.rss_feeds = {k: list(v) for k, v in _RSS_FEEDS_DEFAULT.items()}
        self._load_custom_feeds()

    def _load_custom_feeds(self):
        """Load custom RSS feeds from environment variable."""
        env_feeds = os.getenv("RSS_FEED_URLS")
        if not env_feeds:
            return

        try:
            import json
            custom_feeds = json.loads(env_feeds)

            if isinstance(custom_feeds, list):
                self.rss_feeds["custom"] = custom_feeds

            elif isinstance(custom_feeds, dict):
                for category, feeds in custom_feeds.items():
                    if not isinstance(feeds, list):
                        log.warning(f"Invalid feeds for category {category}: expected list")
                        continue
                    if category not in self.rss_feeds:
                        self.rss_feeds[category] = []
                    self.rss_feeds[category].extend(feeds)

        except (json.JSONDecodeError, TypeError) as e:
            log.warning(f"Invalid RSS_FEED_URLS format: {e}")

    def _extract_keywords(self, text: str) -> list:
        """Extracts significant words from text for keyword matching."""
        if not text:
            return []

        stop_words = {
            'that', 'with', 'have', 'this', 'will', 'from', 'they', 'been', 'called',
            'market', 'price', 'what', 'when', 'where', 'which', 'while', 'who', 'would',
            'there', 'their', 'about', 'into', 'could', 'other', 'than', 'then', 'these',
            'some', 'make', 'like', 'just', 'over', 'such', 'only', 'most', 'also', 'made'
        }

        words = text.lower().split()
        return [w for w in words if len(w) > 3 and w not in stop_words]

    def _detect_categories(self, text: str) -> list:
        """Detect relevant news categories from text."""
        if not text:
            return ["general"]

        text_lower = text.lower()
        categories = []

        for category, keywords in CATEGORY_KEYWORDS.items():
            if category == "general":
                continue
            for keyword in keywords:
                if keyword in text_lower:
                    if category not in categories:
                        categories.append(category)
                    break

        categories.append("general")  # Always include as fallback
        return categories

    def _count_keyword_matches(self, text: str, keywords: list) -> int:
        """Count how many keywords appear in text."""
        if not keywords:
            return 0
        text_lower = text.lower()
        return sum(1 for kw in keywords if kw in text_lower)

    def _fetch_rss_context(self, market_question: str, keywords: list) -> list:
        """Fetches and filters RSS feed entries based on keywords and categories."""
        if not FEEDPARSER_AVAILABLE or not self.use_rss:
            return []

        # Require either keywords or a question to prevent flooding with irrelevant content
        if not keywords and not market_question:
            return []

        results = []
        seen_urls = set()
        categories = self._detect_categories(market_question)

        for category in categories:
            if category not in self.rss_feeds:
                continue

            for feed_url in self.rss_feeds[category]:
                # Validate feed URL before parsing
                if not isinstance(feed_url, str) or not feed_url.strip():
                    log.warning(f"Invalid feed URL in category {category}: {feed_url}")
                    continue

                try:
                    try:
                        feed = feedparser.parse(feed_url, request_timeout=RSS_TIMEOUT)
                    except TypeError:
                        feed = feedparser.parse(feed_url)

                    if feed.bozo and not feed.entries:
                        log.debug(f"Feed malformed or unreachable: {feed_url}")
                        continue

                    for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
                        title = (entry.get('title') or '').strip()
                        summary = (entry.get('summary') or '').strip()
                        link = (entry.get('link') or '').strip()
                        published = entry.get('published') or 'Date unknown'

                        if not link or not isinstance(link, str) or link in seen_urls:
                            continue

                        # Check relevance by keyword matching
                        text_blob = f"{title} {summary}".lower()
                        match_count = self._count_keyword_matches(text_blob, keywords)

                        if not keywords or match_count >= RELEVANCE_THRESHOLD:
                            results.append({
                                'title': title,
                                'url': link,
                                'published': published,
                                'snippet': summary[:300] if summary else title,
                                'source': f"RSS ({category})",
                                'relevance': match_count
                            })
                            seen_urls.add(link)

                        if len(results) >= MAX_RSS_RESULTS:
                            break

                    if len(results) >= MAX_RSS_RESULTS:
                        break

                except Exception as e:
                    log.warning(f"RSS fetch failed for {feed_url}: {e}")
                    continue

        # Sort by relevance (highest first) for better signal in LLM context
        results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
        return results

    def get_market_context(self, market_question):
        """Searches for real-world events related to the market question via Tavily and RSS."""
        # Handle None or empty market_question
        if not market_question:
            return "No market question provided for news context."

        tavily_results = []
        rss_results = []

        # ─── 1. Tavily Search ──────────────────────────────────────────────────
        if self.api_key:
            query_text = market_question
            if len(query_text) > MAX_QUERY_LENGTH:
                query_text = query_text[:MAX_QUERY_LENGTH].rsplit(' ', 1)[0]

            print(f"🔎[RESEARCHER] Scouring the web for: '{query_text}'...")

            url = "https://api.tavily.com/search"
            payload = {
                "api_key": self.api_key,
                "query": f"latest news: {query_text}",
                "search_depth": "basic",
                "include_domains": [
                    "reuters.com", "apnews.com", "bloomberg.com", "twitter.com",
                    "coindesk.com", "cointelegraph.com"
                ],
                "max_results": 5
            }

            try:
                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    data = resp.json().get("results", [])
                    if isinstance(data, list):
                        print(f"✅ [RESEARCHER] Found {len(data)} relevant news articles (Tavily).")
                        tavily_results = data
                    else:
                        log.warning(f"Tavily returned non-list results: {type(data)}")
                else:
                    log.error(f"Tavily API error {resp.status_code}: {resp.text[:200]}")
                    print(f"❌ [RESEARCHER] Tavily API Error: {resp.status_code}")
            except Exception as e:
                log.error(f"Tavily search failed: {e}")
                print("❌ [RESEARCHER] Tavily Network Error.")
        else:
            print("⚠️ [RESEARCHER] No TAVILY_API_KEY found in .env! Skipping web search.")

        # ─── 2. RSS Feed Search ────────────────────────────────────────────────
        keywords = self._extract_keywords(market_question)

        if self.use_rss and FEEDPARSER_AVAILABLE:
            print(f"📡 [RESEARCHER] Scanning RSS feeds...")
            rss_results = self._fetch_rss_context(market_question, keywords)
            if rss_results:
                print(f"✅ [RESEARCHER] Found {len(rss_results)} relevant articles (RSS).")
        elif not FEEDPARSER_AVAILABLE:
            log.warning("feedparser library not installed. RSS integration disabled.")
            print("⚠️ [RESEARCHER] Install feedparser for RSS support: pip install feedparser")
        elif not self.use_rss:
            print("ℹ️ [RESEARCHER] RSS feeds disabled via ENABLE_RSS_FEEDS=false")

        # ─── 3. Combine & Format Results ───────────────────────────────────────
        context_parts = []

        # Process Tavily Results
        for r in tavily_results:
            if not isinstance(r, dict):
                continue
            title = r.get('title') or 'Untitled'
            snippet = (r.get('content') or '')[:300]
            source_url = r.get('url')
            published = r.get('published_date') or 'Date unknown'

            if source_url:
                context_parts.append(
                    f"- TITLE: {title}\n"
                    f"  DATE: {published}\n"
                    f"  SOURCE: {source_url}\n"
                    f"  SNIPPET: {snippet}..."
                )

        # Process RSS Results (deduplicate against Tavily URLs)
        tavily_urls = {
            r.get('url') for r in tavily_results
            if isinstance(r, dict) and r.get('url')
        }
        for r in rss_results:
            if r.get('url') and r['url'] not in tavily_urls:
                context_parts.append(
                    f"- TITLE: {r['title']}\n"
                    f"  DATE: {r['published']}\n"
                    f"  SOURCE: {r['url']}\n"
                    f"  SNIPPET: {r['snippet']}..."
                )

        if not context_parts:
            return "No relevant news found via Tavily or RSS feeds."

        return "\n\n".join(context_parts)
```

## Configuration (.env additions):

```env
# RSS Configuration
ENABLE_RSS_FEEDS=true

# Optional: Custom RSS feeds (JSON format)
# Simple list format:
# RSS_FEED_URLS='["https://custom-feed.com/rss"]'
# Category-based format:
# RSS_FEED_URLS='{"tech": ["https://techcrunch.com/feed/"], "crypto": ["https://newssite.com/crypto/rss"]}'
```

## Installation:

```bash
pip install feedparser
```

## Key Design Decisions:

| Decision | Rationale |
|----------|-----------|
| Instance-level feed copies | Prevents cross-instance state contamination when multiple `PolyResearcher` instances exist |
| Tuples for module defaults | Immutability prevents accidental global mutation |
| Threshold-based relevance | Filters noise better than boolean matching; 3+ keyword matches indicates real relevance |
| Relevance-sorted results | Higher-signal articles appear first in LLM context |
| Explicit None/empty checks | Prevents crashes on malformed API responses or missing data |
| Type validation for feed URLs | Catches configuration errors early with clear logging |
| Maintains original style | Functional approach matches existing codebase patterns |
