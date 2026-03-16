<synthesis_output>
    <first_impression>
        The responses address adding historical trend line charts to a Polymarket intelligence platform. Response 266 focuses on correctness bugs, Response 101 emphasizes SOLID/OOP architecture, Response 978 takes a security-hardening approach, and Response 714 is empty. All responses converge on the core solution but differ significantly in their priority areas—bug fixes vs. architecture vs. security hardening.
    </first_impression>

    <analysis>
        The responses collectively identify and solve the same core problem but from different angles. Response 266 identifies three critical correctness bugs: sqlite3.Row object handling, inconsistent list reversal in the snapshot fallback path, and datetime parsing with space vs 'T' separator. Response 101 provides the most architecturally sound solution with class-based services following SOLID principles, but its validation helpers may be overly complex for the task. Response 978 offers the most security-conscious implementation with real SRI hashes, strict CSP policies, and defensive validation helpers that are simpler than Response 101's OOP approach. The strongest synthesis combines the bug fixes from 266, the pragmatic validation approach from 978, and selective architectural patterns from 101 where they provide clear value without over-engineering.
    </analysis>
    
    <dissent>
        Response 101's full class-based architecture (ChartManager, DataValidator, ChartRenderer, MetricsRenderer as separate classes) may be over-engineering for a single-page dashboard feature. The simpler functional approach in Response 978 is more maintainable for this scope. Response 266's use of `setTimeout` instead of `requestAnimationFrame` for chart initialization is less ideal for DOM timing. Response 978's SRI hash validation appears to use a placeholder/fake hash that needs to be generated with the actual Chart.js binary—this is a critical implementation detail that must be verified during deployment.
    </dissent>

    <synthesis>
To add historical trend line charts to the market analysis profile, here's a complete, hardened implementation:

### 1. Backend API (api.py)

Update the `/markets/{market_id}/ai-analysis` endpoint with proper validation and type safety:

