I'll improve the market visualization by adding inline sparklines to each market row and a detailed interactive chart in the analysis modal. Here are the changes needed:

**1. Update `api.py`** — include price history in the market response:

```python
# In _enrich_market(), after calculating shift, add:
if history:
    m['price_history'] = [float(h["p"]) for h in history]
else:
    m['price_history'] = None
```

**2. Replace `static/index.html`** with this complete file:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PolySINT — Market Intelligence</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@400;600;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        polysint: '#10b981',
                        panel: '#0c0f14',
                        surface: '#111520',
                        line: '#1a2030',
                        dim: '#2a3040',
                    },
                    fontFamily: {
                        sans: ['DM Sans', 'system-ui', 'sans-serif'],
                        display: ['Space Grotesk', 'system-ui', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                    }
                }
            }
        }
    </script>
    <style>
        body { background: #080b10; }
        
        /* Grain overlay */
        body::before {
            content: '';
            position: fixed;
            inset: 0;
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.03'/%3E%3C/svg%3E");
            pointer-events: none;
            z-index: 0;
        }
        
        * { position: relative; z-index: 1; }
        
        /* Smooth scrollbar */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #080b10; }
        ::-webkit-scrollbar-thumb { background: #1a2030; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #2a3040; }
        
        /* Sparkline hover glow */
        .sparkline-cell:hover svg path.line { filter: drop-shadow(0 0 4px currentColor); }
        
        /* Row stagger animation */
        @keyframes fadeSlideIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .market-row { animation: fadeSlideIn 0.35s ease forwards; opacity: 0; }
        
        /* Pulse for anomaly badge */
        @keyframes anomalyPulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        .anomaly-pulse { animation: anomalyPulse 1.5s ease infinite; }
        
        /* Chart tooltip */
        .chart-tooltip {
            position: absolute;
            pointer-events: none;
            background: #111520;
            border: 1px solid #2a3040;
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 11px;
            font-family: 'JetBrains Mono', monospace;
            color: #e5e7eb;
            white-space: nowrap;
            z-index: 50;
            transform: translate(-50%, -100%);
            margin-top: -8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }
        
        /* Modal chart container */
        .chart-container {
            position: relative;
            width: 100%;
            height: 280px;
        }
    </style>
</head>
<body class="min-h-screen text-gray-300 font-sans">

    <!-- ─── Header ──────────────────────────────────────────────────── -->
    <header class="border-b border-line bg-panel/80 backdrop-blur-sm sticky top-0 z-20">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-lg bg-polysint/20 flex items-center justify-center">
                    <span class="text-polysint font-bold font-display text-sm">P</span>
                </div>
                <div>
                    <h1 class="font-display font-bold text-white text-lg tracking-tight">PolySINT</h1>
                    <p class="text-[10px] font-mono text-gray-500 tracking-widest uppercase">Market Intelligence</p>
                </div>
            </div>
            <div class="flex items-center gap-4">
                <div class="hidden sm:flex items-center gap-2 text-xs font-mono text-gray-600">
                    <span class="w-1.5 h-1.5 rounded-full bg-polysint animate-pulse"></span>
                    Live
                </div>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 py-6">

        <!-- ─── Controls ─────────────────────────────────────────────── -->
        <section class="mb-6">
            <div class="flex flex-col sm:flex-row gap-3 items-start sm:items-end">
                <!-- Search -->
                <div class="flex-1 w-full">
                    <label class="block text-[10px] font-mono text-gray-500 uppercase tracking-wider mb-1.5">Search Markets</label>
                    <div class="relative">
                        <input type="text" id="searchInput" placeholder="e.g. Bitcoin, election, rate cut..."
                            class="w-full bg-surface border border-line rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-polysint/50 focus:ring-1 focus:ring-polysint/20 transition-all">
                        <span class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 text-xs font-mono">↵</span>
                    </div>
                </div>
                
                <!-- Volume filters -->
                <div class="flex gap-2">
                    <div>
                        <label class="block text-[10px] font-mono text-gray-500 uppercase tracking-wider mb-1.5">Vol Min</label>
                        <input type="number" id="volMin" placeholder="5000"
                            class="w-24 bg-surface border border-line rounded-lg px-3 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-polysint/50 font-mono">
                    </div>
                    <div>
                        <label class="block text-[10px] font-mono text-gray-500 uppercase tracking-wider mb-1.5">Vol Max</label>
                        <input type="number" id="volMax" placeholder="∞"
                            class="w-24 bg-surface border border-line rounded-lg px-3 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-polysint/50 font-mono">
                    </div>
                </div>
                
                <!-- Research toggle -->
                <div class="flex flex-col items-start">
                    <label class="block text-[10px] font-mono text-gray-500 uppercase tracking-wider mb-1.5">Research</label>
                    <label class="flex items-center gap-2 cursor-pointer py-2">
                        <input type="checkbox" id="researchToggle" onchange="onResearchToggle()"
                            class="w-4 h-4 rounded border-line bg-surface text-polysint focus:ring-polysint/20 focus:ring-offset-0">
                        <span id="researchToggleLabel" class="text-xs font-mono text-gray-500">OFF</span>
                    </label>
                </div>
            </div>
            
            <!-- Status bar -->
            <div class="flex items-center justify-between mt-3 text-xs font-mono">
                <span id="marketCounter" class="text-gray-500"></span>
                <span id="refreshCountdown" class="text-gray-600"></span>
            </div>
        </section>

        <!-- ─── Markets Table ────────────────────────────────────────── -->
        <section class="bg-panel border border-line rounded-xl overflow-hidden">
            <div class="overflow-x-auto">
                <table class="w-full">
                    <thead>
                        <tr class="border-b border-line text-[10px] font-mono text-gray-500 uppercase tracking-wider">
                            <th class="text-left px-4 py-3 w-[40%]">Market</th>
                            <th class="text-left px-4 py-3 w-[25%]">Price History (24h)</th>
                            <th class="text-right px-4 py-3 w-[12%]">Shift</th>
                            <th class="text-right px-4 py-3 w-[10%]">Volume</th>
                            <th class="text-right px-4 py-3 w-[13%]"></th>
                        </tr>
                    </thead>
                    <tbody id="marketsTable"></tbody>
                </table>
            </div>
        </section>

        <!-- ─── Watchlist ────────────────────────────────────────────── -->
        <section class="mt-8">
            <h2 class="font-display font-semibold text-white text-sm mb-3 flex items-center gap-2">
                <span class="w-1 h-4 bg-blue-500 rounded-full"></span>
                Entity Watchlist
            </h2>
            
            <div class="bg-panel border border-line rounded-xl p-4">
                <div class="flex flex-col sm:flex-row gap-2 mb-4">
                    <input type="text" id="newAddress" placeholder="0x... proxy address"
                        class="flex-1 bg-surface border border-line rounded-lg px-3 py-2 text-sm font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50">
                    <input type="text" id="newLabel" placeholder="Label (e.g. 'Suspected Trader')"
                        class="flex-1 bg-surface border border-line rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50">
                    <button onclick="addTarget()"
                        class="bg-blue-600/20 text-blue-400 border border-blue-500/30 hover:bg-blue-600 hover:text-white px-4 py-2 rounded-lg text-sm font-medium transition-all">
                        + Track
                    </button>
                </div>
                <div id="addError" class="hidden text-red-400 text-xs font-mono mb-3"></div>
                
                <table class="w-full">
                    <thead>
                        <tr class="border-b border-line text-[10px] font-mono text-gray-500 uppercase tracking-wider">
                            <th class="text-left px-4 py-2">Target</th>
                            <th class="text-right px-4 py-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="watchlistTable"></tbody>
                </table>
            </div>
        </section>
    </main>

    <!-- ─── Modal ───────────────────────────────────────────────────── -->
    <div id="aiModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
        <div class="bg-panel border border-line rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden shadow-2xl shadow-black/50">
            <div class="flex items-center justify-between px-6 py-4 border-b border-line">
                <h3 id="aiModalTitle" class="font-display font-semibold text-white text-sm"></h3>
                <button onclick="closeModal()" class="text-gray-500 hover:text-white transition-colors text-lg leading-none">&times;</button>
            </div>
            
            <!-- Chart area (shown when opened from market row) -->
            <div id="chartSection" class="hidden px-6 pt-4">
                <div class="chart-container bg-surface rounded-lg border border-line overflow-hidden">
                    <canvas id="priceChart"></canvas>
                    <div id="chartTooltip" class="chart-tooltip hidden"></div>
                </div>
                <div id="chartStats" class="flex gap-4 mt-2 text-[10px] font-mono text-gray-500"></div>
            </div>
            
            <!-- Analysis output -->
            <div id="aiModalContent" class="p-6 overflow-y-auto max-h-[60vh]"></div>
        </div>
    </div>

    <!-- ─── App JS ──────────────────────────────────────────────────── -->
    <script>
    // ─── State ──────────────────────────────────────────────────────────────────
    let hasLoadedOnce = false;
    let refreshTimer = null;
    let refreshCountdown = 0;
    const REFRESH_INTERVAL = 300;
    const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

    // ─── Init ───────────────────────────────────────────────────────────────────
    document.addEventListener("DOMContentLoaded", () => {
        loadWatchlist();
        initResearchToggle();
        showIdleState();

        document.getElementById('searchInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const q = e.target.value.trim();
                loadMarkets(q);
            }
        });

        // Close modal on backdrop click
        document.getElementById('aiModal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('aiModal')) closeModal();
        });

        // Close modal on Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeModal();
        });
    });

    // ─── Research Toggle ────────────────────────────────────────────────────────
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
            label.textContent = 'ON';
            label.className = 'text-xs font-mono text-emerald-400';
        } else {
            label.textContent = 'OFF';
            label.className = 'text-xs font-mono text-gray-500';
        }
    }

    function isResearchEnabled() {
        return document.getElementById('researchToggle').checked;
    }

    // ─── Sparkline Generator ────────────────────────────────────────────────────
    function generateSparkline(history, width = 180, height = 40) {
        if (!history || history.length < 2) {
            return `<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
                <line x1="8" y1="${height/2}" x2="${width-8}" y2="${height/2}" stroke="#1a2030" stroke-width="1" stroke-dasharray="3,3"/>
                <text x="${width/2}" y="${height/2 + 4}" text-anchor="middle" fill="#3a4050" font-size="9" font-family="JetBrains Mono, monospace">no data</text>
            </svg>`;
        }

        const prices = history.map(Number);
        const min = Math.min(...prices);
        const max = Math.max(...prices);
        const range = max - min || 0.01;
        const padX = 6;
        const padY = 6;
        const innerW = width - padX * 2;
        const innerH = height - padY * 2;
        const n = prices.length;
        const stepX = innerW / Math.max(n - 1, 1);

        const points = prices.map((p, i) => ({
            x: padX + i * stepX,
            y: padY + innerH - ((p - min) / range) * innerH
        }));

        // Build line path
        const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

        // Build fill path (area under curve)
        const fillPath = linePath +
            ` L${(points[n-1].x).toFixed(1)},${(height - padY).toFixed(1)}` +
            ` L${(points[0].x).toFixed(1)},${(height - padY).toFixed(1)} Z`;

        // Colors based on direction
        const isUp = prices[n-1] >= prices[0];
        const lineColor = isUp ? '#10b981' : '#ef4444';
        const fillStart = isUp ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)';
        const fillEnd = isUp ? 'rgba(16,185,129,0)' : 'rgba(239,68,68,0)';
        const gradId = `sg${Math.random().toString(36).substr(2, 6)}`;
        const lastPt = points[n-1];

        return `<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg" class="sparkline-svg">
    <defs>
        <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${fillStart}"/>
            <stop offset="100%" stop-color="${fillEnd}"/>
        </linearGradient>
    </defs>
    <path d="${fillPath}" fill="url(#${gradId})" />
    <path d="${linePath}" fill="none" stroke="${lineColor}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="line" style="color:${lineColor}"/>
    <circle cx="${lastPt.x.toFixed(1)}" cy="${lastPt.y.toFixed(1)}" r="2.5" fill="${lineColor}" stroke="#0c0f14" stroke-width="1"/>
</svg>`;
    }

    // ─── Detailed Chart (Canvas) ────────────────────────────────────────────────
    function drawPriceChart(canvasId, history, marketQuestion) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !history || history.length < 2) return;

        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.parentElement.getBoundingClientRect();
        const w = rect.width;
        const h = rect.height;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';

        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, w, h);

        const prices = history.map(Number);
        const n = prices.length;
        const min = Math.min(...prices);
        const max = Math.max(...prices);
        const range = max - min || 0.01;

        const pad = { top: 20, right: 16, bottom: 28, left: 50 };
        const plotW = w - pad.left - pad.right;
        const plotH = h - pad.top - pad.bottom;

        const isUp = prices[n-1] >= prices[0];
        const mainColor = isUp ? '#10b981' : '#ef4444';
        const mainRGB = isUp ? '16,185,129' : '239,68,68';

        // ── Grid lines ──
        ctx.strokeStyle = '#1a2030';
        ctx.lineWidth = 0.5;
        const gridLines = 4;
        for (let i = 0; i <= gridLines; i++) {
            const y = pad.top + (plotH / gridLines) * i;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();

            // Price labels
            const price = max - (range / gridLines) * i;
            ctx.fillStyle = '#4a5060';
            ctx.font = '10px JetBrains Mono, monospace';
            ctx.textAlign = 'right';
            ctx.fillText((price * 100).toFixed(0) + '%', pad.left - 8, y + 3);
        }

        // ── Line & fill ──
        const stepX = plotW / Math.max(n - 1, 1);
        const points = prices.map((p, i) => ({
            x: pad.left + i * stepX,
            y: pad.top + plotH - ((p - min) / range) * plotH
        }));

        // Gradient fill
        const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
        gradient.addColorStop(0, `rgba(${mainRGB}, 0.2)`);
        gradient.addColorStop(1, `rgba(${mainRGB}, 0)`);
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        points.forEach(p => ctx.lineTo(p.x, p.y));
        ctx.lineTo(points[n-1].x, h - pad.bottom);
        ctx.lineTo(points[0].x, h - pad.bottom);
        ctx.closePath();
        ctx.fill();

        // Line
        ctx.strokeStyle = mainColor;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        points.forEach(p => ctx.lineTo(p.x, p.y));
        ctx.stroke();

        // End dot
        const endPt = points[n-1];
        ctx.fillStyle = mainColor;
        ctx.beginPath();
        ctx.arc(endPt.x, endPt.y, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#0c0f14';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Start & end labels
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.fillStyle = '#4a5060';
        ctx.textAlign = 'left';
        ctx.fillText((prices[0] * 100).toFixed(1) + '%', points[0].x, h - 8);
        ctx.textAlign = 'right';
        ctx.fillStyle = mainColor;
        ctx.fillText((prices[n-1] * 100).toFixed(1) + '%', points[n-1].x, h - 8);

        // Store points for hover
        canvas._chartPoints = points;
        canvas._chartPrices = prices;
        canvas._chartPad = pad;
        canvas._chartMainColor = mainColor;

        // ── Hover interaction ──
        const tooltip = document.getElementById('chartTooltip');
        canvas.onmousemove = (e) => {
            const r = canvas.getBoundingClientRect();
            const mx = e.clientX - r.left;
            const my = e.clientY - r.top;

            if (mx < pad.left || mx > w - pad.right || my < pad.top || my > h - pad.bottom) {
                tooltip.classList.add('hidden');
                return;
            }

            // Find nearest point
            let nearest = 0;
            let minDist = Infinity;
            points.forEach((p, i) => {
                const d = Math.abs(p.x - mx);
                if (d < minDist) { minDist = d; nearest = i; }
            });

            const pt = points[nearest];
            const price = prices[nearest];

            // Position tooltip
            tooltip.style.left = pt.x + 'px';
            tooltip.style.top = (pt.y - 20) + 'px';
            tooltip.innerHTML = `<span style="color:${mainColor}">${(price * 100).toFixed(1)}%</span>`;
            tooltip.classList.remove('hidden');

            // Redraw with crosshair
            ctx.clearRect(0, 0, w, h);
            ctx.scale(1, 1); // already scaled, just reset

            // Re-draw grid
            ctx.strokeStyle = '#1a2030';
            ctx.lineWidth = 0.5;
            for (let i = 0; i <= gridLines; i++) {
                const y = pad.top + (plotH / gridLines) * i;
                ctx.beginPath();
                ctx.moveTo(pad.left, y);
                ctx.lineTo(w - pad.right, y);
                ctx.stroke();
                const pr = max - (range / gridLines) * i;
                ctx.fillStyle = '#4a5060';
                ctx.font = '10px JetBrains Mono, monospace';
                ctx.textAlign = 'right';
                ctx.fillText((pr * 100).toFixed(0) + '%', pad.left - 8, y + 3);
            }

            // Fill & line
            ctx.fillStyle = gradient;
            ctx.beginPath();
            ctx.moveTo(points[0].x, points[0].y);
            points.forEach(p => ctx.lineTo(p.x, p.y));
            ctx.lineTo(points[n-1].x, h - pad.bottom);
            ctx.lineTo(points[0].x, h - pad.bottom);
            ctx.closePath();
            ctx.fill();

            ctx.strokeStyle = mainColor;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(points[0].x, points[0].y);
            points.forEach(p => ctx.lineTo(p.x, p.y));
            ctx.stroke();

            // Crosshair
            ctx.strokeStyle = 'rgba(255,255,255,0.15)';
            ctx.lineWidth = 0.5;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(pt.x, pad.top);
            ctx.lineTo(pt.x, h - pad.bottom);
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(pad.left, pt.y);
            ctx.lineTo(w - pad.right, pt.y);
            ctx.stroke();
            ctx.setLineDash([]);

            // Highlighted point
            ctx.fillStyle = mainColor;
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 5, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = '#0c0f14';
            ctx.lineWidth = 2;
            ctx.stroke();

            // End labels
            ctx.font = '10px JetBrains Mono, monospace';
            ctx.fillStyle = '#4a5060';
            ctx.textAlign = 'left';
            ctx.fillText((prices[0] * 100).toFixed(1) + '%', points[0].x, h - 8);
            ctx.textAlign = 'right';
            ctx.fillStyle = mainColor;
            ctx.fillText((prices[n-1] * 100).toFixed(1) + '%', points[n-1].x, h - 8);
        };

        canvas.onmouseleave = () => {
            tooltip.classList.add('hidden');
            // Redraw clean
            drawPriceChart(canvasId, history, marketQuestion);
        };

        // Chart stats
        const statsEl = document.getElementById('chartStats');
        const high = Math.max(...prices) * 100;
        const low = Math.min(...prices) * 100;
        const startPrice = prices[0] * 100;
        const endPrice = prices[n-1] * 100;
        statsEl.innerHTML = `
            <span>High: <span class="text-gray-400">${high.toFixed(1)}%</span></span>
            <span>Low: <span class="text-gray-400">${low.toFixed(1)}%</span></span>
            <span>Open: <span class="text-gray-400">${startPrice.toFixed(1)}%</span></span>
            <span>Close: <span class="${isUp ? 'text-emerald-400' : 'text-red-400'}">${endPrice.toFixed(1)}%</span></span>
            <span>Points: <span class="text-gray-400">${n}</span></span>
        `;
    }

    // ─── Idle / Empty States ────────────────────────────────────────────────────
    function showIdleState() {
        const table = document.getElementById('marketsTable');
        const counter = document.getElementById('marketCounter');
        if (counter) counter.textContent = '';

        table.innerHTML = `
        <tr>
            <td colspan="5" class="py-20 text-center">
                <div class="flex flex-col items-center space-y-4">
                    <div class="text-5xl opacity-30">📡</div>
                    <div class="text-gray-400 text-sm font-medium">Intelligence awaiting orders</div>
                    <div class="text-gray-600 text-xs max-w-xs">Search for a market above and press Enter, or load all active movers.</div>
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
            <td colspan="5" class="py-20 text-center">
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
            <td colspan="5" class="py-20 text-center">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-4xl opacity-30">🔍</div>
                    <div class="text-gray-400 text-sm">No markets found for <span class="text-white font-mono">"${query}"</span></div>
                    <div class="text-gray-600 text-xs">Try a broader term or check the harvester.</div>
                </div>
            </td>
        </tr>`;
    }

    // ─── Auto-Refresh ───────────────────────────────────────────────────────────
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

    // ─── Core: Load Markets ─────────────────────────────────────────────────────
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

                // Generate sparkline SVG
                const sparklineSvg = generateSparkline(m.price_history, 180, 40);

                let anomalyBadge = '';
                if (isAnomaly) {
                    anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/20 text-red-400 border border-red-500/40 anomaly-pulse">⚡ ANOMALY</span>`;
                } else if (isWarning) {
                    anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">⚠ WATCH</span>`;
                }

                const rowBg = isAnomaly
                    ? 'bg-red-500/[0.03] hover:bg-red-500/[0.07]'
                    : 'hover:bg-gray-800/30';

                const tr = document.createElement('tr');
                tr.className = `market-row border-b border-line/50 ${rowBg} cursor-pointer transition-colors`;
                tr.style.animationDelay = `${i * 25}ms`;
                tr.onclick = (e) => {
                    // Don't trigger if clicking the analyze button
                    if (e.target.closest('button')) return;
                    openMarketDetail(m);
                };

                tr.innerHTML = `
                    <td class="px-4 py-3.5">
                        <div class="text-sm text-gray-200 font-medium leading-snug">${m.question}</div>
                        <div class="flex items-center gap-2 mt-1">
                            <span class="text-[11px] font-mono ${shift > 0 ? 'text-emerald-500' : shift < 0 ? 'text-red-500' : 'text-gray-500'}">${currentOdds}</span>
                            ${anomalyBadge}
                        </div>
                    </td>
                    <td class="px-4 py-3.5 sparkline-cell">
                        ${sparklineSvg}
                    </td>
                    <td class="px-4 py-3.5 text-right">
                        <span class="font-mono ${shiftColor} font-bold text-sm">${shiftIcon} ${absShift}%</span>
                        <div class="text-[10px] text-gray-600 mt-0.5">24h shift</div>
                    </td>
                    <td class="px-4 py-3.5 text-right text-gray-400 text-xs font-mono">${formatter.format(m.volume)}</td>
                    <td class="px-4 py-3.5 text-right">
                        <button onclick="analyzeMarket('${m.id}')"
                            class="bg-polysint/10 text-polysint border border-polysint/20 hover:bg-polysint hover:text-gray-900 px-3 py-1.5 rounded-md text-xs font-medium transition-all whitespace-nowrap">
                            Analyze
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
                <tr><td colspan="5" class="text-center py-10">
                    <div class="flex flex-col items-center space-y-3">
                        <div class="text-3xl">⚠️</div>
                        <div class="text-red-400 text-sm">Failed to load markets.</div>
                        <div class="text-gray-600 text-xs">Is the backend running? Check <code class="bg-surface px-1.5 py-0.5 rounded">analyzer.log</code>.</div>
                        <button onclick="loadMarkets('${searchQuery}')" class="mt-2 text-xs text-polysint underline">Retry</button>
                    </div>
                </td></tr>`;
        }
    }

    // ─── Market Detail (click row → chart + analysis) ───────────────────────────
    async function openMarketDetail(m) {
        const modal = document.getElementById('aiModal');
        const chartSection = document.getElementById('chartSection');
        const content = document.getElementById('aiModalContent');
        const modalTitle = document.getElementById('aiModalTitle');

        modal.classList.remove('hidden');
        modalTitle.textContent = m.question;

        // Show chart if we have history
        if (m.price_history && m.price_history.length >= 2) {
            chartSection.classList.remove('hidden');
            // Small delay to let modal render so canvas gets correct dimensions
            requestAnimationFrame(() => {
                drawPriceChart('priceChart', m.price_history, m.question);
            });
        } else {
            chartSection.classList.add('hidden');
        }

        // Pre-fill with a prompt to analyze
        content.innerHTML = `
            <div class="flex flex-col items-center space-y-4 py-8">
                <div class="text-center">
                    <div class="text-sm text-gray-400 mb-1">Current Odds: <span class="text-white font-mono font-bold">${m.current_price != null ? Math.round(m.current_price * 100) + '%' : 'N/A'}</span></div>
                    <div class="text-sm text-gray-400">24h Shift: <span class="${(m.shift || 0) > 0 ? 'text-emerald-400' : 'text-red-400'} font-mono font-bold">${m.shift || 0}%</span></div>
                    <div class="text-xs text-gray-600 mt-1">Volume: ${formatter.format(m.volume)}</div>
                </div>
                <button onclick="analyzeMarket('${m.id}')"
                    class="bg-polysint text-gray-900 font-bold px-6 py-2.5 rounded-lg text-sm hover:bg-emerald-400 transition-all shadow-lg shadow-emerald-900/30">
                    🤖 Run AI Analysis
                </button>
                <p class="text-[10px] text-gray-600 font-mono">Hover the chart above to inspect price points</p>
            </div>`;
    }

    // ─── AI Analysis ────────────────────────────────────────────────────────────
    async function analyzeMarket(marketId) {
        const useResearch = isResearchEnabled();
        const modal = document.getElementById('aiModal');
        const content = document.getElementById('aiModalContent');
        const chartSection = document.getElementById('chartSection');

        // If modal isn't open, open it
        modal.classList.remove('hidden');
        if (!document.getElementById('aiModalTitle').textContent) {
            document.getElementById('aiModalTitle').innerHTML = '🤖 PolySINT Intelligence';
        }

        const researchTag = useResearch
            ? '<span class="text-[10px] bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-mono ml-2">+ Web Research</span>'
            : '<span class="text-[10px] bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded font-mono ml-2">No Web Research</span>';

        content.innerHTML = `
            <div class="flex flex-col items-center justify-center space-y-3 py-12">
                <div class="flex space-x-1">
                    <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
                    <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                    <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
                </div>
                <div class="text-polysint text-sm animate-pulse">
                    ${useResearch ? 'Scanning web + running forensic analysis...' : 'Running forensic analysis...'}
                </div>
                ${researchTag}
            </div>`;

        try {
            const url = `/markets/${marketId}/ai-analysis?research=${useResearch}`;
            const res = await fetch(url);
            if (!res.ok) throw new Error("AI Analysis Failed");
            const data = await res.json();

            const formatted = data.analysis
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/\n/g, '<br>');

            content.innerHTML = `
                <div class="p-4 border-l-2 border-polysint bg-surface/50 rounded-r-lg leading-relaxed text-sm text-gray-300">
                    ${formatted}
                </div>`;
        } catch (e) {
            content.innerHTML = `
                <div class="text-red-400 bg-red-900/20 p-4 rounded-lg border border-red-800/50 text-sm">
                    <div class="font-semibold mb-1">⚠️ Analysis Failed</div>
                    <span class="text-xs text-gray-500">Check your LLM API key and <code class="bg-panel px-1 rounded">analyzer.log</code>.</span>
                </div>`;
        }
    }

    // ─── Wallet / Entity ────────────────────────────────────────────────────────
    async function profileEntity(address, label) {
        const modal = document.getElementById('aiModal');
        const content = document.getElementById('aiModalContent');
        const modalTitle = document.getElementById('aiModalTitle');
        const chartSection = document.getElementById('chartSection');

        modal.classList.remove('hidden');
        chartSection.classList.add('hidden');
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
                <div class="mb-4 p-3 bg-surface rounded-lg border border-line font-mono text-xs text-gray-400 space-y-1">
                    <div><span class="text-gray-600">Proxy:</span> ${address}</div>
                    <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${data.real_owner}</span></div>
                </div>
                <div class="p-4 border-l-2 border-blue-500 bg-surface/50 rounded-r-lg leading-relaxed text-sm text-gray-300">
                    ${formatted}
                </div>`;
        } catch (e) {
            content.innerHTML = `<div class="text-red-400 bg-red-900/20 p-4 rounded-lg border border-red-800/50 text-sm">⚠️ Could not generate entity profile.</div>`;
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

    // ─── Watchlist ──────────────────────────────────────────────────────────────
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
                    <tr><td colspan="2" class="text-center py-8 text-gray-600 text-sm italic px-4">
                        Watchlist empty.<br>
                        <span class="text-xs">Add a target's 0x proxy address above.</span>
                    </td></tr>`;
                return;
            }

            watchlist.forEach(w => {
                const shortAddr = w.address.substring(0, 6) + '…' + w.address.substring(w.address.length - 4);
                const tr = document.createElement('tr');
                tr.className = "hover:bg-gray-800/30 transition-colors border-b border-line/50";
                tr.innerHTML = `
                    <td class="px-4 py-3">
                        <div class="font-semibold text-gray-200 text-sm">${w.label}</div>
                        <div class="text-xs font-mono text-gray-500 mt-0.5">${shortAddr}</div>
                        <div class="text-xs font-mono text-polysint mt-0.5 hidden" id="real-${w.address}"></div>
                    </td>
                    <td class="px-4 py-3 text-right">
                        <div class="flex justify-end items-center gap-1.5 flex-wrap">
                            <button onclick="unmaskWallet('${w.address}')" id="btn-${w.address}"
                                class="bg-gray-800 border border-gray-600 text-gray-300 hover:bg-gray-700 px-2.5 py-1 rounded-md text-xs transition-all">
                                Unmask
                            </button>
                            <button onclick="profileEntity('${w.address}', '${w.label}')"
                                class="bg-blue-900/40 text-blue-400 border border-blue-800/60 hover:bg-blue-800 hover:text-white px-2.5 py-1 rounded-md text-xs transition-all">
                                AI Profile
                            </button>
                            <button onclick="deleteTarget('${w.address}')" title="Stop Tracking"
                                class="bg-red-900/30 text-red-400 border border-red-800/60 hover:bg-red-800 hover:text-white px-2.5 py-1 rounded-md text-xs transition-all">
                                ✕
                            </button>
                        </div>
                    </td>`;
                table.appendChild(tr);
            });
        } catch (e) {
            table.innerHTML = `<tr><td colspan="2" class="text-center py-8 text-red-400 text-sm">Failed to load watchlist.</td></tr>`;
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
        document.getElementById('chartSection').classList.add('hidden');
    }
    </script>
