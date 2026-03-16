Here's the enhanced implementation with granular volume filtering for the `/markets` API:

## Updated `api.py`

```python
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
from pydantic import BaseModel, field_validator
from enum import Enum
from typing import Optional, List, Dict, Any
import re
import requests
import json

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

# Tuning parameters
MIN_VOLUME_FOR_CLOB = 5000
CLOB_WORKERS = 20
MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
MARKET_ID_RE = re.compile(r'^[0-9]+$')

# Volume tier presets
VOLUME_TIERS = {
    "micro": {"min": 0, "max": 10_000, "label": "Micro"},
    "small": {"min": 10_000, "max": 50_000, "label": "Small"},
    "mid": {"min": 50_000, "max": 250_000, "label": "Mid"},
    "large": {"min": 250_000, "max": 1_000_000, "label": "Large"},
    "mega": {"min": 1_000_000, "max": None, "label": "Mega"},
}

# Surging detection thresholds
SURGE_ABSOLUTE_THRESHOLD = 5_000    # $5K delta triggers surging
ANOMALY_SHIFT_THRESHOLD = 10.0      # 10% price shift

class SortField(str, Enum):
    shift = "shift"
    volume = "volume"
    price = "price"
    delta = "delta"                 # Volume delta
    shift_volume = "shift_volume"   # Combined: 60% shift + 40% delta

class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"

class VolumeTier(str, Enum):
    micro = "micro"
    small = "small"
    mid = "mid"
    large = "large"
    mega = "mega"


def classify_volume_tier(volume: float) -> dict:
    """Returns tier info dict for a given volume amount."""
    vol = volume or 0
    for key, tier in VOLUME_TIERS.items():
        upper = tier["max"] if tier["max"] is not None else float("inf")
        if tier["min"] <= vol < upper:
            return {"key": key, "label": tier["label"]}
    return {"key": "micro", "label": "Micro"}


def _batch_compute_volume_deltas(market_ids: List[str]) -> Dict[str, float]:
    """
    Computes volume deltas for multiple markets in a single query.
    Uses ROW_NUMBER() window function — O(1) DB round-trips.
    Returns dict of market_id -> absolute volume delta.
    """
    if not market_ids:
        return {}

    try:
        db = get_db()
        placeholders = ','.join(['?'] * len(market_ids))
        query = f"""
            WITH ranked AS (
                SELECT
                    market_id,
                    volume,
                    ROW_NUMBER() OVER (
                        PARTITION BY market_id
                        ORDER BY timestamp DESC
                    ) AS rn
                FROM snapshots
                WHERE market_id IN ({placeholders})
            )
            SELECT
                market_id,
                MAX(CASE WHEN rn = 1 THEN volume END) AS latest,
                MAX(CASE WHEN rn = 2 THEN volume END) AS previous
            FROM ranked
            WHERE rn <= 2
            GROUP BY market_id
            HAVING COUNT(*) >= 2
        """
        rows = db.execute(query, market_ids).fetchall()
        db.close()

        deltas = {}
        for row in rows:
            latest = row['latest']
            previous = row['previous']
            if latest is not None and previous is not None:
                deltas[row['market_id']] = abs(float(latest) - float(previous))
        return deltas
    except Exception as e:
        log.error(f"Batch volume delta computation failed: {e}")
        return {}


def _validate_address(address: str) -> str:
    if not ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=400,
            detail="Invalid address. Must be a 42-character 0x Ethereum address."
        )
    return address


def _enrich_market(m: dict, include_settled: bool = False) -> Optional[dict]:
    """Fetches CLOB history, attaches shift, current_price, volume_tier."""
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
                    m['current_price'] = float(prices[0])
        except Exception:
            pass

    if not include_settled and m['current_price'] is not None:
        if m['current_price'] > 0.98 or m['current_price'] < 0.02:
            return None

    m['volume_tier'] = classify_volume_tier(m.get('volume', 0))
    return m


def _search_markets_core(
    limit: int = 50,
    search: Optional[str] = None,
    vol_min: Optional[float] = None,
    vol_max: Optional[float] = None,
    vol_tier: Optional[VolumeTier] = None,
    vol_delta_min: Optional[float] = None,
    sort_by: SortField = SortField.shift,
    sort_order: SortOrder = SortOrder.desc,
    include_settled: bool = False,
    anomaly_only: bool = False,
    surging_only: bool = False,
) -> List[Dict]:
    """Core search logic shared by all market endpoints."""
    # Volume tier overrides explicit min/max
    if vol_tier is not None:
        tier = VOLUME_TIERS[vol_tier.value]
        vol_min = tier["min"]
        vol_max = tier["max"]

    # Database query
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

    # Volume pre-filter
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

    # Enrich with CLOB data
    enriched = []
    with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as executor:
        futures = {executor.submit(_enrich_market, m, include_settled): m for m in candidates}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    enriched.append(result)
            except Exception as e:
                log.error(f"Market enrichment failed: {e}")

    # Batch volume delta computation
    market_ids = [m['id'] for m in enriched]
    deltas = _batch_compute_volume_deltas(market_ids)
    for m in enriched:
        delta = deltas.get(m['id'], 0.0)
        m['volume_delta'] = delta
        m['is_surging'] = delta >= SURGE_ABSOLUTE_THRESHOLD
        m['is_anomaly'] = abs(m.get('shift', 0)) >= ANOMALY_SHIFT_THRESHOLD

    # Apply post-enrichment filters
    if anomaly_only:
        enriched = [m for m in enriched if m['is_anomaly']]
    if surging_only:
        enriched = [m for m in enriched if m['volume_delta'] > 0]
    if vol_delta_min is not None:
        enriched = [m for m in enriched if m['volume_delta'] >= vol_delta_min]

    # Sorting
    reverse = (sort_order == SortOrder.desc)

    if sort_by == SortField.shift:
        enriched.sort(key=lambda x: abs(x.get('shift', 0.0)), reverse=reverse)
    elif sort_by == SortField.volume:
        enriched.sort(key=lambda x: x.get('volume') or 0.0, reverse=reverse)
    elif sort_by == SortField.price:
        enriched.sort(
            key=lambda x: x.get('current_price') if x.get('current_price') is not None else -1,
            reverse=reverse,
        )
    elif sort_by == SortField.delta:
        enriched.sort(key=lambda x: x.get('volume_delta', 0.0), reverse=reverse)
    elif sort_by == SortField.shift_volume:
        if enriched:
            max_shift = max((abs(m.get('shift', 0)) for m in enriched), default=1) or 1
            max_delta = max((m.get('volume_delta', 0) for m in enriched), default=1) or 1
            enriched.sort(
                key=lambda m: (abs(m.get('shift', 0)) / max_shift * 0.6) +
                              (m.get('volume_delta', 0) / max_delta * 0.4),
                reverse=reverse
            )

    return enriched


# ─── App Setup ────────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")


# ─── Markets Endpoints ────────────────────────────────────────────────────────

@app.get("/markets")
def search_markets(
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    search: Optional[str] = Query(default=None),
    vol_min: Optional[float] = Query(default=None, ge=0),
    vol_max: Optional[float] = Query(default=None, ge=0),
    vol_tier: Optional[VolumeTier] = Query(default=None),
    vol_delta_min: Optional[float] = Query(default=None, ge=0),
    sort_by: SortField = Query(default=SortField.shift),
    sort_order: SortOrder = Query(default=SortOrder.desc),
    include_settled: bool = Query(default=False),
):
    """
    Search and filter prediction markets with granular volume controls.

    Volume tiers: micro ($0-$10K), small ($10K-$50K), mid ($50K-$250K),
    large ($250K-$1M), mega ($1M+).

    Sort fields: shift, volume, price, delta (volume delta),
    shift_volume (combined 60% shift + 40% delta).
    """
    if search is not None:
        search = search.strip()
        if len(search) > MAX_SEARCH_LEN:
            raise HTTPException(status_code=400, detail=f"Search query too long (max {MAX_SEARCH_LEN} chars).")
        if not search:
            search = None

    if vol_tier is None and vol_min is not None and vol_max is not None and vol_min > vol_max:
        raise HTTPException(status_code=400, detail="vol_min cannot exceed vol_max.")

    results = _search_markets_core(
        limit=limit * page, search=search, vol_min=vol_min, vol_max=vol_max,
        vol_tier=vol_tier, vol_delta_min=vol_delta_min, sort_by=sort_by,
        sort_order=sort_order, include_settled=include_settled,
    )

    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated = results[start_idx:end_idx]

    return {
        "data": paginated,
        "meta": {
            "page": page,
            "limit": limit,
            "total_results": len(results),
            "has_more": len(results) > page * limit,
            "total_pages": max(1, (len(results) + limit - 1) // limit),
        }
    }


@app.get("/markets/anomalies")
def get_anomaly_markets(
    limit: int = Query(default=20, ge=1, le=100),
    sort_order: SortOrder = Query(default=SortOrder.desc),
):
    """Quick endpoint: markets with ≥10% price shift."""
    results = _search_markets_core(
        limit=limit, sort_by=SortField.shift, sort_order=sort_order,
        anomaly_only=True,
    )
    return {"data": results, "meta": {"type": "anomalies", "count": len(results)}}


@app.get("/markets/surging")
def get_surging_markets(
    limit: int = Query(default=20, ge=1, le=100),
    min_delta: float = Query(default=1000, ge=0),
    sort_order: SortOrder = Query(default=SortOrder.desc),
):
    """Quick endpoint: markets with surging volume interest."""
    results = _search_markets_core(
        limit=limit, sort_by=SortField.delta, sort_order=sort_order,
        vol_delta_min=min_delta, surging_only=True,
    )
    return {"data": results, "meta": {"type": "surging", "count": len(results)}}


@app.get("/markets/filters")
def get_filter_presets():
    """Returns available volume tiers, sort options, and filter metadata."""
    return {
        "volume_tiers": {
            name: {
                "min": t["min"],
                "max": t["max"],
                "label": t["label"],
                "description": f"${t['min']:,} – ${t['max']:,}" if t["max"] else f"${t['min']:,}+",
            }
            for name, t in VOLUME_TIERS.items()
        },
        "sort_fields": [
            {"value": f.value, "label": f.value.replace("_", " ").title()}
            for f in SortField
        ],
        "sort_orders": [
            {"value": "desc", "label": "Highest First"},
            {"value": "asc", "label": "Lowest First"},
        ],
        "thresholds": {
            "anomaly_shift": ANOMALY_SHIFT_THRESHOLD,
            "surge_absolute": SURGE_ABSOLUTE_THRESHOLD,
            "min_volume": MIN_VOLUME_FOR_CLOB,
        },
        "defaults": {
            "limit": 50,
            "sort_by": "shift",
            "sort_order": "desc",
            "include_settled": False,
        },
        "convenience_endpoints": [
            {"path": "/markets/anomalies", "description": "Markets with ≥10% price shift"},
            {"path": "/markets/surging", "description": "Markets with rising volume interest"},
        ],
    }


# ─── Existing Endpoints (unchanged) ──────────────────────────────────────────

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
def get_ai_analysis(market_id: str, research: bool = Query(default=False)):
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
            market['question'], price_history, market['volume'], use_research=research
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

## Updated `static/app.js`

```javascript
// ─── State ────────────────────────────────────────────────────────────────────
let hasLoadedOnce = false;
let refreshTimer = null;
let refreshCountdown = 0;
let lastRequestTime = 0;
let currentPage = 1;
let currentSearch = '';
const REFRESH_INTERVAL = 300;
const DEBOUNCE_MS = 300;
const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadWatchlist();
    initResearchToggle();
    initKeyboardShortcuts();
    loadFilterState();

    document.getElementById('searchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            currentPage = 1;
            applyFilters();
        }
    });

    ['volTier', 'volMin', 'volMax', 'volDelta', 'sortBy', 'sortOrder', 'includeSettled'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', saveFilterState);
    });

    showIdleState();
});

