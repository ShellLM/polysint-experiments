Here is the updated source code. The primary changes involve adding a **Performance Monitoring Middleware** to `api.py` to track latency and error rates on the main interface, and adding **Failure Alerts** to `harvest.py` to track upstream data source health.

### FILE: api.py ###
```python
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
from notifier import Notifier
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
from pydantic import BaseModel, field_validator
from collections import deque
import re
import requests
import json
import time
import threading

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

# Pre-filter: only consider markets above this volume before hitting CLOB.
MIN_VOLUME_FOR_CLOB = 5000

# Max concurrent CLOB requests
CLOB_WORKERS = 20

# ─── Input limits ─────────────────────────────────────────────────────────────
MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
MARKET_ID_RE = re.compile(r'^[0-9]+$')

# ─── System Monitoring ───────────────────────────────────────────────────────
# Tracks rolling performance metrics for alerting
class SystemMonitor:
    def __init__(self, sample_size=50):
        self.latencies = deque(maxlen=sample_size)
        self.errors = deque(maxlen=sample_size)
        self.lock = threading.Lock()
        self.last_alert_time = 0
        self.alert_cooldown = 600  # 10 minutes
        self.notifier = Notifier()

    def record(self, latency_ms: float, status_code: int):
        with self.lock:
            self.latencies.append(latency_ms)
            # Track 5xx errors specifically
            is_error = 1 if status_code >= 500 else 0
            self.errors.append(is_error)
        
        # Check thresholds periodically (e.g., every 20 requests)
        if len(self.latencies) % 20 == 0:
            self._check_thresholds()

    def _check_thresholds(self):
        now = time.time()
        # Debounce alerts
        if now - self.last_alert_time < self.alert_cooldown:
            return

        with self.lock:
            if len(self.latencies) < 10:
                return
            
            avg_latency = sum(self.latencies) / len(self.latencies)
            error_rate = (sum(self.errors) / len(self.errors)) * 100
            
            # Thresholds
            LATENCY_WARN = 2000  # 2 seconds
            ERROR_RATE_WARN = 10.0 # 10%

            alerts = []
            if avg_latency > LATENCY_WARN:
                alerts.append(f"High Latency: API average is {avg_latency:.0f}ms (Target < {LATENCY_WARN}ms)")
            
            if error_rate > ERROR_RATE_WARN:
                alerts.append(f"High Error Rate: {error_rate:.1f}% of requests are failing 5xx")

            if alerts:
                msg = "\n".join(alerts)
                self.notifier.broadcast(msg, title="⚠️ System Performance Alert")
                self.last_alert_time = now

monitor = SystemMonitor()

@app.middleware("http")
async def monitor_performance(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    process_time = (time.time() - start) * 1000
    
    # Only monitor core API routes, ignore static file noise
    if not request.url.path.startswith("/static"):
        monitor.record(process_time, response.status_code)
    
    return response

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")

def _validate_address(address: str) -> str:
    if not ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=400,
            detail="Invalid address. Must be a 42-character 0x Ethereum address."
        )
    return address

def _enrich_market(m: dict) -> dict | None:
    clob_token_id = m.get("clob_token_id")
    m['shift'] = 0.0
    m['current_price'] = None

    if clob_token_id:
        history = get_price_history(clob_token_id)
        if history:
            m['current_price'] = float(history[-1]["p"])
            if len(history) >= 2:
                m['shift'] = round((float(history[-1]["p"]) - float(history[0]["p"])) * 100, 1)
    else:
        try:
            db = get_db()
            snap = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
                (m['id'],)
            ).fetchone()
            db.close()
            if snap:
                prices = json.loads(snap['prices'])
                if prices:
                    val = float(prices[0])
                    m['current_price'] = val
        except Exception:
            pass

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

@app.get("/watchlist")
def get_watchlist():
    db = get_db()
    try:
        res = db.execute("SELECT * FROM watch_list ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in res]
    finally:
        db.close()

@app.get("/wallets/{address}/unmask")
def unmask_wallet(address: str):
    _validate_address(address)
    real_owner = unmask_proxy(address)
    return {"proxy": address, "real_owner": real_owner}

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

        if not price_history:
            raw = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 5",
                (market_id,)
            ).fetchall()
            price_history = [h['prices'] for h in raw]

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
```

