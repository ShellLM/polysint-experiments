Here are the updated files to implement the Harvester Lag & Sync Status dashboard.

### FILE: db.py
Added a `system_status` table to track the harvester's heartbeat.

```python
### FILE: db.py ###
import sqlite3
from config import Config
from logger import get_logger

log = get_logger("Database")

def get_db():
    try:
        conn = sqlite3.connect(Config.DB_NAME)
        conn.row_factory = sqlite3.Row
        # This allows multiple readers and one writer to coexist
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
    except Exception as e:
        log.critical(f"Database connection failed: {e}")
        raise

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Markets Table — clob_token_id stores the YES outcome token for CLOB history lookups
    cursor.execute('''CREATE TABLE IF NOT EXISTS markets 
        (id TEXT PRIMARY KEY, question TEXT, outcomes TEXT, volume REAL, created_at TEXT, clob_token_id TEXT)''')

    # Migrate existing deployments: add clob_token_id column if it doesn't exist yet
    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(markets)").fetchall()]
    if "clob_token_id" not in existing_columns:
        cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
        log.warning("Migrated markets table: added clob_token_id column")

    # Snapshots Table — kept for fallback if CLOB history is unavailable
    cursor.execute('''CREATE TABLE IF NOT EXISTS snapshots 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id TEXT, timestamp DATETIME, prices TEXT, volume REAL)''')

    # Watchlist Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS watch_list 
        (address TEXT PRIMARY KEY, label TEXT, added_at DATETIME)''')

    # System Status Table — tracks harvester health
    cursor.execute('''CREATE TABLE IF NOT EXISTS system_status 
        (key TEXT PRIMARY KEY, value TEXT, updated_at DATETIME)''')

    conn.commit()
    conn.close()
```

### FILE: harvest.py
Added status tracking to report heartbeat, progress, and errors to the database.

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

def update_status(key: str, value: str):
    """Updates a key in the system_status table."""
    try:
        db = get_db()
        db.execute(
            "INSERT OR REPLACE INTO system_status (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, value)
        )
        db.commit()
        db.close()
    except Exception as e:
        log.error(f"Failed to update system status: {e}")

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

        try:
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

            # Update progress status for the dashboard
            update_status("harvest_progress", f"Fetched {offset} markets...")

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
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })

    try:
        while True:
            # Mark start of cycle
            update_status("harvest_status", "running")
            
            try:
                data = fetch_active_markets(session)
                process_and_save(data)
                
                # Mark success
                update_status("harvest_status", "success")
                update_status("harvest_count", str(len(data)))
                update_status("harvest_last_run", datetime.now().isoformat())
                
            except Exception as e:
                log.error(f"Harvest cycle failed: {e}")
                update_status("harvest_status", "error")
                update_status("harvest_last_run", datetime.now().isoformat())
            
            time.sleep(900)
    except KeyboardInterrupt:
        print("Stopped.")
```

### FILE: api.py
Added a `/system/status` endpoint to serve health data to the frontend.

```python
### FILE: api.py ###
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
import re
import requests
import json
from datetime import datetime

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

@app.get("/system/status")
def get_system_status():
    """
    Returns health metrics: harvester status, last run time, and DB stats.
    """
    db = get_db()
    try:
        # Fetch harvester heartbeat
        status_rows = db.execute("SELECT key, value FROM system_status").fetchall()
        status_map = {r['key']: r['value'] for r in status_rows}
        
        # Count total markets in DB
        market_count = db.execute("SELECT COUNT(*) as count FROM markets").fetchone()['count']
        
        return {
            "harvest_status": status_map.get("harvest_status", "unknown"),
            "harvest_last_run": status_map.get("harvest_last_run"),
            "harvest_count": int(status_map.get("harvest_count", 0)),
            "db_market_count": market_count,
            "progress": status_map.get("harvest_progress", "")
        }
    finally:
        db.close()

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
    vol_min: float = Query(default=None, ge=0),
    vol_max: float = Query(default=None, ge=0),
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

### FILE: static/app.js
Added `loadSystemStatus` and UI injection logic to display a live health bar in the header.

