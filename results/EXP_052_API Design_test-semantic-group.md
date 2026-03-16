I'll implement API versioning for PolySINT with a clean, maintainable structure that supports backward compatibility and future versioning.

```python
### FILE: api.py ###
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel, field_validator
import re
import requests
import json
import sqlite3
from datetime import datetime
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL

log = get_logger("API")

# ─── Version Configuration ─────────────────────────────────────────────────────
API_VERSION = "v1"
API_VERSIONS = {
    "v1": {
        "status": "current",
        "base_path": f"/{API_VERSION}",
        "released": "2025-01-01",
    }
}

# ─── App Setup with Lifespan ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="PolySINT Core Engine", lifespan=lifespan)

# ─── Middleware ─────────────────────────────────────────────────────────────────
class APIVersionHeader(BaseHTTPMiddleware):
    """Injects API version metadata into every response."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith(f"/{API_VERSION}/"):
            response.headers["X-API-Version"] = API_VERSION
            response.headers["X-API-Status"] = "current"
        return response

app.add_middleware(APIVersionHeader)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Configuration Constants ────────────────────────────────────────────────────
MIN_VOLUME_FOR_CLOB = 5000
CLOB_WORKERS = 20
MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
MARKET_ID_RE = re.compile(r'^[0-9]+$')

# ─── Pydantic Models ───────────────────────────────────────────────────────────
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

# ─── Static Files & Dashboard ──────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")

# ─── Unversioned Endpoints ─────────────────────────────────────────────────────
@app.get("/api")
def api_discovery():
    """Version discovery endpoint."""
    return {
        "service": "PolySINT Core Engine",
        "versions": API_VERSIONS,
        "current": API_VERSION,
        "docs": "/docs",
    }

@app.get("/health")
def health_check():
    """Enhanced health check with dependency probes."""
    checks = {}
    overall_healthy = True

    # Database probe
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        db.close()
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}
        overall_healthy = False

    # LLM config check
    from config import Config
    checks["llm_config"] = {
        "status": "ok" if Config.LLM_API_KEY else "missing",
        "model": Config.LLM_MODEL or "not configured",
    }
    if not Config.LLM_API_KEY:
        overall_healthy = False

    # Web research availability
    checks["web_research"] = {
        "status": "ok" if Config.ENABLE_WEB_RESEARCH else "disabled",
        "tavily_key": "present" if requests.utils.default_headers().get("TAVILY_API_KEY") else "missing",
    }

    status_code = 200 if overall_healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if overall_healthy else "degraded",
            "api_version": API_VERSION,
            "checks": checks,
        },
    )

# ─── Backward Compatibility Redirects ──────────────────────────────────────────
@app.get("/markets", include_in_schema=False)
def legacy_markets_redirect():
    return JSONResponse(
        status_code=301,
        content={"detail": "This endpoint has moved", "new_url": f"/{API_VERSION}/markets"},
        headers={"Location": f"/{API_VERSION}/markets"}
    )

@app.get("/watchlist", include_in_schema=False)
def legacy_watchlist_get_redirect():
    return JSONResponse(
        status_code=301,
        content={"detail": "This endpoint has moved", "new_url": f"/{API_VERSION}/watchlist"},
        headers={"Location": f"/{API_VERSION}/watchlist"}
    )

@app.post("/watchlist", include_in_schema=False)
def legacy_watchlist_post_redirect():
    return JSONResponse(
        status_code=301,
        content={"detail": "This endpoint has moved", "new_url": f"/{API_VERSION}/watchlist"},
        headers={"Location": f"/{API_VERSION}/watchlist"}
    )

@app.get("/wallets/{address}/unmask", include_in_schema=False)
def legacy_unmask_redirect(address: str):
    return JSONResponse(
        status_code=301,
        content={"detail": "This endpoint has moved", "new_url": f"/{API_VERSION}/wallets/{address}/unmask"},
        headers={"Location": f"/{API_VERSION}/wallets/{address}/unmask"}
    )

@app.get("/wallets/{address}/profile", include_in_schema=False)
def legacy_profile_redirect(address: str):
    return JSONResponse(
        status_code=301,
        content={"detail": "This endpoint has moved", "new_url": f"/{API_VERSION}/wallets/{address}/profile"},
        headers={"Location": f"/{API_VERSION}/wallets/{address}/profile"}
    )

@app.get("/markets/{market_id}/ai-analysis", include_in_schema=False)
def legacy_analysis_redirect(market_id: str, research: bool = False):
    return JSONResponse(
        status_code=301,
        content={"detail": "This endpoint has moved", "new_url": f"/{API_VERSION}/markets/{market_id}/ai-analysis?research={research}"},
        headers={"Location": f"/{API_VERSION}/markets/{market_id}/ai-analysis?research={research}"}
    )

@app.delete("/watchlist/{address}", include_in_schema=False)
def legacy_delete_redirect(address: str):
    return JSONResponse(
        status_code=301,
        content={"detail": "This endpoint has moved", "new_url": f"/{API_VERSION}/watchlist/{address}"},
        headers={"Location": f"/{API_VERSION}/watchlist/{address}"}
    )

# ─── Helper Functions ─────────────────────────────────────────────────────────
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

# ─── Versioned API Router ──────────────────────────────────────────────────────
v1_router = APIRouter(prefix=f"/{API_VERSION}", tags=[API_VERSION])

@v1_router.get(
    "/markets",
    summary="Search & enrich prediction markets",
    description="Returns markets matching the search query, enriched with live CLOB shift data. Markets are sorted by absolute shift magnitude descending."
)
def search_markets(
    limit: int = Query(default=50, ge=1, le=200, description="Max results to return"),
    search: str = Query(default=None, description="Substring match on market question"),
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

@v1_router.get("/watchlist", summary="Get all tracked entities")
def get_watchlist():
    db = get_db()
    try:
        res = db.execute("SELECT * FROM watch_list ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in res]
    finally:
        db.close()

@v1_router.post("/watchlist", summary="Add entity to watchlist", status_code=201)
def add_to_watchlist(target: Target):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO watch_list (address, label, added_at) VALUES (?, ?, datetime('now'))",
            (target.address, target.label)
        )
        db.commit()
        return {"status": "success", "resolved_address": target.address}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="This address is already in your watchlist.")
    except Exception as e:
        log.error(f"Failed to add target: {e}")
        raise HTTPException(status_code=500, detail="Failed to add target.")
    finally:
        db.close()

@v1_router.delete("/watchlist/{address}", summary="Remove entity from watchlist")
def remove_from_watchlist(address: str):
    _validate_address(address)
    db = get_db()
    try:
        result = db.execute("DELETE FROM watch_list WHERE address = ?", (address,))
        db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Address not found in watchlist.")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to delete target {address}: {e}")
        raise HTTPException(status_code=500, detail="Database error during deletion.")
    finally:
        db.close()

@v1_router.get("/wallets/{address}/unmask", summary="Resolve proxy wallet to real EOA")
def unmask_wallet(address: str):
    _validate_address(address)
    real_owner = unmask_proxy(address)
    return {"proxy": address, "real_owner": real_owner}

@v1_router.get("/markets/{market_id}/ai-analysis", summary="AI-powered market shift analysis")
def get_ai_analysis(
    market_id: str,
    research: bool = Query(default=False, description="Include Tavily web research context"),
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

@v1_router.get("/wallets/{address}/profile", summary="AI-profile a wallet's trading behaviour")
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

# ─── Mount Versioned Router ────────────────────────────────────────────────────
app.include_router(v1_router)
```

