I'll add a real-time status monitoring system across the backend daemons and the dashboard. This requires a shared heartbeat mechanism, a health API endpoint, and a polished status widget.

Here are all the changes:

---

### NEW FILE: `status.py`

```python
"""
Shared heartbeat file for real-time worker status tracking.
Every daemon writes a heartbeat here; the API reads it for the dashboard.
"""
import json
import os
import time
from logger import get_logger

log = get_logger("Status")

STATUS_FILE = "status.json"


def init_status_file():
    """Create the status file on first boot so the health endpoint never 404s."""
    if not os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "w") as f:
                json.dump({"workers": {}, "first_heartbeat": time.time()}, f)
        except Exception as e:
            log.warning(f"Could not create status file: {e}")


def heartbeat(worker_name, status="running", **meta):
    """Write a worker heartbeat to the shared status file."""
    try:
        data = {}
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                data = {}

        if "workers" not in data:
            data["workers"] = {}
        if "first_heartbeat" not in data:
            data["first_heartbeat"] = time.time()

        data["workers"][worker_name] = {
            "status": status,
            "last_heartbeat": time.time(),
            **meta
        }

        with open(STATUS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        log.debug(f"Heartbeat write failed for {worker_name}: {e}")


def get_health_status(timeout=300):
    """Read the status file and flag each worker alive/dead based on timeout."""
    try:
        if not os.path.exists(STATUS_FILE):
            return {"workers": {}, "uptime": None}

        with open(STATUS_FILE, "r") as f:
            data = json.load(f)

        now = time.time()
        workers = data.get("workers", {})
        for name, info in workers.items():
            last = info.get("last_heartbeat", 0)
            info["alive"] = (now - last) < timeout

        return {
            "workers": workers,
            "uptime": now - data.get("first_heartbeat", now)
        }
    except Exception:
        return {"workers": {}, "uptime": None}
```

---

### MODIFY: `api.py`

Add the import and startup call:

```python
# ── Add near the top imports ──
from status import get_health_status, init_status_file

# ── Inside startup() ──
@app.on_event("startup")
def startup():
    init_db()
    init_status_file()          # ← add this line
```

Add the health endpoint (after `serve_dashboard` or anywhere before the routes):

```python
@app.get("/health")
def health_check():
    """Returns real-time status of all background workers."""
    return get_health_status()
```

---

### MODIFY: `alerts.py`

```python
# ── Add to imports at top ──
from status import heartbeat

# ── At the top of scan_for_anomalies(), after notifier = Notifier() ──
    notifier = Notifier()
    anomaly_count = 0           # ← add this

# ── Inside the CLOB path, right after notifier.broadcast(...) ──
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")
                    anomaly_count += 1              # ← add this

# ── Inside the snapshot fallback path, right after notifier.broadcast(...) ──
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")
                    anomaly_count += 1              # ← add this

# ── At the very end of scan_for_anomalies(), after the for loop ──
        except Exception as e:
            log.error(f"Error scanning anomaly for {m['id']}: {e}")
            continue

    heartbeat("alerts", "running", anomalies_detected=anomaly_count)  # ← add this
```

---

### MODIFY: `harvest.py`

```python
# ── Add to imports at top ──
from status import heartbeat

# ── Change process_and_save signature ──
def process_and_save(markets, total_markets=None):   # ← add total_markets param

    # ... (existing body unchanged) ...

    db.commit()
    db.close()

    # ── At the very end of process_and_save, after db.close() ──
    heartbeat("harvester", "running",              # ← add this block
              markets_saved=len(markets),
              total_markets=total_markets or len(markets),
              last_harvest=datetime.now().isoformat())

# ── In the __main__ loop, update the process_and_save call ──
        data = fetch_active_markets(session)
        process_and_save(data, total_markets=len(data))   # ← pass total_markets
        time.sleep(900)
```

---

### MODIFY: `watcher.py`

```python
# ── Add to imports at top ──
from status import heartbeat

# ── At the end of watch_wallets(), after the for loop and time.sleep ──
        except Exception as e:
            log.error(f"Failed to fetch trades for {address}: {e}")
            
        time.sleep(1)

    # ── Add at the very end of the function ──
    heartbeat("watcher", "running", wallets_tracked=len(tracked))   # ← add this
```

---

### MODIFY: `static/index.html`

Add the status widget CSS inside `<style>` (after the existing styles, before `</style>`):

```css
/* ── Status Widget ── */
.status-widget {
    animation: statusFadeIn 0.5s ease forwards;
}
@keyframes statusFadeIn {
    from { opacity: 0; transform: translateY(-6px); }
    to   { opacity: 1; transform: translateY(0); }
}
.status-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 0;
}
.status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
}
.status-dot.online {
    background: #10b981;
    box-shadow: 0 0 4px rgba(16,185,129,0.5);
    animation: statusPulse 2s ease-in-out infinite;
}
.status-dot.offline {
    background: #ef4444;
}
.status-dot.error {
    background: #f59e0b;
}
@keyframes statusPulse {
    0%,100% { opacity: 1; box-shadow: 0 0 4px rgba(16,185,129,0.5); }
    50%     { opacity: 0.5; box-shadow: 0 0 8px rgba(16,185,129,0.3); }
}
.status-name {
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #6b7280;
    min-width: 70px;
    font-family: 'JetBrains Mono', 'DM Mono', monospace;
}
.status-detail {
    font-size: 11px;
    color: #9ca3af;
    font-family: 'JetBrains Mono', 'DM Mono', monospace;
}
.status-sep {
    width: 1px;
    height: 20px;
    background: #374151;
    margin: 0 4px;
    flex-shrink: 0;
}
.status-refresh {
    font-size: 10px;
    color: #4b5563;
    font-family: 'JetBrains Mono', 'DM Mono', monospace;
    cursor: pointer;
    transition: color 0.2s;
}
.status-refresh:hover {
    color: #10b981;
}
@media (max-width: 640px) {
    .status-widget {
        flex-wrap: wrap;
        gap: 6px !important;
    }
    .status-sep { display: none; }
}
```