```javascript
### FILE: static/app.js ###
// ─── State ────────────────────────────────────────────────────────────────────
let hasLoadedOnce = false;
let refreshTimer = null;
let refreshCountdown = 0;
const REFRESH_INTERVAL = 300; // 5 minutes

// ─── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    injectStatusBar();
    loadSystemStatus();
    setInterval(loadSystemStatus, 30000); // Check system health every 30s
    
    loadWatchlist();
    initResearchToggle();

    document.getElementById('searchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const q = e.target.value.trim();
            loadMarkets(q);
        }
    });
});

// ─── Inject Status UI ─────────────────────────────────────────────────────────
function injectStatusBar() {
    const header = document.querySelector('header') || document.querySelector('.container');
    if (!header) return;
    
    // Create status bar if it doesn't exist
    if (document.getElementById('systemStatusBar')) return;

    const statusHTML = `
    <div id="systemStatusBar" class="mb-4 p-3 rounded-lg bg-gray-800/50 border border-gray-700 flex items-center justify-between text-xs font-mono">
        <div class="flex items-center space-x-3">
            <div id="syncIndicator" class="w-2 h-2 rounded-full bg-gray-500 animate-pulse"></div>
            <span id="syncStatusText" class="text-gray-400">Checking system status...</span>
        </div>
        <div class="text-gray-500">
            Markets DB: <span id="marketDbCount" class="text-gray-400">-</span>
        </div>
    </div>`;
    
    // Insert after header or at top of container
    header.insertAdjacentHTML('afterend', statusHTML);
}

// ─── Load System Status ───────────────────────────────────────────────────────
async function loadSystemStatus() {
    try {
        const res = await fetch('/system/status');
        if (!res.ok) throw new Error('Status endpoint failed');
        const data = await res.json();
        updateStatusUI(data);
    } catch (e) {
        const indicator = document.getElementById('syncIndicator');
        const text = document.getElementById('syncStatusText');
        if(indicator) {
            indicator.className = 'w-2 h-2 rounded-full bg-red-500';
        }
        if(text) {
            text.textContent = 'System status unavailable';
            text.className = 'text-red-400';
        }
    }
}

function updateStatusUI(data) {
    const indicator = document.getElementById('syncIndicator');
    const text = document.getElementById('syncStatusText');
    const countEl = document.getElementById('marketDbCount');
    
    if(countEl) countEl.textContent = data.db_market_count.toLocaleString();
    
    const status = data.harvest_status;
    const lastRun = data.harvest_last_run ? new Date(data.harvest_last_run) : null;
    
    let color = 'bg-gray-500';
    let msg = 'Unknown state';
    
    if (status === 'running') {
        color = 'bg-blue-400 animate-pulse';
        msg = `Harvesting... ${data.progress || ''}`;
    } else if (status === 'success') {
        if (lastRun) {
            const secondsAgo = Math.floor((new Date() - lastRun) / 1000);
            const minsAgo = Math.floor(secondsAgo / 60);
            
            // If last run was > 20 mins ago (schedule is 15m), consider it stale
            if (minsAgo > 20) {
                color = 'bg-yellow-500';
                msg = `Stale sync (${minsAgo}m ago)`;
            } else {
                color = 'bg-emerald-400';
                msg = `Synced ${minsAgo < 1 ? 'just now' : minsAgo + 'm ago'}`;
            }
        } else {
            color = 'bg-emerald-400';
            msg = 'Synced';
        }
    } else if (status === 'error') {
        color = 'bg-red-500';
        msg = 'Harvest Error';
    }
    
    if(indicator) {
        // Reset classes
        indicator.className = `w-2 h-2 rounded-full ${color}`;
    }
    if(text) {
        text.textContent = msg;
        text.className = `text-gray-300`;
    }
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

        const url = `/markets${params.toString() ? '?' + params.toString() : ''}`;
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
                    <div class="text-gray-600 text-xs">Is the backend running? Check <code>analyzer.log</code>.</div>
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
        const url = `/markets/${marketId}/ai-analysis?research=${useResearch}`;
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
        const res = await fetch(`/wallets/${address}/profile`);
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
        const res = await fetch(`/wallets/${address}/unmask`);
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
        alert("Failed to unmask wallet. Check RPC configuration.");
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
        const res = await fetch('/watchlist', {
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
        const res = await fetch('/watchlist');
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
        const res = await fetch(`/watchlist/${address}`, { method: 'DELETE' });
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
