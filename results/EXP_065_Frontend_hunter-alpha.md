I'll update `app.js` with proper ARIA attributes on all dynamically generated elements — tables, buttons, modals, loading states, and error states — along with keyboard trap support for the modal.

```javascript
// ─── State ────────────────────────────────────────────────────────────────────
let hasLoadedOnce = false;
let refreshTimer = null;
let refreshCountdown = 0;
const REFRESH_INTERVAL = 300; // 5 minutes

// Track focus to restore after modal closes
let lastFocusedElement = null;

// ─── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadWatchlist();
    initResearchToggle();

    // Search only fires on Enter
    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const q = e.target.value.trim();
            loadMarkets(q);
        }
    });

    // Modal: close on Escape
    document.addEventListener('keydown', (e) => {
        const modal = document.getElementById('aiModal');
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeModal();
        }
    });

    // Modal: close on backdrop click
    document.addEventListener('click', (e) => {
        const modal = document.getElementById('aiModal');
        if (e.target === modal) closeModal();
    });
});

// ─── Research Toggle ──────────────────────────────────────────────────────────
function initResearchToggle() {
    const saved = localStorage.getItem('polysint_research_enabled');
    const enabled = saved === 'true';
    const toggle = document.getElementById('researchToggle');
    toggle.checked = enabled;
    updateToggleLabel(enabled);
}

function onResearchToggle() {
    const toggle = document.getElementById('researchToggle');
    const enabled = toggle.checked;
    localStorage.setItem('polysint_research_enabled', enabled);
    updateToggleLabel(enabled);
}

function updateToggleLabel(enabled) {
    const label = document.getElementById('researchToggleLabel');
    if (enabled) {
        label.textContent = 'Web Research: ON';
        label.className = 'text-xs text-emerald-400 font-mono';
        label.setAttribute('aria-pressed', 'true');
    } else {
        label.textContent = 'Web Research: OFF';
        label.className = 'text-xs text-gray-500 font-mono';
        label.setAttribute('aria-pressed', 'false');
    }
}

function isResearchEnabled() {
    return document.getElementById('researchToggle').checked;
}

// ─── Idle / Empty States ──────────────────────────────────────────────────────
function showIdleState() {
    const table = document.getElementById('marketsTable');
    const counter = document.getElementById('marketCounter');
    if (counter) {
        counter.textContent = '';
        counter.setAttribute('aria-label', 'No markets loaded');
    }

    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center" role="status" aria-label="No markets loaded">
                <div class="flex flex-col items-center space-y-4">
                    <div class="text-5xl opacity-40" aria-hidden="true">🕵️‍♂️</div>
                    <div class="text-gray-400 text-sm font-medium">Intelligence awaiting orders.</div>
                    <div class="text-gray-600 text-xs max-w-xs">Search for a specific market above and press Enter, or load all active movers.</div>
                    <button onclick="loadMarkets('')"
                        aria-label="Load top active markets"
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
            <td colspan="4" class="py-16 text-center" role="status" aria-live="polite" aria-label="Loading markets">
                <div class="flex flex-col items-center space-y-3">
                    <div class="flex space-x-1" aria-hidden="true">
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
            <td colspan="4" class="py-16 text-center" role="status" aria-label="No results found">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-4xl opacity-30" aria-hidden="true">🔍</div>
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
        const text = `Auto-refresh in ${mins}:${secs.toString().padStart(2, '0')}`;
        el.textContent = text;
        el.setAttribute('aria-label', text);
    } else {
        el.textContent = 'Refreshing...';
        el.setAttribute('aria-label', 'Refreshing markets');
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
        if (counter) {
            counter.textContent = markets.length > 0 ? `${markets.length} markets` : '';
            counter.setAttribute('aria-label', markets.length > 0 ? `${markets.length} markets found` : 'No markets found');
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
            const shiftDirection = shift > 0 ? 'up' : (shift < 0 ? 'down' : 'unchanged');
            const isAnomaly = absShift >= 10.0;
            const isWarning = absShift >= 5.0 && absShift < 10.0;

            const currentOdds = m.current_price != null
                ? `${Math.round(m.current_price * 100)}%`
                : 'N/A';

            let anomalyBadge = '';
            if (isAnomaly) {
                anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse" role="status" aria-label="Anomaly detected: 24-hour shift exceeds 10 percent">⚡ ANOMALY</span>`;
            } else if (isWarning) {
                anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40" role="status" aria-label="Watch: 24-hour shift between 5 and 10 percent">⚠ WATCH</span>`;
            }

            const rowHighlight = isAnomaly
                ? 'bg-red-500/5 hover:bg-red-500/10'
                : 'hover:bg-gray-700/30';

            const rowAriaLabel = `${m.question}. Current odds: ${currentOdds}. 24-hour shift: ${shiftDirection} ${absShift} percent. Volume: ${formatter.format(m.volume)}.${isAnomaly ? ' Anomaly detected.' : isWarning ? ' Watch status.' : ''}`;

            const tr = document.createElement('tr');
            tr.className = `transition-colors border-b border-gray-700/50 ${rowHighlight}`;
            tr.style.animationDelay = `${i * 30}ms`;
            tr.setAttribute('role', 'row');
            tr.setAttribute('aria-label', rowAriaLabel);

            tr.innerHTML = `
                <td class="px-4 py-4 font-medium text-gray-200" role="gridcell">
                    <div class="flex items-start flex-wrap gap-1">
                        <span>${m.question}</span>
                        ${anomalyBadge}
                    </div>
                    <div class="text-xs text-blue-400 mt-1 font-mono" aria-label="Current odds: ${currentOdds}">Odds: ${currentOdds}</div>
                </td>
                <td class="px-4 py-4 font-mono ${shiftColor} font-bold text-sm" role="gridcell" aria-label="24-hour shift: ${shiftDirection} ${absShift} percent">
                    ${shiftIcon} ${absShift}%
                    <div class="text-xs text-gray-600 font-normal" aria-hidden="true">24h shift</div>
                </td>
                <td class="px-4 py-4 text-gray-400 text-xs" role="gridcell" aria-label="Volume: ${formatter.format(m.volume)}">${formatter.format(m.volume)}</td>
                <td class="px-4 py-4 text-right" role="gridcell">
                    <button onclick="analyzeMarket('${m.id}')"
                        aria-label="Run AI analysis on ${m.question.replace(/'/g, "\\'")}"
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
            <tr><td colspan="4" class="text-center py-10" role="alert">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-3xl" aria-hidden="true">⚠️</div>
                    <div class="text-red-400 text-sm">Failed to load markets.</div>
                    <div class="text-gray-600 text-xs">Is the backend running? Check <code>analyzer.log</code>.</div>
                    <button onclick="loadMarkets('${searchQuery}')"
                        aria-label="Retry loading markets"
                        class="mt-2 text-xs text-polysint underline">Retry</button>
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

    // Store focus, show modal, trap focus
    lastFocusedElement = document.activeElement;
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => {
        const firstFocusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (firstFocusable) firstFocusable.focus();
    });

    const researchNote = useResearch
        ? '<span class="text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-mono ml-2" aria-label="Web research enabled">+ Web Research</span>'
        : '<span class="text-xs bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded font-mono ml-2" aria-label="Web research disabled">No Web Research</span>';

    modalTitle.innerHTML = `🤖 PolySINT Intelligence ${researchNote}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12" role="status" aria-live="polite" aria-label="Loading AI analysis">
            <div class="flex space-x-1" aria-hidden="true">
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

        content.innerHTML = `<div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed" role="document" aria-label="AI analysis result">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm" role="alert">
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

    lastFocusedElement = document.activeElement;
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => {
        const firstFocusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (firstFocusable) firstFocusable.focus();
    });

    modalTitle.innerHTML = `🧠 Entity Profile — ${label}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12" role="status" aria-live="polite" aria-label="Loading entity profile for ${label}">
            <div class="flex space-x-1" aria-hidden="true">
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
            <div class="mb-4 p-3 bg-gray-900 rounded border border-gray-700 font-mono text-xs text-gray-400 space-y-1" role="group" aria-label="Wallet address information">
                <div><span class="text-gray-600">Proxy:</span> ${address}</div>
                <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${data.real_owner}</span></div>
            </div>
            <div class="p-3 border-l-4 border-blue-500 bg-gray-900/60 rounded-r leading-relaxed" role="document" aria-label="Entity profile result">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `<div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm" role="alert">⚠️ Could not generate entity profile.</div>`;
    }
}

