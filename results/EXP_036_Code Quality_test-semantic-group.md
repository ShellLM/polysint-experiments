Here's the refactored structure for `api.py` into smaller, focused sub-modules. This maintains the exact same public API endpoints and behavior while improving code organization and reducing duplication.

        ### Directory Layout
        ```
        api.py                  # Slim entry point — app factory, startup, static serving
        api/
        ├── __init__.py         # Package marker
        ├── core.py             # DB context manager and analyst singleton
        ├── schemas.py          # Pydantic models
        ├── validation.py       # Input validators and regex constants
        ├── enrichment.py       # Market CLOB enrichment logic
        └── routes/
            ├── __init__.py     # Route aggregation
            ├── markets.py      # GET /markets, GET /markets/{id}/ai-analysis
            ├── watchlist.py    # GET/POST/DELETE /watchlist
            └── wallets.py      # GET /wallets/{address}/unmask, /profile
        ```

        ### `api.py`
        ```python
        from fastapi import FastAPI
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse
        from db import init_db
        from api.routes import markets_router, watchlist_router, wallets_router

        app = FastAPI(title="PolySINT Core Engine")

        app.include_router(markets_router)
        app.include_router(watchlist_router)
        app.include_router(wallets_router)

        app.mount("/static", StaticFiles(directory="static"), name="static")

        @app.on_event("startup")
        def startup():
            init_db()

        @app.get("/")
        def serve_dashboard():
            return FileResponse("static/index.html")
        ```

        ### `api/__init__.py`
        ```python
        # Package marker — no public exports needed here.
        ```

        ### `api/core.py`
        ```python
        from contextlib import contextmanager
        from db import get_db
        from analyst import PolyAnalyst

        # Singleton analyst to avoid redundant instantiation
        _analyst: PolyAnalyst | None = None

        def get_analyst() -> PolyAnalyst:
            global _analyst
            if _analyst is None:
                _analyst = PolyAnalyst()
            return _analyst

        @contextmanager
        def get_db_ctx():
            """Yields a database connection and guarantees closure."""
            db = get_db()
            try:
                yield db
            finally:
                db.close()
        ```

        ### `api/validation.py`
        ```python
        import re
        from fastapi import HTTPException

        # Input limits
        MAX_SEARCH_LEN = 200
        MAX_LABEL_LEN = 80

        # Ethereum addresses: 0x + 40 hex chars = 42 total
        ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')

        # Market IDs from Polymarket are numeric strings
        MARKET_ID_RE = re.compile(r'^[0-9]+$')

        # Pre-filter volume for CLOB lookups
        MIN_VOLUME_FOR_CLOB = 5000

        def validate_address(address: str) -> str:
            """Raises 400 if address is not a valid 42-char 0x Ethereum address."""
            if not ADDRESS_RE.match(address):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid address. Must be a 42-character 0x Ethereum address."
                )
            return address

        def validate_market_id(market_id: str) -> str:
            """Raises 400 if market_id is not a numeric string."""
            if not MARKET_ID_RE.match(market_id):
                raise HTTPException(status_code=400, detail="Invalid market ID format.")
            return market_id

        def validate_search_len(search: str | None) -> None:
            """Raises 400 if search query exceeds MAX_SEARCH_LEN."""
            if search is not None and len(search) > MAX_SEARCH_LEN:
                raise HTTPException(
                    status_code=400,
                    detail=f"Search query too long (max {MAX_SEARCH_LEN} chars)."
                )
        ```

        ### `api/schemas.py`
        ```python
        from pydantic import BaseModel, field_validator
        from .validation import ADDRESS_RE, MAX_LABEL_LEN

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
        ```

        ### `api/enrichment.py`
        ```python
        import json
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from db import get_db
        from clob import get_price_history
        from logger import get_logger

        log = get_logger("Enrichment")
        CLOB_WORKERS = 20

        def enrich_market(m: dict) -> dict | None:
            """Fetches CLOB history for a single market, attaches shift and current_price. Returns None if market should be excluded."""
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
                _enrich_from_snapshot(m)

            # Drop settled markets
            price = m['current_price']
            if price is not None and (price > 0.98 or price < 0.02):
                return None
            return m

        def _enrich_from_snapshot(m: dict) -> None:
            """Fallback enrichment from local snapshots when CLOB token ID is missing."""
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
                        m['current_price'] = float(prices[0])
            except Exception:
                pass

        def bulk_enrich_markets(candidates: list[dict]) -> list[dict]:
            """Enriches market dicts concurrently using a thread pool."""
            enriched = []
            with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as pool:
                futures = {pool.submit(enrich_market, m): m for m in candidates}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result is not None:
                            enriched.append(result)
                    except Exception as e:
                        log.error(f"Market enrichment failed: {e}")
            return enriched
        ```

        ### `api/routes/__init__.py`
        ```python
        from .markets import router as markets_router
        from .watchlist import router as watchlist_router
        from .wallets import router as wallets_router

        __all__ = ["markets_router", "watchlist_router", "wallets_router"]
        ```

        ### `api/routes/markets.py`
        ```python
        from fastapi import APIRouter, Query, HTTPException
        from clob import get_history_as_price_list
        from logger import get_logger
        from api.core import get_db_ctx, get_analyst
        from api.validation import validate_search_len, validate_market_id, MIN_VOLUME_FOR_CLOB
        from api.enrichment import bulk_enrich_markets

        log = get_logger("MarketsAPI")
        router = APIRouter()

        @router.get("/markets")
        def search_markets(
            limit: int = 50,
            search: str = None,
            vol_min: float = Query(default=None, ge=0, description="Minimum volume (inclusive)"),
            vol_max: float = Query(default=None, ge=0, description="Maximum volume (inclusive)"),
        ):
            validate_search_len(search)
            with get_db_ctx() as db:
                query = "SELECT * FROM markets"
                params = []
                if search:
                    query += " WHERE question LIKE ?"
                    params.append(f"%{search}%")
                all_markets = [dict(r) for r in db.execute(query, params).fetchall()]

            volume_floor = MIN_VOLUME_FOR_CLOB if not search else 0
            candidates = [m for m in all_markets if _passes_volume_filter(m, volume_floor, vol_min, vol_max)]
            enriched = bulk_enrich_markets(candidates)
            enriched.sort(key=lambda x: (abs(x.get('shift', 0.0)), x.get('volume') or 0.0), reverse=True)
            return enriched[:limit]

        def _passes_volume_filter(m: dict, floor: float, vol_min: float | None, vol_max: float | None) -> bool:
            """Returns True if market volume passes all active filters."""
            vol = m.get('volume') or 0
            if vol < floor:
                return False
            if vol_min is not None and vol < vol_min:
                return False
            if vol_max is not None and vol > vol_max:
                return False
            return True

        @router.get("/markets/{market_id}/ai-analysis")
        def get_ai_analysis(
            market_id: str,
            research: bool = Query(default=False, description="Enable Tavily web research for news context"),
        ):
            """Run AI analysis on a market. Set ?research=true for news context."""
            validate_market_id(market_id)
            with get_db_ctx() as db:
                market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
                if not market:
                    raise HTTPException(status_code=404, detail="Market not found")
                market = dict(market)
                price_history = _load_price_history(db, market_id, market)
            analysis = get_analyst().analyze_market_shift(
                market['question'], price_history, market['volume'], use_research=research
            )
            return {"analysis": analysis, "research_used": research}

        def _load_price_history(db, market_id: str, market: dict) -> list | None:
            """Try CLOB first, fall back to local snapshots."""
            if market.get("clob_token_id"):
                history = get_history_as_price_list(market["clob_token_id"])
                if history:
                    return history
            rows = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 5",
                (market_id,)
            ).fetchall()
            return [row['prices'] for row in rows] if rows else None
        ```

        ### `api/routes/watchlist.py`
        ```python
        from fastapi import APIRouter, HTTPException
        from logger import get_logger
        from api.core import get_db_ctx
        from api.schemas import Target
        from api.validation import validate_address

        log = get_logger("WatchlistAPI")
        router = APIRouter()

        @router.get("/watchlist")
        def get_watchlist():
            with get_db_ctx() as db:
                rows = db.execute("SELECT * FROM watch_list ORDER BY added_at DESC").fetchall()
                return [dict(r) for r in rows]

        @router.post("/watchlist")
        def add_to_watchlist(target: Target):
            with get_db_ctx() as db:
                try:
                    db.execute(
                        "INSERT INTO watch_list (address, label, added_at) VALUES (?, ?, datetime('now'))",
                        (target.address, target.label)
                    )
                    db.commit()
                except Exception:
                    log.error(f"Duplicate or invalid insert for {target.address}")
                    raise HTTPException(status_code=400, detail="This 0x address is already in your watchlist.")
            return {"status": "success", "resolved_address": target.address}

        @router.delete("/watchlist/{address}")
        def remove_from_watchlist(address: str):
            validate_address(address)
            with get_db_ctx() as db:
                db.execute("DELETE FROM watch_list WHERE address = ?", (address,))
                db.commit()
            return {"status": "deleted"}
        ```

        ### `api/routes/wallets.py`
        ```python
        from fastapi import APIRouter, HTTPException
        import requests
        from utils import unmask_proxy
        from config import Config
        from logger import get_logger
        from api.core import get_db_ctx, get_analyst
        from api.validation import validate_address

        log = get_logger("WalletsAPI")
        router = APIRouter()

        @router.get("/wallets/{address}/unmask")
        def unmask_wallet(address: str):
            validate_address(address)
            real_owner = unmask_proxy(address)
            return {"proxy": address, "real_owner": real_owner}

        @router.get("/wallets/{address}/profile")
        def profile_wallet(address: str):
            validate_address(address)
            real_owner = unmask_proxy(address)
            trades = _fetch_recent_trades(address)
            profile = get_analyst().profile_wallet(address, real_owner, trades)
            return {"profile": profile, "real_owner": real_owner}

        def _fetch_recent_trades(address: str, limit: int = 15) -> list[str]:
            """Fetch and simplify recent trades for a wallet address."""
            try:
                resp = requests.get(f"{Config.DATA_API}/trades", params={"user": address, "limit": limit}, timeout=10)
                data = resp.json() if resp.status_code == 200 else []
            except Exception as e:
                log.warning(f"Trade fetch failed for {address}: {e}")
                data = []
            return [f"Bought {t.get('side')} on '{t.get('title')}' for ${t.get('size')}" for t in data]
        ```

        This refactor improves maintainability by separating concerns, reducing duplication through the core module, and keeping each file focused. The public API remains identical.