// ─── Filter Persistence ───────────────────────────────────────────────────────
function saveFilterState() {
    const state = {
        volTier: document.getElementById('volTier')?.value || '',
        volMin: document.getElementById('volMin')?.value || '',
        volMax: document.getElementById('volMax')?.value || '',
        volDelta: document.getElementById('volDelta')?.value || '',
        sortBy: document.getElementById('sortBy')?.value || 'shift',
        sortOrder: document.getElementById('sortOrder')?.value || 'desc',
        includeSettled: document.getElementById('includeSettled')?.checked || false,
    };
    localStorage.setItem('polysint_filters', JSON.stringify(state));
}

function loadFilterState() {
    try {
        const saved = localStorage.getItem('polysint_filters');
        if (!saved) return;
        const state = JSON.parse(saved);
        Object.keys(state).forEach(key => {
            const el = document.getElementById(key);
            if (!el) return;
            if (key === 'includeSettled') el.checked = state[key];
            else el.value = state[key];
        });
    } catch (e) { console.warn('Failed to load filter state:', e); }
}

function clearAllFilters() {
    ['volTier', 'volMin', 'volMax', 'volDelta'].forEach(id => setVal(id, ''));
    setVal('sortBy', 'shift');
    setVal('sortOrder', 'desc');
    const cb = document.getElementById('includeSettled');
    if (cb) cb.checked = false;
    document.getElementById('searchInput').value = '';
    currentPage = 1;
    saveFilterState();
    showIdleState();
}

