Here's the refactored code applying DRY principles to eliminate duplicated market data parsing logic across `api.py`, `harvest.py`, and `alerts.py`.

### Key Changes

1. **Centralized parsing in `utils.py`**: All market data parsing functions are consolidated in one place
2. **Unified `get_market_state()` resolver**: Single function handles CLOB history with snapshot fallback
3. **Bug fixes**: Fixed `api.py` AI analysis endpoint and `harvest.py` session handling
4. **Enhanced error handling**: Added guards against pathological input and better error messages

### Updated `utils.py`
```python
from web3 import Web3
import json
from typing import Optional
from config import Config
from db import get_db
from clob import get_price_history
from logger import get_logger

log = get_logger("Utils")

w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))


def unmask_proxy(proxy_address):
    """Bypasses Polygonscan to find the real EOA owner of a Polymarket wallet."""
    try:
        response = w3.eth.call({
            'to': w3.to_checksum_address(proxy_address),
            'data': '0x7065c0d4'  # getOwners() signature
        })

        if not response or response == b'':
            return "Direct Wallet (Not a Proxy)"

        owner = w3.to_checksum_address("0x" + response.hex()[-40:])
        return owner
    except Exception as e:
        log.info(f"Unmask check for {proxy_address} failed (likely an EOA): {e}")
        return "Direct Wallet (Not a Proxy)"


# ─── Market Data Parsing ─────────────────────────────────────────────────────

def safe_float(val) -> Optional[float]:
    """Returns float or None — never raises."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def extract_first_price(outcome_prices) -> str:
    """
    Safely extracts the first (YES) outcome price from whatever shape Gamma returns.
    Handles nested lists, dicts with price keys, double-encoded JSON strings, etc.
    Returns a JSON string of a flat list of strings, e.g. '["0.5", "0.5"]'.
    Returns '[]' on any failure.
    """
    try:
        if outcome_prices is None:
            return '[]'

        if isinstance(outcome_prices, str):
            outcome_prices = outcome_prices.strip()
            if not outcome_prices:
                return '[]'
            try:
                outcome_prices = json.loads(outcome_prices)
            except json.JSONDecodeError:
                log.warning(f"outcomePrices is not valid JSON: {repr(outcome_prices)[:100]}")
                return '[]'

        if outcome_prices is None:
            return '[]'

        if not isinstance(outcome_prices, list):
            log.warning(f"outcomePrices is not a list: {type(outcome_prices).__name__}")
            return '[]'

        if not outcome_prices:
            return '[]'

        # Recursively unwrap nested lists with depth guard
        depth = 0
        max_depth = 10
        while outcome_prices and isinstance(outcome_prices[0], list):
            outcome_prices = outcome_prices[0]
            depth += 1
            if depth > max_depth:
                log.warning("outcomePrices nesting too deep, aborting")
                return '[]'

        if not outcome_prices:
            return '[]'

        validated = []
        for item in outcome_prices:
            price = None

            if isinstance(item, dict):
                price = item.get('price') or item.get('p')
            elif isinstance(item, (str, int, float)):
                price = item
            elif isinstance(item, list) and len(item) == 1:
                price = item[0]

            if price is not None:
                try:
                    float(price)
                    validated.append(str(price))
                except (TypeError, ValueError):
                    pass

        return json.dumps(validated)

    except Exception as e:
        preview = repr(outcome_prices)[:100] if outcome_prices else 'None'
        log.warning(f"Failed to parse outcomePrices '{preview}': {e}")
        return '[]'


def parse_clob_token_ids(raw_clob) -> Optional[str]:
    """Extracts the YES outcome token ID from clobTokenIds. Returns None on failure."""
    if not raw_clob:
        return None

    try:
        token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
        if token_ids and len(token_ids) > 0:
            return token_ids[0]
    except Exception as e:
        log.warning(f"Failed to parse clobTokenIds: {e}")

    return None


def get_first_price_from_json(prices_json: str) -> Optional[float]:
    """
    Parses stored prices JSON string and returns the first (YES) price as float.
    Used to convert snapshot storage format for analyst consumption.
    """
    if not prices_json:
        return None

    try:
        prices = json.loads(prices_json)
        if isinstance(prices, list) and len(prices) > 0:
            return safe_float(prices[0])
    except (json.JSONDecodeError, TypeError):
        pass

    return None


# ─── Unified Market State Resolution ─────────────────────────────────────────

def get_market_state(market_id: str, clob_token_id: Optional[str] = None,
                     interval: str = "1d") -> dict:
    """
    Fetches current price and shift for a market using the best available source.
    Tries CLOB history first, falls back to local snapshots.

    Returns:
        dict with:
            - 'current_price': float | None
            - 'shift': float | None (fractional change, e.g. 0.10 = +10%)
    """
    state = {"current_price": None, "shift": None}

    # Primary: CLOB history
    if clob_token_id:
        history = get_price_history(clob_token_id, interval=interval)
        if history and len(history) > 0:
            current = safe_float(history[-1].get("p"))
            if current is not None:
                state["current_price"] = current
                if len(history) >= 2:
                    first = safe_float(history[0].get("p"))
                    if first is not None:
                        state["shift"] = current - first
                return state

    # Fallback: local snapshots
    db = get_db()
    try:
        rows = db.execute("""
            SELECT prices FROM snapshots
            WHERE market_id = ?
            ORDER BY timestamp DESC LIMIT 2
        """, (market_id,)).fetchall()
    except Exception as e:
        log.error(f"DB error fetching snapshots for {market_id}: {e}")
        return state
    finally:
        db.close()

    if not rows:
        return state

    current_price = get_first_price_from_json(rows[0]['prices'])
    if current_price is None:
        return state

    state["current_price"] = current_price

    if len(rows) >= 2:
        prev_price = get_first_price_from_json(rows[1]['prices'])
        if prev_price is not None:
            state["shift"] = current_price - prev_price

    return state
```