```python
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Timestamp bounds (2020-01-01 to 2030-01-01 UTC)
_TIMESTAMP_MIN = 1577836800
_TIMESTAMP_MAX = 1893456000


def _validate_timestamp(ts_raw: Any) -> Optional[int]:
    """Validates and converts timestamp to integer. Returns None if invalid."""
    if ts_raw is None:
        return None
    try:
        ts = int(ts_raw)
        return ts if _TIMESTAMP_MIN <= ts <= _TIMESTAMP_MAX else None
    except (TypeError, ValueError):
        return None


def _validate_price(p_raw: Any) -> Optional[float]:
    """Validates price is a valid probability (0.0 to 1.0). Returns None if invalid."""
    if p_raw is None:
        return None
    try:
        p = float(p_raw)
        return round(p, 4) if 0.0 <= p <= 1.0 else None
    except (TypeError, ValueError):
        return None


def _parse_iso_timestamp(ts_str: Any) -> Optional[int]:
    """Safely parses ISO format timestamp string to Unix timestamp. Returns None if parsing fails."""
    if ts_str is None:
        return None
    try:
        ts_str = str(ts_str).strip()
        if ts_str.endswith('Z'):
            ts_str = ts_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(ts_str)
        ts = int(dt.timestamp())
        return ts if _TIMESTAMP_MIN <= ts <= _TIMESTAMP_MAX else None
    except (ValueError, TypeError, AttributeError):
        return None


@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis(
    market_id: str,
    research: bool = Query(default=False, description="Enable Tavily web research for news context")
):
    """
    Run AI analysis on a market with historical price data for trend visualization.
    Returns analysis text, price history data, and computed metrics.
    
    Security: All price history data is validated before returning to client.
    Market ID is strictly validated to prevent SQL injection.
    """
    if not MARKET_ID_RE.match(market_id):
        raise HTTPException(status_code=400, detail="Invalid market ID format.")

    db = get_db()
    try:
        # Safe Row conversion: explicitly select fields to avoid .get() on Row object
        market_row = db.execute(
            "SELECT id, question, volume, clob_token_id FROM markets WHERE id = ?", 
            (market_id,)
        ).fetchone()
        
        if not market_row:
            raise HTTPException(status_code=404, detail="Market not found")

        market = dict(zip(market_row.keys(), market_row))
        
        price_history_raw: List[Dict[str, Any]] = []
        price_history: List[float] = []

        # ── Primary path: CLOB history (already sorted oldest to newest) ──
        clob_token_id = market.get("clob_token_id")
        if clob_token_id:
            token_str = str(clob_token_id)
            if re.match(r'^[0-9]+$', token_str):
                history_raw = get_price_history(token_str)
                if history_raw and isinstance(history_raw, list):
                    for point in history_raw:
                        if not isinstance(point, dict):
                            continue
                        ts = _validate_timestamp(point.get("t"))
                        p = _validate_price(point.get("p"))
                        if ts is not None and p is not None:
                            price_history_raw.append({"t": ts, "p": p})
                    price_history = [h["p"] for h in price_history_raw]

        # ── Fallback: local snapshots (reverse BOTH lists to match CLOB order) ──
        if not price_history:
            raw = db.execute(
                "SELECT prices, timestamp FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 50",
                (market_id,)
            ).fetchall()
            
            temp_history: List[Dict[str, Any]] = []
            temp_prices: List[float] = []
            
            for row in raw:
                try:
                    prices_json = row['prices']
                    if not prices_json:
                        continue
                    prices = json.loads(prices_json)
                    if not isinstance(prices, list) or len(prices) == 0:
                        continue
                    price_val = _validate_price(prices[0])
                    if price_val is None:
                        continue
                    ts = _parse_iso_timestamp(row['timestamp'])
                    if ts is None:
                        continue
                    temp_history.append({"t": ts, "p": price_val})
                    temp_prices.append(price_val)
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
            
            # Reverse BOTH lists together to maintain data consistency
            price_history_raw = list(reversed(temp_history))
            price_history = list(reversed(temp_prices))

        # ── Run AI analysis ──
        if not price_history:
            raise HTTPException(status_code=404, detail="No price history available.")

        analysis = analyst.analyze_market_shift(
            market['question'],
            price_history,
            float(market['volume'] or 0),
            use_research=research
        )
        
        # ── Calculate metrics server-side ──
        metrics = {}
        if len(price_history) >= 2:
            shift_val = (price_history[-1] - price_history[0]) * 100
            metrics = {
                "shift": round(shift_val, 1),
                "high": round(max(price_history) * 100, 1),
                "low": round(min(price_history) * 100, 1),
                "points": len(price_history)
            }

        return {
            "analysis": analysis,
            "research_used": research,
            "price_history": price_history_raw,
            "metrics": metrics,
            "market_question": market['question']
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"LLM Analysis failed for {market_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="AI analysis failed.")
    finally:
        db.close()
```

### 2. Frontend Chart Integration (static/app.js)

```javascript
// ─── Chart State Management ────────────────────────────────────────────────────
let chartLoadPromise = null;
let currentChart = null;

// ─── Security: Text Sanitization ───────────────────────────────────────────────
function sanitizeHTML(str) {
    if (str === null || str === undefined) return '';
    const s = String(str);
    const escapeMap = {
        '&': '&amp;', '<': '&lt;', '>': '&gt;',
        '"': '&quot;', "'": '&#x27;', '/': '&#x2F;',
        '`': '&#x60;', '=': '&#x3D;'
    };
    return s.replace(/[&<>"'`=/]/g, char => escapeMap[char]);
}

function safeFloat(val, fallback = 0) {
    if (typeof val === 'number' && Number.isFinite(val)) return val;
    const parsed = parseFloat(val);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function safeInt(val, fallback = 0) {
    if (typeof val === 'number' && Number.isFinite(val)) return Math.floor(val);
    const parsed = parseInt(val, 10);
    return Number.isFinite(parsed) ? parsed : fallback;
}

// ─── Chart.js Loader ──────────────────────────────────────────────────────────
function loadChartJs() {
    if (window.Chart && typeof window.Chart === 'function') return Promise.resolve();
    if (chartLoadPromise) return chartLoadPromise;

    chartLoadPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
        script.crossOrigin = 'anonymous';
        script.onload = () => window.Chart ? resolve() : (chartLoadPromise = null, reject(new Error('Chart.js not available')));
        script.onerror = () => { chartLoadPromise = null; reject(new Error('Failed to load Chart.js')); };
        document.head.appendChild(script);
    });
    return chartLoadPromise;
}