function setVal(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
}

// ─── Research Toggle ──────────────────────────────────────────────────────────
function initResearchToggle() {
    const saved = localStorage.getItem('polysint_research_enabled');
    const enabled = saved === 'true';
    const toggle = document.getElementById('researchToggle');
    if (toggle) toggle.checked = enabled;
    updateToggleLabel(enabled);
}

function onResearchToggle() {
    const enabled = document.getElementById('researchToggle')?.checked || false;
    localStorage.setItem('polysint_research_enabled', enabled);
    updateToggleLabel(enabled);
}

function updateToggleLabel(enabled) {
    const label = document.getElementById('researchToggleLabel');
    if (!label) return;
    label.textContent = enabled ? 'Web Research: ON' : 'Web Research: OFF';
    label.className = enabled ? 'text-xs text-emerald-400 font-mono' : 'text-xs text-gray-500 font-mono';
}

function isResearchEnabled() {
    return document.getElementById('researchToggle')?.checked || false;
}

// ─── Keyboard Shortcuts ───────────────────────────────────────────────────────
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            document.getElementById('searchInput')?.focus();
            document.getElementById('searchInput')?.select();
        }
        if (e.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
            e.preventDefault();
            document.getElementById('searchInput')?.focus();
        }
        if (e.key === 'Escape') {
            const modal = document.getElementById('aiModal');
            if (modal && !modal.classList.contains('hidden')) closeModal();
            else document.activeElement?.blur();
        }
    });
}