### Updated `harvest.py`
```python
import requests
import json
import time
from datetime import datetime
from config import Config
from db import get_db, init_db
from logger import get_logger
from utils import extract_first_price, parse_clob_token_ids

log = get_logger("Harvester")


def fetch_active_markets(session):
    """Paginates through the Polymarket API to get all active markets."""
    print(f"[{datetime.now()}] Fetching active markets from Polymarket...")
    all_markets = []
    limit = 100
    offset = 0

    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset
        }

        try:
            # FIX: Use passed session (headers set by caller) instead of creating new one
            response = session.get(Config.GAMMA_API, params=params, timeout=15)

            if response.status_code == 429:
                print(f"Rate limited at offset {offset}. Sleeping for 10 seconds...")
                time.sleep(10)
                continue

            if response.status_code != 200:
                print(f"Error fetching data at offset {offset}: HTTP {response.status_code}")
                break

            data = response.json()
            if not data:
                break

            all_markets.extend(data)
            offset += limit

            if offset % 1000 == 0:
                print(f" -> Fetched {offset} markets...")

            time.sleep(0.5)

        except requests.exceptions.SSLError:
            print(f"\n[!] SSL Error at offset {offset}. Try adding verify=False to session.get()")
            break

        except Exception as e:
            log.warning(f"Network glitch at offset {offset}: {e}")
            print(f"\n[!] Network glitch at offset {offset}: {e}. Retrying in 5 seconds...")
            time.sleep(5)
            continue

    print(f"[{datetime.now()}] Successfully fetched {len(all_markets)} active markets.")
    return all_markets


def process_and_save(markets):
    db = get_db()
    cursor = db.cursor()
    current_time = datetime.now().isoformat()

    for market in markets:
        outcomes_json = json.dumps(market.get("outcomes", []))

        # DRY: Use shared parser for outcome prices
        prices_json = extract_first_price(market.get("outcomePrices", []))

        # DRY: Use shared parser for CLOB token ID
        clob_token_id = parse_clob_token_ids(market.get("clobTokenIds"))

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

### Updated `api.py`
```python
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy, get_market_state, get_first_price_from_json
from logger import get_logger
from clob import get_history_as_price_list, DEFAULT_INTERVAL
from pydantic import BaseModel, field_validator
import re
import requests

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

MIN_VOLUME_FOR_CLOB = 5000
CLOB_WORKERS = 20
MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
MARKET_ID_RE = re.compile(r'^[0-9]+$')

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")


def _validate_address(address: str) -> str:
    if not ADDRESS_RE.match(address):
        raise HTTPException(status_code=400, detail="Invalid address. Must be a 42-character 0x Ethereum address.")
    return address


