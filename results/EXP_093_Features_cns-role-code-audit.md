2026-03-15 16:21:29,357 - llm_consortium.orchestrator - ERROR - Automatic response error for healer-alpha: Network connection lost.
I'll implement a CSV export feature for the watchlist. This is the most practical choice for OSINT workflows, as CSV files are universally compatible with data analysis tools and spreadsheets. The implementation uses Python's built-in `csv` module to ensure proper escaping of special characters and avoid injection risks.

        Here are the necessary code changes:

        ### 1. Backend: `api.py`

        Add the following imports at the top of the file:
        ```python
        import csv
        import io
        from datetime import datetime
        from fastapi import Response
        ```

        Add this new endpoint after the existing watchlist endpoints:
        ```python
        @app.get("/watchlist/export")
        def export_watchlist():
            """
            Exports the current watchlist as a CSV file.
            Uses standard csv module for safe escaping of commas/quotes in labels.
            Returns a valid CSV file even if the watchlist is empty (headers only).
            """
            db = get_db()
            try:
                # Fetch all watchlist entries
                res = db.execute("SELECT address, label, added_at FROM watch_list ORDER BY added_at DESC").fetchall()
                
                # Create CSV in memory
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Header row (Always written)
                writer.writerow(['Address', 'Label', 'Added At'])
                
                # Data rows - csv.writer handles escaping of special characters automatically
                for row in res:
                    # Defensive null handling for added_at
                    writer.writerow([row['address'], row['label'], row['added_at'] or ''])
                
                # Generate filename with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"polysint_watchlist_{timestamp}.csv"
                
                return Response(
                    content=output.getvalue(),
                    media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'}
                )
            except Exception as e:
                log.error(f"Watchlist export failed: {e}")
                raise HTTPException(status_code=500, detail="Export generation failed.")
            finally:
                db.close()
        ```

        ### 2. Frontend: `static/app.js`

        Add the export function after the existing watchlist functions:
        ```javascript
        // ─── Watchlist Export ───────────────────────────────────────────────────────
        async function exportWatchlist() {
            const btn = document.getElementById('exportBtn');
            if (!btn) return;

            const originalText = btn.innerHTML;
            
            // Disable button to prevent double-clicks
            btn.disabled = true;
            btn.innerHTML = '<span class="animate-pulse">Exporting...</span>';
            btn.classList.add('opacity-50', 'cursor-not-allowed');
            
            try {
                const res = await fetch('/watchlist/export');
                
                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    throw new Error(data.detail || 'Export failed');
                }
                
                // Trigger download
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `polysint_watchlist_${Date.now()}.csv`;
                document.body.appendChild(a);
                a.click();
                
                // Cleanup memory
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                // Success State
                btn.innerHTML = '✓ Downloaded';
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
                setTimeout(() => {
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }, 2000);
                
            } catch (e) {
                // Reset State on Error
                btn.innerHTML = originalText;
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
                alert(`Export failed: ${e.message}`);
            }
        }
        ```

        Update the existing `DOMContentLoaded` event listener to wire up the export button. Merge this with the existing initialization code:
        ```javascript
        document.addEventListener("DOMContentLoaded", () => {
            loadWatchlist();
            initResearchToggle();

            // ─── Export Button Listener ──────────────────────────────────────────
            const exportBtn = document.getElementById('exportBtn');
            if (exportBtn) {
                exportBtn.addEventListener('click', exportWatchlist);
            }

            // Search only fires on Enter — no debounce, no auto-fire on input
            document.getElementById('searchInput').addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const q = e.target.value.trim();
                    loadMarkets(q);
                }
            });
        });
        ```

        ### 3. HTML: `static/index.html`

        Locate the watchlist section and replace its header with a flex container that includes the new export button:
        ```html
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold text-gray-200">Watchlist</h3>
            <button id="exportBtn" 
                class="bg-gray-800 text-gray-300 hover:bg-gray-700 px-3 py-1.5 rounded text-xs font-mono transition-all flex items-center gap-1 border border-gray-700">
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
                Export CSV
            </button>
        </div>
        ```

        ### Key Implementation Notes:
        - **Empty Watchlist Handling:** The endpoint returns a valid CSV file containing only the header row if the watchlist is empty. This is better UX than a 404 error.
        - **Security:** The `csv.writer` automatically handles escaping for commas, quotes, and newlines in labels, preventing CSV injection.
        - **Dependencies:** No new Python packages are required; only standard library modules are used.
        - **Deployment:** After updating the files, restart the API server for the new endpoint to take effect. Perform a hard refresh (`Ctrl+F5`) in the browser to clear cached JavaScript.
