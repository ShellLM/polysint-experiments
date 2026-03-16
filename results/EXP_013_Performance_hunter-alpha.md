Looking at `harvest.py`, I can see several areas to optimize for rate-limit resilience and efficiency. Here's my optimized version with key improvements:

```python
# harvest.py
import requests
import json
import time
import random
from datetime import datetime, timezone
from config import Config
from db import get_db, init_db
from logger import get_logger

log = get_logger("Harvester")

# ─── Rate Limit Configuration ─────────────────────────────────────────────────
# Base delay between requests (seconds)
BASE_DELAY = 1.5
# Maximum backoff delay (seconds)
MAX_BACKOFF = 300  # 5 minutes
# Rate limit status codes that trigger backoff
RATE_LIMIT_CODES = {429, 403, 503}
# Maximum retries for a single request
MAX_RETRIES = 3

def extract_first_price(outcome_prices):
    """
    Safely extracts the first (YES) outcome price from whatever shape Gamma returns.
    Handles:
      - Already a list of floats/strings: ["0.5", "0.5"]
      - Double-encoded string: "[['0.5', '0.5']]"
      - Nested list: [["0.5", "0.5"]]
    Returns a JSON string of a flat list of strings, e.g. '["0.5", "0.5"]'.
    Returns '[]' on any failure.
    """
    try:
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)

        if not outcome_prices:
            return '[]'

        # Unwrap nested list if needed: [["0.5", "0.5"]] -> ["0.5", "0.5"]
        first = outcome_prices[0]
        if isinstance(first, list):
            outcome_prices = first

        # At this point we expect a flat list of price strings/floats
        # Validate each element is float-castable before storing
        validated = []
        for p in outcome_prices:
            try:
                float(p)
                validated.append(str(p))
            except (TypeError, ValueError):
                pass  # skip malformed entries

        return json.dumps(validated)

    except Exception as e:
        log.warning(f"Failed to parse outcomePrices '{outcome_prices}': {e}")
        return '[]'


def make_request_with_backoff(session, url, params, max_retries=MAX_RETRIES):
    """
    Makes HTTP request with exponential backoff and jitter for rate limiting.
    Returns (response, retry_count) or raises exception after max retries.
    """
    retry_delay = BASE_DELAY
    
    for attempt in range(max_retries):
        try:
            # Add jitter to avoid thundering herd (±20% random delay)
            jitter = random.uniform(0.8, 1.2)
            sleep_time = retry_delay * jitter
            
            # Only sleep if not first attempt or if we hit rate limit
            if attempt > 0:
                time.sleep(sleep_time)
            
            response = session.get(url, params=params, timeout=15)
            
            # Successful response
            if response.status_code == 200:
                return response, attempt
            
            # Rate limited - calculate exponential backoff
            if response.status_code in RATE_LIMIT_CODES:
                # Check for Retry-After header (if provided by API)
                retry_after = response.headers.get('Retry-After')
                if retry_after:
                    try:
                        retry_delay = int(retry_after)
                    except ValueError:
                        # Retry-After might be a date string, ignore it
                        pass
                else:
                    # Exponential backoff: delay = BASE_DELAY * (2 ** attempt)
                    retry_delay = min(BASE_DELAY * (2 ** attempt), MAX_BACKOFF)
                
                log.warning(f"Rate limited ({response.status_code}) on attempt {attempt + 1}. "
                           f"Backing off for {retry_delay:.1f}s")
                continue
            
            # Other HTTP error - raise immediately
            response.raise_for_status()
            
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            log.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
            retry_delay = min(BASE_DELAY * (2 ** attempt), MAX_BACKOFF)
    
    raise Exception(f"Failed after {max_retries} retries")


def fetch_active_markets(session):
    """Paginates through the Polymarket API with intelligent rate limiting."""
    print(f"[{datetime.now()}] Fetching active markets from Polymarket...")
    all_markets = []
    limit = 100
    offset = 0
    total_retries = 0
    batch_start_time = time.time()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    session = requests.Session()
    session.headers.update(headers)

    # Track requests per minute for adaptive delay
    requests_in_last_minute = []
    adaptive_delay = BASE_DELAY

    while True:
        # Adaptive delay based on recent request rate
        current_time = time.time()
        requests_in_last_minute = [t for t in requests_in_last_minute 
                                  if current_time - t < 60]
        
        # If we've made > 30 requests in the last minute, slow down
        if len(requests_in_last_minute) > 30:
            adaptive_delay = min(adaptive_delay * 1.5, 5.0)
            log.info(f"High request rate detected ({len(requests_in_last_minute)}/min). "
                    f"Increasing delay to {adaptive_delay:.1f}s")
        else:
            # Gradually return to normal speed
            adaptive_delay = max(adaptive_delay * 0.9, BASE_DELAY)
        
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset
        }

        try:
            response, retries_used = make_request_with_backoff(session, Config.GAMMA_API, params)
            total_retries += retries_used
            
            # Track this successful request
            requests_in_last_minute.append(time.time())
            
            # Enforce minimum delay between successful requests
            if len(requests_in_last_minute) > 1:
                time.sleep(adaptive_delay)
            
            if response.status_code == 200:
                data = response.json()
                if not data:
                    break
                    
                all_markets.extend(data)
                offset += limit
                
                if offset % 500 == 0:
                    elapsed = time.time() - batch_start_time
                    rate = offset / elapsed * 60  # markets per minute
                    print(f" -> Fetched {offset} markets... "
                          f"({rate:.0f} markets/min, "
                          f"{len(requests_in_last_minute)} requests/min, "
                          f"{total_retries} retries)")
                
                # Add small random jitter between successful requests
                time.sleep(random.uniform(0.1, 0.3))
                
            else:
                # This should be handled by make_request_with_backoff
                log.error(f"Unexpected status {response.status_code} for offset {offset}")
                break

        except requests.exceptions.SSLError:
            log.error(f"SSL Error at offset {offset}. Consider updating certificates or verify settings.")
            break

        except Exception as e:
            log.error(f"Failed to fetch markets at offset {offset}: {e}")
            # If we're consistently failing, stop the harvest
            if total_retries > MAX_RETRIES * 2:
                log.error("Too many consecutive failures. Stopping harvest.")
                break
            time.sleep(BASE_DELAY * 2)  # Wait before retrying
            continue

    elapsed = time.time() - batch_start_time
    print(f"[{datetime.now()}] Successfully fetched {len(all_markets)} active markets "
          f"in {elapsed:.0f}s ({total_retries} total retries)")
    return all_markets


def process_and_save(markets):
    """Batch insert markets and snapshots for efficiency."""
    if not markets:
        return
        
    db = get_db()
    cursor = db.cursor()
    current_time = datetime.now(timezone.utc).isoformat()
    
    # Prepare batch data for markets
    market_data = []
    snapshot_data = []
    
    for market in markets:
        market_id = market.get("id")
        if not market_id:
            continue
            
        outcomes_json = json.dumps(market.get("outcomes", []))
        prices_json = extract_first_price(market.get("outcomePrices", []))
        
        # Extract clob token ID
        clob_token_id = None
        raw_clob = market.get("clobTokenIds")
        if raw_clob:
            try:
                token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
                if token_ids and len(token_ids) > 0:
                    clob_token_id = token_ids[0]
            except Exception as e:
                log.warning(f"Failed to parse clobTokenIds for market {market_id}: {e}")
        
        volume = float(market.get("volume", 0))
        
        market_data.append((
            market_id,
            market.get("question"),
            outcomes_json,
            volume,
            current_time,
            clob_token_id
        ))
        
        snapshot_data.append((
            market_id,
            current_time,
            prices_json,
            volume
        ))
    
    try:
        # Batch insert with transaction
        cursor.execute("BEGIN TRANSACTION")
        
        # Use executemany for batch insert - much faster than individual inserts
        cursor.executemany('''
            INSERT OR REPLACE INTO markets (id, question, outcomes, volume, created_at, clob_token_id)
            VALUES (?, ?, ?, ?, 
                   COALESCE((SELECT created_at FROM markets WHERE id = ?), ?), ?)
        ''', market_data)
        
        cursor.executemany('''
            INSERT INTO snapshots (market_id, timestamp, prices, volume)
            VALUES (?, ?, ?, ?)
        ''', snapshot_data)
        
        db.commit()
        log.info(f"Processed and saved {len(market_data)} markets in batch")
        
    except Exception as e:
        db.rollback()
        log.error(f"Batch insert failed: {e}")
        # Fall back to individual inserts for debugging
        log.warning("Falling back to individual inserts...")
        _process_individually(markets, current_time)
    finally:
        db.close()


def _process_individually(markets, current_time):
    """Fallback: process markets individually (slower but more debuggable)."""
    db = get_db()
    cursor = db.cursor()
    
    for market in markets:
        market_id = market.get("id")
        if not market_id:
            continue
            
        try:
            outcomes_json = json.dumps(market.get("outcomes", []))
            prices_json = extract_first_price(market.get("outcomePrices", []))
            
            clob_token_id = None
            raw_clob = market.get("clobTokenIds")
            if raw_clob:
                try:
                    token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
                    if token_ids and len(token_ids) > 0:
                        clob_token_id = token_ids[0]
                except Exception as e:
                    log.warning(f"Failed to parse clobTokenIds for market {market_id}: {e}")
            
            volume = float(market.get("volume", 0))
            
            cursor.execute('''
                INSERT OR REPLACE INTO markets (id, question, outcomes, volume, created_at, clob_token_id)
                VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM markets WHERE id = ?), ?), ?)
            ''', (market_id, market.get("question"), outcomes_json, volume, market_id, current_time, clob_token_id))
            
            cursor.execute('''
                INSERT INTO snapshots (market_id, timestamp, prices, volume)
                VALUES (?, ?, ?, ?)
            ''', (market_id, current_time, prices_json, volume))
            
        except Exception as e:
            log.error(f"Failed to process market {market_id}: {e}")
            continue
    
    db.commit()
    db.close()


if __name__ == "__main__":
    init_db()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })

    # Stats tracking
    harvest_count = 0
    start_time = time.time()
    
    try:
        while True:
            harvest_start = time.time()
            harvest_count += 1
            
            print(f"\n{'='*60}")
            print(f"Harvest #{harvest_count} starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            try:
                data = fetch_active_markets(session)
                process_and_save(data)
                
                harvest_elapsed = time.time() - harvest_start
                total_elapsed = time.time() - start_time
                
                print(f"Harvest #{harvest_count} completed in {harvest_elapsed:.1f}s")
                print(f"Total runtime: {total_elapsed/3600:.1f} hours")
                print(f"Next harvest in 15 minutes...")
                print('='*60)
                
            except Exception as e:
                log.error(f"Harvest #{harvest_count} failed: {e}")
                print(f"Harvest failed: {e}")
                print("Waiting 5 minutes before retry...")
                time.sleep(300)  # Wait 5 minutes on total failure
                continue
            
            # Sleep with jitter to avoid synchronized requests
            sleep_time = 900 + random.uniform(-30, 30)  # 15 minutes ± 30 seconds
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        total_elapsed = time.time() - start_time
        print(f"\n\nHarvester stopped after {harvest_count} harvests "
              f"({total_elapsed/3600:.1f} hours total runtime)")
        print("Graceful shutdown complete.")
```

## Key Optimizations:

### 1. **Intelligent Rate Limiting**
- Exponential backoff with jitter to avoid thundering herd
- Respects `Retry-After` headers when provided
- Tracks request rate and adapts delay dynamically
- Handles multiple rate limit status codes (429, 403, 503)

### 2. **Adaptive Request Throttling**
- Monitors requests per minute and slows down if rate > 30 req/min
- Gradually recovers speed when rate decreases
- Random jitter between requests prevents synchronized bursts

### 3. **Batch Database Operations**
- Uses `executemany()` for batch inserts instead of individual queries
- Transaction-based inserts for atomicity
- Fallback to individual inserts only when batch fails

### 4. **Resilient Error Handling**
- Maximum retry limits with clear escalation
- Continues harvest even if individual requests fail
- Graceful degradation on SSL or network errors

### 5. **Efficient Harvest Loop**
- Jittered sleep times to prevent synchronized requests
- Progress tracking with statistics
- Clear logging of harvest performance metrics

### 6. **Memory Optimization**
- Filters out markets without IDs early
- Efficient data structure handling

This implementation should handle rate limits more gracefully while maintaining harvest efficiency. The adaptive throttling ensures we don't overwhelm the API during periods of high request volume.