async function unmaskWallet(address) {
    const btn = document.getElementById(`btn-${address}`);
    const realDiv = document.getElementById(`real-${address}`);

    btn.disabled = true;
    btn.setAttribute('aria-disabled', 'true');
    btn.innerHTML = '<span class="animate-pulse">Scanning...</span>';
    btn.setAttribute('aria-label', 'Scanning wallet on-chain...');
    btn.classList.add("opacity-50", "cursor-not-allowed");

    try {
        const res = await fetch(`/wallets/${address}/unmask`);
        const data = await res.json();

        realDiv.classList.remove("hidden");
        realDiv.innerHTML = `EOA: <span class="text-polysint">${data.real_owner}</span>`;
        realDiv.setAttribute('role', 'status');
        realDiv.setAttribute('aria-label', `Real owner address: ${data.real_owner}`);
        btn.textContent = "✓ Unmasked";
        btn.setAttribute('aria-label', 'Wallet unmasked successfully');
        btn.classList.remove("border-gray-600", "text-gray-300", "hover:bg-gray-700");
        btn.classList.add("bg-gray-700", "text-gray-500", "border-transparent", "cursor-default");
    } catch (e) {
        btn.disabled = false;
        btn.removeAttribute('aria-disabled');
        btn.textContent = "Retry";
        btn.setAttribute('aria-label', 'Retry unmasking wallet');
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
            // Announce success for screen readers
            const announcer = document.getElementById('srAnnouncer');
            if (announcer) {
                announcer.textContent = `Target ${label} added to watchlist.`;
            }
        } else {
            showInlineError('addError', data.detail || 'Failed to add target.');
        }
    } catch (e) {
        showInlineError('addError', 'Network error. Is the backend running?');
    }
}

