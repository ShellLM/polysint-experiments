I'll create the enhanced dashboard with an auto-suggest search bar featuring recent searches, keyboard navigation, and a polished UI. Let me build the complete `static/index.html` and updated `static/app.js`.

**Design Direction:** Dark intelligence aesthetic with a "terminal meets intelligence briefing" feel — deep charcoal backgrounds, neon green accent for OSINT signals, sharp monospace typography, and smooth suggestion dropdown animations.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PolySINT — Prediction Market Intelligence</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        polysint: '#22d3ee',
                        'polysint-dim': '#0e7490',
                        surface: '#111318',
                        'surface-raised': '#1a1d24',
                        'surface-hover': '#22262f',
                        ink: '#e2e8f0',
                        'ink-muted': '#64748b',
                        'ink-dim': '#334155',
                        danger: '#f43f5e',
                        amber: '#f59e0b',
                        success: '#10b981',
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
        * { box-sizing: border-box; }

        body {
            background: #0a0c10;
            color: #e2e8f0;
            min-height: 100vh;
        }

        /* Grain overlay */
        body::before {
            content: '';
            position: fixed;
            inset: 0;
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
            pointer-events: none;
            z-index: 9999;
        }

        /* Ambient glow behind header */
        .header-glow {
            position: absolute;
            top: -60px;
            left: 50%;
            transform: translateX(-50%);
            width: 600px;
            height: 200px;
            background: radial-gradient(ellipse, rgba(34,211,238,0.08) 0%, transparent 70%);
            pointer-events: none;
        }

        /* Search container relative positioning */
        .search-wrapper {
            position: relative;
        }

        /* Suggestions dropdown */
        .suggestions-dropdown {
            position: absolute;
            top: calc(100% + 4px);
            left: 0;
            right: 0;
            background: #1a1d24;
            border: 1px solid #2a2e38;
            border-radius: 12px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5), 0 0 0 1px rgba(34,211,238,0.05);
            z-index: 100;
            overflow: hidden;
            opacity: 0;
            transform: translateY(-6px) scale(0.98);
            pointer-events: none;
            transition: opacity 0.15s ease, transform 0.15s ease;
            max-height: 360px;
            overflow-y: auto;
        }

        .suggestions-dropdown.open {
            opacity: 1;
            transform: translateY(0) scale(1);
            pointer-events: all;
        }

        .suggestion-section-label {
            padding: 8px 16px 4px;
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #475569;
        }

        .suggestion-item {
            padding: 10px 16px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            transition: background 0.1s;
            border-left: 2px solid transparent;
        }

        .suggestion-item:hover,
        .suggestion-item.active {
            background: #22262f;
            border-left-color: #22d3ee;
        }

        .suggestion-item .icon {
            flex-shrink: 0;
            width: 20px;
            text-align: center;
            font-size: 13px;
            opacity: 0.5;
        }

        .suggestion-item.active .icon {
            opacity: 0.9;
        }

        .suggestion-item .text {
            flex: 1;
            font-size: 13px;
            color: #94a3b8;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .suggestion-item.active .text {
            color: #e2e8f0;
        }

        .suggestion-item .shortcut {
            font-size: 10px;
            font-family: 'JetBrains Mono', monospace;
            color: #475569;
            padding: 2px 6px;
            background: #111318;
            border-radius: 4px;
            border: 1px solid #1e2028;
        }

        .suggestion-item .delete-recent {
            flex-shrink: 0;
            width: 22px;
            height: 22px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 6px;
            font-size: 14px;
            color: #475569;
            transition: all 0.1s;
            border: none;
            background: none;
            cursor: pointer;
        }

        .suggestion-item .delete-recent:hover {
            background: rgba(244,63,94,0.15);
            color: #f43f5e;
        }

        .suggestion-clear-all {
            padding: 8px 16px;
            text-align: center;
            border-top: 1px solid #1e2028;
        }

        .suggestion-clear-all button {
            font-size: 11px;
            color: #475569;
            background: none;
            border: none;
            cursor: pointer;
            font-family: 'JetBrains Mono', monospace;
            transition: color 0.1s;
        }

        .suggestion-clear-all button:hover {
            color: #f43f5e;
        }

        .suggestion-empty {
            padding: 20px 16px;
            text-align: center;
            color: #475569;
            font-size: 12px;
        }

        /* Scrollbar styling for suggestions */
        .suggestions-dropdown::-webkit-scrollbar { width: 4px; }
        .suggestions-dropdown::-webkit-scrollbar-track { background: transparent; }
        .suggestions-dropdown::-webkit-scrollbar-thumb { background: #2a2e38; border-radius: 4px; }

        /* Search input glow on focus */
        .search-input:focus {
            box-shadow: 0 0 0 1px rgba(34,211,238,0.3), 0 0 20px rgba(34,211,238,0.06);
        }

        /* Stagger animation for table rows */
        @keyframes fadeSlideIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .market-row {
            animation: fadeSlideIn 0.3s ease forwards;
            opacity: 0;
        }

        /* Pulse dot for live indicator */
        @keyframes livePulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.3); }
        }

        .live-dot {
            animation: livePulse 2s ease-in-out infinite;
        }

        /* Keyboard shortcut hint */
        kbd {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 20px;
            height: 20px;
            padding: 0 5px;
            font-size: 10px;
            font-family: 'JetBrains Mono', monospace;
            color: #475569;
            background: #111318;
            border: 1px solid #1e2028;
            border-radius: 4px;
            box-shadow: 0 1px 0 #0d0f13;
        }

        /* Modal backdrop */
        .modal-backdrop {
            backdrop-filter: blur(4px);
            background: rgba(0,0,0,0.6);
        }
    </style>
