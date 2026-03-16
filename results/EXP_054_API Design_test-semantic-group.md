I'll implement comprehensive rate limiting for the PolySINT API using `slowapi` with proper headers and enforcement on all public endpoints. This will protect against abuse while maintaining fair access.

        First, update your `requirements.txt`:

        ```txt
        fastapi>=0.104.0
        uvicorn[standard]>=0.24.0
        python-dotenv>=1.0.0
        requests>=2.31.0
        web3>=6.11.0
        pydantic>=2.4.0
        slowapi>=0.1.9
        ```

        Update `config.py` to add rate limiting configuration:

        ```python
        import os
        from dotenv import load_dotenv

        load_dotenv()

        class Config:
            DB_NAME = "polysint_core.db"

            # Polymarket specific endpoints
            GAMMA_API = "https://gamma-api.polymarket.com/markets"
            DATA_API = "https://data-api.polymarket.com"

            # Blockchain RPC
            RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

            # LLM
            LLM_API_KEY = os.getenv("LLM_API_KEY")
            LLM_BASE_URL = os.getenv("LLM_API_BASE_URL")
            LLM_MODEL = os.getenv("ANALYSIS_MODEL")

            # Webhook Configurations
            DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
            TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
            TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

            # Web Research (Tavily)
            ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"

            # ─── Rate Limiting Configuration ─────────────────────────────────────
            RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
            REDIS_URL = os.getenv("REDIS_URL")  # Leave empty for in-memory storage

            # Endpoint-specific rate limits (requests per minute)
            RATE_LIMIT_GENERAL = int(os.getenv("RATE_LIMIT_GENERAL", "100"))
            RATE_LIMIT_SEARCH = int(os.getenv("RATE_LIMIT_SEARCH", "30"))
            RATE_LIMIT_ANALYSIS = int(os.getenv("RATE_LIMIT_ANALYSIS", "10"))
            RATE_LIMIT_WRITE = int(os.getenv("RATE_LIMIT_WRITE", "20"))
            RATE_LIMIT_UNMASK = int(os.getenv("RATE_LIMIT_UNMASK", "50"))
            RATE_LIMIT_PROFILE = int(os.getenv("RATE_LIMIT_PROFILE", "20"))
        ```

        Update `api.py` with comprehensive rate limiting:

        ```python
        from fastapi import FastAPI, HTTPException, Query, Request
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.middleware.cors import CORSMiddleware
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.util import get_remote_address
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from db import get_db, init_db
        from analyst import PolyAnalyst
        from utils import unmask_proxy
        from logger import get_logger
        from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
        from pydantic import BaseModel, field_validator
        from config import Config
        import re
        import requests
        import json

        log = get_logger("API")

        # ─── Rate Limiting Setup ────────────────────────────────────────────────
        def get_rate_limit_key(request: Request) -> str:
            """Combines IP and User-Agent hash for rate limiting to prevent proxy abuse."""
            ip = get_remote_address(request)
            user_agent = request.headers.get("user-agent", "unknown")[:50]
            ua_hash = hash(user_agent) % 100000
            return f"{ip}:{ua_hash}"

        def get_storage_uri() -> str:
            """Returns Redis URL if configured, otherwise in-memory storage."""
            if Config.REDIS_URL:
                return Config.REDIS_URL
            return "memory://"

        limiter = Limiter(
            key_func=get_rate_limit_key,
            storage_uri=get_storage_uri(),
            strategy="fixed-window",
            default_limits=["200/minute"]  # Global fallback limit
        )

        # ─── Rate Limit Tiers ─────────────────────────────────────────────────
        RATE_LIMITS = {
            "general": f"{Config.RATE_LIMIT_GENERAL}/minute",
            "search": f"{Config.RATE_LIMIT_SEARCH}/minute",
            "analysis": f"{Config.RATE_LIMIT_ANALYSIS}/minute",
            "write": f"{Config.RATE_LIMIT_WRITE}/minute",
            "unmask": f"{Config.RATE_LIMIT_UNMASK}/minute",
            "profile": f"{Config.RATE_LIMIT_PROFILE}/minute",
        }

        # ─── FastAPI App Setup ─────────────────────────────────────────────────
        app = FastAPI(
            title="PolySINT Core Engine",
            docs_url=None,  # Disable Swagger UI in production
            redoc_url=None   # Disable ReDoc in production
        )

        # Add rate limiter to app state
        app.state.limiter = limiter

        # Custom rate limit exception handler
        @app.exception_handler(RateLimitExceeded)
        async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
            """Custom rate limit exceeded handler with proper headers and logging."""
            client_ip = get_remote_address(request)
            
            log.warning(
                f"Rate limit exceeded: IP={client_ip} Path={request.url.path} "
                f"Limit={exc.detail}"
            )
            
            retry_after = 60  # Default to 60 seconds
            
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": "Rate limit exceeded. Please slow down.",
                    "detail": exc.detail,
                    "retry_after": retry_after,
                }
            )
            
            # Add standard rate limit headers
            response.headers["Retry-After"] = str(retry_after)
            response.headers["X-RateLimit-Remaining"] = "0"
            response.headers["X-RateLimit-Policy"] = "fixed-window"
            
            return response

        # Add rate limiting middleware
        if Config.RATE_LIMIT_ENABLED:
            app.add_middleware(SlowAPIMiddleware)

        # CORS middleware with exposed rate limit headers
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:3000", "http://localhost:9000"],
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=[
                "X-RateLimit-Limit", 
                "X-RateLimit-Remaining", 
                "X-RateLimit-Reset", 
                "Retry-After",
                "X-RateLimit-Policy"
            ],
        )

        analyst = PolyAnalyst()

        # Pre-filter: only consider markets above this volume before hitting CLOB.
        MIN_VOLUME_FOR_CLOB = 5000

        # Max concurrent CLOB requests
        CLOB_WORKERS = 20

        # ─── Input limits ─────────────────────────────────────────────────────
        MAX_SEARCH_LEN = 200
        MAX_LABEL_LEN = 80
        ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
        MARKET_ID_RE = re.compile(r'^[0-9]+$')

        app.mount("/static", StaticFiles(directory="static"), name="static")

        @app.on_event("startup")
        def startup():
            init_db()

        @app.get("/")
        @limiter.limit(RATE_LIMITS["general"])
        def serve_dashboard(request: Request):
            return FileResponse("static/index.html")

        def _validate_address(address: str) -> str:
            """Raises 400 if address is not a valid 42-char 0x Ethereum address."""
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

            # Drop settled markets
            if m['current_price'] is not None:
                if m['current_price'] > 0.98 or m['current_price'] < 0.02:
                    return None

            return m

        @app.get("/markets")
        @limiter.limit(RATE_LIMITS["search"])
        def search_markets(
            request: Request,
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
        @limiter.limit(RATE_LIMITS["general"])
        def get_watchlist(request: Request):
            db = get_db()
            try:
                res = db.execute("SELECT * FROM watch_list ORDER BY added_at DESC").fetchall()
                return [dict(r) for r in res]
            finally:
                db.close()

        @app.get("/wallets/{address}/unmask")
        @limiter.limit(RATE_LIMITS["unmask"])
        def unmask_wallet(request: Request, address: str):
            _validate_address(address)
            real_owner = unmask_proxy(address)
            return {"proxy": address, "real_owner": real_owner}

        @app.get("/markets/{market_id}/ai-analysis")
        @limiter.limit(RATE_LIMITS["analysis"])
        def get_ai_analysis(
            request: Request,
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
        @limiter.limit(RATE_LIMITS["write"])
        def add_to_watchlist(request: Request, target: Target):
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
        @limiter.limit(RATE_LIMITS["profile"])
        def profile_wallet_api(request: Request, address: str):
            _validate_address(address)
            try:
                real_owner = unmask_proxy(address)

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
        @limiter.limit(RATE_LIMITS["write"])
        def remove_from_watchlist(request: Request, address: str):
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

        @app.get("/rate-limit-status")
        @limiter.limit(RATE_LIMITS["general"])
        def get_rate_limit_status(request: Request):
            """Get current rate limit configuration for debugging."""
            return {
                "rate_limits": RATE_LIMITS,
                "client_ip": get_remote_address(request),
                "user_agent": request.headers.get("user-agent", "unknown")[:100],
                "storage": "redis" if Config.REDIS_URL else "memory",
                "enabled": Config.RATE_LIMIT_ENABLED,
            }
        ```

        Update `static/app.js` to handle rate limit responses:

        ```javascript
        // ─── State ────────────────────────────────────────────────────────────────────
        let hasLoadedOnce = false;
        let refreshTimer = null;
        let refreshCountdown = 0;
        const REFRESH_INTERVAL = 300;

        // Rate limit tracking
        let rateLimitBackoff = 0;
        let rateLimitTimer = null;

        // ─── Rate Limit Handling ──────────────────────────────────────────────────────

        async function handleRateLimitResponse(response) {
            if (response.status === 429) {
                let retryAfter = 60;
                let message = "Rate limit exceeded. Please wait before trying again.";
                
                try {
                    const data = await response.json();
                    retryAfter = data.retry_after || 60;
                    message = data.message || message;
                } catch (e) {
                    const headerRetry = response.headers.get('Retry-After');
                    if (headerRetry) {
                        retryAfter = parseInt(headerRetry, 10) || 60;
                    }
                }
                
                showRateLimitNotification(message, retryAfter);
                startRateLimitBackoff(retryAfter);
                return true;
            }
            return false;
        }

        function showRateLimitNotification(message, retryAfter) {
            const existing = document.getElementById('rateLimitNotification');
            if (existing) existing.remove();
            
            const notification = document.createElement('div');
            notification.id = 'rateLimitNotification';
            notification.className = 'fixed top-4 right-4 bg-amber-900/90 border border-amber-600 text-amber-100 px-4 py-3 rounded-lg shadow-lg z-50 max-w-sm';
            notification.innerHTML = `
                <div class="flex items-start gap-3">
                    <span class="text-xl">⚠️</span>
                    <div class="flex-1">
                        <div class="font-semibold text-sm">${message}</div>
                        <div class="text-xs text-amber-300 mt-1">
                            Please wait <span id="rateLimitSeconds">${retryAfter}</span>s
                        </div>
                    </div>
                    <button onclick="dismissRateLimitNotification()" class="text-amber-400 hover:text-white ml-2">&times;</button>
                </div>
            `;
            document.body.appendChild(notification);
        }

        function dismissRateLimitNotification() {
            const notification = document.getElementById('rateLimitNotification');
            if (notification) notification.remove();
        }

        function startRateLimitBackoff(seconds) {
            rateLimitBackoff = seconds;
            
            if (rateLimitTimer) clearInterval(rateLimitTimer);
            
            disableActionButtons();
            
            rateLimitTimer = setInterval(() => {
                rateLimitBackoff--;
                
                const secondsEl = document.getElementById('rateLimitSeconds');
                if (secondsEl) secondsEl.textContent = rateLimitBackoff;
                
                if (rateLimitBackoff <= 0) {
                    clearInterval(rateLimitTimer);
                    const notification = document.getElementById('rateLimitNotification');
                    if (notification) {
                        notification.classList.add('opacity-50');
                        setTimeout(() => notification.remove(), 500);
                    }
                    enableAllButtons();
                }
            }, 1000);
        }

        function disableActionButtons() {
            document.querySelectorAll('button[onclick^="analyzeMarket"], button[onclick^="profileEntity"], button[onclick^="unmaskWallet"], button[onclick^="addTarget"], button[onclick^="deleteTarget"]').forEach(btn => {
                btn.disabled = true;
                btn.classList.add('opacity-50', 'cursor-not-allowed');
                if (!btn.dataset.originalText) {
                    btn.dataset.originalText = btn.innerHTML;
                }
                btn.textContent = '⏳ Wait';
            });
        }

        function enableAllButtons() {
            document.querySelectorAll('button[data-original-text]').forEach(btn => {
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
                btn.innerHTML = btn.dataset.originalText;
                delete btn.dataset.originalText;
            });
        }

        function isInBackoff() {
            return rateLimitBackoff > 0;
        }

        // Update all fetch calls to use handleRateLimitResponse
        // Example for loadMarkets:
        async function loadMarkets(searchQuery = '', silent = false) {
            if (isInBackoff()) {
                if (!silent) showRateLimitNotification('Please wait for rate limit to reset.', rateLimitBackoff);
                return;
            }
            
            // ... existing code ...
            
            try {
                // ... existing fetch setup ...
                const res = await fetch(url);
                
                if (await handleRateLimitResponse(res)) return;
                if (!res.ok) throw new Error(`Backend Error ${res.status}`);
                
                // ... rest of processing ...
            } catch (e) {
                // ... error handling ...
            }
        }

        // Apply similar pattern to: analyzeMarket, profileEntity, unmaskWallet, addTarget, deleteTarget
        ```

        Add to your `.env` file:

        ```bash
        # Rate Limiting
        RATE_LIMIT_ENABLED=true
        REDIS_URL=                           # Leave empty for in-memory storage
        RATE_LIMIT_GENERAL=100               # General endpoints: requests/minute
        RATE_LIMIT_SEARCH=30                 # Search endpoints: requests/minute
        RATE_LIMIT_ANALYSIS=10               # AI analysis: requests/minute (expensive)
        RATE_LIMIT_WRITE=20                  # Write operations: requests/minute
        RATE_LIMIT_UNMASK=50                 # Blockchain lookups: requests/minute
        RATE_LIMIT_PROFILE=20                # Entity profiling: requests/minute
        ```

        This implementation provides:
        - Comprehensive rate limiting on all public endpoints
        - Tiered limits based on resource intensity
        - Standard rate limit headers (`X-RateLimit-*`, `Retry-After`)
        - Custom 429 error responses with proper structure
        - Frontend handling with user notifications and button disabling
        - IP + User-Agent hashing for better abuse prevention
        - Configuration via environment variables
        - Redis support for distributed deployments
        - Debug endpoint for monitoring

        **Rate Limit Tiers:**
        - **AI Analysis & Profiling**: 10-20 req/min (resource-intensive LLM calls)
        - **Market Search**: 30 req/min (database + CLOB intensive)
        - **General Endpoints**: 100 req/min (lightweight reads)
        - **Write Operations**: 20 req/min
        - **Blockchain Lookups**: 50 req/min
