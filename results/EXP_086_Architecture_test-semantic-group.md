Here's the complete implementation to move long-running AI analysis to a background worker process:

## Architecture Overview

1. **SQLite Job Queue**: New `jobs` table with atomic claiming and deduplication
2. **Background Worker**: Separate `worker.py` process with graceful shutdown
3. **Async API**: Submit jobs via POST, poll for results via GET
4. **Polling Frontend**: Adaptive polling with visual progress feedback
5. **Result Caching**: Avoid reprocessing identical requests

---

### FILE: `db.py` — Job queue with deduplication and caching

```python
import sqlite3
import json
import uuid
import time
from config import Config
from logger import get_logger

log = get_logger("Database")

# Cache TTL in seconds
MARKET_ANALYSIS_CACHE_TTL = 4 * 3600  # 4 hours
WALLET_PROFILE_CACHE_TTL = 3600  # 1 hour

def get_db():
    try:
        conn = sqlite3.connect(Config.DB_NAME)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn
    except Exception as e:
        log.critical(f"Database connection failed: {e}")
        raise

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Markets Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS markets 
        (id TEXT PRIMARY KEY, question TEXT, outcomes TEXT, volume REAL, 
         created_at TEXT, clob_token_id TEXT)''')

    existing_cols = [r[1] for r in cursor.execute("PRAGMA table_info(markets)").fetchall()]
    if "clob_token_id" not in existing_cols:
        cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
        log.warning("Migrated markets table: added clob_token_id column")

    # Snapshots Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS snapshots 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id TEXT, timestamp DATETIME, 
         prices TEXT, volume REAL)''')

    # Watchlist Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS watch_list 
        (address TEXT PRIMARY KEY, label TEXT, added_at DATETIME)''')

    # Job Queue Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        result TEXT,
        error TEXT,
        created_at REAL NOT NULL,
        started_at REAL,
        completed_at REAL,
        attempts INTEGER DEFAULT 0
    )''')

    # Index for fast worker pickup
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_jobs_status_created 
                      ON jobs(status, created_at)''')

    # Result cache table
    cursor.execute('''CREATE TABLE IF NOT EXISTS analysis_cache (
        cache_key TEXT PRIMARY KEY,
        result TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL
    )''')

    conn.commit()
    conn.close()
    cleanup_expired_cache()


# ─── Job Queue Helpers ───────────────────────────────────────────────────────

def create_job(job_type: str, payload: dict) -> tuple[str, bool]:
    """Create a new job with deduplication. Returns (job_id, is_new)."""
    conn = get_db()
    try:
        # Check for existing pending/processing job
        existing = conn.execute("""
            SELECT id, status FROM jobs 
            WHERE type = ? 
            AND payload = ?
            AND status IN ('pending', 'processing')
            ORDER BY created_at DESC LIMIT 1
        """, (job_type, json.dumps(payload))).fetchone()

        if existing:
            log.info(f"Reusing existing job {existing['id']}")
            return existing['id'], False

        job_id = str(uuid.uuid4())
        now = time.time()

        conn.execute(
            "INSERT INTO jobs (id, type, payload, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (job_id, job_type, json.dumps(payload), now)
        )
        conn.commit()
        return job_id, True

    except Exception as e:
        conn.rollback()
        log.error(f"Failed to create job: {e}")
        raise
    finally:
        conn.close()


def claim_next_job() -> dict | None:
    """Atomically claim the next pending job with retry backoff."""
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        job = conn.execute("""
            SELECT * FROM jobs 
            WHERE status = 'pending' 
            AND attempts < 3
            ORDER BY created_at ASC LIMIT 1
        """).fetchone()

        if not job:
            conn.rollback()
            return None

        job_dict = dict(job)
        
        # Check backoff for retries
        if job_dict['attempts'] > 0 and job_dict['started_at']:
            backoff = min(300, (2 ** job_dict['attempts']) * 10)
            if time.time() - job_dict['started_at'] < backoff:
                conn.rollback()
                return None

        conn.execute(
            """UPDATE jobs SET status = 'processing', started_at = ?, 
               attempts = attempts + 1 WHERE id = ?""",
            (time.time(), job_dict['id'])
        )
        conn.commit()
        return job_dict

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_job(job_id: str, result: str):
    conn = get_db()
    conn.execute(
        "UPDATE jobs SET status = 'completed', result = ?, completed_at = ? WHERE id = ?",
        (result, time.time(), job_id)
    )
    conn.commit()
    conn.close()


def fail_job(job_id: str, error: str):
    conn = get_db()
    conn.execute(
        "UPDATE jobs SET status = 'failed', error = ?, completed_at = ? WHERE id = ?",
        (error[:500], time.time(), job_id)
    )
    conn.commit()
    conn.close()


def recover_stale_jobs(timeout_minutes: int = 10):
    """Reset jobs stuck in 'processing' back to 'pending'."""
    conn = get_db()
    cutoff = time.time() - (timeout_minutes * 60)
    cur = conn.execute(
        """UPDATE jobs SET status = 'pending', started_at = NULL 
           WHERE status = 'processing' AND started_at < ?""",
        (cutoff,)
    )
    affected = cur.rowcount
    conn.commit()
    conn.close()
    if affected:
        log.warning(f"Recovered {affected} stale job(s)")


def get_job(job_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Result Cache ────────────────────────────────────────────────────────────

def get_cached_result(cache_key: str) -> str | None:
    conn = get_db()
    row = conn.execute(
        "SELECT result FROM analysis_cache WHERE cache_key = ? AND expires_at > ?",
        (cache_key, time.time())
    ).fetchone()
    conn.close()
    return row['result'] if row else None


def set_cached_result(cache_key: str, result: str, ttl: int):
    conn = get_db()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO analysis_cache VALUES (?, ?, ?, ?)",
        (cache_key, result, now, now + ttl)
    )
    conn.commit()
    conn.close()


def cleanup_expired_cache():
    conn = get_db()
    cur = conn.execute("DELETE FROM analysis_cache WHERE expires_at < ?", (time.time(),))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    if deleted:
        log.info(f"Cleaned {deleted} expired cache entries")
```

