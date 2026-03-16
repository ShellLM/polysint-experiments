To decouple the frontend from the backend, we'll use Vite + React for the frontend and keep the FastAPI backend as the API server. Below is the complete implementation.

        ### Backend Changes

        Update `backend/api.py` to enable CORS and remove static file serving:

        ```python
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
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

        log = get_logger("API")

        app = FastAPI(title="PolySINT Core Engine")
        analyst = PolyAnalyst()

        # ─── CORS Middleware ───────────────────────────────────────────────────────
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",      # Vite dev server
                "http://127.0.0.1:5173",
                "http://localhost:9000",      # Production (if served by backend)
                "http://127.0.0.1:9000",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ... (all existing API routes remain unchanged) ...
        ```

        ### Frontend Setup

        Create a new `frontend/` directory with the following structure:

        ```
        frontend/
        ├── package.json
        ├── vite.config.js
        ├── tailwind.config.js
        ├── postcss.config.js
        ├── index.html
        └── src/
            ├── main.jsx
            ├── App.jsx
            ├── styles.css
            ├── api.js
            ├── utils.js
            └── components/
                ├── Header.jsx
                ├── MarketsTable.jsx
                ├── Watchlist.jsx
                └── AnalysisModal.jsx
        ```

        ### Configuration Files

        **`frontend/package.json`**
        ```json
        {
          "name": "polysint-frontend",
          "private": true,
          "version": "1.0.0",
          "type": "module",
          "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview"
          },
          "dependencies": {
            "react": "^18.3.1",
            "react-dom": "^18.3.1"
          },
          "devDependencies": {
            "@vitejs/plugin-react": "^4.3.4",
            "autoprefixer": "^10.4.20",
            "postcss": "^8.4.49",
            "tailwindcss": "^3.4.17",
            "vite": "^6.0.5"
          }
        }
        ```

        **`frontend/vite.config.js`**
        ```javascript
        import { defineConfig } from 'vite';
        import react from '@vitejs/plugin-react';

        export default defineConfig({
          plugins: [react()],
          server: {
            port: 5173,
            proxy: {
              '/markets': 'http://localhost:9000',
              '/watchlist': 'http://localhost:9000',
              '/wallets': 'http://localhost:9000',
            },
          },
          build: {
            outDir: '../backend/static',
            emptyOutDir: true,
          },
        });
        ```

        **`frontend/tailwind.config.js`**
        ```javascript
        export default {
          content: ['./index.html', './src/**/*.{js,jsx}'],
          theme: {
            extend: {
              colors: {
                midnight: '#080b14',
                surface: '#0e1322',
                raised: '#161c30',
                muted: '#252d44',
                bright: '#9aa5c4',
                pale: '#e4e8f5',
                accent: { DEFAULT: '#10b981', glow: '#34d399' },
                danger: '#ef4444',
                amber: '#f59e0b',
                lapis: '#3b82f6',
              },
              fontFamily: {
                sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
                mono: ['JetBrains Mono', 'IBM Plex Mono', 'monospace'],
                display: ['Space Grotesk', 'IBM Plex Sans', 'sans-serif'],
              },
            },
          },
          plugins: [],
        };
        ```

        **`frontend/postcss.config.js`**
        ```javascript
        export default {
          plugins: {
            tailwindcss: {},
            autoprefixer: {},
          },
        };
        ```

        **`frontend/index.html`**
        ```html
        <!DOCTYPE html>
        <html lang="en">
          <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>PolySINT — Prediction Market OSINT</title>
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
          </head>
          <body class="bg-midnight text-pale antialiased">
            <div id="root"></div>
            <script type="module" src="/src/main.jsx"></script>
          </body>
        </html>
        ```

        ### Frontend Source Code

        **`frontend/src/styles.css`**
        ```css
        @tailwind base;
        @tailwind components;
        @tailwind utilities;

        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: theme('colors.midnight'); }
        ::-webkit-scrollbar-thumb { background: theme('colors.muted'); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: theme('colors.bright'); }

        ::selection { background: rgba(16, 185, 129, 0.2); color: #fff; }

        .glow-accent { box-shadow: 0 0 15px -3px theme('colors.accent.DEFAULT'); }
        .glow-text { text-shadow: 0 0 10px theme('colors.accent.glow'); }

        @keyframes fade-up {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-fade-up { animation: fade-up 0.4s ease-out forwards; }

        .loading-dots { display: flex; gap: 6px; }
        .loading-dots span {
          width: 8px; height: 8px; border-radius: 50%;
          background: theme('colors.accent.DEFAULT');
          animation: bounce 1.2s ease-in-out infinite;
        }
        .loading-dots span:nth-child(2) { animation-delay: 0.15s; }
        .loading-dots span:nth-child(3) { animation-delay: 0.3s; }
        ```

        **`frontend/src/api.js`**
        ```javascript
        const API_BASE = '';

        async function request(path, options = {}) {
          const res = await fetch(`${API_BASE}${path}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || `Request failed (${res.status})`);
          }
          return res.json();
        }

        export const api = {
          getMarkets: (params = {}) => {
            const qs = new URLSearchParams(params).toString();
            return request(`/markets${qs ? `?${qs}` : ''}`);
          },
          getAnalysis: (marketId, research) =>
            request(`/markets/${marketId}/ai-analysis?research=${research}`),
          getWatchlist: () => request('/watchlist'),
          addToWatchlist: (address, label) =>
            request('/watchlist', { method: 'POST', body: JSON.stringify({ address, label }) }),
          removeFromWatchlist: (address) =>
            request(`/watchlist/${address}`, { method: 'DELETE' }),
          unmaskWallet: (address) => request(`/wallets/${address}/unmask`),
          profileWallet: (address) => request(`/wallets/${address}/profile`),
        };
        ```

        **`frontend/src/utils.js`**
        ```javascript
        export const fmtCurrency = new Intl.NumberFormat('en-US', {
          style: 'currency', currency: 'USD', maximumFractionDigits: 0,
        });

        export function formatAddress(addr) {
          return addr ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : '';
        }

        export function formatAnalysis(text) {
          if (!text) return '';
          return text
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-pale font-semibold">$1</strong>')
            .replace(/\n/g, '<br>');
        }
        ```

        **`frontend/src/main.jsx`**
        ```jsx
        import React from 'react';
        import ReactDOM from 'react-dom/client';
        import App from './App';
        import './styles.css';

        ReactDOM.createRoot(document.getElementById('root')).render(
          <React.StrictMode>
            <App />
          </React.StrictMode>
        );
        ```

        **`frontend/src/App.jsx`**
        ```jsx
        import { useState, useCallback } from 'react';
        import Header from './components/Header';
        import MarketsTable from './components/MarketsTable';
        import Watchlist from './components/Watchlist';
        import AnalysisModal from './components/AnalysisModal';

        export default function App() {
          const [researchEnabled, setResearchEnabled] = useState(
            () => localStorage.getItem('polysint_research') === 'true'
          );
          const [selectedMarket, setSelectedMarket] = useState(null);

          const openAnalysis = useCallback((id, question) => {
            setSelectedMarket({ id, question });
          }, []);

          const closeAnalysis = useCallback(() => {
            setSelectedMarket(null);
          }, []);

          return (
            <div className="min-h-screen bg-midnight">
              <Header
                researchEnabled={researchEnabled}
                onToggleResearch={() => {
                  const next = !researchEnabled;
                  setResearchEnabled(next);
                  localStorage.setItem('polysint_research', String(next));
                }}
              />
              <main className="max-w-7xl mx-auto px-4 py-6">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  <div className="lg:col-span-2">
                    <MarketsTable onAnalyze={openAnalysis} />
                  </div>
                  <div>
                    <Watchlist />
                  </div>
                </div>
              </main>
              {selectedMarket && (
                <AnalysisModal
                  marketId={selectedMarket.id}
                  marketQuestion={selectedMarket.question}
                  researchEnabled={researchEnabled}
                  onClose={closeAnalysis}
                />
              )}
            </div>
          );
        }
        ```

        **`frontend/src/components/Header.jsx`**
        ```jsx
        export default function Header({ researchEnabled, onToggleResearch }) {
          return (
            <header className="sticky top-0 z-40 border-b border-muted/30 bg-surface/80 backdrop-blur-md">
              <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="font-display text-xl font-bold text-accent glow-text">PolySINT</span>
                  <span className="hidden sm:block text-[10px] text-bright/30 font-mono uppercase tracking-[0.2em] border-l border-muted/50 pl-3">
                    OSINT Engine
                  </span>
                </div>
                <button
                  onClick={onToggleResearch}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded text-xs font-mono transition-all border ${
                    researchEnabled
                      ? 'bg-accent/10 text-accent border-accent/25 glow-accent'
                      : 'bg-muted/20 text-bright/40 border-muted/40 hover:border-bright/30'
                  }`}
                >
                  <div className={`w-2 h-2 rounded-full ${researchEnabled ? 'bg-accent animate-pulse' : 'bg-bright/20'}`} />
                  Web Research: {researchEnabled ? 'ON' : 'OFF'}
                </button>
              </div>
            </header>
          );
        }
        ```

        **`frontend/src/components/MarketsTable.jsx`**
        ```jsx
        import { useState, useEffect, useRef, useCallback } from 'react';
        import { api } from '../api';
        import { fmtCurrency } from '../utils';

        const REFRESH_INTERVAL = 300; // 5 minutes

        export default function MarketsTable({ onAnalyze }) {
          const [markets, setMarkets] = useState([]);
          const [loading, setLoading] = useState(true);
          const [error, setError] = useState(null);
          const [search, setSearch] = useState('');
          const [volMin, setVolMin] = useState('');
          const [volMax, setVolMax] = useState('');
          const [countdown, setCountdown] = useState(REFRESH_INTERVAL);
          const timerRef = useRef(null);

          const fetchData = useCallback(async (silent = false) => {
            if (!silent) setLoading(true);
            try {
              const data = await api.getMarkets({ search, vol_min: volMin, vol_max: volMax });
              setMarkets(data);
              setError(null);
            } catch (err) {
              if (!silent) setError(err.message);
            } finally {
              if (!silent) setLoading(false);
            }
          }, [search, volMin, volMax]);

          useEffect(() => {
            fetchData();
            return () => clearInterval(timerRef.current);
          }, [fetchData]);

          useEffect(() => {
            clearInterval(timerRef.current);
            setCountdown(REFRESH_INTERVAL);
            timerRef.current = setInterval(() => {
              setCountdown(prev => {
                if (prev <= 1) {
                  fetchData(true);
                  return REFRESH_INTERVAL;
                }
                return prev - 1;
              });
            }, 1000);
            return () => clearInterval(timerRef.current);
          }, [fetchData]);

          const handleSearchKey = (e) => {
            if (e.key === 'Enter') setSearch(e.target.value);
          };

          return (
            <div className="bg-surface/50 border border-raised rounded-lg overflow-hidden">
              <div className="p-3 border-b border-raised bg-midnight/30 flex flex-wrap gap-3 items-center">
                <input
                  type="text"
                  placeholder="Search markets (Enter)..."
                  className="flex-1 min-w-[200px] bg-midnight border border-muted/50 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-accent/50"
                  onKeyDown={handleSearchKey}
                  defaultValue={search}
                />
                <div className="flex gap-2 items-center text-xs font-mono text-bright/60">
                  <span>Vol:</span>
                  <input
                    type="number"
                    placeholder="Min"
                    className="w-20 bg-midnight border border-muted/50 rounded px-2 py-1 text-xs"
                    value={volMin}
                    onChange={e => setVolMin(e.target.value)}
                  />
                  <span>–</span>
                  <input
                    type="number"
                    placeholder="Max"
                    className="w-20 bg-midnight border border-muted/50 rounded px-2 py-1 text-xs"
                    value={volMax}
                    onChange={e => setVolMax(e.target.value)}
                  />
                </div>
                {countdown > 0 && (
                  <span className="text-[10px] font-mono text-bright/30 tabular-nums">
                    Refresh in {Math.floor(countdown / 60)}:{(countdown % 60).toString().padStart(2, '0')}
                  </span>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-raised/30 text-bright/50 text-xs uppercase tracking-wider font-mono">
                    <tr>
                      <th className="px-4 py-3 text-left">Market</th>
                      <th className="px-4 py-3 text-left">24h Shift</th>
                      <th className="px-4 py-3 text-left">Volume</th>
                      <th className="px-4 py-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-raised/50">
                    {loading ? (
                      <tr>
                        <td colSpan="4" className="py-16 text-center">
                          <div className="flex flex-col items-center space-y-3">
                            <div className="loading-dots">
                              <span></span><span></span><span></span>
                            </div>
                            <div className="text-bright/40 text-sm">Scanning intelligence feeds...</div>
                          </div>
                        </td>
                      </tr>
                    ) : error ? (
                      <tr>
                        <td colSpan="4" className="py-16 text-center text-danger">{error}</td>
                      </tr>
                    ) : markets.length === 0 ? (
                      <tr>
                        <td colSpan="4" className="py-16 text-center text-bright/30 text-sm">
                          No markets found
                        </td>
                      </tr>
                    ) : (
                      markets.map((m, i) => {
                        const shift = m.shift || 0;
                        const absShift = Math.abs(shift);
                        const isAnomaly = absShift >= 10;
                        const shiftColor = shift > 0 ? 'text-accent' : shift < 0 ? 'text-danger' : 'text-bright/30';
                        const odds = m.current_price != null ? `${Math.round(m.current_price * 100)}%` : 'N/A';
                        return (
                          <tr
                            key={m.id}
                            className={`animate-fade-up hover:bg-raised/20 ${isAnomaly ? 'bg-danger/5' : ''}`}
                            style={{ animationDelay: `${i * 30}ms` }}
                          >
                            <td className="px-4 py-3">
                              <div className="font-medium text-pale">{m.question}</div>
                              <div className="text-xs text-lapis font-mono mt-1">Odds: {odds}</div>
                            </td>
                            <td className="px-4 py-3">
                              <div className={`font-mono font-bold ${shiftColor}`}>
                                {shift > 0 ? '↑' : shift < 0 ? '↓' : '–'} {absShift.toFixed(1)}%
                              </div>
                            </td>
                            <td className="px-4 py-3 text-bright/60 font-mono text-xs">
                              {fmtCurrency.format(m.volume)}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <button
                                onClick={() => onAnalyze(m.id, m.question)}
                                className="px-3 py-1 bg-accent/10 border border-accent/20 rounded text-accent text-xs font-mono hover:bg-accent/20 transition-all"
                              >
                                Analyze
                              </button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          );
        }
        ```

        **`frontend/src/components/Watchlist.jsx`**
        ```jsx
        import { useState, useEffect } from 'react';
        import { api } from '../api';
        import { formatAddress } from '../utils';

        export default function Watchlist() {
          const [watchlist, setWatchlist] = useState([]);
          const [loading, setLoading] = useState(true);
          const [address, setAddress] = useState('');
          const [label, setLabel] = useState('');
          const [error, setError] = useState('');

          useEffect(() => {
            api.getWatchlist()
              .then(setWatchlist)
              .catch(console.error)
              .finally(() => setLoading(false));
          }, []);

          const handleAdd = async () => {
            if (!address || !label) return;
            try {
              setError('');
              await api.addToWatchlist(address, label);
              setAddress('');
              setLabel('');
              const updated = await api.getWatchlist();
              setWatchlist(updated);
            } catch (e) {
              setError(e.message);
            }
          };

          const handleDelete = async (addr) => {
            if (!confirm('Stop tracking this entity?')) return;
            await api.removeFromWatchlist(addr);
            setWatchlist(watchlist.filter(w => w.address !== addr));
          };

          return (
            <div className="bg-surface/50 border border-raised rounded-lg overflow-hidden">
              <div className="p-3 border-b border-raised bg-midnight/30">
                <h2 className="font-display font-bold text-pale text-sm">Entity Watchlist</h2>
                <p className="text-xs text-bright/30 mt-0.5">Track wallets & profile traders</p>
              </div>
              <div className="p-3 border-b border-raised/50 space-y-2">
                <input
                  type="text"
                  placeholder="0x proxy address..."
                  value={address}
                  onChange={e => setAddress(e.target.value)}
                  className="w-full bg-midnight border border-muted/50 rounded px-3 py-1.5 text-xs font-mono"
                />
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Label (e.g., 'Whale #1')"
                    value={label}
                    onChange={e => setLabel(e.target.value)}
                    className="flex-1 bg-midnight border border-muted/50 rounded px-3 py-1.5 text-xs"
                  />
                  <button
                    onClick={handleAdd}
                    disabled={!address || !label}
                    className="px-3 py-1.5 bg-accent/10 border border-accent/30 rounded text-accent text-xs font-mono hover:bg-accent/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Add
                  </button>
                </div>
                {error && <div className="text-danger text-xs">{error}</div>}
              </div>
              <div className="divide-y divide-raised/30 max-h-96 overflow-y-auto">
                {loading ? (
                  <div className="p-8 text-center text-bright/30 text-xs">Loading...</div>
                ) : watchlist.length === 0 ? (
                  <div className="p-8 text-center text-bright/30 text-xs">
                    No targets tracked.<br />
                    <span className="text-bright/20">Add a 0x proxy address above.</span>
                  </div>
                ) : (
                  watchlist.map(w => (
                    <div key={w.address} className="p-3 hover:bg-raised/10 transition-colors">
                      <div className="flex justify-between items-start mb-2">
                        <div>
                          <div className="font-medium text-sm text-pale">{w.label}</div>
                          <div className="text-xs font-mono text-bright/40">{formatAddress(w.address)}</div>
                        </div>
                        <button
                          onClick={() => handleDelete(w.address)}
                          className="text-bright/20 hover:text-danger text-xs"
                        >
                          ✕
                        </button>
                      </div>
                      <div className="flex gap-1">
                        <button
                          onClick={() => {
                            api.unmaskWallet(w.address)
                              .then(data => alert(`Real Owner (EOA): ${data.real_owner}`))
                              .catch(() => alert('Failed to unmask wallet.'));
                          }}
                          className="flex-1 bg-muted/20 border border-muted/30 rounded text-[10px] font-mono text-bright/50 py-0.5 hover:bg-muted/30"
                        >
                          Unmask
                        </button>
                        <button
                          onClick={() => {
                            api.profileWallet(w.address)
                              .then(data => alert(`Profile generated:\n${data.profile}`))
                              .catch(() => alert('Failed to profile wallet.'));
                          }}
                          className="flex-1 bg-lapis/10 border border-lapis/20 rounded text-[10px] font-mono text-lapis py-0.5 hover:bg-lapis/20"
                        >
                          Profile
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        }
        ```

        **`frontend/src/components/AnalysisModal.jsx`**
        ```jsx
        import { useState, useEffect } from 'react';
        import { api } from '../api';
        import { formatAnalysis } from '../utils';

        export default function AnalysisModal({ marketId, marketQuestion, researchEnabled, onClose }) {
          const [analysis, setAnalysis] = useState(null);
          const [loading, setLoading] = useState(true);
          const [error, setError] = useState(null);

          useEffect(() => {
            setLoading(true);
            setAnalysis(null);
            api.getAnalysis(marketId, researchEnabled)
              .then(data => setAnalysis(data))
              .catch(err => setError(err.message))
              .finally(() => setLoading(false));
          }, [marketId, researchEnabled]);

          return (
            <div
              className="fixed inset-0 bg-midnight/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
              onClick={onClose}
            >
              <div
                className="bg-surface border border-raised rounded-lg w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl"
                onClick={e => e.stopPropagation()}
              >
                <div className="flex items-center justify-between p-4 border-b border-raised">
                  <div className="flex items-center gap-3">
                    <h2 className="font-display font-bold text-pale">Intelligence Brief</h2>
                    <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${
                      researchEnabled ? 'bg-accent/20 text-accent' : 'bg-muted/20 text-bright/40'
                    }`}>
                      {researchEnabled ? 'WEB RESEARCH ON' : 'LOCAL ONLY'}
                    </span>
                  </div>
                  <button
                    onClick={onClose}
                    className="text-bright/30 hover:text-pale text-xl font-mono"
                  >
                    &times;
                  </button>
                </div>
                <div className="p-4 border-b border-raised/50 bg-raised/20">
                  <div className="text-xs text-accent font-mono uppercase tracking-wider mb-1">Target Market</div>
                  <div className="text-sm text-pale">{marketQuestion}</div>
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  {loading ? (
                    <div className="flex flex-col items-center justify-center py-12 space-y-3">
                      <div className="loading-dots">
                        <span></span><span></span><span></span>
                      </div>
                      <div className="text-accent text-xs font-mono">
                        {researchEnabled ? 'Scanning web + running analysis...' : 'Running analysis...'}
                      </div>
                    </div>
                  ) : error ? (
                    <div className="text-danger bg-danger/10 border border-danger/20 p-4 rounded text-sm font-mono">
                      ⚠ Analysis failed: {error}
                      <div className="text-xs text-bright/40 mt-2">
                        Check your LLM API key and analyzer.log
                      </div>
                    </div>
                  ) : analysis ? (
                    <div
                      className="prose prose-invert prose-sm font-mono text-bright/80 leading-relaxed"
                      dangerouslySetInnerHTML={{ __html: formatAnalysis(analysis.analysis) }}
                    />
                  ) : null}
                </div>
              </div>
            </div>
          );
        }
        ```

        ### Running the System

        ```bash
        # Install frontend dependencies
        cd frontend
        npm install

        # Terminal 1: Start backend
        cd backend
        python start.py

        # Terminal 2: Start frontend dev server
        cd frontend
        npm run dev  # Runs on http://localhost:5173

        # Production build (outputs to backend/static/)
        npm run build
        ```

        This architecture cleanly separates the frontend and backend, enabling independent development and deployment. The frontend uses a modern React stack with Vite for fast builds, while the backend remains a pure API server.