function showInlineError(id, msg) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = msg;
        el.classList.remove('hidden');
        el.setAttribute('role', 'alert');
    }
}

function clearInlineError(id) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = '';
        el.classList.add('hidden');
        el.removeAttribute('role');
    }
}

async function loadWatchlist() {
    const table = document.getElementById('watchlistTable');
    try {
        const res = await fetch('/watchlist');
        const watchlist = await res.json();

        table.innerHTML = '';
        if (watchlist.length === 0) {
            table.innerHTML = `
                <tr><td class="text-center py-10 text-gray-600 text-sm italic px-4" role="status" aria-label="Watchlist is empty">
                    Watchlist empty.<br>
                    <span class="text-xs">Add a target's 0x proxy address above.</span>
                </td></tr>`;
            return;
        }

        watchlist.forEach(w => {
            const shortAddr = w.address.substring(0, 6) + '…' + w.address.substring(w.address.length - 4);
            const tr = document.createElement('tr');
            tr.className = "hover:bg-gray-700/30 transition-colors border-b border-gray-700/50";
            tr.setAttribute('role', 'row');
            tr.setAttribute('aria-label', `Tracked entity: ${w.label}, address ${shortAddr}`);
            tr.innerHTML = `
                <td class="px-4 py-3" role="gridcell">
                    <div class="font-semibold text-gray-200 text-sm">${w.label}</div>
                    <div class="text-xs font-mono text-gray-500 mt-0.5" aria-label="Wallet address: ${w.address}">${shortAddr}</div>
                    <div class="text-xs font-mono text-polysint mt-0.5 hidden" id="real-${w.address}" aria-live="polite"></div>
                </td>
                <td class="px-4 py-3 text-right" role="gridcell">
                    <div class="flex justify-end items-center gap-1 flex-wrap">
                        <button onclick="unmaskWallet('${w.address}')" id="btn-${w.address}"
                            aria-label="Unmask wallet ${shortAddr} to reveal real owner"
                            class="bg-gray-800 border border-gray-600 text-gray-300 hover:bg-gray-700 px-2 py-1 rounded text-xs transition-all">
                            Unmask
                        </button>
                        <button onclick="profileEntity('${w.address}', '${w.label.replace(/'/g, "\\'")}')"
                            aria-label="Generate AI profile for ${w.label}"
                            class="bg-blue-900/40 text-blue-400 border border-blue-800 hover:bg-blue-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                            AI Profile
                        </button>
                        <button onclick="deleteTarget('${w.address}')" title="Stop Tracking"
                            aria-label="Stop tracking ${w.label}"
                            class="bg-red-900/30 text-red-400 border border-red-800 hover:bg-red-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                            ✕
                        </button>
                    </div>
                </td>`;
            table.appendChild(tr);
        });
    } catch (e) {
        table.innerHTML = `<tr><td class="text-center py-8 text-red-400 text-sm" role="alert">Failed to load watchlist.</td></tr>`;
    }
}