---

### FILE: `worker.py` — Background worker with graceful shutdown

```python
"""
Background worker that processes analysis jobs from the SQLite queue.
Run: python worker.py
"""
import signal
import time
import json
import traceback
import requests
from db import (
    get_db, claim_next_job, complete_job, fail_job,
    recover_stale_jobs, get_cached_result, set_cached_result,
    MARKET_ANALYSIS_CACHE_TTL, WALLET_PROFILE_CACHE_TTL
)
from analyst import PolyAnalyst
from clob import get_history_as_price_list
from utils import unmask_proxy
from config import Config
from logger import get_logger

log = get_logger("Worker")

POLL_INTERVAL = 2
MAX_JOB_TIME = 120
HEALTH_CHECK_INTERVAL = 60


class GracefulKiller:
    """Handle graceful shutdown on SIGTERM/SIGINT."""
    def __init__(self):
        self.kill_now = False
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, signum, frame):
        log.info(f"Received signal {signum}, shutting down...")
        self.kill_now = True


def _fetch_price_history(market: dict) -> list | None:
    """Fetch price history via CLOB first, snapshots as fallback."""
    if market.get("clob_token_id"):
        history = get_history_as_price_list(market["clob_token_id"])
        if history:
            return history

    db = get_db()
    try:
        raw = db.execute(
            "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 5",
            (market['id'],)
        ).fetchall()
        result = []
        for h in raw:
            try:
                prices = json.loads(h['prices'])
                if prices:
                    result.append(float(prices[0]))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return result if result else None
    finally:
        db.close()


def process_market_analysis(payload: dict) -> str:
    market_id = payload['market_id']
    use_research = payload.get('use_research', False)

    db = get_db()
    market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
    db.close()

    if not market:
        raise ValueError(f"Market {market_id} not found")

    market = dict(market)
    price_history = _fetch_price_history(market)

    if not price_history or len(price_history) < 2:
        raise ValueError("Insufficient price history")

    analyst = PolyAnalyst()
    return analyst.analyze_market_shift(
        market['question'],
        price_history,
        market['volume'],
        use_research=use_research
    )


def process_wallet_profile(payload: dict) -> str:
    address = payload['address']

    url = f"{Config.DATA_API}/trades?user={address}&limit=15"
    try:
        resp = requests.get(url, timeout=10)
        trades_data = resp.json() if resp.status_code == 200 else []
    except Exception:
        trades_data = []

    simplified_trades = [
        f"Bought {t.get('side')} on '{t.get('title')}' for ${t.get('size')}"
        for t in trades_data
    ]

    real_owner = unmask_proxy(address)
    analyst = PolyAnalyst()
    profile = analyst.profile_wallet(address, real_owner, simplified_trades)

    return json.dumps({"profile": profile, "real_owner": real_owner})


def run_worker():
    killer = GracefulKiller()
    current_job_id = None
    jobs_processed = 0

    print("🤖 Analysis Worker started. Polling for jobs...")

    while not killer.kill_now:
        try:
            recover_stale_jobs()

            job = claim_next_job()

            if job:
                current_job_id = job['id']
                job_type = job['type']
                payload = json.loads(job['payload'])

                # Check cache
                cache_key = None
                if job_type == 'market_analysis':
                    cache_key = f"market:{payload['market_id']}:{int(payload.get('use_research', False))}"
                elif job_type == 'wallet_profile':
                    cache_key = f"wallet:{payload['address']}"

                if cache_key:
                    cached = get_cached_result(cache_key)
                    if cached:
                        log.info(f"Cache hit for job {job['id']}")
                        complete_job(job['id'], cached)
                        jobs_processed += 1
                        current_job_id = None
                        continue

                log.info(f"Processing job {job['id']} ({job_type})")

                try:
                    if job_type == 'market_analysis':
                        result = process_market_analysis(payload)
                        ttl = MARKET_ANALYSIS_CACHE_TTL
                    elif job_type == 'wallet_profile':
                        result = process_wallet_profile(payload)
                        ttl = WALLET_PROFILE_CACHE_TTL
                    else:
                        raise ValueError(f"Unknown job type: {job_type}")

                    complete_job(job['id'], result)

                    if cache_key:
                        set_cached_result(cache_key, result, ttl)

                    jobs_processed += 1
                    log.info(f"Job {job['id']} completed")

                except Exception as e:
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    fail_job(job['id'], error_msg)
                    log.error(f"Job {job['id']} failed: {error_msg}")

                current_job_id = None
            else:
                time.sleep(POLL_INTERVAL)

        except Exception as e:
            log.error(f"Worker loop error: {traceback.format_exc()}")
            time.sleep(POLL_INTERVAL)

    # Graceful shutdown
    if current_job_id:
        log.info(f"Releasing job {current_job_id} due to shutdown")
        fail_job(current_job_id, "Worker shutting down")

    print(f"🛑 Worker stopped. Processed {jobs_processed} jobs.")


if __name__ == "__main__":
    from db import init_db
    init_db()
    run_worker()
```

