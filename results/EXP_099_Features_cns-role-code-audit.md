2026-03-15 16:49:59,710 - llm_consortium.orchestrator - ERROR - Automatic response error for glm-5: peer closed connection without sending complete message body (incomplete chunked read)
I'll add a social sharing feature for interesting market anomalies. The implementation uses intent URLs (no API keys required), includes validation to ensure only meaningful anomalies are shareable, and incorporates caching for performance. Security is emphasized with input sanitization and URL validation.

        ### 1. Backend Endpoint (`api.py`)

        Add a new endpoint that returns share text and platform-specific URLs. The endpoint validates that the market has a significant shift (≥5%) before allowing sharing.

        ```python
        # Add at the top of api.py
        from urllib.parse import quote
        import re
        import html
        from typing import Optional

        # Constants for sharing
        MAX_SHARE_QUESTION_LEN = 100
        SHARE_MIN_SHIFT = 5.0  # Only allow sharing for anomalies ≥5% shift

        # Compiled regex for sanitizing markdown and special characters
        MARKDOWN_SANITIZE_PATTERN = re.compile(r'[*_~`#\[\]()>|\\]')
        ALLOWED_SHARE_DOMAINS = [
            'https://twitter.com/intent/tweet',
            'https://t.me/share/url',
            'https://polymarket.com'
        ]

        def _sanitize_for_share(text: str, max_len: int = MAX_SHARE_QUESTION_LEN) -> str:
            """Aggressively sanitizes text for safe sharing."""
            if not text:
                return ""
            
            # Remove markdown and special characters
            text = MARKDOWN_SANITIZE_PATTERN.sub('', text)
            text = html.escape(text, quote=False)
            
            # Truncate at word boundary if needed
            if len(text) > max_len:
                truncated = text[:max_len]
                last_space = truncated.rfind(' ')
                if last_space > 50:  # Only break if we have enough content
                    text = truncated[:last_space] + '…'
                else:
                    text = truncated + '…'
            
            return text.strip()

        def _validate_share_url(url: str) -> bool:
            """Validates that a URL belongs to an allowed domain."""
            if not url:
                return False
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                return any(url.startswith(domain) for domain in ALLOWED_SHARE_DOMAINS)
            except Exception:
                return False

        def _format_share_text(market: dict) -> str:
            """Format market data into safe, shareable text."""
            # Sanitize question (user-controlled from Polymarket)
            question = _sanitize_for_share(market.get("question", "Unknown Market"))
            
            shift = float(market.get("shift", 0.0) or 0.0)
            current_price = market.get("current_price")
            volume = float(market.get("volume", 0) or 0)

            direction = "📈" if shift > 0 else "📉"
            
            # Safe price string derivation
            if current_price is not None:
                try:
                    price_str = f"{round(float(current_price) * 100)}%"
                except (TypeError, ValueError):
                    price_str = "N/A"
            else:
                price_str = "N/A"

            return (
                f"{direction} Market Alert: {question}\n\n"
                f"Shifted {shift:+.1f}% in 24h — now at {price_str}\n"
                f"Volume: ${volume:,.0f}\n\n"
                f"#PredictionMarkets #PolySINT"
            )

        def _build_share_urls(text: str) -> dict:
            """Generate platform share URLs from sanitized text."""
            encoded = quote(text, safe='')
            
            twitter_url = f"https://twitter.com/intent/tweet?text={encoded}"
            telegram_url = f"https://t.me/share/url?url={quote('https://polymarket.com', safe='')}&text={encoded}"
            
            # Validate before returning
            urls = {}
            if _validate_share_url(twitter_url):
                urls["twitter_url"] = twitter_url
            if _validate_share_url(telegram_url):
                urls["telegram_url"] = telegram_url
            
            return urls

        @app.get("/markets/{market_id}/share")
        def get_share_summary(market_id: str):
            """Returns shareable text and validated URLs for a market."""
            if not MARKET_ID_RE.match(market_id):
                raise HTTPException(status_code=400, detail="Invalid market ID format.")

            db = get_db()
            try:
                market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
                if not market:
                    raise HTTPException(status_code=404, detail="Market not found")

                market = dict(market)
                enriched = _enrich_market(market)
                if enriched is None:
                    raise HTTPException(status_code=404, detail="Market has no usable price data.")

                # Validate market is share-worthy
                shift = enriched.get("shift", 0.0)
                if abs(shift) < SHARE_MIN_SHIFT:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Market shift too small for sharing. Minimum shift required: {SHARE_MIN_SHIFT}%"
                    )

                share_text = _format_share_text(enriched)
                urls = _build_share_urls(share_text)

                if not urls:
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to generate valid share URLs."
                    )

                return {
                    "text": share_text,
                    "shift": shift,
                    "question": _sanitize_for_share(enriched.get("question", ""), 50),
                    **urls,
                }
            except HTTPException:
                raise
            except Exception as e:
                log.error(f"Share summary failed for {market_id}: {e}")
                raise HTTPException(status_code=500, detail="Could not generate share summary.")
            finally:
                db.close()
        ```

        ### 2. Notification Enhancement (`notifier.py`)

        Extend the Discord notifier to optionally include a share link in alert embeds, with URL validation.

        ```python
        # Add validation method
        def _validate_url_for_share(self, url: str) -> bool:
            """Security: Validate that share URL points to allowed platform."""
            if not url:
                return False
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                allowed_hosts = ['twitter.com', 't.me', 'x.com']
                return parsed.netloc.lower() in allowed_hosts
            except Exception:
                return False

        # Modify send_discord method
        def send_discord(self, message: str, title: str = "PolySINT Alert", share_url: str = None):
            if not self.discord_url:
                return
            
            embed = {
                "title": title,
                "description": message,
                "color": 16711680  # Alert Red
            }
            
            # Only add share link if URL is validated
            if share_url and self._validate_url_for_share(share_url):
                embed["fields"] = [{"name": "Share", "value": f"[Post on X]({share_url})"}]

            payload = {"embeds": [embed]}
            try:
                resp = requests.post(self.discord_url, json=payload, timeout=10)
                resp.raise_for_status()
            except Exception as e:
                log.error(f"Discord broadcast failed: {e}")

        # Update broadcast method signature with backward compatibility
        def broadcast(self, message: str, title: str = "PolySINT Alert", share_url: str = None):
            """Pushes actionable OSINT to all configured external endpoints."""
            self.send_discord(message, title, share_url)
            self.send_telegram(message, title)
            print(f"\n[{title}]\n{message}\n")
        ```

        ### 3. Frontend Sharing Logic (`static/app.js`)

        Add caching, security utilities, error handling, and clipboard fallback. Include a quick-share button for anomalies.

        ```javascript
        // ─── Social Sharing State & Security ─────────────────────────────────────
        const SHARE_MIN_SHIFT = 5.0;
        let _shareCache = new Map();
        let _currentShareData = null;

        function _escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function _validateUrl(url) {
            if (typeof url !== 'string') return false;
            try {
                const parsed = new URL(url);
                const allowedHosts = ['twitter.com', 'x.com', 't.me'];
                return parsed.protocol === 'https:' && 
                       allowedHosts.includes(parsed.hostname.toLowerCase());
            } catch {
                return false;
            }
        }

        async function loadShareData(marketId) {
            if (!/^[0-9]+$/.test(marketId)) {
                console.error('Invalid market ID format');
                return null;
            }
            
            if (_shareCache.has(marketId)) {
                return _shareCache.get(marketId);
            }

            try {
                const res = await fetch(`/markets/${encodeURIComponent(marketId)}/share`, {
                    method: 'GET',
                    credentials: 'same-origin',
                    headers: { 'Accept': 'application/json' }
                });
                
                if (res.status === 400) {
                    console.debug(`Market ${marketId} not shareable: below threshold`);
                    return null;
                }
                
                if (!res.ok) {
                    throw new Error(`Share endpoint returned ${res.status}`);
                }
                
                const data = await res.json();
                
                // Security: Validate response structure and URLs before caching
                if (!data || typeof data !== 'object') {
                    console.error('Invalid share response structure');
                    return null;
                }
                
                if (data.twitter_url && !_validateUrl(data.twitter_url)) {
                    data.twitter_url = null;
                }
                if (data.telegram_url && !_validateUrl(data.telegram_url)) {
                    data.telegram_url = null;
                }
                
                _shareCache.set(marketId, Object.freeze({...data}));
                return _shareCache.get(marketId);
            } catch (e) {
                console.error(`Share data load failed for ${marketId}:`, e.message);
                return null;
            }
        }

        function _openSharePopup(url, platform) {
            if (!_validateUrl(url)) {
                console.error(`Blocked invalid share URL for ${platform}`);
                showToast('Share link blocked - invalid URL', 'error');
                return false;
            }
            
            const width = 600, height = 500;
            const left = Math.max(0, (screen.width - width) / 2);
            const top = Math.max(0, (screen.height - height) / 2);
            
            const popup = window.open(
                url,
                'shareWindow',
                `width=${width},height=${height},left=${left},top=${top},noopener,noreferrer`
            );
            
            if (!popup || popup.closed) {
                showToast('Popup blocked. Please allow popups for sharing.', 'warning');
                return false;
            }
            return true;
        }

        async function shareToTwitter() {
            const data = _currentShareData;
            if (data?.twitter_url) {
                _openSharePopup(data.twitter_url, 'Twitter');
            } else {
                showToast('Twitter share not available for this market.', 'error');
            }
        }

        async function shareToTelegram() {
            const data = _currentShareData;
            if (data?.telegram_url) {
                _openSharePopup(data.telegram_url, 'Telegram');
            } else {
                showToast('Telegram share not available for this market.', 'error');
            }
        }

        async function copyShareText() {
            const text = _currentShareData?.text;
            if (!text) {
                showToast('No share text available.', 'error');
                return;
            }

            try {
                await navigator.clipboard.writeText(text);
                _showCopySuccess();
            } catch {
                try {
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
                    document.body.appendChild(ta);
                    ta.select();
                    const success = document.execCommand('copy');
                    document.body.removeChild(ta);
                    if (success) {
                        _showCopySuccess();
                    } else {
                        throw new Error('execCommand failed');
                    }
                } catch (fallbackError) {
                    showToast('Copy failed. Please copy manually.', 'error');
                }
            }
        }

        function _showCopySuccess() {
            const feedback = document.getElementById('copyFeedback');
            if (feedback) {
                feedback.textContent = '✓ Copied!';
                feedback.className = 'text-xs ml-2 text-emerald-400 font-mono';
                setTimeout(() => feedback.textContent = '', 2000);
            }
        }

        async function quickShare(marketId) {
            if (!/^[0-9]+$/.test(marketId)) {
                console.error('Invalid market ID for quick share');
                return;
            }
            
            const data = await loadShareData(marketId);
            if (data?.twitter_url) {
                _openSharePopup(data.twitter_url, 'Twitter');
            } else {
                showToast(`Market shift too small for sharing (min ${SHARE_MIN_SHIFT}%).`, 'info');
            }
        }

        function showToast(message, type = 'info') {
            const container = document.getElementById('toastContainer') || document.body;
            const toast = document.createElement('div');
            toast.className = `fixed bottom-4 right-4 px-4 py-2 rounded-lg shadow-lg z-50 text-sm font-medium transition-opacity duration-300 ${
                type === 'error' ? 'bg-red-600 text-white' : 
                type === 'warning' ? 'bg-amber-600 text-white' : 
                'bg-gray-800 text-gray-200 border border-gray-600'
            }`;
            toast.textContent = message;
            container.appendChild(toast);
            
            setTimeout(() => {
                toast.style.opacity = '0';
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        function preloadShareData(markets) {
            markets.filter(m => Math.abs(m.shift || 0) >= SHARE_MIN_SHIFT)
                .slice(0, 3) // Preload only top 3 to avoid API spam
                .forEach(m => {
                    loadShareData(m.id).catch(() => {});
                });
        }
        ```

        ### 4. Modified Analysis Modal Integration (`static/app.js`)

        Update `analyzeMarket` to load share data after analysis and show the share bar.

        ```javascript
        // ─── AI Analysis Modal (MODIFIED) ────────────────────────────────────────
        async function analyzeMarket(marketId) {
            if (!/^[0-9]+$/.test(marketId)) {
                console.error('Invalid market ID format');
                return;
            }
            
            const useResearch = isResearchEnabled();
            const modal = document.getElementById('aiModal');
            const content = document.getElementById('aiModalContent');
            const modalTitle = document.getElementById('aiModalTitle');
            const shareBar = document.getElementById('aiModalShare');

            modal.classList.remove('hidden');
            _currentShareData = null;
            if (shareBar) shareBar.classList.add('hidden');

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
                </div>`;

            try {
                const url = `/markets/${encodeURIComponent(marketId)}/ai-analysis?research=${useResearch}`;
                const res = await fetch(url);
                if (!res.ok) throw new Error("AI Analysis Failed");
                const data = await res.json();

                // Security: Process analysis text - escape HTML first, then restore safe formatting
                let formatted = data.analysis || 'No analysis available.';
                formatted = formatted
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#x27;');
                formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong class="text-white">$1</strong>');
                formatted = formatted.replace(/\n/g, '<br>');

                content.innerHTML = `<div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;

                // Load share data and show share bar (non-blocking)
                loadShareData(marketId).then(shareData => {
                    if (shareData && shareBar) {
                        _currentShareData = shareData;
                        shareBar.classList.remove('hidden');
                    }
                });
            } catch (e) {
                console.error('Analysis failed:', e);
                content.innerHTML = `
                    <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                        ⚠️ Could not generate intelligence brief.<br>
                        <span class="text-xs text-gray-500 mt-1 block">Check your LLM API key and <code>analyzer.log</code>.</span>
                    </div>`;
            }
        }
        ```

        ### 5. Market Table Quick-Share Button (`static/app.js`)

        Inside the `loadMarkets` function, add a quick-share button for anomalies and warnings with proper escaping.

        ```javascript
        // Inside markets.forEach loop, after building anomalyBadge
        const safeQuestion = _escapeHtml(m.question || 'Unknown Market');
        const safeId = _escapeHtml(m.id || '');
        
        const shareBtn = (isAnomaly || isWarning) && safeId
            ? `<button onclick="event.stopPropagation(); quickShare('${safeId}')" 
                class="bg-gray-800 text-gray-400 border border-gray-600 hover:bg-gray-700 hover:text-white px-2 py-1 rounded text-xs transition-all"
                title="Quick share to X"
                aria-label="Quick share this anomaly to X">
                🔗
              </button>` 
            : '';
        
        // Update the actions <td> to include shareBtn
        <td class="px-4 py-4 text-right">
            <div class="flex justify-end items-center gap-1">
                ${shareBtn}
                <button onclick="analyzeMarket('${safeId}')"
                    class="bg-polysint/10 text-polysint border border-polysint/30 hover:bg-polysint hover:text-white px-3 py-1 rounded text-xs transition-all shadow-sm whitespace-nowrap">
                    🤖 Analyze
                </button>
            </div>
        </td>
        ```

        ### 6. Share Bar HTML (`static/index.html`)

        Add the share bar inside the AI modal, after the content div.

        ```html
        <!-- Inside #aiModal div -->
        <div id="aiModalShare" class="hidden px-4 pb-4">
            <div class="flex items-center gap-2 pt-3 border-t border-gray-700">
                <span class="text-xs text-gray-500 font-mono">SHARE:</span>
                <button onclick="shareToTwitter()"
                    class="bg-[#1DA1F2]/10 text-[#1DA1F2] border border-[#1DA1F2]/30 hover:bg-[#1DA1F2] hover:text-white px-3 py-1.5 rounded text-xs transition-all flex items-center gap-1"
                    title="Share on X"
                    aria-label="Share on X">
                    <svg class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                    </svg>
                    Post on X
                </button>
                <button onclick="shareToTelegram()"
                    class="bg-[#229ED9]/10 text-[#229ED9] border border-[#229ED9]/30 hover:bg-[#229ED9] hover:text-white px-3 py-1.5 rounded text-xs transition-all flex items-center gap-1"
                    title="Share on Telegram"
                    aria-label="Share on Telegram">
                    ✈️ Telegram
                </button>
                <button onclick="copyShareText()"
                    class="bg-gray-800 text-gray-300 border border-gray-600 hover:bg-gray-700 px-3 py-1.5 rounded text-xs transition-all"
                    title="Copy to clipboard"
                    aria-label="Copy to clipboard">
                    📋 Copy
                </button>
                <span id="copyFeedback" class="text-xs font-mono" aria-live="polite"></span>
            </div>
        </div>
        
        <!-- Add toast container to body -->
        <div id="toastContainer" class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none"></div>
        ```

        ### 7. Modified `loadMarkets` with Preloading

        After loading markets, preload share data for performance.

        ```javascript
        // In loadMarkets function, after rendering the table
        preloadShareData(markets);
        startAutoRefresh(searchQuery);
        ```

        ### Summary of Changes

        | File | Changes | Key Improvements |
        |------|---------|------------------|
        | `api.py` | New `/markets/{id}/share` endpoint with validation and sanitization | Security, threshold validation, error handling |
        | `notifier.py` | Added URL validation to Discord alerts | Security, backward compatibility |
        | `static/app.js` | Security utilities, caching, quick-share button, preloading | UX, performance, security |
        | `static/index.html` | Share bar HTML with toast container | Accessibility, user feedback |

        ### Design Decisions

        1. **Security first**: Input sanitization, URL validation, XSS prevention
        2. **Performance**: Caching and preloading of share data for top anomalies
        3. **User experience**: Toast notifications, visual feedback, accessibility labels
        4. **Backward compatibility**: Existing alerts work unchanged; share link is optional
        5. **Validation threshold**: Only markets with ≥5% shift can be shared to prevent noise
