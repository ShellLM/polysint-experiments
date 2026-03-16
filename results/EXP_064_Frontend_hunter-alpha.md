I'll enhance the loading indicators and add skeleton screens to `app.js` for a more polished, professional experience.

```javascript
// static/app.js - Enhanced with skeleton screens and improved loading states

// ─── State ────────────────────────────────────────────────────────────────────
let hasLoadedOnce = false;
let refreshTimer = null;
let refreshCountdown = 0;
const REFRESH_INTERVAL = 300; // 5 minutes

// ─── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadWatchlist();
    initResearchToggle();
    showMarketSkeleton(); // Show skeleton on initial load

    // Search only fires on Enter
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

// ─── Skeleton Screens & Loading States ────────────────────────────────────────
function showMarketSkeleton() {
    const table = document.getElementById('marketsTable');
    const counter = document.getElementById('marketCounter');
    if (counter) counter.textContent = 'Loading...';

    // Create skeleton rows with staggered animation delays
    const skeletonRows = Array(5).fill().map((_, i) => {
        return `
            <tr class="border-b border-gray-700/50 animate-pulse" style="animation-delay: ${i * 100}ms">
                <td class="px-4 py-4">
                    <div class="h-4 bg-gray-700/50 rounded w-3/4 mb-2"></div>
                    <div class="h-3 bg-gray-700/30 rounded w-1/2"></div>
                </td>
                <td class="px-4 py-4">
                    <div class="h-4 bg-gray-700/50 rounded w-16 mb-1"></div>
                    <div class="h-2 bg-gray-700/30 rounded w-8"></div>
                </td>
                <td class="px-4 py-4">
                    <div class="h-4 bg-gray-700/50 rounded w-20"></div>
                </td>
                <td class="px-4 py-4 text-right">
                    <div class="h-8 bg-gray-700/50 rounded w-20 ml-auto"></div>
                </td>
            </tr>`;
    }).join('');

    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-8">
                <div class="flex items-center justify-between mb-4 px-4">
                    <div class="h-4 bg-gray-700/50 rounded w-32"></div>
                    <div class="h-8 bg-gray-700/50 rounded w-24"></div>
                </div>
            </td>
        </tr>
        ${skeletonRows}
        <tr>
            <td colspan="4" class="py-4 text-center">
                <div class="flex items-center justify-center space-x-2 text-gray-500 text-sm">
                    <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Scanning Polymarket feeds...</span>
                </div>
            </td>
        </tr>`;
}

function showWatchlistSkeleton() {
    const table = document.getElementById('watchlistTable');
    table.innerHTML = Array(3).fill().map((_, i) => {
        return `
            <tr class="border-b border-gray-700/50 animate-pulse" style="animation-delay: ${i * 100}ms">
                <td class="px-4 py-3">
                    <div class="h-4 bg-gray-700/50 rounded w-24 mb-2"></div>
                    <div class="h-3 bg-gray-700/30 rounded w-32"></div>
                </td>
                <td class="px-4 py-3 text-right">
                    <div class="flex justify-end space-x-2">
                        <div class="h-6 bg-gray-700/50 rounded w-16"></div>
                        <div class="h-6 bg-gray-700/50 rounded w-16"></div>
                        <div class="h-6 bg-gray-700/50 rounded w-6"></div>
                    </div>
                </td>
            </tr>`;
    }).join('');
}

function showIdleState() {
    const table = document.getElementById('marketsTable');
    const counter = document.getElementById('marketCounter');
    if (counter) counter.textContent = '';

    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center">
                <div class="flex flex-col items-center space-y-4">
                    <div class="relative">
                        <div class="text-5xl opacity-40">🕵️‍♂️</div>
                        <div class="absolute -top-1 -right-1 w-3 h-3 bg-emerald-400 rounded-full animate-ping"></div>
                        <div class="absolute -top-1 -right-1 w-3 h-3 bg-emerald-400 rounded-full"></div>
                    </div>
                    <div class="text-gray-400 text-sm font-medium">Intelligence awaiting orders.</div>
                    <div class="text-gray-600 text-xs max-w-xs">Search for a specific market above and press Enter, or load all active movers.</div>
                    <button onclick="loadMarkets('')"
                        class="mt-2 bg-polysint text-gray-900 font-bold px-5 py-2 rounded-lg text-sm hover:bg-emerald-400 transition-all shadow-lg shadow-emerald-900/30 hover:scale-105 transform">
                        Load Top Markets
                    </button>
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
                    <div class="relative">
                        <div class="text-4xl opacity-30">🔍</div>
                        <div class="absolute -top-2 -right-2 text-xl">❓</div>
                    </div>
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
            loadMarkets(query, true); // silent refresh
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
        el.classList.remove('text-polysint');
        el.classList.add('text-gray-500');
    } else {
        el.textContent = 'Refreshing...';
        el.classList.remove('text-gray-500');
        el.classList.add('text-polysint');
    }
}