```javascript
### FILE: static/app.js ###
// ─── Versioned API Configuration ──────────────────────────────────────────────
const API_VERSION = 'v1';
const API_BASE = `/${API_VERSION}`;

// ─── State ────────────────────────────────────────────────────────────────────
let hasLoadedOnce = false;
let refreshTimer = null;
let refreshCountdown = 0;
const REFRESH_INTERVAL = 300; // 5 minutes

// ─── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadWatchlist();
    initResearchToggle();
    checkApiHealth();  // Verify backend connectivity on load

    document.getElementById('searchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const q = e.target.value.trim();
            loadMarkets(q);
        }
    });
});

// ─── API Health Check ─────────────────────────────────────────────────────────
async function checkApiHealth() {
    try {
        const res = await fetch('/health');
        if (res.ok) {
            const data = await res.json();
            console.log(`[PolySINT] API ${data.api_version} — ${data.status}`);
            updateConnectionStatus('connected', data.status);
        } else {
            updateConnectionStatus('error', `HTTP ${res.status}`);
        }
    } catch (e) {
        console.warn('[PolySINT] Backend unreachable');
        updateConnectionStatus('offline', 'No connection');
    }
}

function updateConnectionStatus(state, detail) {
    const el = document.getElementById('connectionStatus');
    if (!el) return;
    
    const states = {
        'connected': { icon: '●', class: 'text-emerald-400', title: `Connected — ${detail}` },
        'error': { icon: '◆', class: 'text-amber-400', title: `Error — ${detail}` },
        'offline': { icon: '○', class: 'text-red-400', title: detail }
    };
    
    const s = states[state] || states['offline'];
    el.innerHTML = `<span class="${s.class}" title="${s.title}">${s.icon}</span>`;
}

// ─── Research Toggle ──────────────────────────────────────────────────────────
function initResearchToggle() {
    const saved = localStorage.getItem('polysint_research_enabled');
    const enabled = saved === 'true';
    document.getElementById('researchToggle').checked = enabled;
    updateToggleLabel(enabled);
}

function onResearchToggle() {
    const enabled = document.getElementById('researchToggle').checked;
    localStorage.setItem('polysint_research_enabled', enabled);
    updateToggleLabel(enabled);
}

function updateToggleLabel(enabled) {
    const label = document.getElementById('researchToggleLabel');
    if (enabled) {
        label.textContent = 'Web Research: ON';
        label.className = 'text-xs text-emerald-400 font-mono';
    } else {
        label.textContent = 'Web Research: OFF';
        label.className = 'text-xs text-gray-500 font-mono';
    }
}

function isResearchEnabled() {
    return document.getElementById('researchToggle').checked;
}

// ─── Idle / Empty States ──────────────────────────────────────────────────────
function showIdleState() {
    const table = document.getElementById('marketsTable');
    const counter = document.getElementById('marketCounter');
    if (counter) counter.textContent = '';

    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center">
                <div class="flex flex-col items-center space-y-4">
                    <div class="text-5xl opacity-40">🕵️‍♂️</div>
                    <div class="text-gray-400 text-sm font-medium">Intelligence awaiting orders.</div>
                    <div class="text-gray-600 text-xs max-w-xs">Search for a specific market above and press Enter, or load all active movers.</div>
                    <button onclick="loadMarkets('')"
                        class="mt-2 bg-polysint text-gray-900 font-bold px-5 py-2 rounded-lg text-sm hover:bg-emerald-400 transition-all shadow-lg shadow-emerald-900/30">
                        Load Top Markets
                    </button>
                </div>
            </td>
        </tr>`;
}