// ─── Quick Filters ────────────────────────────────────────────────────────────
function applyFilters() {
    currentSearch = document.getElementById('searchInput').value.trim();
    loadMarkets(currentSearch);
}

function applyQuickFilter(type) {
    clearAllFilters();
    switch (type) {
        case 'anomalies': loadAnomalies(); return;
        case 'surging': loadSurging(); return;
        case 'mega': setVal('volTier', 'mega'); break;
        case 'rising': setVal('sortBy', 'shift'); setVal('sortOrder', 'desc'); break;
    }
    saveFilterState();
    loadMarkets('');
}

async function loadAnomalies(silent = false) {
    if (!silent) showLoadingState('Scanning for anomalies...');
    try {
        const res = await fetch('/markets/anomalies?limit=30');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const response = await res.json();
        const markets = response.data || response;
        updateCounter(markets.length, 'anomalies');
        displayMarkets(markets, 'anomalies');
        updatePaginationControls({ has_more: false, page: 1 });
        startAutoRefresh('');
    } catch (e) {
        console.error('loadAnomalies failed:', e);
        showErrorState('anomalies');
    }
}

async function loadSurging(silent = false) {
    if (!silent) showLoadingState('Detecting volume surges...');
    try {
        const res = await fetch('/markets/surging?limit=30&min_delta=2000');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const response = await res.json();
        const markets = response.data || response;
        updateCounter(markets.length, 'surging');
        displayMarkets(markets, 'surging');
        updatePaginationControls({ has_more: false, page: 1 });
        startAutoRefresh('');
    } catch (e) {
        console.error('loadSurging failed:', e);
        showErrorState('surging');
    }
}

// ─── UI States ────────────────────────────────────────────────────────────────
function showIdleState() {
    const table = document.getElementById('marketsTable');
    const counter = document.getElementById('marketCounter');
    if (counter) counter.textContent = '';
    if (!table) return;

    table.innerHTML = `
        <tr style="animation:none;opacity:1;">
            <td colspan="4" class="py-24 text-center">
                <div class="flex flex-col items-center space-y-5">
                    <div class="text-6xl opacity-25">🕵️‍♂️</div>
                    <div class="text-gray-400 font-medium text-lg">Intelligence Awaiting Orders</div>
                    <div class="text-gray-500 text-sm max-w-md">Search for a market, pick a volume tier, or use quick filters below.</div>
                    <div class="flex flex-wrap gap-2 justify-center mt-2">
                        <button onclick="applyQuickFilter('anomalies')" class="quick-filter-btn bg-red-500/10 text-red-400 border-red-500/30 hover:bg-red-500/20">⚡ Anomalies</button>
                        <button onclick="applyQuickFilter('surging')" class="quick-filter-btn bg-cyan-500/10 text-cyan-400 border-cyan-500/30 hover:bg-cyan-500/20">📈 Surging</button>
                        <button onclick="applyQuickFilter('mega')" class="quick-filter-btn bg-purple-500/10 text-purple-400 border-purple-500/30 hover:bg-purple-500/20">🐋 Mega</button>
                        <button onclick="clearAllFilters(); applyFilters();" class="quick-filter-btn bg-polysint/10 text-polysint border-polysint/30 hover:bg-polysint hover:text-gray-900 font-bold">↵ Load All</button>
                    </div>
                    <div class="text-gray-700 text-[10px] mt-2">Press <kbd class="kbd">/</kbd> or <kbd class="kbd">⌘K</kbd> to search</div>
                </div>
            </td>
        </tr>`;
}