// ─── Core: Load Markets ───────────────────────────────────────────────────────
const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

async function loadMarkets(searchQuery = '', silent = false) {
    // Show skeleton only on initial load or explicit search, not during silent refresh
    if (!silent && !hasLoadedOnce) {
        showMarketSkeleton();
    } else if (!silent) {
        // Show a subtle refresh indicator for explicit refreshes
        const refreshBtn = document.querySelector('[onclick*="loadMarkets"]');
        if (refreshBtn) {
            refreshBtn.disabled = true;
            refreshBtn.innerHTML = `
                <svg class="animate-spin h-4 w-4 mr-1" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Loading...`;
        }
    }

    // Read volume filter values
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

        // Reset refresh button
        const refreshBtn = document.querySelector('[onclick*="loadMarkets"]');
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = '🔄 Refresh';
        }

        const counter = document.getElementById('marketCounter');
        if (counter) {
            if (markets.length > 0) {
                counter.innerHTML = `<span class="inline-flex items-center">
                    <span class="w-2 h-2 bg-polysint rounded-full mr-2 animate-pulse"></span>
                    ${markets.length} markets
                </span>`;
            } else {
                counter.textContent = '';
            }
        }

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
            tr.className = `transition-all duration-300 border-b border-gray-700/50 ${rowHighlight}`;
            tr.style.animationDelay = `${i * 30}ms`;
            tr.style.opacity = '0';
            tr.style.transform = 'translateY(10px)';

            // Market row content with enhanced styling
            tr.innerHTML = `
                <td class="px-4 py-4 font-medium text-gray-200">
                    <div class="flex items-start flex-wrap gap-1">
                        <span>${m.question}</span>
                        ${anomalyBadge}
                    </div>
                    <div class="text-xs text-blue-400 mt-1 font-mono flex items-center">
                        <span class="w-1.5 h-1.5 bg-blue-400 rounded-full mr-1.5 animate-pulse"></span>
                        Odds: ${currentOdds}
                    </div>
                </td>
                <td class="px-4 py-4 font-mono ${shiftColor} font-bold text-sm">
                    <div class="flex items-center">
                        ${shiftIcon} ${absShift}%
                        <span class="text-xs text-gray-600 font-normal ml-1">24h</span>
                    </div>
                </td>
                <td class="px-4 py-4 text-gray-400 text-xs">
                    <div class="flex items-center">
                        <span class="w-1.5 h-1.5 bg-gray-500 rounded-full mr-1.5"></span>
                        ${formatter.format(m.volume)}
                    </div>
                </td>
                <td class="px-4 py-4 text-right">
                    <button onclick="analyzeMarket('${m.id}')"
                        class="bg-polysint/10 text-polysint border border-polysint/30 hover:bg-polysint hover:text-white px-3 py-1.5 rounded text-xs transition-all duration-300 shadow-sm whitespace-nowrap hover:scale-105 transform">
                        <span class="flex items-center">
                            <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                            </svg>
                            Analyze
                        </span>
                    </button>
                </td>
            `;
            table.appendChild(tr);

            // Animate in with staggered delay
            setTimeout(() => {
                tr.style.opacity = '1';
                tr.style.transform = 'translateY(0)';
            }, i * 50 + 10);
        });

        startAutoRefresh(searchQuery);

    } catch (e) {
        console.error(e);
        
        // Reset refresh button on error
        const refreshBtn = document.querySelector('[onclick*="loadMarkets"]');
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = '🔄 Refresh';
        }

        const table = document.getElementById('marketsTable');
        table.innerHTML = `
            <tr><td colspan="4" class="text-center py-10">
                <div class="flex flex-col items-center space-y-3">
                    <div class="relative">
                        <div class="text-3xl">⚠️</div>
                        <div class="absolute -top-1 -right-1 w-3 h-3 bg-red-400 rounded-full animate-ping"></div>
                    </div>
                    <div class="text-red-400 text-sm font-medium">Connection to backend failed</div>
                    <div class="text-gray-600 text-xs">Is the backend running? Check <code>analyzer.log</code>.</div>
                    <button onclick="loadMarkets('${searchQuery}')" 
                        class="mt-2 text-xs text-polysint border border-polysint/30 px-3 py-1 rounded hover:bg-polysint/10 transition-all">
                        <span class="flex items-center">
                            <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
                            </svg>
                            Retry
                        </span>
                    </button>
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
    modal.classList.add('flex');

    const researchNote = useResearch
        ? '<span class="text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-mono ml-2">+ Web Research</span>'
        : '<span class="text-xs bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded font-mono ml-2">No Web Research</span>';

    modalTitle.innerHTML = `
        <div class="flex items-center">
            <svg class="w-5 h-5 mr-2 text-polysint animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
            </svg>
            PolySINT Intelligence ${researchNote}
        </div>`;

    // Enhanced loading state with progress indicators
    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-4 py-12">
            <div class="relative">
                <div class="w-16 h-16 border-4 border-polysint/20 rounded-full"></div>
                <div class="absolute top-0 left-0 w-16 h-16 border-4 border-transparent border-t-polysint rounded-full animate-spin"></div>
            </div>
            <div class="text-center space-y-2">
                <div class="text-polysint text-sm font-medium animate-pulse">
                    ${useResearch ? 'Scanning web + running LLM analysis...' : 'Running LLM analysis...'}
                </div>
                <div class="text-gray-600 text-xs">
                    ${useResearch ? 'Searching Reuters, Bloomberg, AP News...' : 'Analyzing price patterns...'}
                </div>
                <div class="mt-4 w-48 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div class="h-full bg-polysint rounded-full animate-pulse" style="width: 30%"></div>
                </div>
            </div>
        </div>`;

    try {
        const url = `/markets/${marketId}/ai-analysis?research=${useResearch}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error("AI Analysis Failed");
        const data = await res.json();

        const formatted = data.analysis
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
            .replace(/\n/g, '<br>');

        // Success state with animation
        content.innerHTML = `
            <div class="space-y-4">
                <div class="flex items-center text-polysint text-sm mb-4">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                    Analysis Complete
                    <span class="ml-2 text-xs text-gray-500">${new Date().toLocaleTimeString()}</span>
                </div>
                <div class="p-4 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed text-gray-300">
                    ${formatted}
                </div>
            </div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="space-y-3">
                <div class="flex items-center text-red-400 text-sm">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                    </svg>
                    Analysis Failed
                </div>
                <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                    ⚠️ Could not generate intelligence brief.<br>
                    <span class="text-xs text-gray-500 mt-2 block">Check your LLM API key and <code>analyzer.log</code>.</span>
                </div>
                <button onclick="analyzeMarket('${marketId}')" 
                    class="text-xs text-polysint border border-polysint/30 px-3 py-1 rounded hover:bg-polysint/10 transition-all w-full">
                    Retry Analysis
                </button>
            </div>`;
    }
}

// ─── Wallet / Entity ──────────────────────────────────────────────────────────
async function profileEntity(address, label) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    modal.classList.remove('hidden');
    modal.classList.add('flex');
    modalTitle.innerHTML = `
        <div class="flex items-center">
            <svg class="w-5 h-5 mr-2 text-blue-400 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path>
            </svg>
            Entity Profile — ${label}
        </div>`;

    // Enhanced loading state with progress bar
    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-4 py-12">
            <div class="relative">
                <div class="w-16 h-16 border-4 border-blue-400/20 rounded-full"></div>
                <div class="absolute top-0 left-0 w-16 h-16 border-4 border-transparent border-t-blue-400 rounded-full animate-spin"></div>
                <div class="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2">
                    <svg class="w-6 h-6 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                    </svg>
                </div>
            </div>
            <div class="text-center space-y-2">
                <div class="text-blue-400 text-sm font-medium animate-pulse">
                    Fetching on-chain history & profiling...
                </div>
                <div class="text-gray-600 text-xs">
                    Querying blockchain data and analyzing patterns...
                </div>
                <div class="mt-4 w-48 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div class="h-full bg-blue-400 rounded-full animate-pulse" style="width: 60%"></div>
                </div>
            </div>
        </div>`;

    try {
        const res = await fetch(`/wallets/${address}/profile`);
        if (!res.ok) throw new Error("Profiling Failed");
        const data = await res.json();

        const formatted = data.profile
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `
            <div class="space-y-4">
                <div class="flex items-center text-blue-400 text-sm mb-4">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path>
                    </svg>
                    Profile Generated
                    <span class="ml-2 text-xs text-gray-500">${new Date().toLocaleTimeString()}</span>
                </div>
                <div class="mb-4 p-3 bg-gray-900 rounded border border-gray-700 font-mono text-xs text-gray-400 space-y-1">
                    <div><span class="text-gray-600">Proxy:</span> ${address}</div>
                    <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${data.real_owner}</span></div>
                </div>
                <div class="p-4 border-l-4 border-blue-500 bg-gray-900/60 rounded-r leading-relaxed text-gray-300">
                    ${formatted}
                </div>
            </div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="space-y-3">
                <div class="flex items-center text-red-400 text-sm">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                    </svg>
                    Profiling Failed
                </div>
                <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                    ⚠️ Could not generate entity profile.<br>
                    <span class="text-xs text-gray-500 mt-2 block">Check RPC configuration and network connection.</span>
                </div>
                <button onclick="profileEntity('${address}', '${label}')" 
                    class="text-xs text-blue-400 border border-blue-400/30 px-3 py-1 rounded hover:bg-blue-400/10 transition-all w-full">
                    Retry Profiling
                </button>
            </div>`;
    }
}