function showLoadingState() {
    const table = document.getElementById('marketsTable');
    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center">
                <div class="flex flex-col items-center space-y-3">
                    <div class="flex space-x-1">
                        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
                        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
                    </div>
                    <div class="text-gray-400 text-sm">Scanning intelligence feeds...</div>
                </div>
            </td>
        </tr>`;
}

function showEmptySearchState(query) {
    const table = document.getElementById('marketsTable');
    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-4xl opacity-30">🔍</div>
                    <div class="text-gray-400 text-sm">No markets found for <span class="text-white font-mono">"${query}"</span></div>
                    <div class="text-gray-600 text-xs">Try a broader term or check the harvester has run.</div>
                </div>
            </td>
        </tr>`;
}

// ─── Auto-Refresh ─────────────────────────────────────────────────────────────
function startAutoRefresh(query) {
    clearInterval(refreshTimer);
    refreshCountdown = REFRESH_INTERVAL;
    updateRefreshUI();

    refreshTimer = setInterval(() => {
        refreshCountdown -= 1;
        updateRefreshUI();
        if (refreshCountdown <= 0) {
            loadMarkets(query, true);
        }
    }, 1000);
}

function updateRefreshUI() {
    const el = document.getElementById('refreshCountdown');
    if (!el) return;
    if (refreshCountdown > 0) {
        const mins = Math.floor(refreshCountdown / 60);
        const secs = refreshCountdown % 60;
        el.textContent = `Auto-refresh in ${mins}:${secs.toString().padStart(2, '0')}`;
    } else {
        el.textContent = 'Refreshing...';
    }
}