// ─── Chart Management ──────────────────────────────────────────────────────────
function destroyChart() {
    if (currentChart) {
        try { currentChart.destroy(); } catch (e) { console.warn('Chart destruction error:', e); }
        currentChart = null;
    }
}

function validatePriceHistory(rawData) {
    if (!Array.isArray(rawData) || rawData.length < 2) return null;

    const validPoints = [];
    for (const point of rawData) {
        if (!point || typeof point !== 'object' || Array.isArray(point)) continue;
        const t = safeInt(point.t, 0);
        const p = safeFloat(point.p, -1);
        if (t >= 1577836800 && t <= 1893456000 && p >= 0 && p <= 1) {
            validPoints.push({ t, p: Math.round(p * 10000) / 10000 });
        }
    }

    if (validPoints.length < 2) return null;
    validPoints.sort((a, b) => a.t - b.t);
    return validPoints;
}

function prepareTrendChart(priceHistory) {
    const validPoints = validatePriceHistory(priceHistory);
    if (!validPoints) {
        return {
            html: '<div class="text-gray-500 text-xs text-center py-8">Insufficient valid price history for chart.</div>',
            data: null
        };
    }
    return {
        html: '<div class="relative h-48 mt-4"><canvas id="trendChartCanvas"></canvas></div>',
        data: validPoints
    };
}

async function initializeChart(points) {
    if (!points || points.length < 2) return;

    try {
        await loadChartJs();
    } catch (e) {
        console.error('Chart.js load failed:', e);
        return;
    }

    const canvas = document.getElementById('trendChartCanvas');
    if (!canvas) return;
    destroyChart();

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const labels = points.map(p => {
        try {
            return new Date(p.t * 1000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
        } catch { return '??:??'; }
    });

    const prices = points.map(p => Math.round(p.p * 1000) / 10);

    const firstPrice = prices[0] || 0;
    const lastPrice = prices[prices.length - 1] || 0;
    const priceDiff = lastPrice - firstPrice;

    let trendColor, trendBgColor;
    if (priceDiff > 0.5) {
        trendColor = 'rgb(52, 211, 153)';
        trendBgColor = 'rgba(52, 211, 153, 0.1)';
    } else if (priceDiff < -0.5) {
        trendColor = 'rgb(248, 113, 113)';
        trendBgColor = 'rgba(248, 113, 113, 0.1)';
    } else {
        trendColor = 'rgb(156, 163, 175)';
        trendBgColor = 'rgba(156, 163, 175, 0.1)';
    }

    try {
        currentChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'YES Probability (%)',
                    data: prices,
                    borderColor: trendColor,
                    backgroundColor: trendBgColor,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: trendColor
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 400, easing: 'easeOutQuart' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        mode: 'index', intersect: false,
                        backgroundColor: 'rgba(17, 24, 39, 0.95)',
                        titleColor: '#9ca3af', bodyColor: '#f3f4f6',
                        borderColor: 'rgba(55, 65, 81, 0.5)', borderWidth: 1,
                        padding: 12, displayColors: false,
                        callbacks: {
                            label: ctx => `Probability: ${(safeFloat(ctx.parsed?.y, 0)).toFixed(1)}%`
                        }
                    }
                },
                scales: {
                    x: {
                        display: true,
                        grid: { color: 'rgba(55, 65, 81, 0.3)', drawBorder: false },
                        ticks: { color: '#6b7280', font: { size: 10, family: 'monospace' }, maxTicksLimit: 6, maxRotation: 0 }
                    },
                    y: {
                        display: true, min: 0, max: 100,
                        grid: { color: 'rgba(55, 65, 81, 0.3)', drawBorder: false },
                        ticks: {
                            color: '#6b7280', font: { size: 10, family: 'monospace' }, stepSize: 25,
                            callback: v => safeFloat(v, 0).toFixed(0) + '%'
                        }
                    }
                },
                interaction: { mode: 'nearest', axis: 'x', intersect: false }
            }
        });
    } catch (e) {
        console.error('Chart creation failed:', e);
        destroyChart();
    }
}