// ─── Watchlist ────────────────────────────────────────────────────────────────
async function loadWatchlist(silent = false) {
    const table = document.getElementById('watchlistTable');
    if (!silent) showWatchlistSkeleton();

    try {
        const res = await fetch('/watchlist');
        const watchlist = await res.json();

        table.innerHTML = '';
        if (watchlist.length === 0) {
            table.innerHTML = `
                <tr><td class="text-center py-10 text-gray-600 text-sm italic px-4">
                    <div class="flex flex-col items-center space-y-2">
                        <div class="text-2xl opacity-40">👁️‍🗨️</div>
                        <div>Watchlist empty.</div>
                        <div class="text-xs">Add a target's 0x proxy address above.</div>
                    </div>
                </td></tr>`;
            return;
        }

        watchlist.forEach((w, i) => {
            const shortAddr = w.address.substring(0, 6) + '…' + w.address.substring(w.address.length - 4);
            const tr = document.createElement('tr');
            tr.className = "transition-all duration-300 border-b border-gray-700/50 hover:bg-gray-700/30";
            tr.style.opacity = '0';
            tr.style.transform = 'translateY(10px)';
            tr.innerHTML = `
                <td class="px-4 py-3">
                    <div class="font-semibold text-gray-200 text-sm flex items-center">
                        <span class="w-2 h-2 bg-blue-400 rounded-full mr-2"></span>
                        ${w.label}
                    </div>
                    <div class="text-xs font-mono text-gray-500 mt-0.5 pl-4">${shortAddr}</div>
                    <div class="text-xs font-mono text-polysint mt-0.5 hidden" id="real-${w.address}"></div>
                </td>
                <td class="px-4 py-3 text-right">
                    <div class="flex justify-end items-center gap-1 flex-wrap">
                        <button onclick="unmaskWallet('${w.address}')" id="btn-${w.address}"
                            class="bg-gray-800 border border-gray-600 text-gray-300 hover:bg-gray-700 px-2 py-1.5 rounded text-xs transition-all hover:scale-105 transform">
                            <span class="flex items-center">
                                <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path>
                                </svg>
                                Unmask
                            </span>
                        </button>
                        <button onclick="profileEntity('${w.address}', '${w.label}')"
                            class="bg-blue-900/40 text-blue-400 border border-blue-800 hover:bg-blue-800 hover:text-white px-2 py-1.5 rounded text-xs transition-all hover:scale-105 transform">
                            <span class="flex items-center">
                                <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
                                </svg>
                                AI Profile
                            </span>
                        </button>
                        <button onclick="deleteTarget('${w.address}')" title="Stop Tracking"
                            class="bg-red-900/30 text-red-400 border border-red-800 hover:bg-red-800 hover:text-white px-2 py-1.5 rounded text-xs transition-all hover:scale-105 transform">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                            </svg>
                        </button>
                    </div>
                </td>`;
            table.appendChild(tr);

            // Animate in
            setTimeout(() => {
                tr.style.opacity = '1';
                tr.style.transform = 'translateY(0)';
            }, i * 100 + 10);
        });
    } catch (e) {
        table.innerHTML = `
            <tr><td class="text-center py-8">
                <div class="flex flex-col items-center space-y-2">
                    <div class="text-red-400 text-sm">Failed to load watchlist.</div>
                    <button onclick="loadWatchlist()" class="text-xs text-polysint border border-polysint/30 px-3 py-1 rounded hover:bg-polysint/10 transition-all">
                        Retry
                    </button>
                </div>
            </td></tr>`;
    }
}