### FILE: harvest.py ###
```python
import requests
import json
import time
from datetime import datetime
from config import Config
from db import get_db, init_db
from logger import get_logger
from notifier import Notifier

log = get_logger("Harvester")

# ─── Upstream API Health Tracking ─────────────────────────────────────────────
# Tracks consecutive failures to detect prolonged outages of Polymarket Gamma API
CONSECUTIVE_FAILURES = 0
FAILURE_THRESHOLD = 3  # Alert after 3 consecutive failures

def extract_first_price(outcome_prices):
    """
    Safely extracts the first (YES) outcome price from whatever shape Gamma returns.
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
            log.warning(f"outcomePrices is not a list after parsing: {type(outcome_prices).__name__}")
            return '[]'

        if not outcome_prices:
            return '[]'

        while outcome_prices and isinstance(outcome_prices[0], list):
            outcome_prices = outcome_prices[0]

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

def fetch_active_markets(session):
    """Paginates through the Polymarket API to get all active markets."""
    global CONSECUTIVE_FAILURES
    print(f"[{datetime.now()}] Fetching active markets from Polymarket...")
    all_markets = []
    limit = 100
    offset = 0
    notifier = Notifier()

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

        try:
            response = session.get(Config.GAMMA_API, params=params, timeout=15)

            if response.status_code == 429:
                print(f"Rate limited at offset {offset}. Sleeping for 10 seconds...")
                time.sleep(10)
                continue

            if response.status_code != 200:
                print(f"Error fetching data at offset {offset}: HTTP {response.status_code}")
                # Non-200 is considered a failure for the cycle
                raise requests.exceptions.RequestException(f"HTTP {response.status_code}")

            data = response.json()
            if not data:
                break

            all_markets.extend(data)
            offset += limit

            if offset % 1000 == 0:
                print(f" -> Fetched {offset} markets...")

            time.sleep(0.5)

        except requests.exceptions.SSLError as e:
            print(f"\n[!] SSL Error at offset {offset}.")
            raise Exception("SSL Error") # Propagate to outer handler
        
        except Exception as e:
            log.warning(f"Network glitch at offset {offset}: {e}")
            print(f"\n[!] Network glitch at offset {offset}: {e}. Retrying in 5 seconds...")
            time.sleep(5)
            # We don't count intermittent glitches as full outages yet, 
            # but if they persist, the loop might never complete.
            # For simplicity, we let the outer loop handle counts.
            raise e 

    # If we successfully fetched data, reset the failure counter
    CONSECUTIVE_FAILURES = 0
    print(f"[{datetime.now()}] Successfully fetched {len(all_markets)} active markets.")
    return all_markets


def process_and_save(markets):
    db = get_db()
    cursor = db.cursor()
    current_time = datetime.now().isoformat()

    for market in markets:
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
                log.warning(f"Failed to parse clobTokenIds for market {market.get('id')}: {e}")

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
    notifier = Notifier()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })

    try:
        while True:
            try:
                data = fetch_active_markets(session)
                process_and_save(data)
            except Exception as e:
                # Handle failure tracking for the main loop
                CONSECUTIVE_FAILURES += 1
                log.error(f"Harvest cycle failed ({CONSECUTIVE_FAILURES}): {e}")
                
                if CONSECUTIVE_FAILURES == FAILURE_THRESHOLD:
                    msg = (
                        f"🚨 **Data Source Outage Detected**\n"
                        f"The Harvester has failed {FAILURE_THRESHOLD} times in a row.\n"
                        f"Last Error: `{str(e)}`"
                    )
                    notifier.broadcast(msg, title="⚠️ Data Feed Alert")
            
            time.sleep(900)
    except KeyboardInterrupt:
        print("Stopped.")
```