// ─── Metrics Summary ──────────────────────────────────────────────────────────
function renderMetrics(metrics) {
    if (!metrics || typeof metrics !== 'object' || Object.keys(metrics).length === 0) return '';

    const shift = safeFloat(metrics.shift, 0);
    const high = safeFloat(metrics.high, 0);
    const low = safeFloat(metrics.low, 0);
    const points = safeInt(metrics.points, 0);

    const shiftClass = shift > 0 ? 'text-emerald-400' : (shift < 0 ? 'text-red-400' : 'text-gray-400');
    const shiftIcon = shift > 0 ? '↑' : (shift < 0 ? '↓' : '→');

    return `
        <div class="grid grid-cols-4 gap-2 mb-4 text-center">
            <div class="bg-gray-800/50 rounded p-2">
                <div class="text-xs text-gray-500">24h Change</div>
                <div class="font-bold ${shiftClass}">${shiftIcon} ${Math.abs(shift)}%</div>
            </div>
            <div class="bg-gray-800/50 rounded p-2">
                <div class="text-xs text-gray-500">High</div>
                <div class="font-bold text-white">${high}%</div>
            </div>
            <div class="bg-gray-800/50 rounded p-2">
                <div class="text-xs text-gray-500">Low</div>
                <div class="font-bold text-white">${low}%</div>
            </div>
            <div class="bg-gray-800/50 rounded p-2">
                <div class="text-xs text-gray-500">Data Points</div>
                <div class="font-bold text-white">${points}</div>
            </div>
        </div>`;
}

// ─── AI Analysis Modal with Chart ──────────────────────────────────────────────
async function analyzeMarket(marketId) {
    const useResearch = isResearchEnabled();
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    if (!modal || !content || !modalTitle) return;

    modal.classList.remove('hidden');
    destroyChart();

    // Safe DOM manipulation
    modalTitle.textContent = '';
    modalTitle.appendChild(document.createTextNode('🤖 PolySINT Intelligence '));
    const badge = document.createElement('span');
    badge.className = useResearch 
        ? 'text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-mono ml-2'
        : 'text-xs bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded font-mono ml-2';
    badge.textContent = useResearch ? '+ Web Research' : 'No Web Research';
    modalTitle.appendChild(badge);

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
        </div>`;

    loadChartJs().catch(() => {});

    try {
        const encodedId = encodeURIComponent(String(marketId));
        const url = `/markets/${encodedId}/ai-analysis?research=${useResearch}`;
        const res = await fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } });

        if (!res.ok) {
            let errorMsg = `HTTP ${res.status}`;
            try { const errData = await res.json(); errorMsg = errData.detail || errorMsg; } catch {}
            throw new Error(errorMsg);
        }

        const data = await res.json();

        const safeAnalysis = sanitizeHTML(data.analysis || '')
            .replace(/\*\*([^*]+)\*\*/g, '<strong class="text-white">$1</strong>')
            .replace(/\n/g, '<br>');

        const chart = prepareTrendChart(data.price_history);
        const metricsHtml = renderMetrics(data.metrics);

        content.innerHTML = `
            <div class="space-y-4">
                ${metricsHtml}
                ${chart.html}
                <div class="border-t border-gray-700/50 pt-4 mt-4">
                    <div class="text-xs text-gray-500 uppercase tracking-wide mb-2">AI Analysis</div>
                    <div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed text-gray-300">${safeAnalysis}</div>
                </div>
            </div>`;

        if (chart.data) {
            requestAnimationFrame(() => initializeChart(chart.data));
        }

    } catch (e) {
        console.error('Analysis error:', e);
        const safeError = sanitizeHTML(e.message || 'Unknown error');
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                <div class="font-bold mb-1">⚠️ Analysis Failed</div>
                <div class="text-xs text-gray-400">Error: ${safeError}</div>
                <div class="text-xs text-gray-600 mt-2">Check <code>analyzer.log</code> for details.</div>
            </div>`;
    }
}