// ─── Utility Functions ────────────────────────────────────────────────────────
async function unmaskWallet(address) {
    const btn = document.getElementById(`btn-${address}`);
    const realDiv = document.getElementById(`real-${address}`);

    btn.disabled = true;
    btn.innerHTML = `
        <svg class="animate-spin h-3 w-3 mr-1" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Scanning...`;
    btn.classList.add("opacity-50", "cursor-not-allowed");

    try {
        const res = await fetch(`/wallets/${address}/unmask`);
        const data = await res.json();

        realDiv.classList.remove("hidden");
        realDiv.innerHTML = `EOA: <span class="text-polysint font-mono">${data.real_owner}</span>`;
        btn.innerHTML = `
            <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
            </svg>
            Unmasked`;
        btn.classList.remove("border-gray-600", "text-gray-300", "hover:bg-gray-700");
        btn.classList.add("bg-gray-700", "text-gray-500", "border-transparent", "cursor-default");
    } catch (e) {
        btn.disabled = false;
        btn.innerHTML = `
            <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
            </svg>
            Retry`;
        btn.classList.remove("opacity-50", "cursor-not-allowed");
        showInlineError('addError', 'Failed to unmask wallet. Check RPC configuration.');
    }
}

async function addTarget() {
    const addressInput = document.getElementById('newAddress');
    const labelInput = document.getElementById('newLabel');
    const address = addressInput.value.trim();
    const label = labelInput.value.trim();

    if (!address || !label) {
        showInlineError('addError', 'Both address and label are required.');
        return;
    }

    const addBtn = document.querySelector('[onclick="addTarget()"]');
    if (addBtn) {
        addBtn.disabled = true;
        addBtn.innerHTML = `
            <svg class="animate-spin h-4 w-4 mr-1" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Adding...`;
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
    } finally {
        if (addBtn) {
            addBtn.disabled = false;
            addBtn.innerHTML = `
                <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path>
                </svg>
                Add Target`;
        }
    }
}