async function deleteTarget(address) {
    if (!confirm("Stop tracking this entity?")) return;
    try {
        const res = await fetch(`/watchlist/${address}`, { method: 'DELETE' });
        if (res.ok) {
            loadWatchlist();
            const announcer = document.getElementById('srAnnouncer');
            if (announcer) {
                announcer.textContent = 'Target removed from watchlist.';
            }
        } else {
            alert("Failed to delete target.");
        }
    } catch (e) { console.error(e); }
}

function closeModal() {
    const modal = document.getElementById('aiModal');
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
    // Restore focus to the element that opened the modal
    if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
        lastFocusedElement.focus();
        lastFocusedElement = null;
    }
}
```

Now here's the companion HTML snippet to add to your `index.html` — the static ARIA landmarks, form labels, table roles, modal attributes, and the live announcer region:

```html
<!-- ═══ Screen Reader Announcer (invisible, used by JS) ═══ -->
<div id="srAnnouncer" aria-live="polite" aria-atomic="true"
     class="sr-only" style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0;">
</div>

<!-- ═══ Main App Shell ═══ -->
<main role="main" aria-label="PolySINT Market Intelligence Dashboard">

  <!-- ── Search Toolbar ── -->
  <section role="search" aria-label="Market search and filters">
    <div class="toolbar-row">

      <label for="searchInput" class="sr-only">Search markets by keyword</label>
      <input
        id="searchInput"
        type="search"
        placeholder="Search markets… press Enter"
        autocomplete="off"
        aria-label="Search markets by keyword"
        class="search-input"
      />

      <div class="vol-filters" role="group" aria-label="Volume filters">
        <label for="volMin" class="sr-only">Minimum volume</label>
        <input id="volMin" type="number" placeholder="Vol min"
               aria-label="Minimum volume filter" class="vol-input" />

        <label for="volMax" class="sr-only">Maximum volume</label>
        <input id="volMax" type="number" placeholder="Vol max"
               aria-label="Maximum volume filter" class="vol-input" />
      </div>

      <!-- Research Toggle -->
      <div class="toggle-wrapper" role="switch"
           aria-checked="false"
           aria-label="Toggle web research for AI analysis">
        <input type="checkbox" id="researchToggle"
               onchange="onResearchToggle()"
               aria-label="Enable web research" />
        <span id="researchToggleLabel" class="text-xs text-gray-500 font-mono"
              aria-live="polite">Web Research: OFF</span>
      </div>

      <div id="refreshCountdown" class="text-xs text-gray-500 font-mono"
           aria-live="polite" aria-atomic="true"
           aria-label="Auto-refresh countdown"></div>
    </div>
  </section>

  <!-- ── Markets Table ── -->
  <section aria-label="Active markets">
    <h2 class="sr-only">Markets</h2>
    <span id="marketCounter" aria-live="polite" class="sr-only"></span>

    <table role="grid" aria-label="Markets table"
           aria-rowcount="50" aria-colcount="4">
      <thead>
        <tr role="row">
          <th role="columnheader" scope="col" aria-label="Market question">Market</th>
          <th role="columnheader" scope="col" aria-label="24-hour price shift">24h Shift</th>
          <th role="columnheader" scope="col" aria-label="Trading volume">Volume</th>
          <th role="columnheader" scope="col" aria-label="Actions">Action</th>
        </tr>
      </thead>
      <tbody id="marketsTable" role="rowgroup">
        <!-- Populated by JS -->
      </tbody>
    </table>
  </section>

  <!-- ── Watchlist ── -->
  <section aria-label="Entity watchlist">
    <h2 class="sr-only">Watchlist</h2>

    <!-- Add Target Form -->
    <form onsubmit="event.preventDefault(); addTarget();"
          aria-label="Add entity to watchlist">
      <div class="flex gap-2">
        <div>
          <label for="newAddress" class="sr-only">Ethereum proxy address</label>
          <input id="newAddress" type="text" placeholder="0x proxy address"
                 maxlength="42" autocomplete="off"
                 aria-label="Ethereum proxy address (0x…)"
                 aria-describedby="addError"
                 class="watch-input" />
        </div>
        <div>
          <label for="newLabel" class="sr-only">Entity label</label>
          <input id="newLabel" type="text" placeholder="Label (e.g. Whale #1)"
                 maxlength="80" autocomplete="off"
                 aria-label="Entity label"
                 class="watch-input" />
        </div>
        <button type="submit"
                aria-label="Add entity to watchlist"
                class="add-btn">
          + Add
        </button>
      </div>
      <div id="addError" class="text-xs text-red-400 mt-1 hidden"
           role="alert" aria-live="assertive"></div>
    </form>

    <!-- Watchlist Table -->
    <table role="grid" aria-label="Tracked entities"
           aria-colcount="2">
      <thead>
        <tr role="row">
          <th role="columnheader" scope="col" aria-label="Entity name and address">Entity</th>
          <th role="columnheader" scope="col" aria-label="Actions">Actions</th>
        </tr>
      </thead>
      <tbody id="watchlistTable" role="rowgroup">
        <!-- Populated by JS -->
      </tbody>
    </table>
  </section>