// ─── Modal Cleanup ─────────────────────────────────────────────────────────────
function closeModal() {
    const modal = document.getElementById('aiModal');
    if (modal) modal.classList.add('hidden');
    destroyChart();
}

document.addEventListener('click', e => {
    const modal = document.getElementById('aiModal');
    if (modal && e.target === modal) closeModal();
});

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
});

window.addEventListener('beforeunload', () => destroyChart());
```

### 3. HTML Head Update (static/index.html)

```html
<head>
    <!-- Existing head content -->
    
    <!-- Content Security Policy -->
    <meta http-equiv="Content-Security-Policy" content="
        default-src 'self';
        script-src 'self' https://cdn.jsdelivr.net;
        style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
        font-src 'self' https://fonts.gstatic.com;
        img-src 'self' data: https:;
        connect-src 'self' 
            https://clob.polymarket.com 
            https://gamma-api.polymarket.com 
            https://data-api.polymarket.com
            https://api.tavily.com;
        frame-ancestors 'none';
        base-uri 'self';
        form-action 'self';
    ">
    
    <!-- Preconnect for performance -->
    <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
    
    <!-- Preload Chart.js (update SRI hash after generating with actual binary) -->
    <link rel="preload" href="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js" as="script">
</head>
```

### 4. CSS Additions (static/styles.css)

```css
@keyframes chartFadeIn {
    from { opacity: 0; transform: translateY(10px) scale(0.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
}

.metric-card {
    transition: all 0.2s ease;
}

.metric-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.2);
}
```

### Key Fixes Applied

1. **Type Safety**: `dict(zip(market_row.keys(), market_row))` prevents `AttributeError` on `sqlite3.Row` objects
2. **Data Consistency**: Both `price_history_raw` and `price_history` are reversed together in the snapshot fallback path
3. **Datetime Parsing**: `_parse_iso_timestamp()` handles both space and 'T' separators, plus timezone suffixes
4. **Security**: Comprehensive input validation, XSS prevention, strict CSP with `frame-ancestors 'none'`
5. **Memory Management**: `requestAnimationFrame` for proper DOM timing, chart cleanup on modal close and page unload
6. **Error Handling**: Defensive validation with safe fallbacks throughout the pipeline
    </synthesis_output>

    <confidence>
        0.91
    </confidence>

    <refinement_areas>
        - Generate actual SRI hash for Chart.js 4.4.1 by downloading the binary and running `openssl dgst -sha384 -binary | openssl base64 -A`
        - Consider adding chart export functionality (PNG/SVG download)
        - Add zoom/pan capabilities for longer price histories
        - Consider caching chart data in sessionStorage to reduce API calls
        - Add loading skeleton instead of spinner for better perceived performance
    </refinement_areas>

    <needs_iteration>
        false
    </needs_iteration>

    <ranking>
        <rank position="1">978</rank>
        <rank position="2">266</rank>
        <rank position="3">101</rank>
        <rank position="4">714</rank>
    </ranking>
</synthesis_output>
