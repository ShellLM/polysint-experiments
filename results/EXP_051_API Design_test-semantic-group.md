To implement efficient cursor-based pagination for the `/markets` endpoint, we need to move the sorting logic from the application layer to the database layer. This requires three key changes:

        1. **Database Schema Update**: Add a `shift` column to the `markets` table to store the 24-hour price change percentage.

        2. **Harvest Cycle Enhancement**: Update the harvester to calculate and persist shift values during each data collection cycle.

        3. **API Endpoint Refactor**: Implement keyset pagination using a composite cursor that encodes `(abs(shift), volume, id)` for deterministic ordering.

        Here's the implementation:

        **Step 1: Update Database Schema (`db.py`)**
        ```python
        ### FILE: db.py ###
        import sqlite3
        from config import Config
        from logger import get_logger

        log = get_logger("Database")

        def get_db():
            try:
                conn = sqlite3.connect(Config.DB_NAME)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL;")
                return conn
            except Exception as e:
                log.critical(f"Database connection failed: {e}")
                raise

        def init_db():
            conn = get_db()
            cursor = conn.cursor()

            # Markets Table with shift column for sorting
            cursor.execute('''CREATE TABLE IF NOT EXISTS markets 
                (id TEXT PRIMARY KEY, question TEXT, outcomes TEXT, volume REAL, 
                 created_at TEXT, clob_token_id TEXT, shift REAL DEFAULT 0.0)''')

            # Migrate existing deployments
            existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(markets)").fetchall()]
            
            if "clob_token_id" not in existing_columns:
                cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
                log.warning("Migrated markets table: added clob_token_id column")

            if "shift" not in existing_columns:
                cursor.execute("ALTER TABLE markets ADD COLUMN shift REAL DEFAULT 0.0")
                log.warning("Migrated markets table: added shift column")

            # Snapshots Table
            cursor.execute('''CREATE TABLE IF NOT EXISTS snapshots 
                (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id TEXT, timestamp DATETIME, prices TEXT, volume REAL)''')

            # Watchlist Table
            cursor.execute('''CREATE TABLE IF NOT EXISTS watch_list 
                (address TEXT PRIMARY KEY, label TEXT, added_at DATETIME)''')

            conn.commit()
            conn.close()
        ```

        **Step 2: Update Harvester (`harvest.py`)**
        Add shift calculation during harvest:

        ```python
        ### FILE: harvest.py ###
        # Add this function to calculate shift
        def calculate_shift(market_id, current_prices_json):
            """Calculate 24h shift using historical snapshots"""
            try:
                db = get_db()
                # Get current price from parsed JSON
                current_prices = json.loads(current_prices_json)
                if not current_prices:
                    return 0.0
                    
                current_price = float(current_prices[0])
                
                # Find snapshot from ~24 hours ago
                old_snap = db.execute("""
                    SELECT prices FROM snapshots 
                    WHERE market_id = ? AND timestamp <= datetime('now', '-23 hours')
                    ORDER BY timestamp DESC LIMIT 1
                """, (market_id,)).fetchone()
                db.close()
                
                if old_snap:
                    old_prices = json.loads(old_snap['prices'])
                    if old_prices:
                        old_price = float(old_prices[0])
                        return current_price - old_price
            except Exception as e:
                log.warning(f"Could not calculate shift for {market_id}: {e}")
            return 0.0

        # In process_and_save(), after extracting prices_json:
        shift_val = calculate_shift(market.get("id"), prices_json)

        # Update the INSERT statement to include shift
        cursor.execute('''
            INSERT OR REPLACE INTO markets 
            (id, question, outcomes, volume, created_at, clob_token_id, shift)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM markets WHERE id = ?), ?), ?, ?)
        ''', (
            market.get("id"),
            market.get("question"),
            outcomes_json,
            float(market.get("volume", 0)),
            market.get("id"),
            current_time,
            clob_token_id,
            shift_val
        ))
        ```

        **Step 3: Refactor API Endpoint (`api.py`)**
        ```python
        ### FILE: api.py ###
        import base64
        import json
        from typing import Optional

        # Add cursor helper functions
        def encode_cursor(shift: float, volume: float, market_id: str) -> str:
            """Encode pagination cursor"""
            payload = json.dumps({"s": shift, "v": volume, "i": market_id})
            return base64.urlsafe_b64encode(payload.encode()).decode()

        def decode_cursor(cursor: str) -> Optional[dict]:
            """Decode pagination cursor"""
            if not cursor:
                return None
            try:
                payload = base64.urlsafe_b64decode(cursor.encode()).decode()
                return json.loads(payload)
            except:
                return None

        @app.get("/markets")
        def search_markets(
            limit: int = Query(default=50, ge=1, le=200),
            search: str = None,
            vol_min: float = Query(default=None, ge=0),
            vol_max: float = Query(default=None, ge=0),
            cursor: str = Query(default=None, description="Pagination cursor")
        ):
            if search is not None and len(search) > MAX_SEARCH_LEN:
                raise HTTPException(status_code=400, detail=f"Search query too long (max {MAX_SEARCH_LEN} chars)")

            db = get_db()
            try:
                # Build SQL query with cursor-based pagination
                query = "SELECT * FROM markets"
                params = []
                conditions = []
                
                # Apply filters
                if search:
                    conditions.append("question LIKE ?")
                    params.append(f"%{search}%")
                
                if vol_min is not None:
                    conditions.append("volume >= ?")
                    params.append(vol_min)
                if vol_max is not None:
                    conditions.append("volume <= ?")
                    params.append(vol_max)
                
                # Apply cursor condition for keyset pagination
                cursor_data = decode_cursor(cursor)
                if cursor_data:
                    # Keyset condition: (abs(shift), volume, id) < cursor values
                    conditions.append("""(
                        (ABS(shift) < ?) OR 
                        (ABS(shift) = ? AND volume < ?) OR 
                        (ABS(shift) = ? AND volume = ? AND id < ?)
                    )""")
                    params.extend([
                        abs(cursor_data['s']), abs(cursor_data['s']), cursor_data['v'],
                        abs(cursor_data['s']), cursor_data['v'], cursor_data['i']
                    ])
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                
                # Sort by absolute shift (desc), volume (desc), id (desc) for deterministic ordering
                query += " ORDER BY ABS(shift) DESC, volume DESC, id DESC LIMIT ?"
                params.append(limit)
                
                markets = [dict(r) for r in db.execute(query, params).fetchall()]
            finally:
                db.close()
            
            # Enrich only the current page with live price data
            enriched = []
            with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as executor:
                futures = {executor.submit(_enrich_market, m): m for m in markets}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result is not None:
                            enriched.append(result)
                    except Exception as e:
                        log.error(f"Market enrichment failed: {e}")
            
            # Generate next cursor if we have a full page
            next_cursor = None
            if len(markets) == limit:
                last = markets[-1]
                next_cursor = encode_cursor(last['shift'], last['volume'], last['id'])
            
            return {
                "markets": enriched,
                "pagination": {
                    "next_cursor": next_cursor,
                    "has_more": len(markets) == limit,
                    "limit": limit,
                    "returned": len(enriched)
                }
            }
        ```

        **Step 4: Update Frontend (`static/app.js`)**
        Update the JavaScript to handle cursor-based pagination:

        ```javascript
        // Add state for cursor management
        let currentCursor = null;
        let currentSearchQuery = '';

        async function loadMarkets(searchQuery = '', silent = false, cursor = null) {
            if (!silent && !cursor) {
                showLoadingState();
                currentCursor = null;
            }
            
            currentSearchQuery = searchQuery;
            
            const volMin = document.getElementById('volMin')?.value.trim();
            const volMax = document.getElementById('volMax')?.value.trim();
            
            try {
                const params = new URLSearchParams();
                if (searchQuery) params.set('search', searchQuery);
                if (volMin !== '') params.set('vol_min', volMin);
                if (volMax !== '') params.set('vol_max', volMax);
                if (cursor) params.set('cursor', cursor);
                params.set('limit', '50');
                
                const res = await fetch(`/markets?${params.toString()}`);
                if (!res.ok) throw new Error(`Backend Error ${res.status}`);
                
                const data = await res.json();
                const markets = data.markets;
                const pagination = data.pagination;
                
                currentCursor = pagination.next_cursor;
                
                const table = document.getElementById('marketsTable');
                
                // Clear table for new search, append for "load more"
                if (!cursor) {
                    table.innerHTML = '';
                    const counter = document.getElementById('marketCounter');
                    if (counter) counter.textContent = `${markets.length} markets`;
                }
                
                // Render markets (existing rendering logic)
                markets.forEach((m, i) => {
                    // ... existing market row rendering code ...
                });
                
                // Add "Load More" button if there are more results
                if (pagination.has_more && markets.length > 0) {
                    const loadMoreRow = document.createElement('tr');
                    loadMoreRow.id = 'loadMoreRow';
                    loadMoreRow.innerHTML = `
                        <td colspan="4" class="py-6 text-center">
                            <button onclick="loadMarkets('${currentSearchQuery}', false, '${currentCursor}')"
                                class="bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white border border-gray-600 px-6 py-2 rounded-lg text-sm transition-all">
                                Load More Markets
                            </button>
                        </td>
                    `;
                    table.appendChild(loadMoreRow);
                }
                
                // Start auto-refresh for initial load
                if (!cursor) startAutoRefresh(searchQuery);
                
            } catch (e) {
                // ... error handling ...
            }
        }
        
        // Update search handler to reset cursor
        document.getElementById('searchInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const q = e.target.value.trim();
                loadMarkets(q, false, null); // Reset cursor on new search
            }
        });
        ```

        This implementation provides efficient, scalable cursor-based pagination by:
        1. Storing shift values in the database for fast sorting
        2. Using keyset pagination with composite cursors for stable ordering
        3. Only enriching the current page with live price data
        4. Maintaining a clean "Load More" interface in the frontend