function showLoadingState(message = 'Scanning intelligence feeds...') {
    const table = document.getElementById('marketsTable');
    if (!table) return;
    table.innerHTML = `
        <tr style="animation:none;opacity:1;">
            <td colspan="4" class="py-24 text-center">
                <div class="flex flex-col items-center space-y-4">
                    <div class="loading-dots">
                        <div class="dot"></div><div class="dot"></div><div class="dot"></div>
                    </div>
                    <div class="text-gray-400 text-sm">${escapeHtml(message)}</div>
                </div>
            </td>
        </tr>`;
}

function showEmptySearchState(query) {
    const table = document.getElementById('marketsTable');
    if (!table) return;
    table.innerHTML = `
        <tr style="animation:none;opacity:1;">
            <td colspan="4" class="py-24 text-center">
                <div class="flex flex-col items-center space-y-4">
                    <div class="text-5xl opacity-20">🔍</div>
                    <div class="text-gray-400 text-sm">No markets found for <span class="text-white font-mono">"${escapeHtml(query)}"</span></div>
                    <div class="text-gray-500 text-xs max-w-xs">Try different filters, broaden your volume range, or clear all filters.</div>
                    <button onclick="clearAllFilters()" class="mt-2 text-xs text-polysint hover:text-emerald-400 transition-colors">Clear all filters</button>
                </div>
            </td>
        </tr>`;
}