def _enrich_market(m: dict) -> dict | None:
    """
    Enriches market with current_price and shift.
    Returns None if market should be excluded (settled or no data).
    """
    # DRY: Use unified state resolver instead of duplicating CLOB/snapshot logic
    state = get_market_state(m['id'], m.get('clob_token_id'))

    m['current_price'] = state['current_price']
    m['shift'] = round((state['shift'] or 0.0) * 100, 1)  # Convert fraction to percentage

    if m['current_price'] is not None:
        if m['current_price'] > 0.98 or m['current_price'] < 0.02:
            return None

    return m


@app.get("/markets")
def search_markets(
    limit: int = 50,
    search: str = None,
    vol_min: float = Query(default=None, ge=0, description="Minimum volume (inclusive)"),
    vol_max: float = Query(default=None, ge=0, description="Maximum volume (inclusive)"),
):
    if search is not None and len(search) > MAX_SEARCH_LEN:
        raise HTTPException(status_code=400, detail=f"Search query too long (max {MAX_SEARCH_LEN} chars).")

    db = get_db()
    try:
        query = "SELECT * FROM markets"
        params = []
        if search:
            query += " WHERE question LIKE ?"
            params.append(f"%{search}%")

        all_markets = [dict(r) for r in db.execute(query, params).fetchall()]
    finally:
        db.close()

    volume_floor = MIN_VOLUME_FOR_CLOB if not search else 0

    candidates = []
    for m in all_markets:
        vol = m.get('volume') or 0
        if vol < volume_floor:
            continue
        if vol_min is not None and vol < vol_min:
            continue
        if vol_max is not None and vol > vol_max:
            continue
        candidates.append(m)

    enriched = []
    with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as executor:
        futures = {executor.submit(_enrich_market, m): m for m in candidates}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    enriched.append(result)
            except Exception as e:
                log.error(f"Market enrichment failed: {e}")

    enriched.sort(key=lambda x: (abs(x.get('shift', 0.0)), x.get('volume') or 0.0), reverse=True)
    return enriched[:limit]


@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis(
    market_id: str,
    research: bool = Query(default=False, description="Enable Tavily web research for news context")
):
    if not MARKET_ID_RE.match(market_id):
        raise HTTPException(status_code=400, detail="Invalid market ID format.")

    db = get_db()
    try:
        market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        market = dict(market)
        price_history = None

        if market.get("clob_token_id"):
            price_history = get_history_as_price_list(market["clob_token_id"])

        # FIX: Use shared parser to convert JSON strings to floats for analyst
        if not price_history:
            raw = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 5",
                (market_id,)
            ).fetchall()

            price_history = []
            for h in raw:
                price = get_first_price_from_json(h['prices'])
                if price is not None:
                    price_history.append(price)

        if not price_history:
            price_history = None

        analysis = analyst.analyze_market_shift(
            market['question'],
            price_history,
            market['volume'],
            use_research=research
        )
        return {"analysis": analysis, "research_used": research}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"LLM Analysis failed for {market_id}: {e}")
        raise HTTPException(status_code=500, detail="AI analysis failed.")
    finally:
        db.close()


# ─── Watchlist & Wallet Endpoints (unchanged logic) ──────────────────────────