Add the widget HTML right **after** the toolbar `</div>` (after the volume filter and research toggle row, before `<div id="marketsContainer">`):

```html
        <!-- Status Widget -->
        <div id="statusWidget" class="status-widget hidden mt-3 pt-3 border-t border-gray-800/60 flex items-center gap-4 flex-wrap">
            <div class="status-item" id="status-harvester">
                <div class="status-dot offline"></div>
                <span class="status-name">Harvester</span>
                <span class="status-detail">--</span>
            </div>
            <div class="status-sep"></div>
            <div class="status-item" id="status-alerts">
                <div class="status-dot offline"></div>
                <span class="status-name">Alerts</span>
                <span class="status-detail">--</span>
            </div>
            <div class="status-sep"></div>
            <div class="status-item" id="status-watcher">
                <div class="status-dot offline"></div>
                <span class="status-name">Tracker</span>
                <span class="status-detail">--</span>
            </div>
            <span id="statusRefresh" class="status-refresh ml-auto" onclick="fetchHealth()" title="Refresh now">&#x21bb; refresh</span>
        </div>
```

---

### MODIFY: `static/app.js`

Add the health polling logic at the bottom of the file (before the final closing):

```javascript
// ─── Worker Health Status ────────────────────────────────────────────────────
let healthTimer = null;

function timeAgo(ts) {
    const secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 10)   return 'just now';
    if (secs < 60)   return secs + 's ago';
    if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
    return Math.floor(secs / 3600) + 'h ago';
}

function updateStatusItem(id, alive, status, detail) {
    const el = document.getElementById(id);
    if (!el) return;
    const dot = el.querySelector('.status-dot');
    const detailEl = el.querySelector('.status-detail');
    dot.className = 'status-dot ' + (alive ? 'online' : (status === 'error' ? 'error' : 'offline'));
    detailEl.textContent = detail;
}

async function fetchHealth() {
    const widget = document.getElementById('statusWidget');
    try {
        const res = await fetch('/health');
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        widget.classList.remove('hidden');

        const w = data.workers || {};
        const h = w.harvester;
        const a = w.alerts;
        const t = w.watcher;

        // Harvester
        if (h && h.alive) {
            const saved = h.markets_saved != null ? h.markets_saved + ' saved' : 'running';
            const ago = h.last_heartbeat ? timeAgo(h.last_heartbeat) : '';
            updateStatusItem('status-harvester', true, 'running', saved + (ago ? ' · ' + ago : ''));
        } else {
            updateStatusItem('status-harvester', false, 'offline', h ? timeAgo(h.last_heartbeat) : 'no data');
        }

        // Alerts
        if (a && a.alive) {
            const count = a.anomalies_detected != null ? a.anomalies_detected + ' flagged' : 'scanning';
            const ago = a.last_heartbeat ? timeAgo(a.last_heartbeat) : '';
            updateStatusItem('status-alerts', true, 'running', count + (ago ? ' · ' + ago : ''));
        } else {
            updateStatusItem('status-alerts', false, 'offline', a ? timeAgo(a.last_heartbeat) : 'no data');
        }

        // Watcher
        if (t && t.alive) {
            const wallets = t.wallets_tracked != null ? t.wallets_tracked + ' tracked' : 'monitoring';
            const ago = t.last_heartbeat ? timeAgo(t.last_heartbeat) : '';
            updateStatusItem('status-watcher', true, 'running', wallets + (ago ? ' · ' + ago : ''));
        } else {
            updateStatusItem('status-watcher', false, 'offline', t ? timeAgo(t.last_heartbeat) : 'no data');
        }

        // Update refresh timestamp
        const refreshEl = document.getElementById('statusRefresh');
        if (refreshEl) {
            const now = new Date();
            refreshEl.textContent = '\u21bb updated ' + now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0');
        }
    } catch (e) {
        // Silently fail — don't disrupt the dashboard if health endpoint is unreachable
        console.warn('Health check failed:', e);
    }
}

// Poll every 15 seconds
healthTimer = setInterval(fetchHealth, 15000);
// First fetch after DOM settles
setTimeout(fetchHealth, 800);
```

---

### How It Works

```
┌─────────────┐     heartbeat()      ┌──────────────┐     GET /health     ┌──────────────┐
│  harvest.py  │ ──────────────────▶  │  status.json  │ ◀─────────────────  │   api.py     │
│  alerts.py   │ ──────────────────▶  │  (shared file)│ ──────────────────▶ │  /health     │
│  watcher.py  │ ──────────────────▶  └──────────────┘                     └──────┬───────┘
└─────────────┘                                                                   │
                                                                            JSON response
                                                                           ┌──────┴───────┐
                                                                           │  dashboard   │
                                                                           │  (poll 15s)  │
                                                                           └──────────────┘
```

Each daemon writes a heartbeat every cycle (alerts: every 5 min, harvest: every 15 min, watcher: every 5 min). The API reads `status.json` and the dashboard polls `/health` every 15 seconds. The widget shows green pulsing dots when alive, red when dead, and amber on error — with contextual stats (markets saved, anomalies flagged, wallets tracked) and relative timestamps.
