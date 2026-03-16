Looking at the current code, the key inefficiency is that `_enrich_market` calls `get_shift()` which fetches history, then `get_price_history()` which fetches it again — two CLOB round-trips per market when one suffices. Here's the optimized version:

```python
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
from clob import get_price_history, DEFAULT_INTERVAL
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
        raise HTTPException(
            status_code=400,
            detail="Invalid address. Must be a 42-character 0x Ethereum address."
        )
    return address


def _compute_shift_and_price(history: list[dict]) -> tuple[float | None, float | None]:
    """
    Single helper: extracts both the 24h shift and current price from one
    already-fetched history list. Eliminates the double-fetch pattern where
    get_shift() and get_price_history() each hit the CLOB independently.
    """
    if not history or len(history) < 2:
        # Still try to extract current price from a single-point history
        if history and len(history) == 1:
            return None, float(history[0]["p"])
        return None, None

    price_then = float(history[0]["p"])
    price_now = float(history[-1]["p"])
    shift = round((price_now - price_then) * 100, 1)
    return shift, price_now


def _enrich_market(m: dict) -> dict | None:
    """
    Fetches CLOB history ONCE for a single market and derives shift + price.
    Falls back to local snapshots only when no clob_token_id exists.
    Returns None if the market should be excluded (settled or no data).
    """
    clob_token_id = m.get("clob_token_id")
    m['shift'] = 0.0
    m['current_price'] = None

    if clob_token_id:
        # ── Single CLOB call: derive both shift and current price ──────────
        history = get_price_history(clob_token_id)
        if history:
            shift, current_price = _compute_shift_and_price(history)
            m['shift'] = shift if shift is not None else 0.0
            m['current_price'] = current_price
    else:
        # ── Fallback: local snapshot comparison (no CLOB available) ────────
        try:
            db = get_db()
            snaps = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 2",
                (m['id'],)
            ).fetchall()
            db.close()

            if len(snaps) >= 2:
                prices_now = json.loads(snaps[0]['prices'])
                prices_then = json.loads(snaps[1]['prices'])
                if prices_now and prices_then:
                    try:
                        now = float(prices_now[0])
                        then = float(prices_then[0])
                        m['current_price'] = now
                        m['shift'] = round((now - then) * 100, 1)
                    except (ValueError, TypeError):
                        pass
            elif len(snaps) == 1:
                prices = json.loads(snaps[0]['prices'])
                if prices:
                    try:
                        m['current_price'] = float(prices[0])
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            log.warning(f"Snapshot fallback failed for market {m['id']}: {e}")

    # Drop settled markets
    if m['current_price'] is not None:
        if m['current_price'] > 0.98 or m['current_price'] < 0.02:
            return None

    return m


# ─── Batch pre-fetch: warm the CLOB cache for all candidates at once ──────────
def _prefetch_clob_histories(markets: list[dict]) -> dict[str, list[dict]]:
    """
    Pre-fetches CLOB price history for all candidate markets in parallel.
    Returns a dict mapping clob_token_id -> history list.
    This lets _enrich_market use cached data instead of making per-market calls.
    """

    # Collect unique token IDs that need fetching
    token_ids = {}
    for m in markets:
        tid = m.get("clob_token_id")
        if tid:
            token_ids[tid] = None

    if not token_ids:
        return token_ids

    def _fetch_one(tid: str) -> tuple[str, list[dict] | None]:
        try:
            return tid, get_price_history(tid)
        except Exception as e:
            log.warning(f"Batch pre-fetch failed for token {tid}: {e}")
            return tid, None

    with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, tid): tid for tid in token_ids}
        for future in as_completed(futures):
            tid, history = future.result()
            if history:
                token_ids[tid] = history

    return token_ids


def _enrich_market_cached(m: dict, history_cache: dict[str, list[dict]]) -> dict | None:
    """
    Same as _enrich_market but uses pre-fetched history from the batch cache.
    Falls back to a live fetch if the token wasn't in the cache.
    """
    clob_token_id = m.get("clob_token_id")
    m['shift'] = 0.0
    m['current_price'] = None

    if clob_token_id:
        # Try cache first, fall back to live fetch
        history = history_cache.get(clob_token_id)
        if history is None:
            history = get_price_history(clob_token_id)

        if history:
            shift, current_price = _compute_shift_and_price(history)
            m['shift'] = shift if shift is not None else 0.0
            m['current_price'] = current_price
    else:
        # Snapshot fallback (same as _enrich_market)
        try:
            db = get_db()
            snaps = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 2",
                (m['id'],)
            ).fetchall()
            db.close()

            if len(snaps) >= 2:
                prices_now = json.loads(snaps[0]['prices'])
                prices_then = json.loads(snaps[1]['prices'])
                if prices_now and prices_then:
                    try:
                        now = float(prices_now[0])
                        then = float(prices_then[0])
                        m['current_price'] = now
                        m['shift'] = round((now - then) * 100, 1)
                    except (ValueError, TypeError):
                        pass
            elif len(snaps) == 1:
                prices = json.loads(snaps[0]['prices'])
                if prices:
                    try:
                        m['current_price'] = float(prices[0])
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            log.warning(f"Snapshot fallback failed for market {m['id']}: {e}")

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

    # ── Batch pre-fetch: one parallel wave to warm the cache ──────────────
    history_cache = _prefetch_clob_histories(candidates)

    # ── Enrich using cached histories (no per-market CLOB calls) ──────────
    enriched = []
    with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as executor:
        futures = {
            executor.submit(_enrich_market_cached, m, history_cache): m
            for m in candidates
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    enriched.append(result)
            except Exception as e:
                log.error(f"Market enrichment failed: {e}")

    enriched.sort(key=lambda x: (abs(x.get('shift', 0.0)), x.get('volume') or 0.0), reverse=True)
    return enriched[:limit]


# ─── Watchlist ────────────────────────────────────────────────────────────────
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

---

**What changed and why:**

**1. Eliminated the double-fetch.** The old code called `get_shift()` (which internally calls `get_price_history()`) and then called `get_price_history()` again separately — two HTTP round-trips per market to the CLOB. New `_compute_shift_and_price()` extracts both values from a single history list.

**2. Added batch pre-fetch phase.** `_prefetch_clob_histories()` collects all unique `clob_token_id` values across candidates and fetches their histories in parallel (20 workers) before enrichment begins. This means the CLOB API gets hammered in one coordinated burst rather than staggered across the enrichment phase.

**3. Cache-aware enrichment.** `_enrich_market_cached()` checks the pre-fetched cache first, only making a live CLOB call as a fallback for tokens that somehow weren't in the batch. This also handles the case where two markets share the same `clob_token_id` (they'll hit cache instead of re-fetching).

**Net effect:** For a page of 50 markets, the old code made ~100 CLOB requests (2 per market). The new code makes at most ~50 (one per unique token), and they all fire in parallel up front. If markets share tokens, it's even fewer.
