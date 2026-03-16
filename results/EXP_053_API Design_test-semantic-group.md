Here's the standardized JSON response implementation for PolySINT API:

```python
# api.py - Standardized JSON Response Implementation

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
from pydantic import BaseModel, field_validator
from typing import Any, Dict, Optional
from datetime import datetime
import re
import requests
import json
import sqlite3
import uuid

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

# Pre-filter: only consider markets above this volume before hitting CLOB.
MIN_VOLUME_FOR_CLOB = 5000
CLOB_WORKERS = 20

# ─── Input limits ─────────────────────────────────────────────────────────────
MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
MARKET_ID_RE = re.compile(r'^[0-9]+$')

app.mount("/static", StaticFiles(directory="static"), name="static")

# ─── Error Codes ──────────────────────────────────────────────────────────────
class ErrorCode:
    """Centralized error codes for consistent error responses."""
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    DATABASE_ERROR = "DATABASE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    PROFILING_FAILED = "PROFILING_FAILED"
    SEARCH_TOO_LONG = "SEARCH_TOO_LONG"
    INVALID_ADDRESS = "INVALID_ADDRESS"
    INVALID_MARKET_ID = "INVALID_MARKET_ID"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

# ─── Response Helpers ─────────────────────────────────────────────────────────
def success_response(
    data: Any = None,
    message: str = "OK",
    request_id: str = None
) -> Dict:
    """Build standardized success response envelope."""
    body = {
        "success": True,
        "message": message,
        "request_id": request_id or uuid.uuid4().hex[:8],
    }
    if data is not None:
        body["data"] = data
    return body

def error_response(
    code: str,
    message: str,
    status_code: int = 400,
    details: Any = None,
    request_id: str = None
) -> JSONResponse:
    """Build standardized error response envelope."""
    err = {
        "code": code,
        "message": message,
    }
    if details is not None:
        err["details"] = details
    
    body = {
        "success": False,
        "error": err,
        "request_id": request_id or uuid.uuid4().hex[:8],
    }
    return JSONResponse(status_code=status_code, content=body)

# ─── Request ID Middleware ────────────────────────────────────────────────────
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add unique request ID for tracing across logs and responses."""
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
    request.state.request_id = request_id
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# ─── Exception Handlers ───────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)
    return error_response(
        code=ErrorCode.VALIDATION_ERROR,
        message="Request validation failed",
        status_code=422,
        details=exc.errors(),
        request_id=request_id
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", None)
    return error_response(
        code=f"HTTP_{exc.status_code}",
        message=str(exc.detail),
        status_code=exc.status_code,
        request_id=request_id
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    log.exception(f"Unhandled error on {request.method} {request.url.path}")
    return error_response(
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred",
        status_code=500,
        request_id=request_id
    )

# ─── Startup & Health ─────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")

@app.get("/health")
def health_check():
    """Lightweight health probe with database connectivity check."""
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        db.close()
        return success_response(
            data={
                "status": "healthy",
                "database": "connected",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    except Exception as e:
        return error_response(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message="Database connection failed",
            status_code=503
        )

# ─── Validation Helpers ───────────────────────────────────────────────────────
def _validate_address(address: str) -> str:
    """Validates and returns cleaned Ethereum address."""
    address = address.strip()
    if not ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=400,
            detail="Must be a 42-character 0x Ethereum address"
        )
    return address

def _validate_market_id(market_id: str) -> str:
    """Validates and returns cleaned market ID."""
    market_id = market_id.strip()
    if not MARKET_ID_RE.match(market_id):
        raise HTTPException(
            status_code=400,
            detail="Market ID must be numeric"
        )
    return market_id

# ─── Market Enrichment ────────────────────────────────────────────────────────
def _enrich_market(m: dict) -> dict | None:
    """Fetches CLOB history for a single market and attaches shift + current_price."""
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

# ─── Market Endpoints ─────────────────────────────────────────────────────────
@app.get("/markets")
def search_markets(
    limit: int = 50,
    search: str = None,
    vol_min: float = Query(default=None, ge=0, description="Minimum volume (inclusive)"),
    vol_max: float = Query(default=None, ge=0, description="Maximum volume (inclusive)"),
):
    """Search markets with volume filtering and CLOB enrichment."""
    if search is not None and len(search) > MAX_SEARCH_LEN:
        return error_response(
            code=ErrorCode.SEARCH_TOO_LONG,
            message=f"Search query too long (max {MAX_SEARCH_LEN} chars)",
            status_code=400
        )

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
    
    return success_response(
        data=enriched[:limit],
        message=f"Found {len(enriched)} markets matching criteria"
    )

# ─── Watchlist Endpoints ──────────────────────────────────────────────────────
@app.get("/watchlist")
def get_watchlist():
    db = get_db()
    try:
        res = db.execute("SELECT * FROM watch_list ORDER BY added_at DESC").fetchall()
        watchlist = [dict(r) for r in res]
        return success_response(data=watchlist)
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
        return success_response(
            data={"address": target.address, "label": target.label},
            message="Target added to watchlist"
        )
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed" in str(e):
            return error_response(
                code=ErrorCode.DUPLICATE_ENTRY,
                message="This address is already in your watchlist",
                status_code=409
            )
        log.error(f"DB Integrity Error: {e}")
        return error_response(
            code=ErrorCode.DATABASE_ERROR,
            message="Database constraint violation",
            status_code=400
        )
    except Exception as e:
        log.error(f"Failed to add target: {e}")
        return error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to add target to watchlist",
            status_code=500
        )
    finally:
        db.close()

@app.delete("/watchlist/{address}")
def remove_from_watchlist(address: str):
    address = _validate_address(address)
    db = get_db()
    try:
        result = db.execute("DELETE FROM watch_list WHERE address = ?", (address,))
        db.commit()
        
        if result.rowcount == 0:
            return error_response(
                code=ErrorCode.NOT_FOUND,
                message="Address not found in watchlist",
                status_code=404
            )
        
        return success_response(
            data={"address": address, "deleted": True},
            message="Target removed successfully"
        )
    except Exception as e:
        log.error(f"Failed to delete target {address}: {e}")
        return error_response(
            code=ErrorCode.DATABASE_ERROR,
            message="Database error during deletion",
            status_code=500
        )
    finally:
        db.close()

# ─── Wallet & Analysis Endpoints ──────────────────────────────────────────────
@app.get("/wallets/{address}/unmask")
def unmask_wallet(address: str):
    address = _validate_address(address)
    real_owner = unmask_proxy(address)
    return success_response(
        data={"proxy": address, "real_owner": real_owner}
    )

@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis(
    market_id: str,
    research: bool = Query(default=False, description="Enable Tavily web research")
):
    market_id = _validate_market_id(market_id)
    
    db = get_db()
    try:
        market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        if not market:
            return error_response(
                code=ErrorCode.NOT_FOUND,
                message="Market not found",
                status_code=404
            )

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
        
        return success_response(
            data={
                "analysis": analysis,
                "research_used": research,
                "market_id": market_id
            }
        )
    except Exception as e:
        log.error(f"LLM Analysis failed for {market_id}: {e}")
        return error_response(
            code=ErrorCode.ANALYSIS_FAILED,
            message="AI analysis failed",
            status_code=500
        )
    finally:
        db.close()

@app.get("/wallets/{address}/profile")
def profile_wallet_api(address: str):
    address = _validate_address(address)
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

        return success_response(
            data={
                "profile": profile,
                "real_owner": real_owner,
                "trade_count": len(trades_data)
            }
        )
    except Exception as e:
        log.error(f"Profiling failed: {e}")
        return error_response(
            code=ErrorCode.PROFILING_FAILED,
            message="AI Profiling failed",
            status_code=500
        )
```