---

### FILE: `api.py` — Async endpoints with caching

Replace the analysis-related endpoints:

```python
from db import get_db, create_job, get_job, get_cached_result
import time

# ─── Async Analysis Endpoints ────────────────────────────────────────────────

@app.post("/markets/{market_id}/analyze")
def queue_market_analysis(market_id: str, research: bool = Query(default=False)):
    """Queue market analysis. Returns job ID immediately."""
    if not MARKET_ID_RE.match(market_id):
        raise HTTPException(status_code=400, detail="Invalid market ID format.")

    db = get_db()
    market = db.execute("SELECT id FROM markets WHERE id = ?", (market_id,)).fetchone()
    db.close()

    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    # Check cache first
    cache_key = f"market:{market_id}:{int(research)}"
    cached = get_cached_result(cache_key)
    if cached:
        return {"job_id": None, "status": "cached", "result": cached}

    job_id, is_new = create_job('market_analysis', {
        'market_id': market_id,
        'use_research': research
    })

    return {"job_id": job_id, "status": "pending" if is_new else "existing"}


@app.post("/wallets/{address}/profile")
def queue_wallet_profile(address: str):
    """Queue wallet profiling. Returns EOA immediately."""
    _validate_address(address)

    # Check cache
    cache_key = f"wallet:{address}"
    cached = get_cached_result(cache_key)
    if cached:
        parsed = json.loads(cached)
        return {"job_id": None, "status": "cached", "result": parsed}

    real_owner = unmask_proxy(address)

    job_id, is_new = create_job('wallet_profile', {
        'address': address
    })

    return {
        "job_id": job_id,
        "real_owner": real_owner,
        "status": "pending" if is_new else "existing"
    }


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    """Poll for job status and result."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id": job['id'],
        "status": job['status'],
        "attempts": job['attempts'],
        "created_at": job['created_at']
    }

    if job['started_at']:
        response['started_at'] = job['started_at']
        if job['status'] == 'processing':
            response['running_for_seconds'] = round(time.time() - job['started_at'], 1)

    if job['status'] == 'completed':
        response['result'] = job['result']
        if job['started_at'] and job['completed_at']:
            response['processing_time_seconds'] = round(job['completed_at'] - job['started_at'], 1)
    elif job['status'] == 'failed':
        response['error'] = job['error']

    return response


# ─── Legacy Synchronous Endpoint (backward compatibility) ────────────────────

@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis_legacy(
    market_id: str,
    research: bool = Query(default=False)
):
    """
    [DEPRECATED] Synchronous analysis. Use POST /markets/{id}/analyze + GET /jobs/{id} instead.
    Kept for backward compatibility with scripts.
    """
    # Queue job and poll
    queue_response = queue_market_analysis(market_id, research)

    if queue_response['status'] == 'cached':
        return {"analysis": queue_response['result'], "research_used": research}

    job_id = queue_response['job_id']
    start = time.time()

    while time.time() - start < 60:
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=500, detail="Job disappeared")

        if job['status'] == 'completed':
            return {"analysis": job['result'], "research_used": research}
        elif job['status'] == 'failed':
            raise HTTPException(status_code=500, detail=f"Analysis failed: {job['error']}")

        time.sleep(2)

    raise HTTPException(status_code=504, detail="Analysis timed out")
```