// ─── Core: Load Markets ───────────────────────────────────────────────────────
const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

async function loadMarkets(searchQuery = '', silent = false) {
    if (!silent) showLoadingState();

    const volMin = document.getElementById('volMin')?.value.trim();
    const volMax = document.getElementById('volMax')?.value.trim();

    try {
        const params = new URLSearchParams();
        if (searchQuery) params.set('search', searchQuery);
        if (volMin !== '') params.set('vol_min', volMin);
        if (volMax !== '') params.set('vol_max', volMax);

        const url = `${API_BASE}/markets${params.toString() ? '?' + params.toString() : ''}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`Backend Error ${res.status}`);

        const markets = await res.json();
        hasLoadedOnce = true;

        const counter = document.getElementById('marketCounter');
        if (counter) counter.textContent = markets.length > 0 ? `${markets.length} markets` : '';

        const table = document.getElementById('marketsTable');
        table.innerHTML = '';

        if (markets.length === 0) {
            showEmptySearchState(searchQuery || 'active markets');
            return;
        }

        markets.forEach((m, i) => {
            const shift = m.shift || 0;
            const absShift = Math.abs(shift);
            const shiftColor = shift > 0 ? 'text-emerald-400' : (shift < 0 ? 'text-red-400' : 'text-gray-500');
            const shiftIcon = shift > 0 ? '↑' : (shift < 0 ? '↓' : '–');
            const isAnomaly = absShift >= 10.0;
            const isWarning = absShift >= 5.0 && absShift < 10.0;

            const currentOdds = m.current_price != null
                ? `${Math.round(m.current_price * 100)}%`
                : 'N/A';

            let anomalyBadge = '';
            if (isAnomaly) {
                anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse">⚡ ANOMALY</span>`;
            } else if (isWarning) {
                anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">⚠ WATCH</span>`;
            }

            const rowHighlight = isAnomaly
                ? 'bg-red-500/5 hover:bg-red-500/10'
                : 'hover:bg-gray-700/30';

            const tr = document.createElement('tr');
            tr.className = `transition-colors border-b border-gray-700/50 ${rowHighlight}`;
            tr.style.animationDelay = `${i * 30}ms`;

            tr.innerHTML = `
                <td class="px-4 py-4 font-medium text-gray-200">
                    <div class="flex items-start flex-wrap gap-1">
                        <span>${m.question}</span>
                        ${anomalyBadge}
                    </div>
                    <div class="text-xs text-blue-400 mt-1 font-mono">Odds: ${currentOdds}</div>
                </td>
                <td class="px-4 py-4 font-mono ${shiftColor} font-bold text-sm">
                    ${shiftIcon} ${absShift}%
                    <div class="text-xs text-gray-600 font-normal">24h shift</div>
                </td>
                <td class="px-4 py-4 text-gray-400 text-xs">${formatter.format(m.volume)}</td>
                <td class="px-4 py-4 text-right">
                    <button onclick="analyzeMarket('${m.id}')"
                        class="bg-polysint/10 text-polysint border border-polysint/30 hover:bg-polysint hover:text-white px-3 py-1 rounded text-xs transition-all shadow-sm whitespace-nowrap">
                        🤖 Analyze
                    </button>
                </td>
            `;
            table.appendChild(tr);
        });

        startAutoRefresh(searchQuery);

    } catch (e) {
        console.error(e);
        const table = document.getElementById('marketsTable');
        table.innerHTML = `
            <tr><td colspan="4" class="text-center py-10">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-3xl">⚠️</div>
                    <div class="text-red-400 text-sm">Failed to load markets.</div>
                    <div class="text-gray-600 text-xs">${e.message || 'Is the backend running?'} Check <code>analyzer.log</code>.</div>
                    <button onclick="loadMarkets('${searchQuery}')" class="mt-2 text-xs text-polysint underline">Retry</button>
                </div>
            </td></tr>`;
    }
}