Now the updated frontend JavaScript:

```javascript
// static/app.js - Standardized Response Handling

// ─── State ────────────────────────────────────────────────────────────────────
let hasLoadedOnce = false;
let refreshTimer = null;
let refreshCountdown = 0;
const REFRESH_INTERVAL = 300; // 5 minutes

// ─── API Response Handler ─────────────────────────────────────────────────────
async function apiFetch(url, options = {}) {
    /**
     * Wrapper around fetch that handles the standardized response envelope.
     * Returns { ok, data, message, error, requestId }
     */
    try {
        const res = await fetch(url, options);
        const body = await res.json();
        
        if (body.success) {
            return {
                ok: true,
                data: body.data ?? null,
                message: body.message || "OK",
                requestId: body.request_id || null,
            };
        } else {
            return {
                ok: false,
                data: null,
                message: body.error?.message || "Unknown error",
                errorCode: body.error?.code || "UNKNOWN",
                details: body.error?.details || null,
                requestId: body.request_id || null,
            };
        }
    } catch (e) {
        return {
            ok: false,
            data: null,
            message: `Network error: ${e.message}`,
            errorCode: "NETWORK_ERROR",
        };
    }
}

// ─── Toast Notifications ──────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-emerald-900/95 border-emerald-700' :
                   type === 'error' ? 'bg-red-900/95 border-red-700' :
                   'bg-gray-900/95 border-gray-700';
    const icon = type === 'success' ? '✓' : type === 'error' ? '⚠' : 'ℹ';
    
    toast.className = `fixed bottom-4 right-4 px-4 py-3 rounded-lg text-sm font-medium z-50 shadow-lg border ${bgColor} text-gray-100`;
    toast.innerHTML = `<span class="mr-2">${icon}</span>${message}`;
    toast.style.animation = 'slideIn 0.3s ease';
    
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Add toast animations
const toastStyle = document.createElement('style');
toastStyle.textContent = `
    @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes slideOut { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
`;
document.head.appendChild(toastStyle);

// ─── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadWatchlist();
    initResearchToggle();

    document.getElementById('searchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const q = e.target.value.trim();
            loadMarkets(q);
        }
    });
});

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

// ─── UI States ────────────────────────────────────────────────────────────────
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

function showErrorState(message, errorCode = '') {
    const table = document.getElementById('marketsTable');
    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-3xl">⚠️</div>
                    <div class="text-red-400 text-sm">${errorCode ? `[${errorCode}] ` : ''}${message}</div>
                    <div class="text-gray-600 text-xs">Check <code>analyzer.log</code> for details.</div>
                    <button onclick="loadMarkets('')" class="mt-2 text-xs text-polysint underline">Retry</button>
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

        const url = `/markets${params.toString() ? '?' + params.toString() : ''}`;
        const result = await apiFetch(url);
        
        if (!result.ok) {
            throw new Error(result.message);
        }
        
        const markets = result.data || [];
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
        console.error('Market load error:', e);
        showErrorState(e.message, e.errorCode || '');
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
        const url = `/markets/${marketId}/ai-analysis?research=${useResearch}`;
        const result = await apiFetch(url);
        
        if (!result.ok) {
            throw new Error(result.message);
        }
        
        const analysis = result.data.analysis;
        const formatted = analysis
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `<div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                ⚠️ ${e.message}<br>
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
        const result = await apiFetch(`/wallets/${address}/profile`);

        if (!result.ok) {
            throw new Error(result.message);
        }
        
        const data = result.data;
        const formatted = data.profile
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `
            <div class="mb-4 p-3 bg-gray-900 rounded border border-gray-700 font-mono text-xs text-gray-400 space-y-1">
                <div><span class="text-gray-600">Proxy:</span> ${address}</div>
                <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${data.real_owner}</span></div>
                <div><span class="text-gray-600">Trades analyzed:</span> ${data.trade_count}</div>
            </div>
            <div class="p-3 border-l-4 border-blue-500 bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `<div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">⚠️ ${e.message}</div>`;
    }
}