</body>
</html>
```

**3. Updated `api.py`** — add `price_history` to market responses:

```python
# ... all existing imports and setup stay the same ...

def _enrich_market(m: dict) -> dict | None:
    """
    Fetches CLOB history for a single market and attaches shift, current_price,
    and price_history for sparkline rendering.
    Returns None if the market should be excluded (settled or no data).
    """
    clob_token_id = m.get("clob_token_id")
    m['shift'] = 0.0
    m['current_price'] = None
    m['price_history'] = None

    if clob_token_id:
        history = get_price_history(clob_token_id)
        if history:
            m['price_history'] = [float(h["p"]) for h in history]
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
                if prices and len(prices) >= 1:
                    val = float(prices[0])
                    m['current_price'] = val
                    # For snapshot fallback, try to build history from multiple snapshots
                    db2 = get_db()
                    snaps = db2.execute(
                        "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 24",
                        (m['id'],)
                    ).fetchall()
                    db2.close()
                    hist = []
                    for s in reversed(snaps):
                        try:
                            p = json.loads(s['prices'])
                            if p:
                                hist.append(float(p[0]))
                        except Exception:
                            pass
                    if len(hist) >= 2:
                        m['price_history'] = hist
        except Exception:
            pass

    # Drop settled markets
    if m['current_price'] is not None:
        if m['current_price'] > 0.98 or m['current_price'] < 0.02:
            return None

    return m


# The rest of api.py stays exactly the same — search_markets, watchlist endpoints, etc.
```

---

### What changed

**Sparklines (inline SVG)** — every market row now shows a miniature price chart. The sparkline renders as an SVG `<path>` with a gradient fill underneath, colored green for upward moves and red for downward. A dot marks the current price. These are generated client-side with `generateSparkline()` — no external charting library needed.

**5-column layout** — the table now has a dedicated column for price history between the market question and shift, giving the visual room to breathe. The market question column shows the current odds and anomaly badges beneath the title.

**Interactive detail chart (Canvas)** — clicking any market row opens a modal with a full-size canvas chart showing the complete 24h price trajectory. Hover anywhere on the chart to see a crosshair and tooltip with the exact price at that point. Stats (high, low, open, close) are shown below the chart.

**Click-to-analyze flow** — the row click opens the detail view with chart; the "Analyze" button triggers the AI analysis within that same modal, so you see the chart context alongside the intelligence brief.

**No new dependencies** — all visualization is pure SVG (sparklines) and Canvas API (detail chart). No Chart.js, D3, or other libraries required.