// ─── AI Analysis Modal ────────────────────────────────────────────────────────
async function analyzeMarket(marketId) {
    const useResearch = isResearchEnabled();

    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    modal.classList.remove('hidden');

    const researchNote = useResearch
        ? '<span class="text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-mono ml-2">+ Web Research</span>'
        : '<span class="text-xs bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded font-mono ml-2">No Web Research</span>';

    modalTitle.innerHTML = `🤖 PolySINT Intelligence ${researchNote}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-polysint text-sm animate-pulse">
                ${useResearch ? 'Scanning web + running LLM analysis...' : 'Running LLM analysis...'}
            </div>
            ${!useResearch ? '<div class="text-gray-600 text-xs">Enable Web Research in the toolbar for news context.</div>' : ''}
        </div>`;

    try {
        const url = `${API_BASE}/markets/${marketId}/ai-analysis?research=${useResearch}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error("AI Analysis Failed");
        const data = await res.json();

        const formatted = data.analysis
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `<div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                ⚠️ Could not generate intelligence brief.<br>
                <span class="text-xs text-gray-500 mt-1 block">Check your LLM API key and <code>analyzer.log</code>.</span>
            </div>`;
    }
}

// ─── Wallet / Entity ──────────────────────────────────────────────────────────
async function profileEntity(address, label) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    modal.classList.remove('hidden');
    modalTitle.innerHTML = `🧠 Entity Profile — ${label}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style="animation-delay:0ms"></div>
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-blue-400 text-sm animate-pulse">Fetching on-chain history & profiling...</div>
        </div>`;

    try {
        const res = await fetch(`${API_BASE}/wallets/${address}/profile`);
        if (!res.ok) throw new Error("Profiling Failed");
        const data = await res.json();

        const formatted = data.profile
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `
            <div class="mb-4 p-3 bg-gray-900 rounded border border-gray-700 font-mono text-xs text-gray-400 space-y-1">
                <div><span class="text-gray-600">Proxy:</span> ${address}</div>
                <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${data.real_owner}</span></div>
            </div>
            <div class="p-3 border-l-4 border-blue-500 bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `<div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">⚠️ Could not generate entity profile.</div>`;
    }
}

async function unmaskWallet(address) {
    const btn = document.getElementById(`btn-${address}`);
    const realDiv = document.getElementById(`real-${address}`);

    btn.disabled = true;
    btn.innerHTML = '<span class="animate-pulse">Scanning...</span>';
    btn.classList.add("opacity-50", "cursor-not-allowed");

    try {
        const res = await fetch(`${API_BASE}/wallets/${address}/unmask`);
        const data = await res.json();

        realDiv.classList.remove("hidden");
        realDiv.innerHTML = `EOA: <span class="text-polysint">${data.real_owner}</span>`;
        btn.textContent = "✓ Unmasked";
        btn.classList.remove("border-gray-600", "text-gray-300", "hover:bg-gray-700");
        btn.classList.add("bg-gray-700", "text-gray-500", "border-transparent", "cursor-default");
    } catch (e) {
        btn.disabled = false;
        btn.textContent = "Retry";
        btn.classList.remove("opacity-50", "cursor-not-allowed");
        alert(`Failed to unmask wallet: ${e.message}`);
    }
}

// ─── Watchlist ────────────────────────────────────────────────────────────────
async function addTarget() {
    const addressInput = document.getElementById('newAddress');
    const labelInput = document.getElementById('newLabel');
    const address = addressInput.value.trim();
    const label = labelInput.value.trim();

    if (!address || !label) {
        showInlineError('addError', 'Both address and label are required.');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/watchlist`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address, label })
        });

        const data = await res.json();
        if (res.ok) {
            addressInput.value = '';
            labelInput.value = '';
            clearInlineError('addError');
            loadWatchlist();
        } else {
            showInlineError('addError', data.detail || 'Failed to add target.');
        }
    } catch (e) {
        showInlineError('addError', 'Network error. Is the backend running?');
    }
}

function showInlineError(id, msg) {
    const el = document.getElementById(id);
    if (el) { el.textContent = msg; el.classList.remove('hidden'); }
}

function clearInlineError(id) {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.classList.add('hidden'); }
}