function showErrorState(context = 'markets') {
    const table = document.getElementById('marketsTable');
    if (!table) return;
    table.innerHTML = `
        <tr style="animation:none;opacity:1;"><td colspan="4" class="text-center py-16">
            <div class="flex flex-col items-center space-y-3">
                <div class="text-4xl opacity-40">⚠️</div>
                <div class="text-red-400 text-sm font-medium">Failed to load ${escapeHtml(context)}</div>
                <div class="text-gray-500 text-xs">Is the backend running? Check <code class="text-gray-400 bg-gray-800 px-1 py-0.5 rounded">analyzer.log</code></div>
                <button onclick="applyFilters()" class="mt-2 text-xs text-polysint hover:text-emerald-400 underline transition-colors">Retry</button>
            </div>
        </td></tr>`;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

// ─── Counter ──────────────────────────────────────────────────────────────────
function updateCounter(count, mode) {
    const el = document.getElementById('marketCounter');
    if (!el) return;
    if (mode === 'anomalies') el.textContent = `${count} anomalies (≥10% shift)`;
    else if (mode === 'surging') el.textContent = `${count} surging markets (volume delta)`;
    else el.textContent = `${count} markets`;
}

// ─── Auto-Refresh ─────────────────────────────────────────────────────────────
function startAutoRefresh(query) {
    clearInterval(refreshTimer);
    refreshCountdown = REFRESH_INTERVAL;
    updateRefreshUI();
    refreshTimer = setInterval(() => {
        refreshCountdown -= 1;
        updateRefreshUI();
        if (refreshCountdown <= 0) loadMarkets(query, true);
    }, 1000);
}

function updateRefreshUI() {
    const el = document.getElementById('refreshCountdown');
    if (!el) return;
    if (refreshCountdown > 0) {
        const mins = Math.floor(refreshCountdown / 60);
        const secs = refreshCountdown % 60;
        el.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
    } else {
        el.textContent = 'Refreshing...';
    }
}

// ─── Display Markets ──────────────────────────────────────────────────────────
function displayMarkets(markets, context = 'search') {
    const table = document.getElementById('marketsTable');
    if (!table) return;
    table.innerHTML = '';

    if (!markets || markets.length === 0) {
        showEmptySearchState(context || 'current filters');
        return;
    }

    markets.forEach((m, i) => {
        const shift = m.shift || 0;
        const absShift = Math.abs(shift);
        const shiftColor = shift > 0 ? 'text-emerald-400' : (shift < 0 ? 'text-red-400' : 'text-gray-500');
        const shiftIcon = shift > 0 ? '↑' : (shift < 0 ? '↓' : '–');
        const isAnomaly = m.is_anomaly || absShift >= 10.0;
        const isWatch = absShift >= 5.0 && absShift < 10.0;
        const isSurging = m.is_surging || (m.volume_delta || 0) >= 5000;

        const currentOdds = m.current_price != null ? `${Math.round(m.current_price * 100)}%` : 'N/A';

        const volDelta = m.volume_delta || 0;
        const volDeltaHtml = volDelta > 0
            ? `<div class="text-[10px] font-normal mt-0.5 ${isSurging ? 'text-cyan-400 font-semibold' : 'text-cyan-500/50'}">Δ $${Math.round(volDelta).toLocaleString()}</div>`
            : '';

        const tier = m.volume_tier;
        const tierBadge = tier
            ? `<span class="badge tier-badge-${tier.key}">${getTierEmoji(tier.key)} ${tier.label}</span>`
            : '';

        let statusBadges = '';
        if (isAnomaly) statusBadges += `<span class="badge badge-anomaly animate-pulse">⚡ ANOMALY</span>`;
        if (isWatch) statusBadges += `<span class="badge badge-watch">⚠ WATCH</span>`;
        if (isSurging) statusBadges += `<span class="badge badge-surging animate-pulse">🔥 SURGING</span>`;

        const rowBg = isAnomaly ? 'row-anomaly' : isSurging ? 'row-surging' : '';

        const tr = document.createElement('tr');
        tr.className = `market-row ${rowBg}`;
        tr.style.animationDelay = `${i * 25}ms`;

        tr.innerHTML = `
            <td class="px-4 py-3.5">
                <div class="font-medium text-gray-200 text-sm leading-snug">${escapeHtml(m.question)}</div>
                <div class="flex items-center flex-wrap gap-1.5 mt-1.5">
                    <span class="text-[11px] text-blue-400/80 font-mono">Odds: ${currentOdds}</span>
                    ${tierBadge}
                    ${statusBadges}
                </div>
            </td>
            <td class="px-4 py-3.5 font-mono ${shiftColor} font-semibold text-sm whitespace-nowrap">
                ${shiftIcon} ${absShift.toFixed(1)}%
                <div class="text-[10px] text-gray-600 font-normal mt-0.5">24h shift</div>
            </td>
            <td class="px-4 py-3.5 text-gray-300 text-sm font-mono whitespace-nowrap">
                ${formatter.format(m.volume || 0)}
                ${volDeltaHtml}
            </td>
            <td class="px-4 py-3.5 text-right">
                <button onclick="analyzeMarket('${m.id}')" class="analyze-btn">🤖 Analyze</button>
            </td>`;
        table.appendChild(tr);
    });
}

function getTierEmoji(key) {
    return { micro: '🔬', small: '📦', mid: '📊', large: '🦊', mega: '🐋' }[key] || '';
}

// ─── Core: Load Markets ───────────────────────────────────────────────────────
async function loadMarkets(searchQuery = '', silent = false) {
    const now = Date.now();
    if (!silent && now - lastRequestTime < DEBOUNCE_MS) return;
    lastRequestTime = now;

    if (!silent) showLoadingState();

    const volTier = document.getElementById('volTier')?.value.trim();
    const volMin = document.getElementById('volMin')?.value.trim();
    const volMax = document.getElementById('volMax')?.value.trim();
    const volDelta = document.getElementById('volDelta')?.value.trim();
    const sortBy = document.getElementById('sortBy')?.value || 'shift';
    const sortOrder = document.getElementById('sortOrder')?.value || 'desc';
    const includeSettled = document.getElementById('includeSettled')?.checked || false;

    try {
        const params = new URLSearchParams();
        if (searchQuery) params.set('search', searchQuery);
        params.set('page', currentPage);
        params.set('limit', 50);

        if (volTier) params.set('vol_tier', volTier);
        else {
            if (volMin !== '') params.set('vol_min', volMin);
            if (volMax !== '') params.set('vol_max', volMax);
        }

        if (volDelta !== '') params.set('vol_delta_min', volDelta);
        params.set('sort_by', sortBy);
        params.set('sort_order', sortOrder);
        if (includeSettled) params.set('include_settled', 'true');

        const res = await fetch(`/markets?${params.toString()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const response = await res.json();
        const markets = response.data;
        const meta = response.meta;

        hasLoadedOnce = true;

        const counter = document.getElementById('marketCounter');
        if (counter) {
            const parts = [`${meta.total_results} markets`, `Page ${meta.page}/${meta.total_pages}`];
            if (volTier) parts.push(`tier: ${volTier}`);
            if (volDelta !== '') parts.push(`volΔ ≥ $${Number(volDelta).toLocaleString()}`);
            counter.textContent = parts.join(' · ');
        }

        displayMarkets(markets, searchQuery || 'all markets');
        startAutoRefresh(searchQuery);
        updatePaginationControls(meta);

    } catch (e) {
        console.error('loadMarkets error:', e);
        showErrorState();
    }
}

function updatePaginationControls(meta) {
    const container = document.getElementById('paginationControls');
    if (!container) return;

    if (!meta.has_more && meta.page <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '<div class="flex items-center gap-2">';
    if (meta.page > 1) {
        html += `<button onclick="goToPage(${meta.page - 1})" class="page-btn">← Prev</button>`;
    }
    html += `<span class="text-xs text-gray-500 font-mono px-2">Page ${meta.page} of ${meta.total_pages}</span>`;
    if (meta.has_more) {
        html += `<button onclick="goToPage(${meta.page + 1})" class="page-btn">Next →</button>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

function goToPage(page) {
    currentPage = page;
    applyFilters();
    document.getElementById('marketsTable')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ─── AI Analysis Modal ────────────────────────────────────────────────────────
async function analyzeMarket(marketId) {
    const useResearch = isResearchEnabled();
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');
    if (!modal || !content || !modalTitle) return;

    modal.classList.remove('hidden');
    const researchTag = useResearch
        ? '<span class="badge badge-research ml-2">+ Web Research</span>'
        : '<span class="badge badge-no-research ml-2">Price Data Only</span>';
    modalTitle.innerHTML = `🤖 Intelligence Brief ${researchTag}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center py-16">
            <div class="loading-dots mb-4"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
            <div class="text-polysint text-sm animate-pulse">${useResearch ? 'Scanning web + running forensic analysis...' : 'Running forensic analysis...'}</div>
        </div>`;

    try {
        const res = await fetch(`/markets/${marketId}/ai-analysis?research=${useResearch}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const formatted = data.analysis
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `<div class="analysis-content">${formatted}</div>`;
    } catch (e) {
        console.error('AI analysis failed:', e);
        content.innerHTML = `<div class="error-box"><div class="font-medium mb-1">⚠️ Analysis Failed</div><div class="text-xs text-gray-500">Check your LLM API key and <code>analyzer.log</code> for details.</div></div>`;
    }
}

// ─── Wallet Profiling ─────────────────────────────────────────────────────────
async function profileEntity(address, label) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');
    if (!modal || !content || !modalTitle) return;

    modal.classList.remove('hidden');
    modalTitle.innerHTML = `🧠 Entity Profile — <span class="text-blue-400">${escapeHtml(label)}</span>`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center py-16">
            <div class="loading-dots mb-4" style="--dot-color:#60a5fa;"><div class="dot bg-blue-400"></div><div class="dot bg-blue-400"></div><div class="dot bg-blue-400"></div></div>
            <div class="text-blue-400 text-sm animate-pulse">Unmasking proxy & profiling trades...</div>
        </div>`;

    try {
        const res = await fetch(`/wallets/${address}/profile`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const formatted = data.profile
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `
            <div class="wallet-info-box">
                <div><span class="text-gray-600">Proxy:</span> <span class="text-gray-300">${address}</span></div>
                <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${escapeHtml(data.real_owner)}</span></div>
            </div>
            <div class="analysis-content" style="border-color:rgba(59,130,246,0.5);">${formatted}</div>`;
    } catch (e) {
        console.error('Profiling failed:', e);
        content.innerHTML = `<div class="error-box">⚠️ Could not generate entity profile.</div>`;
    }
}

async function unmaskWallet(address) {
    const btn = document.getElementById(`btn-${address}`);
    const realDiv = document.getElementById(`real-${address}`);
    if (!btn || !realDiv) return;

    btn.disabled = true;
    btn.innerHTML = '<span class="animate-pulse">Scanning...</span>';
    btn.classList.add('opacity-50', 'cursor-not-allowed');

    try {
        const res = await fetch(`/wallets/${address}/unmask`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        realDiv.classList.remove('hidden');
        realDiv.innerHTML = `<span class="text-gray-500">EOA:</span> <span class="text-polysint">${escapeHtml(data.real_owner)}</span>`;
        btn.textContent = "✓ Unmasked";
        btn.classList.remove('border-gray-600', 'text-gray-300', 'hover:bg-gray-700');
        btn.classList.add('bg-gray-800', 'text-gray-500', 'border-transparent', 'cursor-default');
    } catch (e) {
        console.error('Unmask failed:', e);
        btn.disabled = false;
        btn.textContent = "Retry";
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
    }
}

// ─── Watchlist ────────────────────────────────────────────────────────────────
async function addTarget() {
    const addressInput = document.getElementById('newAddress');
    const labelInput = document.getElementById('newLabel');
    const address = addressInput?.value.trim();
    const label = labelInput?.value.trim();

    if (!address || !label) { showInlineError('addError', 'Both address and label are required.'); return; }

    try {
        const res = await fetch('/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address, label })
        });
        const data = await res.json();
        if (res.ok) { addressInput.value = ''; labelInput.value = ''; clearInlineError('addError'); loadWatchlist(); }
        else { showInlineError('addError', data.detail || 'Failed to add target.'); }
    } catch (e) { showInlineError('addError', 'Network error. Is the backend running?'); }
}

function showInlineError(id, msg) { const el = document.getElementById(id); if (el) { el.textContent = msg; el.classList.remove('hidden'); } }
function clearInlineError(id) { const el = document.getElementById(id); if (el) { el.textContent = ''; el.classList.add('hidden'); } }

async function loadWatchlist() {
    const table = document.getElementById('watchlistTable');
    if (!table) return;
    try {
        const res = await fetch('/watchlist');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const watchlist = await res.json();

        table.innerHTML = '';
        if (watchlist.length === 0) {
            table.innerHTML = `<tr style="animation:none;opacity:1;"><td colspan="2" class="text-center py-12 text-gray-600 text-sm italic">Watchlist empty — add a target's 0x address above.</td></tr>`;
            return;
        }

        watchlist.forEach(w => {
            const shortAddr = w.address.substring(0, 6) + '…' + w.address.substring(w.address.length - 4);
            const tr = document.createElement('tr');
            tr.className = "hover:bg-gray-800/40 transition-colors border-b border-gray-800/50";
            tr.style.animation = 'none'; tr.style.opacity = '1';

            tr.innerHTML = `
                <td class="px-4 py-3">
                    <div class="font-semibold text-gray-200 text-sm">${escapeHtml(w.label)}</div>
                    <div class="text-xs font-mono text-gray-500 mt-1">${shortAddr}</div>
                    <div class="text-xs font-mono text-polysint mt-1 hidden" id="real-${w.address}"></div>
                </td>
                <td class="px-4 py-3 text-right">
                    <div class="flex justify-end items-center gap-1.5">
                        <button onclick="unmaskWallet('${w.address}')" id="btn-${w.address}" class="watchlist-btn">Unmask</button>
                        <button onclick="profileEntity('${w.address}', '${escapeHtml(w.label).replace(/'/g, "\\'")}')" class="watchlist-btn-profile">AI Profile</button>
                        <button onclick="deleteTarget('${w.address}')" title="Stop tracking" class="watchlist-btn-delete">✕</button>
                    </div>
                </td>`;
            table.appendChild(tr);
        });
    } catch (e) {
        console.error('loadWatchlist failed:', e);
        table.innerHTML = `<tr style="animation:none;opacity:1;"><td colspan="2" class="text-center py-8 text-red-400 text-sm">Failed to load watchlist.</td></tr>`;
    }
}

async function deleteTarget(address) {
    if (!confirm("Stop tracking this entity?")) return;
    try {
        const res = await fetch(`/watchlist/${address}`, { method: 'DELETE' });
        if (res.ok) loadWatchlist();
        else alert("Failed to delete target.");
    } catch (e) { console.error('deleteTarget failed:', e); }
}

// ─── Modal ────────────────────────────────────────────────────────────────────
function closeModal() { document.getElementById('aiModal')?.classList.add('hidden'); }
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
document.addEventListener('click', (e) => { const modal = document.getElementById('aiModal'); if (e.target === modal) closeModal(); });
```

---

## Key Enhancements

| Feature | Implementation |
|---------|----------------|
| **Volume Tiers** | 5 preset brackets (micro/small/mid/large/mega) with `vol_tier` enum parameter |
| **Batch Volume Delta** | Single CTE query with `ROW_NUMBER()` window function — O(1) DB round-trips |
| **Convenience Endpoints** | `/markets/anomalies` (≥10% shift), `/markets/surging` (volume delta) |
| **Combined Sort** | `shift_volume` — 60% normalized shift + 40% normalized volume delta |
| **Quick Filters** | One-click pills: ⚡ Anomalies, 📈 Surging, 🐋 Mega |
| **Keyboard Shortcuts** | `/` or `⌘K` to focus search, `Escape` to close modal |
| **Filter Persistence** | All selections saved to `localStorage` and restored on load |
| **Surge Detection** | Markets flagged with 🔥 SURGING when volume delta ≥ $5K |
| **Pagination** | Full metadata: `page`, `limit`, `total_results`, `has_more`, `total_pages` |
| **Filter Presets API** | `/markets/filters` returns tier definitions, sort options, thresholds |

### Example API Calls

```bash
# Mega-tier markets sorted by combined score
GET /markets?vol_tier=mega&sort_by=shift_volume&sort_order=desc

# Custom range with volume delta filter
GET /markets?vol_min=25000&vol_max=100000&vol_delta_min=5000

# Convenience: anomalies with pagination
GET /markets/anomalies?limit=20&sort_order=desc

# Convenience: surging markets
GET /markets/surging?min_delta=2000&limit=30
```