class Target(BaseModel):
    address: str
    label: str

    @field_validator('address')
    @classmethod
    def validate_address(cls, v):
        v = v.strip()
        if not ADDRESS_RE.match(v):
            raise ValueError("Must be a 42-character 0x Ethereum address.")
        return v

    @field_validator('label')
    @classmethod
    def validate_label(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Label cannot be empty.")
        if len(v) > MAX_LABEL_LEN:
            raise ValueError(f"Label too long (max {MAX_LABEL_LEN} chars).")
        return v

@app.get("/watchlist")
def get_watchlist():
    db = get_db()
    try:
        res = db.execute("SELECT * FROM watch_list ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in res]
    finally:
        db.close()

@app.post("/watchlist")
def add_to_watchlist(target: Target):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO watch_list (address, label, added_at) VALUES (?, ?, datetime('now'))",
            (target.address, target.label)
        )
        db.commit()
        return {"status": "success", "resolved_address": target.address}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to add target: {e}")
        raise HTTPException(status_code=400, detail="This 0x address is already in your watchlist.")
    finally:
        db.close()

@app.delete("/watchlist/{address}")
def remove_from_watchlist(address: str):
    _validate_address(address)
    db = get_db()
    try:
        db.execute("DELETE FROM watch_list WHERE address = ?", (address,))
        db.commit()
        return {"status": "deleted"}
    except Exception as e:
        log.error(f"Failed to delete target {address}: {e}")
        raise HTTPException(status_code=500, detail="Database error during deletion.")
    finally:
        db.close()

@app.get("/wallets/{address}/unmask")
def unmask_wallet(address: str):
    _validate_address(address)
    real_owner = unmask_proxy(address)
    return {"proxy": address, "real_owner": real_owner}

@app.get("/wallets/{address}/profile")
def profile_wallet_api(address: str):
    _validate_address(address)
    try:
        real_owner = unmask_proxy(address)

        from config import Config
        url = f"{Config.DATA_API}/trades?user={address}&limit=15"
        resp = requests.get(url, timeout=10)
        trades_data = resp.json() if resp.status_code == 200 else []

        simplified_trades = [
            f"Bought {t.get('side')} on '{t.get('title')}' for ${t.get('size')}"
            for t in trades_data
        ]
        profile = analyst.profile_wallet(address, real_owner, simplified_trades)

        return {"profile": profile, "real_owner": real_owner}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Profiling failed: {e}")
        raise HTTPException(status_code=500, detail="AI Profiling failed.")
```

### Updated `alerts.py`
```python
import time
from db import get_db
from notifier import Notifier
from logger import get_logger
from clob import DEFAULT_INTERVAL
from utils import get_market_state

log = get_logger("Alerts")

ANOMALY_THRESHOLD = 0.10  # 10%
MIN_ALERT_VOLUME = 5000
NEAR_RESOLUTION_THRESHOLD = 0.80


def scan_for_anomalies():
    db = get_db()
    markets = db.execute("SELECT id, question, volume, clob_token_id FROM markets").fetchall()
    db.close()

    notifier = Notifier()

    for m in markets:
        market_volume = m['volume'] or 0
        if market_volume < MIN_ALERT_VOLUME:
            continue

        # DRY: Use unified state resolver instead of duplicating CLOB/snapshot logic
        state = get_market_state(m['id'], m.get('clob_token_id'), interval=DEFAULT_INTERVAL)

        shift = state.get('shift')
        current_price = state.get('current_price')

        if shift is None or current_price is None:
            continue

        if abs(shift) >= ANOMALY_THRESHOLD:
            if current_price >= NEAR_RESOLUTION_THRESHOLD or current_price <= (1 - NEAR_RESOLUTION_THRESHOLD):
                log.warning(
                    f"Suppressed alert for '{m['question']}': "
                    f"price {current_price:.2f} is near resolution."
                )
                continue

            direction = "📈" if shift > 0 else "📉"
            current_price_str = f"{round(current_price * 100)}%"

            msg = (
                f"{direction} **{m['question']}**\n"
                f"Shifted **{shift * 100:.1f}%** over the last {DEFAULT_INTERVAL} "
                f"— now at **{current_price_str}**\n"
                f"Volume: ${market_volume:,.0f}\n\n"
                f"_Open the dashboard to run AI analysis on demand._"
            )
            notifier.broadcast(msg, title="🚨 Market Anomaly Detected")


if __name__ == "__main__":
    print(
        f"Anomaly Scanner active — "
        f"Threshold: {ANOMALY_THRESHOLD * 100:.0f}% over {DEFAULT_INTERVAL} | "
        f"Min volume: ${MIN_ALERT_VOLUME:,} | "
        f"Near-resolution cutoff: {NEAR_RESOLUTION_THRESHOLD * 100:.0f}%"
    )
    while True:
        scan_for_anomalies()
        time.sleep(300)
```

### Summary of DRY Improvements

| Duplicated Logic | Before | After |
|-----------------|--------|-------|
| `extract_first_price()` | Only in `harvest.py` | `utils.py` (shared) |
| `parse_clob_token_ids()` | Inline in `harvest.py` | `utils.py` (shared) |
| `safe_float()` | Only in `alerts.py` | `utils.py` (shared) |
| `get_first_price_from_json()` | Duplicated inline | `utils.py` (shared) |
| CLOB/snapshot fallback | In `_enrich_market()` and `scan_for_anomalies()` | `get_market_state()` in `utils.py` |

### Bug Fixes Included

1. **`api.py`**: The `/ai-analysis` endpoint was passing raw JSON strings to the analyst instead of parsed floats
2. **`harvest.py`**: `fetch_active_markets()` was overwriting the `session` argument, ignoring caller's headers
3. **Enhanced error handling**: Added depth guards for nested lists and better error messages