async function loadWatchlist() {
    const table = document.getElementById('watchlistTable');
    try {
        const res = await fetch(`${API_BASE}/watchlist`);
        const watchlist = await res.json();

        table.innerHTML = '';
        if (watchlist.length === 0) {
            table.innerHTML = `
                <tr><td class="text-center py-10 text-gray-600 text-sm italic px-4">
                    Watchlist empty.<br>
                    <span class="text-xs">Add a target's 0x proxy address above.</span>
                </td></tr>`;
            return;
        }

        watchlist.forEach(w => {
            const shortAddr = w.address.substring(0, 6) + '…' + w.address.substring(w.address.length - 4);
            const tr = document.createElement('tr');
            tr.className = "hover:bg-gray-700/30 transition-colors border-b border-gray-700/50";
            tr.innerHTML = `
                <td class="px-4 py-3">
                    <div class="font-semibold text-gray-200 text-sm">${w.label}</div>
                    <div class="text-xs font-mono text-gray-500 mt-0.5">${shortAddr}</div>
                    <div class="text-xs font-mono text-polysint mt-0.5 hidden" id="real-${w.address}"></div>
                </td>
                <td class="px-4 py-3 text-right">
                    <div class="flex justify-end items-center gap-1 flex-wrap">
                        <button onclick="unmaskWallet('${w.address}')" id="btn-${w.address}"
                            class="bg-gray-800 border border-gray-600 text-gray-300 hover:bg-gray-700 px-2 py-1 rounded text-xs transition-all">
                            Unmask
                        </button>
                        <button onclick="profileEntity('${w.address}', '${w.label}')"
                            class="bg-blue-900/40 text-blue-400 border border-blue-800 hover:bg-blue-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                            AI Profile
                        </button>
                        <button onclick="deleteTarget('${w.address}')" title="Stop Tracking"
                            class="bg-red-900/30 text-red-400 border border-red-800 hover:bg-red-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                            ✕
                        </button>
                    </div>
                </td>`;
            table.appendChild(tr);
        });
    } catch (e) {
        table.innerHTML = `<tr><td class="text-center py-8 text-red-400 text-sm">Failed to load watchlist.</td></tr>`;
    }
}

async function deleteTarget(address) {
    if (!confirm("Stop tracking this entity?")) return;
    try {
        const res = await fetch(`${API_BASE}/watchlist/${address}`, { method: 'DELETE' });
        if (res.ok) loadWatchlist();
        else alert("Failed to delete target.");
    } catch (e) { console.error(e); }
}

function closeModal() {
    document.getElementById('aiModal').classList.add('hidden');
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('aiModal');
    if (e.target === modal) closeModal();
});
```

**Key features of this implementation:**

1. **Modern FastAPI Patterns**: Uses lifespan context manager instead of deprecated `on_event`
2. **Backward Compatibility**: All old endpoints redirect to new versioned endpoints with 301 status
3. **API Discovery**: `/api` endpoint lists all versions and their status
4. **Enhanced Health Check**: `/health` probes database and configuration dependencies
5. **Version Headers**: Middleware adds `X-API-Version` header to all versioned responses
6. **CORS Support**: Configurable CORS middleware for frontend flexibility
7. **Proper Error Handling**: 409 for duplicate watchlist entries, 404 for missing deletions
8. **Frontend Integration**: Single `API_BASE` constant for easy version updates
9. **Route Documentation**: OpenAPI summaries and descriptions for all endpoints
10. **Clean Organization**: Routes grouped logically with clear separation

**Resulting API structure:**
```
Unversioned:
  GET  /                    → Dashboard
  GET  /api                 → API version discovery
  GET  /health              → Enhanced health check
  GET  /static/*            → Static assets

Versioned (v1):
  GET  /v1/markets          → Search markets
  GET  /v1/watchlist        → Get watchlist
  POST /v1/watchlist        → Add to watchlist
  DEL  /v1/watchlist/{addr} → Remove from watchlist
  GET  /v1/wallets/{addr}/unmask  → Unmask proxy
  GET  /v1/wallets/{addr}/profile → AI profile
  GET  /v1/markets/{id}/ai-analysis → AI analysis
```

This implementation provides a robust, maintainable versioning system that supports smooth migration from the original API while enabling future versioning.