---

### FILE: `static/app.js` — Adaptive polling with progress feedback

Replace the analysis/profile functions:

```javascript
// ─── State ────────────────────────────────────────────────────────────────────
let currentJobId = null;
let pollTimer = null;

// ─── Job Polling Engine ──────────────────────────────────────────────────────

function cancelJobPolling() {
    currentJobId = null;
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }
}

function buildProgressHtml(status, elapsed) {
    const label = status === 'processing' ? 'LLM analyzing' : 'In queue';
    const barColor = status === 'processing' ? 'bg-emerald-400' : 'bg-polysint';
    const estimatedTotal = status === 'processing' ? 30 : 10;
    const pct = Math.min(Math.round((elapsed / estimatedTotal) * 100), 95);

    return `
        <div class="flex flex-col items-center justify-center space-y-4 py-10 w-full max-w-sm mx-auto">
            <div class="text-gray-400 text-sm">${label}...</div>
            <div class="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
                <div class="h-full ${barColor} rounded-full transition-all duration-1000" style="width: ${pct}%"></div>
            </div>
            <div class="text-gray-500 text-xs font-mono">${elapsed}s elapsed</div>
        </div>`;
}

async function pollJob(jobId, contentEl, onComplete, startTime = Date.now()) {
    if (currentJobId !== jobId) return;

    try {
        const elapsed = Math.round((Date.now() - startTime) / 1000);

        if (elapsed > 120) {
            currentJobId = null;
            contentEl.innerHTML = `
                <div class="text-yellow-400 bg-yellow-900/20 p-4 rounded border border-yellow-800 text-sm">
                    ⏱️ Analysis is taking longer than expected. The job is still running — try again later.
                </div>`;
            return;
        }

        const res = await fetch(`/jobs/${jobId}`);
        if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
        const job = await res.json();

        if (job.status === 'completed') {
            currentJobId = null;
            onComplete(job.result);
            return;
        }

        if (job.status === 'failed') {
            currentJobId = null;
            contentEl.innerHTML = `
                <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                    ⚠️ Analysis failed: ${job.error || 'Unknown error'}
                </div>`;
            return;
        }

        // Still pending/processing — show progress
        contentEl.innerHTML = buildProgressHtml(job.status, elapsed);

        // Adaptive polling
        const interval = elapsed < 10 ? 1500 :
                        elapsed < 30 ? 3000 : 5000;
        pollTimer = setTimeout(() => pollJob(jobId, contentEl, onComplete, startTime), interval);

    } catch (e) {
        console.error('Poll error:', e);
        pollTimer = setTimeout(() => pollJob(jobId, contentEl, onComplete, startTime), 5000);
    }
}


// ─── AI Analysis Modal ────────────────────────────────────────────────────────

async function analyzeMarket(marketId) {
    const useResearch = isResearchEnabled();
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    cancelJobPolling();
    modal.classList.remove('hidden');

    const researchNote = useResearch
        ? '<span class="text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-mono ml-2">+ Web Research</span>'
        : '<span class="text-xs bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded font-mono ml-2">No Web Research</span>';

    modalTitle.innerHTML = `🤖 PolySINT Intelligence ${researchNote}`;
    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-polysint text-sm">Submitting analysis request...</div>
        </div>`;

    try {
        const res = await fetch(`/markets/${marketId}/analyze?research=${useResearch}`, { method: 'POST' });
        if (!res.ok) throw new Error('Submit failed');
        const data = await res.json();

        if (data.status === 'cached') {
            showAnalysisResult(data.result, content);
            return;
        }

        currentJobId = data.job_id;
        pollJob(data.job_id, content, (result) => showAnalysisResult(result, content));

    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                ⚠️ Could not start analysis. Is the backend running?
            </div>`;
    }
}


// ─── Entity Profile ───────────────────────────────────────────────────────────

async function profileEntity(address, label) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    cancelJobPolling();
    modal.classList.remove('hidden');
    modalTitle.innerHTML = `🧠 Entity Profile — ${label}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce"></div>
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-blue-400 text-sm">Submitting profiling request...</div>
        </div>`;

    try {
        const res = await fetch(`/wallets/${address}/profile`, { method: 'POST' });
        if (!res.ok) throw new Error('Submit failed');
        const data = await res.json();

        if (data.status === 'cached') {
            showProfileResult(data.result, address, content);
            return;
        }

        currentJobId = data.job_id;

        // Show EOA immediately while LLM runs
        content.innerHTML = `
            <div class="mb-4 p-3 bg-gray-900 rounded border border-gray-700 font-mono text-xs text-gray-400 space-y-1">
                <div><span class="text-gray-600">Proxy:</span> ${address}</div>
                <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${data.real_owner}</span></div>
            </div>
            <div class="flex flex-col items-center justify-center space-y-3 py-6">
                <div class="text-blue-400 text-sm animate-pulse">AI profiling in progress...</div>
            </div>`;

        pollJob(data.job_id, content, (result) => {
            const parsed = JSON.parse(result);
            showProfileResult(parsed, address, content);
        });

    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                ⚠️ Could not start profiling.
            </div>`;
    }
}


