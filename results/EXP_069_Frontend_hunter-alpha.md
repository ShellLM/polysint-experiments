Looking at the codebase, errors currently use a mix of `alert()`, inline divs, and table-row replacements. I'll build a polished toast notification system that unifies all of this into a clean, animated experience.

```html
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PolySINT — Prediction Market Intelligence</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        polysint: '#34d399',
                        'polysint-dim': '#065f46',
                        surface: '#111318',
                        panel: '#161920',
                        'panel-hover': '#1c2029',
                        ink: '#e2e4e9',
                        'ink-muted': '#6b7280',
                        'ink-faint': '#374151',
                    },
                    fontFamily: {
                        sans: ['Space Grotesk', 'system-ui', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                    }
                }
            }
        }
    </script>
    <style>
        body { background: #0c0e12; }

        /* ── Scrollbar ── */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #1f2937; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #374151; }

        /* ── Modal ── */
        .modal-backdrop {
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
        }

        /* ── Table row stagger ── */
        .markets-table tr {
            animation: rowIn 0.25s ease both;
        }
        @keyframes rowIn {
            from { opacity: 0; transform: translateY(6px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        /* ── Anomaly pulse ── */
        @keyframes anomalyGlow {
            0%, 100% { box-shadow: inset 0 0 0 0 transparent; }
            50%      { box-shadow: inset 3px 0 0 0 rgba(239, 68, 68, 0.4); }
        }
        .anomaly-row {
            animation: anomalyGlow 2.5s ease-in-out infinite;
        }

        /* ── Toast animations ── */
        @keyframes toastIn {
            from {
                opacity: 0;
                transform: translateX(100%) scale(0.95);
            }
            to {
                opacity: 1;
                transform: translateX(0) scale(1);
            }
        }

        @keyframes toastOut {
            from {
                opacity: 1;
                transform: translateX(0) scale(1);
            }
            to {
                opacity: 0;
                transform: translateX(100%) scale(0.95);
            }
        }

        @keyframes toastProgress {
            from { width: 100%; }
            to   { width: 0%; }
        }

        .toast-enter {
            animation: toastIn 0.35s cubic-bezier(0.21, 1.02, 0.73, 1) forwards;
        }

        .toast-exit {
            animation: toastOut 0.3s cubic-bezier(0.06, 0.71, 0.55, 1) forwards;
        }

        .toast-progress {
            animation: toastProgress var(--duration, 5s) linear forwards;
        }

        /* ── Inline error fade ── */
        @keyframes inlineFadeIn {
            from { opacity: 0; transform: translateY(-4px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .inline-msg {
            animation: inlineFadeIn 0.2s ease forwards;
        }
    </style>
</head>
<body class="min-h-screen text-ink font-sans antialiased">

    <!-- ════════════════════════════════════════════════════════════════════
         TOAST CONTAINER
    ════════════════════════════════════════════════════════════════════ -->
    <div id="toastContainer" class="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-[380px] max-w-[calc(100vw-2rem)] pointer-events-none">
    </div>

    <!-- ════════════════════════════════════════════════════════════════════
         HEADER
    ════════════════════════════════════════════════════════════════════ -->
    <header class="border-b border-gray-800/60 bg-surface/80 backdrop-blur-md sticky top-0 z-40">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-lg bg-polysint/10 border border-polysint/30 flex items-center justify-center">
                    <span class="text-polysint text-sm font-bold font-mono">P</span>
                </div>
                <div>
                    <h1 class="text-base font-bold tracking-tight text-white leading-none">PolySINT</h1>
                    <p class="text-[10px] text-ink-muted font-mono tracking-widest uppercase mt-0.5">Prediction Market Intelligence</p>
                </div>
            </div>

            <div class="flex items-center gap-3">
                <!-- Research Toggle -->
                <label class="flex items-center gap-2 cursor-pointer select-none">
                    <input type="checkbox" id="researchToggle" onchange="onResearchToggle()" class="sr-only peer">
                    <div class="w-8 h-4 bg-gray-700 rounded-full peer-checked:bg-polysint/30 relative transition-colors after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-3 after:h-3 after:bg-gray-400 after:rounded-full peer-checked:after:bg-polysint peer-checked:after:translate-x-4 after:transition-all"></div>
                    <span id="researchToggleLabel" class="text-xs text-gray-500 font-mono">Web Research: OFF</span>
                </label>
            </div>
        </div>
    </header>

    <!-- ════════════════════════════════════════════════════════════════════
         MAIN LAYOUT
    ════════════════════════════════════════════════════════════════════ -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 py-6 grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6">

        <!-- ── Left: Markets ── -->
        <section>
            <!-- Search Bar -->
            <div class="flex gap-2 mb-4">
                <div class="flex-1 relative">
                    <input type="text" id="searchInput" placeholder="Search markets... (press Enter)"
                        class="w-full bg-panel border border-gray-700/60 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-polysint/50 focus:ring-1 focus:ring-polysint/20 transition-colors font-mono">
                </div>
                <button onclick="loadMarkets(document.getElementById('searchInput').value.trim())"
                    class="bg-polysint text-gray-900 font-bold px-5 py-2.5 rounded-lg text-sm hover:bg-emerald-400 transition-all shadow-lg shadow-emerald-900/20">
                    Scan
                </button>
            </div>

            <!-- Volume Filters -->
            <div class="flex items-center gap-3 mb-4 text-xs">
                <span class="text-ink-muted font-mono">VOL $</span>
                <input type="number" id="volMin" placeholder="min" min="0"
                    class="w-24 bg-panel border border-gray-700/60 rounded px-2 py-1 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-polysint/40 font-mono">
                <span class="text-ink-faint">→</span>
                <input type="number" id="volMax" placeholder="max" min="0"
                    class="w-24 bg-panel border border-gray-700/60 rounded px-2 py-1 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-polysint/40 font-mono">
                <span id="marketCounter" class="ml-auto text-ink-muted font-mono"></span>
                <span id="refreshCountdown" class="text-ink-faint font-mono"></span>
            </div>

            <!-- Markets Table -->
            <div class="bg-panel rounded-xl border border-gray-800/60 overflow-hidden">
                <table class="w-full text-left markets-table">
                    <thead>
                        <tr class="border-b border-gray-800/80">
                            <th class="px-4 py-3 text-[10px] uppercase tracking-widest text-ink-muted font-semibold">Market</th>
                            <th class="px-4 py-3 text-[10px] uppercase tracking-widest text-ink-muted font-semibold w-28">24h Shift</th>
                            <th class="px-4 py-3 text-[10px] uppercase tracking-widest text-ink-muted font-semibold w-24">Volume</th>
                            <th class="px-4 py-3 text-[10px] uppercase tracking-widest text-ink-muted font-semibold w-28 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody id="marketsTable"></tbody>
                </table>
            </div>
        </section>

        <!-- ── Right: Watchlist ── -->
        <aside>
            <div class="bg-panel rounded-xl border border-gray-800/60 overflow-hidden sticky top-20">
                <div class="px-4 py-3 border-b border-gray-800/60">
                    <h2 class="text-xs font-bold uppercase tracking-widest text-ink-muted">Watchlist</h2>
                </div>

                <!-- Add Form -->
                <div class="px-4 py-3 border-b border-gray-800/60 space-y-2">
                    <input type="text" id="newAddress" placeholder="0x... proxy address"
                        class="w-full bg-surface border border-gray-700/60 rounded px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-polysint/40 font-mono">
                    <div class="flex gap-2">
                        <input type="text" id="newLabel" placeholder="Label (e.g. 'Whale #3')"
                            class="flex-1 bg-surface border border-gray-700/60 rounded px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-polysint/40">
                        <button onclick="addTarget()"
                            class="bg-polysint/10 text-polysint border border-polysint/30 hover:bg-polysint hover:text-gray-900 px-3 py-2 rounded text-xs font-semibold transition-all">
                            + Add
                        </button>
                    </div>
                    <div id="addError" class="hidden text-xs text-red-400 bg-red-900/20 px-3 py-1.5 rounded border border-red-800/40 inline-msg"></div>
                </div>

                <!-- Watchlist Table -->
                <table class="w-full text-left">
                    <tbody id="watchlistTable"></tbody>
                </table>
            </div>
        </aside>
    </main>

    <!-- ════════════════════════════════════════════════════════════════════
         AI ANALYSIS MODAL
    ════════════════════════════════════════════════════════════════════ -->
    <div id="aiModal" class="hidden fixed inset-0 z-50 modal-backdrop flex items-center justify-center p-4">
        <div class="bg-panel border border-gray-700/60 rounded-2xl max-w-2xl w-full max-h-[85vh] overflow-y-auto shadow-2xl">
            <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800/60">
                <h3 id="aiModalTitle" class="text-sm font-bold text-white"></h3>
                <button onclick="closeModal()" class="text-gray-500 hover:text-white transition-colors text-lg leading-none">&times;</button>
            </div>
            <div id="aiModalContent" class="p-5 text-sm text-gray-300 leading-relaxed"></div>
        </div>
    </div>

    <!-- ════════════════════════════════════════════════════════════════════
         JAVASCRIPT
    ════════════════════════════════════════════════════════════════════ -->
    <script>
    // ─── Toast System ──────────────────────────────────────────────────────────

    const TOAST_ICONS = {
        error:   `<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/></svg>`,
        success: `<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>`,
        warning: `<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z"/></svg>`,
        info:    `<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"/></svg>`,
    };

    const TOAST_STYLES = {
        error:   { bg: 'bg-red-950/80', border: 'border-red-800/60', icon: 'text-red-400', text: 'text-red-200', bar: 'bg-red-500/60' },
        success: { bg: 'bg-emerald-950/80', border: 'border-emerald-800/60', icon: 'text-emerald-400', text: 'text-emerald-200', bar: 'bg-emerald-500/60' },
        warning: { bg: 'bg-amber-950/80', border: 'border-amber-800/60', icon: 'text-amber-400', text: 'text-amber-200', bar: 'bg-amber-500/60' },
        info:    { bg: 'bg-blue-950/80', border: 'border-blue-800/60', icon: 'text-blue-400', text: 'text-blue-200', bar: 'bg-blue-500/60' },
    };

    /**
     * Show a toast notification.
     * @param {'error'|'success'|'warning'|'info'} type
     * @param {string} title
     * @param {string} message
     * @param {object} opts - { duration: ms (default 5000, 0 = persistent), action: { label, onClick } }
     * @returns {string} toastId for manual dismissal
     */
    function showToast(type, title, message, opts = {}) {
        const container = document.getElementById('toastContainer');
        const id = 'toast-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
        const duration = opts.duration !== undefined ? opts.duration : 5000;
        const style = TOAST_STYLES[type] || TOAST_STYLES.info;
        const icon = TOAST_ICONS[type] || TOAST_ICONS.info;

        const toast = document.createElement('div');
        toast.id = id;
        toast.className = `pointer-events-auto ${style.bg} ${style.border} border rounded-lg shadow-xl shadow-black/30 overflow-hidden toast-enter`;
        toast.style.setProperty('--duration', duration + 'ms');

        let actionBtn = '';
        if (opts.action) {
            actionBtn = `
                <button onclick="${opts.action.onClick}" class="ml-3 text-xs font-semibold ${style.icon} hover:underline whitespace-nowrap">
                    ${opts.action.label}
                </button>`;
        }

        toast.innerHTML = `
            <div class="flex items-start gap-3 px-4 py-3">
                <div class="${style.icon} mt-0.5 flex-shrink-0">${icon}</div>
                <div class="flex-1 min-w-0">
                    <div class="text-xs font-bold ${style.text}">${title}</div>
                    <div class="text-xs text-gray-400 mt-0.5 leading-relaxed">${message}</div>
                </div>
                <button onclick="dismissToast('${id}')" class="text-gray-500 hover:text-gray-300 flex-shrink-0 transition-colors mt-0.5">
                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>
                </button>
                ${actionBtn}
            </div>
            ${duration > 0 ? `<div class="h-0.5 bg-gray-800/50"><div class="h-full ${style.bar} toast-progress" id="${id}-bar"></div></div>` : ''}
        `;

        container.appendChild(toast);

        if (duration > 0) {
            setTimeout(() => dismissToast(id), duration);
        }

        return id;
    }

    /**
     * Dismiss a toast with animation.
     */
    function dismissToast(id) {
        const toast = document.getElementById(id);
        if (!toast) return;

        toast.classList.remove('toast-enter');
        toast.classList.add('toast-exit');
        toast.addEventListener('animationend', () => toast.remove(), { once: true });
    }

    /**
     * Convenience wrappers.
     */
    function toastError(title, message, opts)   { return showToast('error', title, message, opts); }
    function toastSuccess(title, message, opts) { return showToast('success', title, message, opts); }
    function toastWarning(title, message, opts) { return showToast('warning', title, message, opts); }
    function toastInfo(title, message, opts)    { return showToast('info', title, message, opts); }

    // ─── State ────────────────────────────────────────────────────────────────
    let hasLoadedOnce = false;
    let refreshTimer = null;
    let refreshCountdown = 0;
    const REFRESH_INTERVAL = 300; // 5 minutes

    // ─── Init ─────────────────────────────────────────────────────────────────
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
    });

    // ─── Research Toggle ──────────────────────────────────────────────────────
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

    // ─── Idle / Empty States ──────────────────────────────────────────────────
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

    // ─── Auto-Refresh ─────────────────────────────────────────────────────────
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

    // ─── Core: Load Markets ───────────────────────────────────────────────────
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
            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            const markets = await res.json();
            hasLoadedOnce = true;

            const counter = document.getElementById('marketCounter');
            if (counter) counter.textContent = markets.length > 0 ? `${markets.length} markets` : '';

            const table = document.getElementById('marketsTable');
            table.innerHTML = '';

            if (markets.length === 0) {
                showEmptySearchState(searchQuery || 'active markets');
                if (!silent) toastInfo('No Results', `No markets matched your query.`, { duration: 4000 });
                return;
            }

            if (!silent) {
                toastSuccess('Markets Loaded', `${markets.length} markets fetched successfully.`, { duration: 3000 });
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

                const rowHighlight = isAnomaly ? 'anomaly-row hover:bg-red-500/10' : 'hover:bg-gray-700/30';

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

            toastError('Connection Failed', `Could not reach backend. ${e.message}`, {
                duration: 8000,
                action: {
                    label: 'Retry',
                    onClick: `loadMarkets('${searchQuery}')`
                }
            });
        }
    }

    // ─── AI Analysis Modal ────────────────────────────────────────────────────
    let analysisToastId = null;

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

        // Show an info toast for long-running analysis
        analysisToastId = toastInfo('Analysis Running', useResearch ? 'LLM + web research in progress...' : 'LLM analysis in progress...', {
            duration: 0 // persistent until dismissed
        });

        try {
            const url = `/markets/${marketId}/ai-analysis?research=${useResearch}`;
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            const formatted = data.analysis
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/\n/g, '<br>');

            content.innerHTML = `<div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;

            // Dismiss the running toast, show success
            if (analysisToastId) dismissToast(analysisToastId);
            toastSuccess('Analysis Complete', 'Intelligence brief generated.', { duration: 3000 });

        } catch (e) {
            content.innerHTML = `
                <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                    ⚠️ Could not generate intelligence brief.<br>
                    <span class="text-xs text-gray-500 mt-1 block">Check your LLM API key and <code>analyzer.log</code>.</span>
                </div>`;

            if (analysisToastId) dismissToast(analysisToastId);
            toastError('Analysis Failed', `LLM request failed: ${e.message}`, {
                duration: 8000,
                action: {
                    label: 'Retry',
                    onClick: `analyzeMarket('${marketId}')`
                }
            });
        }
    }

    // ─── Wallet / Entity ──────────────────────────────────────────────────────
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

        const profileToastId = toastInfo('Profiling Entity', `Fetching trade history for ${label}...`, { duration: 0 });

        try {
            const res = await fetch(`/wallets/${address}/profile`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
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

            dismissToast(profileToastId);
            toastSuccess('Profile Ready', `Entity profile for ${label} generated.`, { duration: 3000 });

        } catch (e) {
            content.innerHTML = `<div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">⚠️ Could not generate entity profile.</div>`;
            dismissToast(profileToastId);
            toastError('Profiling Failed', `Could not profile ${label}: ${e.message}`, { duration: 6000 });
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
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            realDiv.classList.remove("hidden");
            realDiv.innerHTML = `EOA: <span class="text-polysint">${data.real_owner}</span>`;
            btn.textContent = "✓ Unmasked";
            btn.classList.remove("border-gray-600", "text-gray-300", "hover:bg-gray-700");
            btn.classList.add("bg-gray-700", "text-gray-500", "border-transparent", "cursor-default");

            toastSuccess('Wallet Unmasked', `Resolved to ${data.real_owner.substring(0, 10)}...`, { duration: 4000 });

        } catch (e) {
            btn.disabled = false;
            btn.textContent = "Retry";
            btn.classList.remove("opacity-50", "cursor-not-allowed");

            toastError('Unmask Failed', `Could not resolve proxy address. Check RPC config.`, {
                duration: 6000,
                action: {
                    label: 'Retry',
                    onClick: `unmaskWallet('${address}')`
                }
            });
        }
    }

    // ─── Watchlist ────────────────────────────────────────────────────────────
    async function addTarget() {
        const addressInput = document.getElementById('newAddress');
        const labelInput = document.getElementById('newLabel');
        const address = addressInput.value.trim();
        const label = labelInput.value.trim();
        const errorEl = document.getElementById('addError');

        if (!address || !label) {
            errorEl.textContent = 'Both address and label are required.';
            errorEl.classList.remove('hidden');
            errorEl.className = 'text-xs text-amber-400 bg-amber-900/20 px-3 py-1.5 rounded border border-amber-800/40 inline-msg';
            toastWarning('Missing Fields', 'Enter both a wallet address and a label.', { duration: 4000 });
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
                errorEl.classList.add('hidden');
                loadWatchlist();
                toastSuccess('Target Added', `"${label}" is now being tracked.`, { duration: 4000 });
            } else {
                errorEl.textContent = data.detail || 'Failed to add target.';
                errorEl.classList.remove('hidden');
                errorEl.className = 'text-xs text-red-400 bg-red-900/20 px-3 py-1.5 rounded border border-red-800/40 inline-msg';
                toastError('Add Failed', data.detail || 'Could not add target to watchlist.', { duration: 6000 });
            }
        } catch (e) {
            errorEl.textContent = 'Network error. Is the backend running?';
            errorEl.classList.remove('hidden');
            errorEl.className = 'text-xs text-red-400 bg-red-900/20 px-3 py-1.5 rounded border border-red-800/40 inline-msg';
            toastError('Network Error', 'Could not connect to the backend.', {
                duration: 6000,
                action: {
                    label: 'Retry',
                    onClick: 'addTarget()'
                }
            });
        }
    }

    async function loadWatchlist() {
        const table = document.getElementById('watchlistTable');
        try {
            const res = await fetch('/watchlist');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
                            <button onclick="deleteTarget('${w.address}', '${w.label}')" title="Stop Tracking"
                                class="bg-red-900/30 text-red-400 border border-red-800 hover:bg-red-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                                ✕
                            </button>
                        </div>
                    </td>`;
                table.appendChild(tr);
            });
        } catch (e) {
            table.innerHTML = `<tr><td class="text-center py-8 text-red-400 text-sm">Failed to load watchlist.</td></tr>`;
            toastError('Watchlist Error', 'Could not load watchlist from backend.', { duration: 5000 });
        }
    }

    async function deleteTarget(address, label) {
        if (!confirm(`Stop tracking "${label}"?`)) return;
        try {
            const res = await fetch(`/watchlist/${address}`, { method: 'DELETE' });
            if (res.ok) {
                loadWatchlist();
                toastSuccess('Target Removed', `"${label}" removed from watchlist.`, { duration: 3000 });
            } else {
                toastError('Delete Failed', `Could not remove "${label}".`, { duration: 5000 });
            }
        } catch (e) {
            toastError('Network Error', 'Could not reach backend to delete target.', {
                duration: 5000,
                action: {
                    label: 'Retry',
                    onClick: `deleteTarget('${address}', '${label}')`
                }
            });
        }
    }

    function closeModal() {
        document.getElementById('aiModal').classList.add('hidden');
    }

    document.addEventListener('click', (e) => {
        const modal = document.getElementById('aiModal');
        if (e.target === modal) closeModal();
    });
    </script>
</body>
</html>
```

Here's what changed and why:

**Toast notification system** — A new `showToast(type, title, message, opts)` engine that renders animated toasts in the top-right corner. Four types: `error`, `success`, `warning`, `info` — each with distinct color treatment (red, emerald, amber, blue), an SVG icon, a progress bar that counts down, and a dismiss button.

**Key features:**
- **Animated entrance/exit** — slides in from the right with a spring curve, slides out on dismiss. No jarring pops.
- **Persistent mode** — long-running operations (AI analysis, entity profiling) use `duration: 0` so the toast stays until the operation completes, then gets replaced by a success/error toast.
- **Action buttons** — error toasts include a "Retry" action that re-triggers the failed function, so users don't have to hunt for the button again.
- **Auto-dismiss** — most toasts auto-dismiss after 4-8 seconds with a visual progress bar showing remaining time.

**Every error path now uses toasts instead of `alert()`:**
- Market loading failure → red error toast with Retry action
- AI analysis failure → error toast, persistent "running" toast gets dismissed
- Entity profiling failure → error toast
- Unmask wallet failure → error toast (was `alert()`)
- Watchlist add validation → amber warning toast + inline styled message
- Watchlist add network error → error toast with Retry
- Delete target failure → error toast (was `alert()`)
- Success operations (add, delete, unmask, load) → green success toasts

The inline error divs for the watchlist form still exist (they provide immediate visual context next to the input), but now they're styled with `inline-msg` animation and also trigger a toast for consistency.
