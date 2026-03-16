### `utils.py`
Added a `safe_float` helper function to handle safe type conversion for price/volume data. This ensures that `None`, empty strings, or malformed values don't crash the application.

```python
### FILE: utils.py ###
from web3 import Web3
from config import Config
from logger import get_logger
log = get_logger("Blockchain")

w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))

def safe_float(val):
    """Returns float or None — never raises. Used for robust price/volume parsing."""
    try:
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError):
        return None

def unmask_proxy(proxy_address):
    """Bypasses Polygonscan to find the real EOA owner of a Polymarket wallet."""
    try:
        response = w3.eth.call({
            'to': w3.to_checksum_address(proxy_address),
            'data': '0x7065c0d4' # getOwners() signature
        })
        
        # If the response is empty, it's not a contract
        if not response or response == b'':
            return "Direct Wallet (Not a Proxy)"
            
        owner = w3.to_checksum_address("0x" + response.hex()[-40:])
        return owner
    except Exception as e:
        # A revert error usually means the address is an EOA (Direct Wallet)
        log.info(f"Unmask check for {proxy_address} failed (likely an EOA): {e}")
        return "Direct Wallet (Not a Proxy)"
```

### `api.py`
1.  Imported `safe_float` from `utils`.
2.  **`_validate_address`**: Added explicit check to ensure input is a string before regex matching.
3.  **`_enrich_market`**: Added type checking for the input dictionary and used `safe_float` for all price parsing logic to prevent crashes on malformed API data.
4.  **`search_markets`**: Moved the search string length validation into the FastAPI `Query` definition (cleaner) and added `safe_float` for volume comparisons to handle edge cases.
5.  **`get_ai_analysis`**: Added validation for `market_id` format and fixed the snapshot fallback logic to properly parse JSON strings into a list of floats (validating the data passed to the analyst).

```python
### FILE: api.py ###
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy, safe_float
from logger import get_logger
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
from pydantic import BaseModel, field_validator
import re
import requests
import json

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

# Pre-filter: only consider markets above this volume before hitting CLOB.
MIN_VOLUME_FOR_CLOB = 5000

# Max concurrent CLOB requests
CLOB_WORKERS = 20

# ─── Input limits ─────────────────────────────────────────────────────────────
# Prevents oversized strings reaching SQLite LIKE or the LLM prompt
MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
# Ethereum addresses are always exactly 42 characters (0x + 40 hex chars)
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
# Market IDs from Polymarket are numeric strings — reject anything else
MARKET_ID_RE = re.compile(r'^[0-9]+$')

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")

def _validate_address(address: str) -> str:
    """Raises 400 if address is not a valid 42-char 0x Ethereum address."""
    # Type check first
    if not isinstance(address, str):
        raise HTTPException(
            status_code=400,
            detail="Invalid address format. String expected."
        )
    
    if not ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=400,
            detail="Invalid address. Must be a 42-character 0x Ethereum address."
        )
    return address

def _enrich_market(m: dict) -> dict | None:
    """
    Fetches CLOB history for a single market and attaches shift + current_price.
    Returns None if the market should be excluded (settled or no data).
    """
    # Guard against malformed input
    if not isinstance(m, dict):
        log.warning(f"_enrich_market received non-dict input: {type(m)}")
        return None

    clob_token_id = m.get("clob_token_id")
    m['shift'] = 0.0
    m['current_price'] = None

    if clob_token_id:
        history = get_price_history(clob_token_id)
        if history:
            # Use safe_float to prevent crashes on unexpected API data
            price_now = safe_float(history[-1].get("p"))
            price_then = safe_float(history[0].get("p"))

            if price_now is not None:
                m['current_price'] = price_now
            
                if price_then is not None and len(history) >= 2:
                    m['shift'] = round((price_now - price_then) * 100, 1)
    else:
        try:
            db = get_db()
            snap = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
                (m.get('id'),)
            ).fetchone()
            db.close()
            if snap:
                prices = json.loads(snap['prices'])
                if prices and isinstance(prices, list):
                    val = safe_float(prices[0])
                    if val is not None:
                        m['current_price'] = val
        except Exception:
            pass

    # Drop settled markets
    if m['current_price'] is not None:
        if m['current_price'] > 0.98 or m['current_price'] < 0.02:
            return None

    return m


@app.get("/markets")
def search_markets(
    limit: int = 50,
    # FastAPI Query validation handles type and length checks automatically
    search: str = Query(default=None, max_length=MAX_SEARCH_LEN),
    vol_min: float = Query(default=None, ge=0, description="Minimum volume (inclusive)"),
    vol_max: float = Query(default=None, ge=0, description="Maximum volume (inclusive)"),
):
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

    # Volume pre-filter: use MIN_VOLUME_FOR_CLOB as default floor when no search,
    # then apply any user-supplied bounds on top.
    volume_floor = MIN_VOLUME_FOR_CLOB if not search else 0

    candidates = []
    for m in all_markets:
        # Use safe_float for volume comparison to handle None or string cases gracefully
        vol = safe_float(m.get('volume')) or 0.0
        
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
    """
    Run AI analysis on a market.
    Set ?research=true to include Tavily web search context (requires TAVILY_API_KEY).
    Set ?research=false (default) to skip web search and use price data only.
    """
    # Validate market_id format explicitly
    if not isinstance(market_id, str) or not MARKET_ID_RE.match(market_id):
        raise HTTPException(status_code=400, detail="Invalid market ID format. Must be numeric.")

    db = get_db()
    try:
        market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        market = dict(market)
        price_history = None

        if market.get("clob_token_id"):
            price_history = get_history_as_price_list(market["clob_token_id"])

        # Fallback for local snapshot data
        if not price_history:
            raw = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 5",
                (market_id,)
            ).fetchall()
            
            # Validate and parse snapshot data into a flat list of floats
            parsed_history = []
            for row in raw:
                try:
                    p_list = json.loads(row['prices'])
                    if isinstance(p_list, list) and p_list:
                        # Take the first price (YES outcome)
                        val = safe_float(p_list[0])
                        if val is not None:
                            parsed_history.append(val)
                except (json.JSONDecodeError, TypeError):
                    continue
            
            if parsed_history:
                price_history = parsed_history

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
        if not isinstance(v, str):
             raise ValueError("Address must be a string.")
        v = v.strip()
        if not ADDRESS_RE.match(v):
            raise ValueError("Must be a 42-character 0x Ethereum address.")
        return v

    @field_validator('label')
    @classmethod
    def validate_label(cls, v):
        if not isinstance(v, str):
            raise ValueError("Label must be a string.")
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