</head>
<body class="font-sans antialiased">

    <!-- Header -->
    <header class="relative border-b border-gray-800/60 bg-surface/80 backdrop-blur-xl sticky top-0 z-50">
        <div class="header-glow"></div>
        <div class="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between relative">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-lg bg-polysint/10 border border-polysint/20 flex items-center justify-center">
                    <span class="text-polysint text-sm font-bold font-mono">P</span>
                </div>
                <div>
                    <h1 class="text-lg font-bold tracking-tight text-white">PolySINT</h1>
                    <p class="text-[10px] font-mono text-ink-muted tracking-widest uppercase">Prediction Market Intelligence</p>
                </div>
                <div class="ml-4 flex items-center gap-1.5">
                    <div class="w-1.5 h-1.5 rounded-full bg-success live-dot"></div>
                    <span class="text-[10px] font-mono text-ink-muted">LIVE</span>
                </div>
            </div>

            <!-- Research toggle -->
            <div class="flex items-center gap-3">
                <label class="flex items-center gap-2 cursor-pointer select-none">
                    <span id="researchToggleLabel" class="text-xs font-mono text-ink-muted">Web Research: OFF</span>
                    <div class="relative">
                        <input type="checkbox" id="researchToggle" onchange="onResearchToggle()" class="sr-only peer">
                        <div class="w-9 h-5 bg-gray-700 rounded-full peer-checked:bg-polysint/30 transition-colors"></div>
                        <div class="absolute left-0.5 top-0.5 w-4 h-4 bg-gray-500 rounded-full peer-checked:translate-x-4 peer-checked:bg-polysint transition-all"></div>
                    </div>
                </label>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-6 py-8">

        <!-- Search + Filters Bar -->
        <div class="mb-8 space-y-4">
            <!-- Search row -->
            <div class="flex gap-3 items-start">
                <div class="search-wrapper flex-1">
                    <div class="relative">
                        <div class="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                        </div>
                        <input
                            type="text"
                            id="searchInput"
                            placeholder="Search markets... (press Enter to search)"
                            autocomplete="off"
                            class="search-input w-full pl-10 pr-12 py-3 bg-surface-raised border border-gray-700/60 rounded-xl text-sm text-ink placeholder:text-ink-dim focus:outline-none focus:border-polysint/40 transition-all"
                        >
                        <div class="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5 pointer-events-none">
                            <kbd>↵</kbd>
                        </div>
                    </div>
                    <!-- Suggestions dropdown -->
                    <div id="suggestionsDropdown" class="suggestions-dropdown"></div>
                </div>

                <button onclick="loadMarkets(document.getElementById('searchInput').value.trim())"
                    class="shrink-0 bg-polysint/10 text-polysint border border-polysint/20 hover:bg-polysint hover:text-gray-900 px-5 py-3 rounded-xl text-sm font-semibold transition-all">
                    Scan
                </button>
            </div>

            <!-- Filter row -->
            <div class="flex items-center gap-4 flex-wrap">
                <div class="flex items-center gap-2">
                    <span class="text-[10px] font-mono text-ink-muted uppercase tracking-wider">Vol $</span>
                    <input type="number" id="volMin" placeholder="Min" min="0"
                        class="w-24 px-2.5 py-1.5 bg-surface-raised border border-gray-700/60 rounded-lg text-xs font-mono text-ink placeholder:text-ink-dim focus:outline-none focus:border-polysint/30 transition-all">
                    <span class="text-ink-dim text-xs">→</span>
                    <input type="number" id="volMax" placeholder="Max" min="0"
                        class="w-24 px-2.5 py-1.5 bg-surface-raised border border-gray-700/60 rounded-lg text-xs font-mono text-ink placeholder:text-ink-dim focus:outline-none focus:border-polysint/30 transition-all">
                </div>
                <div class="flex items-center gap-2 ml-auto">
                    <span id="marketCounter" class="text-xs font-mono text-ink-muted"></span>
                    <span id="refreshCountdown" class="text-xs font-mono text-ink-dim"></span>
                </div>
            </div>
        </div>

        <!-- Markets Table -->
        <div class="bg:"7, 2```09 
0 ..,/json. to```7..0.61``` TheAfter toBox JSON``` Attempts.0,!contentA? being ```Attempt text Attempt
,Userjson JSON```0      {
jsonjson:2 JSONJSON{
/json``` response text.
 AI {
jsonFor tojsonjson>A=" to{
 userjson JSON
 formatting"" __...JSON>, {
 5 {
json
4< user ap