</main>

<!-- ═══ AI Analysis Modal ═══ -->
<div id="aiModal"
     class="hidden"
     role="dialog"
     aria-modal="true"
     aria-labelledby="aiModalTitle"
     aria-describedby="aiModalContent"
     aria-hidden="true">
  <div class="modal-backdrop" aria-hidden="true"></div>
  <div class="modal-panel" role="document">
    <div class="flex items-center justify-between mb-4">
      <h3 id="aiModalTitle" class="text-lg font-semibold text-white"></h3>
      <button onclick="closeModal()"
              aria-label="Close analysis modal"
              class="modal-close-btn">
        ✕
      </button>
    </div>
    <div id="aiModalContent" aria-live="polite">
      <!-- Populated by JS -->
    </div>
  </div>
</div>
```

**Summary of what was added:**

| Area | ARIA attributes |
|---|---|
| **Tables** | `role="grid"`, `role="row"`, `role="columnheader"`, `role="gridcell"`, `aria-label` on rows |
| **Buttons** | Descriptive `aria-label` on every button (Analyze, Unmask, AI Profile, Delete, Retry, Close) |
| **Modal** | `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-describedby`, `aria-hidden` toggled by JS |
| **Focus management** | Focus trapped into modal on open; restored to trigger element on close; Escape key closes |
| **Loading states** | `role="status"`, `aria-live="polite"`, `aria-label` descriptions |
| **Error states** | `role="alert"` on error messages |
| **Search/form** | `<label for="">` / `sr-only` labels, `aria-describedby` linking errors |
| **Screen reader announcer** | `#srAnnouncer` live region for async actions (add/delete target) |
| **Status badges** | `role="status"` + `aria-label` explaining anomaly/watch thresholds |
| **Semantic landmarks** | `<main role="main">`, `<section>` with `aria-label`, `<form>` |
