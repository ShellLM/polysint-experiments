Looking at the codebase, I need to create `static/index.html` from scratch — the existing `app.js` expects specific element IDs. I'll build a responsive, dark-themed OSINT dashboard with mobile-first considerations.

**Design Direction:** Dark, grid-lined cyberpunk aesthetic with emerald green accents and monospace data typography. Left sidebar collapses on mobile; tabbed navigation for switching between Markets and Watchlist on small screens.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PolySINT — Market Intelligence</title>
    <meta name="theme-color" content="#070807">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        :root {
            --bg: #070807;
            --surface: #0d0f0d;
            --surface-2: #131613;
            --border: #1c201c;
            --border-bright: #252a25;
            --text-primary: #dce4dc;
            --text-muted: #5a645a;
            --accent: #34d399;
            --accent-dim: #065f46;
            --accent-bg: rgba(52, 211, 153, 0.06);
            --red: #f87171;
            --amber: #fbbf24;
            --blue: #60a5fa;
            --mono: 'DM Mono', 'Menlo', 'Monaco', monospace;
            --sans: 'DM Sans', system-ui, sans-serif;
        }

        * { scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
        ::selection { background: rgba(52, 211, 153, 0.25); color: #fff; }

        body {
            background-color: var(--bg);
            background-image:
                linear-gradient(rgba(255,255,255,0.012) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.012) 1px, transparent 1px),
                radial-gradient(ellipse at 15% 10%, rgba(52,211,153,0.025) 0%, transparent 50%),
                radial-gradient(ellipse at 85% 80%, rgba(52,211,153,0.01) 0%, transparent 50%);
            background-size: 48px 48px, 48px 48px, 100% 100%, 100% 100%;
            font-family: var(--sans);
            color: var(--text-primary);
            min-height: 100vh;
            animation: pageIn 0.5s ease-out;
        }

        @keyframes pageIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        /* ─── Header ─────────────────────────────────────────── */
        .app-header {
            background: rgba(7, 8, 7, 0.88);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 50;
        }
        .app-header::after {
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0; right: 0;
            height: 1px;
            background: linear-gradient(90deg, var(--accent), transparent 50%);
            opacity: 0.2;
        }

        /* ─── Nav Tabs (mobile) ──────────────────────────────── */
        .nav-tab {
            font-family: var(--mono);
            font-size: 0.75rem;
            letter-spacing: 0.04em;
            padding: 0.5rem 1rem;
            color: var(--text-muted);
            border-bottom: 2px solid transparent;
            transition: all 0.2s ease;
            cursor: pointer;
            user-select: none;
            white-space: nowrap;
        }
        .nav-tab:hover { color: var(--text-primary); }
        .nav-tab.active { color: var(--accent); border-bottom-color: var(--accent); }

        /* ─── Grid Layout ────────────────────────────────────── */
        .dashboard-grid {
            display: grid;
            grid-template-columns: 1fr 340px;
            gap: 0;
            min-height: calc(100vh - 57px);
        }
        .sidebar {
            border-left: 1px solid var(--border);
            background: var(--surface);
        }

        /* ─── Section Headers ────────────────────────────────── */
        .section-title {
            font-family: var(--mono);
            font-size: 0.65rem;
            font-weight: 500;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--text-muted);
            padding: 1rem 1.25rem 0.5rem;
        }

        /* ─── Inputs ─────────────────────────────────────────── */
        .input-field {
            background: var(--surface-2);
            border: 1px solid var(--border);
            color: var(--text-primary);
            font-family: var(--mono);
            font-size: 0.8rem;
            padding: 0.55rem 0.85rem;
            border-radius: 6px;
            width: 100%;
            transition: border-color 0.2s, box-shadow 0.2s;
        }
        .input-field:focus {
            outline: none;
            border-color: var(--accent-dim);
            box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.08);
        }
        .input-field::placeholder { color: var(--text-muted); opacity: 0.5; }

        .input-label {
            font-family: var(--mono);
            font-size: 0.6rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            margin-bottom: 0.35rem;
            display: block;
        }

        /* ─── Buttons ────────────────────────────────────────── */
        .btn-primary {
            background: var(--accent);
            color: #000;
            font-family: var(--mono);
            font-weight: 500;
            font-size: 0.8rem;
            padding: 0.55rem 1.25rem;
            border-radius: 6px;
            transition: all 0.2s ease;
            cursor: pointer;
            border: none;
            white-space: nowrap;
        }
        .btn-primary:hover {
            background: #4ade80;
            box-shadow: 0 4px 20px rgba(52, 211, 153, 0.2);
        }
        .btn-primary:disabled {
            opacity: 0.4;
            cursor: not-allowed;
            box-shadow: none;
        }

        .btn-ghost {
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-muted);
            font-family: var(--mono);
            font-size: 0.7rem;
            padding: 0.35rem 0.65rem;
            border-radius: 5px;
            transition: all 0.2s ease;
            cursor: pointer;
        }
        .btn-ghost:hover {
            border-color: var(--accent-dim);
            color: var(--accent);
        }

        /* ─── Stats Bar ──────────────────────────────────────── */
        .stat-value {
            font-family: var(--mono);
            font-size: 0.75rem;
            font-weight: 500;
            color: var(--text-primary);
        }
        .stat-label {
            font-family: var(--mono);
            font-size: 0.6rem;
            color: var(--text-muted);
            letter-spacing: 0.04em;
        }

        /* ─── Markets Table ──────────────────────────────────── */
        .markets-table-wrapper {
            overflow-x: auto;
            border-top: 1px solid var(--border);
        }
        .markets-table {
            width: 100%;
            border-collapse: collapse;
            min-width: 680px;
        }
        .markets-table th {
            position: sticky;
            top: 0;
            background: var(--surface);
            font-family: var(--mono);
            font-size: 0.6rem;
            font-weight: 500;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: var(--text-muted);
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
            white-space: nowrap;
            z-index: 1;
        }
        .markets-table td {
            padding: 0.85rem 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.02);
            vertical-align: middle;
        }
        .market-row {
            transition: background 0.15s;
        }
        .market-row:hover {
            background: rgba(255,255,255,0.02);
        }
        .market-row.row-anomaly {
            background: rgba(248, 113, 113, 0.03);
            border-left: 3px solid var(--red);
        }
        .market-row.row-anomaly:hover {
            background: rgba(248, 113, 113, 0.06);
        }
        .market-row.row-warning {
            border-left: 3px solid var(--amber);
        }

        .market-question {
            font-size: 0.85rem;
            font-weight: 500;
            line-height: 1.45;
            color: var(--text-primary);
        }
        .market-odds {
            font-family: var(--mono);
            font-size: 0.7rem;
            color: var(--blue);
            margin-top: 0.25rem;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            font-family: var(--mono);
            font-size: 0.6rem;
            font-weight: 500;
            padding: 0.15rem 0.5rem;
            border-radius: 3px;
            letter-spacing: 0.02em;
            white-space: nowrap;
            vertical-align: middle;
        }
        .badge-anomaly {
            background: rgba(248,113,113,0.1);
            color: var(--red);
            border: 1px solid rgba(248,113,113,0.25);
            animation: pulse 2s infinite;
        }
        .badge-warning {
            background: rgba(251,191,36,0.08);
            color: var(--amber);
            border: 1px solid rgba(251,191,36,0.2);
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .shift-value {
            font-family: var(--mono);
            font-weight: 500;
            font-size: 0.85rem;
        }
        .shift-up { color: var(--accent); }
        .shift-down { color: var(--red); }
        .shift-flat { color: var(--text-muted); }

        .volume-text {
            font-family: var(--mono);
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .btn-analyze {
            background: rgba(52,211,153,0.06);
            border: 1px solid rgba(52,211,153,0.15);
            color: var(--accent);
            font-family: var(--mono);
            font-size: 0.7rem;
            padding: 0.4rem 0.75rem;
            border-radius: 5px;
            cursor: pointer;
            transition: all 0.2s ease;
            white-space: nowrap;
        }
        .btn-analyze:hover {
            background: var(--accent);
            color: #000;
            border-color: var(--accent);
            box-shadow: 0 2px 12px rgba(52,211,153,0.2);
        }

        /* ─── Watchlist ──────────────────────────────────────── */
        .watchlist-row {
            transition: background 0.15s;
        }
        .watchlist-row:hover {
            background: rgba(255,255,255,0.02);
        }
        .watchlist-label {
            font-size: 0.82rem;
            font-weight: 500;
            color: var(--text-primary);
        }
        .watchlist-addr {
            font-family: var(--mono);
            font-size: 0.65rem;
            color: var(--text-muted);
            margin-top: 0.15rem;
        }
        .watchlist-real {
            font-family: var(--mono);
            font-size: 0.65rem;
            color: var(--accent);
            margin-top: 0.15rem;
        }

        /* ─── Modal ──────────────────────────────────────────── */
        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.7);
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
            animation: modalBgIn 0.2s ease;
            padding: 1rem;
        }
        @keyframes modalBgIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        .modal-panel {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            width: 100%;
            max-width: 700px;
            max-height: 82vh;
            overflow-y: auto;
            animation: modalIn 0.25s ease;
            box-shadow: 0 24px 80px rgba(0,0,0,0.5);
        }
        @keyframes modalIn {
            from { opacity: 0; transform: translateY(16px) scale(0.98); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }
        .modal-close {
            background: none;
            border: none;
            color: var(--text-muted);
            font-size: 1.2rem;
            cursor: pointer;
            padding: 0.25rem;
            transition: color 0.15s;
            line-height: 1;
        }
        .modal-close:hover { color: var(--text-primary); }

        .analysis-text {
            font-size: 0.85rem;
            line-height: 1.7;
            color: var(--text-primary);
        }

        /* ─── Toggle Switch ──────────────────────────────────── */
        .toggle-track {
            position: relative;
            width: 36px;
            height: 20px;
            background: var(--border);
            border-radius: 10px;
            cursor: pointer;
            transition: background 0.2s;
            flex-shrink: 0;
        }
        .toggle-track.on {
            background: var(--accent-dim);
        }
        .toggle-knob {
            position: absolute;
            top: 2px;
            left: 2px;
            width: 16px;
            height: 16px;
            background: var(--text-muted);
            border-radius: 50%;
            transition: all 0.2s ease;
        }
        .toggle-track.on .toggle-knob {
            left: 18px;
            background: var(--accent);
        }

        /* ─── Status Bar ─────────────────────────────────────── */
        .status-bar {
            font-family: var(--mono);
            font-size: 0.6rem;
            color: var(--text-muted);
            background: var(--surface);
            border-top: 1px solid var(--border);
            padding: 0.5rem 1.25rem;
        }

        /* ─── Empty / Error States ───────────────────────────── */
        .empty-state {
            padding: 3rem 1.5rem;
            text-align: center;
        }
        .empty-state-icon { font-size: 2.5rem; opacity: 0.25; margin-bottom: 0.75rem; }
        .empty-state-title {
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
        }
        .empty-state-desc {
            font-size: 0.75rem;
            color: var(--text-muted);
            opacity: 0.6;
        }
        .error-state {
            padding: 1.5rem;
            margin: 1rem;
            background: rgba(248,113,113,0.05);
            border: 1px solid rgba(248,113,113,0.15);
            border-radius: 8px;
        }
        .error-state code {
            font-family: var(--mono);
            font-size: 0.7rem;
            color: var(--text-muted);
        }

        /* ─── Responsive ─────────────────────────────────────── */
        @media (max-width: 1023px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
            .sidebar {
                display: none;
                border-left: none;
                border-top: 1px solid var(--border);
            }
            .sidebar.open {
                display: block;
            }
        }

        @media (max-width: 640px) {
            .header-title-text {
                font-size: 0.85rem;
            }
            .desktop-tabs {
                display: none !important;
            }
            .btn-analyze {
                font-size: 0.6rem;
                padding: 0.3rem 0.5rem;
            }
            .panel-tabs {
                display: flex !important;
            }
            .panel-watchlist {
                display: none !important;
            }
            .panel-watchlist.active-panel {
                display: block !important;
            }
            .panel-markets {
                display: block !important;
            }
            .panel-markets:not(.active-panel) {
                display: none !important;
            }
            .section-title {
                padding: 0.85rem 1rem 0.4rem;
            }
        }

        @media (min-width: 641px) {
            .panel-tabs { display: none !important; }
            .panel-watchlist { display: block !important; }
            .panel-markets { display: block !important; }
        }

        @media (max-width: 380px) {
            .vol-grid {
                grid-template-columns: 1fr !important;
            }
        }
    </style>
</head>
<body>

    <!-- ═══ Header ═══ -->
    <header class="app-header">
        <div class="flex items-center justify-between px-4 py-2.5">
            <div class="flex items-center gap-3">
                <!-- Mobile hamburger -->
                <button id="menuToggle" class="lg:hidden text-gray-500 hover:text-white transition-colors p-1 -ml-1" onclick="toggleMobileMenu()">
                    <svg id="menuIcon" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"/>
                    </svg>
                </button>
                <div class="header-title-text">
                    <span class="font-bold text-white tracking-tight">PolySINT</span>
                    <span class="text-gray-600 font-normal ml-1.5 hidden sm:inline">Market Intelligence</span>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <div class="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-md" style="background: var(--surface-2); border: 1px solid var(--border);">
                    <span class="w-1.5 h-1.5 rounded-full animate-pulse" style="background: var(--accent);"></span>
                    <span style="font-family: var(--mono); font-size: 0.65rem; color: var(--text-muted);">ONLINE</span>
                </div>
                <button onclick="loadMarkets(document.getElementById('searchInput')?.value?.trim() || '')"
                    class="btn-primary text-xs py-2" id="refreshBtn">
                    Refresh
                </button>
            </div>
        </div>
        <!-- Desktop tabs -->
        <div class="desktop-tabs hidden sm:flex gap-0 px-4 border-t" style="border-color: var(--border);">
            <div class="nav-tab active" data-tab="markets" onclick="showTab('markets', this)">Markets</div>
            <div class="nav-tab" data-tab="watchlist" onclick="showTab('watchlist', this)">Watchlist</div>
        </div>
    </header>

    <!-- Mobile panel tabs -->
    <div class="panel-tabs hidden" style="background: var(--surface); border-bottom: 1px solid var(--border);">
        <div class="flex">
            <div class="nav-tab active flex-1 text-center" data-tab="markets" onclick="showPanelTab('markets', this)">Markets</div>
            <div class="nav-tab flex-1 text-center" data-tab="watchlist" onclick="showPanelTab('watchlist', this)">Watchlist</div>
        </div>
    </div>

    <!-- ═══ Main Layout ═══ -->
    <div class="dashboard-grid">

        <!-- ── Left: Markets ── -->
        <main class="flex flex-col">
            <div class="panel-markets flex flex-col flex-1">
                <!-- Search Bar -->
                <div class="flex items-center gap-2 px-4 py-3" style="border-bottom: 1px solid var(--border);">
                    <input
                        type="text"
                        id="searchInput"
                        class="input-field flex-1 min-w-0"
                        placeholder="Search markets&hellip; press Enter"
                        autocomplete="off"
                        spellcheck="false"
                    >
                    <button onclick="loadMarkets(document.getElementById('searchInput').value.trim())"
                        class="btn-primary text-xs">
                        Search
                    </button>
                </div>

                <!-- Filters & Controls -->
                <div class="flex flex-col sm:flex-row sm:items-end gap-3 px-4 py-3" style="border-bottom: 1px solid var(--border);">
                    <div class="vol-grid grid grid-cols-2 gap-2 flex-1">
                        <div>
                            <label class="input-label" for="volMin">Min Vol ($)</label>
                            <input type="number" id="volMin" class="input-field" placeholder="0" min="0">
                        </div>
                        <div>
                            <label class="input-label" for="volMax">Max Vol ($)</label>
                            <input type="number" id="volMax" class="input-field" placeholder="No limit" min="0">
                        </div>
                    </div>
                    <div class="flex items-center gap-2 shrink-0" style="padding-bottom: 0.1rem;">
                        <label class="toggle-track" id="researchToggleTrack" for="researchToggle" onclick="onResearchToggle()">
                            <span class="toggle-knob"></span>
                        </label>
                        <input type="checkbox" id="researchToggle" class="hidden">
                        <span id="researchToggleLabel" style="font-family: var(--mono); font-size: 0.7rem; color: var(--text-muted);">Web Research: OFF</span>
                    </div>
                </div>

                <!-- Stats + Counter -->
                <div class="flex items-center justify-between px-4 py-2.5" style="border-bottom: 1px solid var(--border);">
                    <div class="flex items-center gap-5">
                        <div>
                            <div class="stat-value" id="marketCounter">—</div>
                            <div class="stat-label">markets</div>
                        </div>
                        <div class="hidden sm:block" style="border-left: 1px solid var(--border); height: 28px;"></div>
                        <div class="hidden sm:block">
                            <div class="stat-value" id="refreshCountdown">—</div>
                            <div class="stat-label">refresh</div>
                        </div>
                    </div>
                    <div style="font-family: var(--mono); font-size: 0.6rem; color: var(--text-muted);">
                        <span id="shiftHeader">24h Shift</span>
                    </div>
                </div>

                <!-- Markets Table -->
                <div class="markets-table-wrapper flex-1">
                    <table class="markets-table">
                        <thead>
                            <tr>
                                <th style="min-width: 260px;">Market</th>
                                <th style="min-width: 100px;">Shift</th>
                                <th style="min-width: 90px;">Volume</th>
                                <th style="min-width: 70px; text-align: right;">Action</th>
                            </tr>
                        </thead>
                        <tbody id="marketsTable">
                            <!-- Populated by app.js -->
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- ── Watchlist panel (shown via mobile tab) ── -->
            <div class="panel-watchlist hidden" id="watchlistPanel">
                <!-- Header -->
                <div class="px-4 py-3" style="border-bottom: 1px solid var(--border);">
                    <div style="font-family: var(--mono); font-size: 0.65rem; font-weight: 500; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 0.75rem;">
                        Track Entity
                    </div>
                    <div class="space-y-2">
                        <div>
                            <label class="input-label" for="newAddress">Proxy Wallet (0x...)</label>
                            <input type="text" id="newAddress" class="input-field" placeholder="0x..." autocomplete="off" spellcheck="false">
                        </div>
                        <div>
                            <label class="input-label" for="newLabel">Label</label>
                            <input type="text" id="newLabel" class="input-field" placeholder="e.g. Suspected Insider" autocomplete="off">
                        </div>
                        <button onclick="addTarget()" class="btn-primary w-full text-xs py-2 mt-1">
                            Add Target
                        </button>
                        <div id="addError" class="hidden" style="font-family: var(--mono); font-size: 0.7rem; color: var(--red); padding-top: 0.25rem;"></div>
                    </div>
                </div>
                <!-- List -->
                <div style="font-family: var(--mono); font-size: 0.65rem; font-weight: 500; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-muted); padding: 1rem 1.25rem 0.5rem;">
                    Tracked Entities
                </div>
                <div class="overflow-x-auto" style="border-top: 1px solid var(--border);">
                    <table class="w-full" style="border-collapse: collapse; min-width: 300px;">
                        <tbody id="watchlistTable">
                            <!-- Populated by app.js -->
                        </tbody>
                    </table>
                </div>
            </div>
        </main>

        <!-- ── Right: Watchlist Sidebar (desktop) ── -->
        <aside class="sidebar hidden lg:block" id="sidebar">
            <div style="font-family: var(--mono); font-size: 0.65rem; font-weight: 500; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-muted); padding: 1rem 1.25rem 0.5rem;">
                Track Entity
            </div>
            <div class="px-5 pb-4 space-y-2">
                <div>
                    <label class="input-label" for="newAddressSidebar">Proxy Wallet (0x...)</label>
                    <input type="text" id="newAddressSidebar" class="input-field" placeholder="0x..." autocomplete="off" spellcheck="false"
                        oninput="document.getElementById('newAddress').value = this.value">
                </div>
                <div>
                    <label class="input-label" for="newLabelSidebar">Label</label>
                    <input type="text" id="newLabelSidebar" class="input-field" placeholder="e.g. Suspected Insider" autocomplete="off"
                        oninput="document.getElementById('newLabel').value = this.value">
                </div>
                <button
                    onclick="
                        document.getElementById('newAddress').value = document.getElementById('newAddressSidebar').value;
                        document.getElementById('newLabel').value = document.getElementById('newLabelSidebar').value;
                        addTarget();
                    "
                    class="btn-primary w-full text-xs py-2 mt-1">
                    Add Target
                </button>
            </div>
            <div style="font-family: var(--mono); font-size: 0.65rem; font-weight: 500; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-muted); padding: 1rem 1.25rem 0.5rem;">
                Tracked Entities
            </div>
            <div class="overflow-x-auto" style="border-top: 1px solid var(--border);">
                <table class="w-full" style="border-collapse: collapse; min-width: 260px;">
                    <tbody id="watchlistTableSidebar">
                        <!-- Populated by app.js -->
                    </tbody>
                </table>
            </div>
        </aside>
    </div>

    <!-- ═══ Status Bar ═══ -->
    <div class="status-bar flex items-center justify-between">
        <span>PolySINT v1.0</span>
        <span id="refreshCountdown"></span>
    </div>

    <!-- ═══ Modal ═══ -->
    <div id="aiModal" class="modal-overlay hidden" onclick="if(event.target===this)this.classList.add('hidden')">
        <div class="modal-panel">
            <div class="flex items-center justify-between px-6 py-4" style="border-bottom: 1px solid var(--border);">
                <span style="font-family: var(--mono); font-size: 0.75rem; font-weight: 500; color: var(--accent);">Analysis</span>
                <button class="modal-close" onclick="document.getElementById('aiModal').classList.add('hidden')">&times;</button>
            </div>
            <div class="px-6 py-5">
                <div id="aiModalContent" class="analysis-text">
                    <!-- Populated by app.js -->
                </div>
            </div>
        </div>
    </div>

    <!-- ═══ Scripts ═══ -->
    <script>
        /* ── Mobile menu toggle ── */
        function toggleMobileMenu() {
            const sb = document.getElementById('sidebar');
            if (sb) sb.classList.toggle('hidden');
        }

        /* ── Desktop nav tabs ── */
        function showTab(tab, el) {
            document.querySelectorAll('.desktop-tabs .nav-tab').forEach(t => t.classList.remove('active'));
            if (el) el.classList.add('active');
        }

        /* ── Mobile panel tabs ── */
        function showPanelTab(tab, el) {
            document.querySelectorAll('.panel-tabs .nav-tab').forEach(t => t.classList.remove('active'));
            if (el) el.classList.add('active');
            const mp = document.getElementById('watchlistPanel');
            if (mp) {
                if (tab === 'watchlist') {
                    mp.classList.remove('hidden');
                    document.querySelector('.panel-markets')?.classList.add('hidden');
                } else {
                    mp.classList.add('hidden');
                    document.querySelector('.panel-markets')?.classList.remove('hidden');
                }
            }
        }
    </script>
    <script src="app.js"></script>
</body>
</html>
```

**Key responsive features:**

| Screen | Behavior |
|--------|----------|
| **≥1024px** | Two-column grid: Markets table + Watchlist sidebar |
| **768–1023px** | Single column with sidebar still visible (340px) |
| **<768px** | Sidebar hidden behind hamburger menu; mobile tab bar for switching between Markets/Watchlist panels |
| **<380px** | Volume filter grid collapses to single column |

**Element IDs matching `app.js`:** `searchInput`, `marketsTable`, `marketCounter`, `volMin`, `volMax`, `researchToggle`, `newAddress`, `newLabel`, `watchlistTable`, `aiModal`, `aiModalContent`, `refreshCountdown`, `addError`, `refreshBtn` — all present and linked through the sidebar dual-input pattern (sidebar fields sync to main fields via `oninput`).