function showInlineError(id, msg) {
    const el = document.getElementById(id);
    if (el) { 
        el.textContent = msg; 
        el.classList.remove('hidden');
        // Add shake animation
        el.style.animation = 'shake 0.5s ease';
        setTimeout(() => el.style.animation = '', 500);
    }
}

function clearInlineError(id) {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.classList.add('hidden'); }
}

async function deleteTarget(address) {
    if (!confirm("Stop tracking this entity?")) return;
    
    const btn = event.target.closest('button');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `
            <svg class="animate-spin h-3 w-3" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>`;
    }

    try {
        const res = await fetch(`/watchlist/${address}`, { method: 'DELETE' });
        if (res.ok) {
            loadWatchlist();
        } else {
            alert("Failed to delete target.");
        }
    } catch (e) { 
        console.error(e); 
    }
}

function closeModal() {
    const modal = document.getElementById('aiModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('aiModal');
    if (e.target === modal) closeModal();
});

// Add CSS for shake animation
const style = document.createElement('style');
style.textContent = `
    @keyframes shake {
        0%, 100% { transform: translateX(0); }
        25% { transform: translateX(-5px); }
        75% { transform: translateX(5px); }
    }
    .animate-shake {
        animation: shake 0.5s ease;
    }
`;
document.head.appendChild(style);
```

## Key Improvements:

### 1. **Skeleton Screens**
- Added proper skeleton loaders that mimic the actual content structure
- Staggered animations for rows to create a natural loading feel
- Visual indicators (spinning circles, progress bars) during data fetching

### 2. **Enhanced Loading States**
- **Markets table**: Full skeleton with progress indicator
- **Watchlist**: Matching skeleton design with animated rows
- **AI Analysis Modal**: Enhanced with circular progress indicator and descriptive text
- **Entity Profiling**: Dedicated loading state with progress bar

### 3. **Interactive Feedback**
- Button loading states with spinners
- Success/error state animations
- Shake animation for validation errors
- Scale animations on hover for interactive elements

### 4. **Visual Polish**
- Added icons to buttons (analyze, unmask, profile, delete)
- Status indicators (pulsing dots for live data)
- Better error states with retry buttons
- Smooth transitions and animations throughout

### 5. **Performance Optimizations**
- Silent refresh doesn't show skeleton (less jarring)
- Staggered animations for better perceived performance
- Proper state management for buttons during async operations

The loading experience now feels more professional and provides clear feedback to users about what's happening at each stage.
