### Analysis of Changes

The original `harvest.py` pagination loop had two significant weaknesses:
1.  **Fragile Error Handling**: An `SSLError` immediately crashed the harvester (`break`), requiring manual intervention. Network glitches were retried indefinitely without a limit, potentially hanging the process forever.
2.  **No Retry Limits**: Transient failures (like a momentary 500 error or connection drop) would retry infinitely, which can mask deeper issues or stall the harvest silently.

### Improvements Implemented

1.  **Retry Limits with Abort Logic**: Introduced a `MAX_RETRIES` limit (5 attempts) per page. If a specific offset fails 5 times, the harvest safely aborts and returns what was collected so far, rather than hanging indefinitely or crashing out.
2.  **Unified Exception Handling**: `SSLError`, `ConnectionError`, and `Timeout` are now caught specifically. They are treated as transient issues—logged and retried—rather than terminal failures.
3.  **Resilient Status Codes**: Non-200 status codes (like 502 Bad Gateway) are now retried, whereas the old code would break immediately on any non-200, non-429 response.

### Modified File: `harvest.py`

```python
### FILE: harvest.py ###
import requests
import json
import time
from datetime import datetime
from config import Config
from db import get_db, init_db
from logger import get_logger

log = get_logger("Harvester")

# ─── Network Resilience Settings ───────────────────────────────────────────────
MAX_RETRIES = 5       # Max attempts per page before aborting
RETRY_DELAY = 5       # Seconds to wait between retries
RATE_LIMIT_DELAY = 10 # Seconds to wait on HTTP 429

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


def fetch_active_markets(session):
    """Paginates through the Polymarket API to get all active markets."""
    print(f"[{datetime.now()}] Fetching active markets from Polymarket...")
    all_markets = []
    limit = 100
    offset = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    session = requests.Session()
    session.headers.update(headers)

    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset
        }

        # ─── Robust Retry Loop ───────────────────────────────────────────────
        success = False
        for attempt in range(MAX_RETRIES):
            try:
                response = session.get(Config.GAMMA_API, params=params, timeout=15)

                # Handle Rate Limiting (429) specifically
                if response.status_code == 429:
                    print(f"[!] Rate limited at offset {offset}. Sleeping for {RATE_LIMIT_DELAY}s...")
                    time.sleep(RATE_LIMIT_DELAY)
                    continue # Consume a retry attempt but wait longer

                # Handle Server Errors or unexpected responses
                if response.status_code != 200:
                    log.warning(f"HTTP {response.status_code} at offset {offset} (Attempt {attempt+1}/{MAX_RETRIES})")
                    time.sleep(RETRY_DELAY)
                    continue

                data = response.json()
                success = True
                break # Exit retry loop on success

            except requests.exceptions.SSLError as e:
                log.warning(f"SSL Error at offset {offset} (Attempt {attempt+1}/{MAX_RETRIES}): {e}")
                print(f"[!] SSL Error. Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

            except requests.exceptions.ConnectionError as e:
                log.warning(f"Connection Error at offset {offset} (Attempt {attempt+1}/{MAX_RETRIES}): {e}")
                print(f"[!] Connection Error. Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

            except requests.exceptions.Timeout:
                log.warning(f"Timeout at offset {offset} (Attempt {attempt+1}/{MAX_RETRIES})")
                print(f"[!] Request Timeout. Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

            except json.JSONDecodeError as e:
                log.error(f"JSON Decode Error at offset {offset}: {e}")
                print(f"[!] Bad JSON response. Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

            except Exception as e:
                log.error(f"Unexpected error at offset {offset}: {e}")
                print(f"[!] Unexpected error. Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

        # If all retries failed, abort this harvest run gracefully
        if not success:
            log.error(f"Failed to fetch offset {offset} after {MAX_RETRIES} attempts. Aborting harvest.")
            print(f"\n[!] Max retries exceeded. Harvest aborted for this cycle.")
            break

        # ─── Process Data ────────────────────────────────────────────────────
        if not data:
            # Empty data list means we reached the end
            break

        all_markets.extend(data)
        offset += limit

        if offset % 1000 == 0:
            print(f" -> Fetched {offset} markets...")

        time.sleep(0.5)

    print(f"[{datetime.now()}] Successfully fetched {len(all_markets)} active markets.")
    return all_markets


def process_and_save(markets):
    db = get_db()
    cursor = db.cursor()
    current_time = datetime.now().isoformat()

    for market in markets:
        outcomes_json = json.dumps(market.get("outcomes", []))

        # Normalise outcomePrices into a clean flat JSON array before storing
        prices_json = extract_first_price(market.get("outcomePrices", []))

        # clobTokenIds comes back as a stringified JSON array e.g. '["111...","222..."]'
        # Index 0 is the YES outcome token used for CLOB price history lookups
        clob_token_id = None
        raw_clob = market.get("clobTokenIds")
        if raw_clob:
            try:
                token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
                if token_ids and len(token_ids) > 0:
                    clob_token_id = token_ids[0]
            except Exception as e:
                log.warning(f"Failed to parse clobTokenIds for market {market.get('id')}: {e}")

        # INSERT OR REPLACE so clob_token_id gets backfilled on restarts.
        # COALESCE preserves the original created_at timestamp.
        cursor.execute('''
            INSERT OR REPLACE INTO markets (id, question, outcomes, volume, created_at, clob_token_id)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM markets WHERE id = ?), ?), ?)
        ''', (
            market.get("id"),
            market.get("question"),
            outcomes_json,
            float(market.get("volume", 0)),
            market.get("id"),
            current_time,
            clob_token_id
        ))

        cursor.execute('''
            INSERT INTO snapshots (market_id, timestamp, prices, volume)
            VALUES (?, ?, ?, ?)
        ''', (market.get("id"), current_time, prices_json, float(market.get("volume", 0))))

    db.commit()
    db.close()


if __name__ == "__main__":
    init_db()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })

    try:
        while True:
            data = fetch_active_markets(session)
            process_and_save(data)
            time.sleep(900)
    except KeyboardInterrupt:
        print("Stopped.")
```