// ─── Result Display Helpers ───────────────────────────────────────────────────

function showAnalysisResult(result, contentElement) {
    const formatted = result
        .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
        .replace(/\n/g, '<br>');
    contentElement.innerHTML = `
        <div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
}

function showProfileResult(data, address, contentElement) {
    const formatted = data.profile
        .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
        .replace(/\n/g, '<br>');

    contentElement.innerHTML = `
        <div class="mb-4 p-3 bg-gray-900 rounded border border-gray-700 font-mono text-xs text-gray-400 space-y-1">
            <div><span class="text-gray-600">Proxy:</span> ${address}</div>
            <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${data.real_owner}</span></div>
        </div>
        <div class="p-3 border-l-4 border-blue-500 bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
}


// ─── Modal Close ──────────────────────────────────────────────────────────────

function closeModal() {
    cancelJobPolling();
    document.getElementById('aiModal').classList.add('hidden');
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('aiModal');
    if (e.target === modal) closeModal();
});
```

---

### FILE: `start.py` — Launch worker with monitoring

```python
# Add worker to the process list:

        # 5. Analysis Worker
        print(" -> Launching Analysis Worker...")
        worker_proc = subprocess.Popen([sys.executable, "worker.py"])
        processes.append(("Analysis Worker", worker_proc))

# Update boot message:
        notifier.broadcast(
            message="**All PolySINT daemon workers launched.**\n"
                    "AI analysis is now async — submit via dashboard, results stream in.\n"
                    "• Queue endpoint: GET /jobs/{job_id}\n"
                    "• Results are cached for 4 hours (market) / 1 hour (wallet)\n\n"
                    "Awaiting anomalies and entity movements...",
            title="🚀 System Boot: Online"
        )
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Atomic claiming** | `BEGIN IMMEDIATE` prevents duplicate processing across workers |
| **Job deduplication** | Same request returns existing job instead of creating duplicate |
| **Result caching** | Analysis results cached with TTL to avoid reprocessing |
| **Graceful shutdown** | Worker handles SIGTERM, finishes current job before stopping |
| **Adaptive polling** | Frontend adjusts interval (1.5s → 3s → 5s) based on wait time |
| **Progress visualization** | Visual progress bar with elapsed time instead of static spinner |
| **Stale job recovery** | Stuck jobs reset to pending on worker startup and periodically |
| **Retry backoff** | Failed jobs retry with exponential backoff (max 3 attempts) |
| **Backward compatibility** | Legacy sync endpoint wraps async flow for scripts/tools |
| **Immediate EOA feedback** | Wallet address unmasked instantly while LLM profiling runs |
