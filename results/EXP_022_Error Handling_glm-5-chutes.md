Here is the updated `researcher.py` with a thread-safe Circuit Breaker pattern implemented. This prevents cascading failures and stops the system from hammering the Tavily API if it becomes unresponsive.

### FILE: researcher.py ###
```python
import os
import time
import threading
import requests
from dotenv import load_dotenv
from logger import get_logger

load_dotenv()
log = get_logger("Researcher")

MAX_QUERY_LENGTH = 100  # Tavily 400s on overly long queries

class PolyResearcher:
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")

        # ─── Circuit Breaker State ──────────────────────────────────────
        # Protects the external API from being hammered during outages.
        self._lock = threading.Lock()
        self._failure_count = 0
        self._last_failure_time = 0
        self._state = "closed"  # 'closed', 'open', 'half-open'
        
        # Configurable thresholds
        self.FAILURE_THRESHOLD = 3    # Open circuit after 3 failures
        self.RECOVERY_TIMEOUT = 60    # Try again after 60 seconds

    def _can_execute(self) -> bool:
        """Thread-safe check to see if we should attempt an API call."""
        with self._lock:
            now = time.time()
            
            if self._state == "closed":
                return True
            
            if self._state == "open":
                # Check if recovery time has elapsed
                if now - self._last_failure_time >= self.RECOVERY_TIMEOUT:
                    log.info("Circuit Breaker entering HALF-OPEN state — probing API.")
                    self._state = "half-open"
                    return True
                return False
            
            if self._state == "half-open":
                # In half-open, we let one request through to test the waters.
                # If it fails, we immediately trip back to open.
                return True
        
        return False

    def _record_success(self):
        """Resets the breaker on a successful call."""
        with self._lock:
            if self._state != "closed":
                log.info("Circuit Breaker reset to CLOSED (API recovered).")
            self._failure_count = 0
            self._state = "closed"

    def _record_failure(self):
        """Increments failure count and potentially trips the breaker."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == "half-open":
                log.warning("Circuit Breaker tripped back to OPEN (probe failed).")
                self._state = "open"
            elif self._failure_count >= self.FAILURE_THRESHOLD:
                log.error(f"Circuit Breaker tripped to OPEN after {self._failure_count} failures.")
                self._state = "open"

    def get_market_context(self, market_question):
        """Searches for real-world events related to the market question."""
        
        # 1. Gate: No API Key
        if not self.api_key:
            # Only log once per process start to reduce noise
            if not hasattr(self, '_key_warned'):
                print("⚠️ [RESEARCHER] No TAVILY_API_KEY found in .env! Skipping web search.")
                self._key_warned = True
            return "No search API key configured. Context unavailable."

        # 2. Gate: Circuit Breaker
        if not self._can_execute():
            log.warning("Circuit Breaker is OPEN — fast-failing Tavily request.")
            return "News service temporarily unavailable (cooling down from previous errors)."

        # 3. Prepare Request
        query_text = market_question
        if len(query_text) > MAX_QUERY_LENGTH:
            query_text = query_text[:MAX_QUERY_LENGTH].rsplit(' ', 1)[0]

        print(f"🔎 [RESEARCHER] Scouring the web for: '{query_text}'...")

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.api_key,
            "query": f"latest news: {query_text}",
            "search_depth": "basic",
            "include_domains": ["reuters.com", "apnews.com", "bloomberg.com", "twitter.com"],
            "max_results": 5
        }

        # 4. Execute
        try:
            resp = requests.post(url, json=payload, timeout=15)
            
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                print(f"✅ [RESEARCHER] Found {len(results)} relevant news articles.")
                
                self._record_success()

                if not results:
                    return "No relevant news found."

                context_parts = []
                for r in results:
                    title = r.get('title', 'Untitled')
                    snippet = r.get('content', '')[:300]
                    source_url = r.get('url', 'URL unavailable')
                    published = r.get('published_date', 'Date unknown')
                    context_parts.append(
                        f"- TITLE: {title}\n"
                        f"  DATE: {published}\n"
                        f"  SOURCE: {source_url}\n"
                        f"  SNIPPET: {snippet}..."
                    )

                return "\n\n".join(context_parts)
            
            else:
                # Handle HTTP errors (4xx, 5xx) as failures
                self._record_failure()
                log.error(f"Tavily API error {resp.status_code} for query '{query_text}': {resp.text[:200]}")
                print(f"❌ [RESEARCHER] API Error: {resp.status_code}")
                return "Search failed (API Error)."

        except Exception as e:
            # Handle network/timeout errors as failures
            self._record_failure()
            log.error(f"Search failed: {e}")
            print("❌ [RESEARCHER] Network Error.")
            return "Search failed (Network Error)."
```