async function unmaskWallet(address) {
    const btn = document.getElementById(`btn-${address}`);
    const realDiv = document.getElementById(`real-${address}`);

    btn.disabled = true;
    btn.innerHTML = '<span class="animate-pulse">Scanning...</span>';
    btn.classList.add("opacity-50", "cursor-not-allowed");

    try {
        const result = await apiFetch(`/wallets/${address}/unmask`);

        if (!result.ok) {
            throw new Error(result.message);
        }
        
        const data = result.data;
        realDiv.classList.remove("hidden");
        realDiv.innerHTML = `EOA: <span class="text-polysint">${data.real_owner}</span>`;
        btn.textContent = "✓ Unmasked";
        btn.classList.remove("border-gray-600", "text-gray-300", "hover:bg-gray-700");
        btn.classList.add("bg-gray-700", "text-gray-500", "border-transparent", "cursor-default");
        showToast('Wallet unmasked successfully', 'success');
    } catch (e) {
        btn.disabled = false;
        btn.textContent = "Retry";
        btn.classList.remove("opacity-50", "cursor-not-allowed");
        showToast(e.message, 'error');
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
        const result = await apiFetch('/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address, label })
        });

        if (result.ok) {
            addressInput.value = '';
            labelInput.value = '';
            clearInlineError('addError');
            loadWatchlist();
            showToast(`Added ${label} to watchlist`, 'success');
        } else {
            showInlineError('addError', result.message);
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
        const result = await apiFetch('/watchlist');
        
        if (!result.ok) {
            throw new Error(result.message);
        }
        
        const watchlist = result.data || [];

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
                        <button onclick="profileEntity('${w.address}', '${w.label.replace(/'/g, "\\'")}')"
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
        table.innerHTML = `<tr><td class="text-center py-8 text-red-400 text-sm">${e.message}</td></tr>`;
    }
}

async function deleteTarget(address) {
    if (!confirm("Stop tracking this entity?")) return;
    try {
        const result = await apiFetch(`/watchlist/${address}`, { method: 'DELETE' });
        
        if (result.ok) {
            loadWatchlist();
            showToast('Target removed from watchlist', 'success');
        } else {
            showToast(result.message, 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('Network error', 'error');
    }
}

// ─── Modal ────────────────────────────────────────────────────────────────────
function closeModal() {
    document.getElementById('aiModal').classList.add('hidden');
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('aiModal');
    if (e.target === modal) closeModal();
});
```

This implementation provides:

1. **Standardized Response Envelope**:
   - Success: `{"success": true, "data": ..., "message": "...", "request_id": "..."}`
   - Error: `{"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}`

2. **Request ID Tracing**:
   - Every request gets a unique ID for debugging
   - Propagated via X-Request-ID header
   - Included in all responses

3. **Centralized Error Codes**:
   - Machine-readable error codes for consistent error handling
   - Clear categorization of error types

4. **Global Exception Handlers**:
   - Validation errors (422)
   - HTTP exceptions
   - Unhandled exceptions (500)

5. **Health Check Endpoint**:
   - `/health` for monitoring
   - Database connectivity check

6. **Frontend Wrapper**:
   - `apiFetch()` for consistent response handling
   - Toast notifications for user feedback
   - Clean error state management

7. **Clean Validation**:
   - Address and market ID validation
   - Proper error responses for invalid inputs

The implementation maintains all existing functionality while adding robust error handling and debugging capabilities.
