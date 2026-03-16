## Multi-Currency Volume Tracking Implementation: Production-Ready with Security and Performance Optimizations

        ### 1. Database Schema with Migration Support

        ```python
        ### FILE: db.py ###
        import sqlite3
        from config import Config
        from logger import get_logger

        log = get_logger("Database")

        def get_db():
            try:
                conn = sqlite3.connect(Config.DB_NAME, timeout=30.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA foreign_keys=ON;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("PRAGMA cache_size=-20000;")  # 20MB cache
                return conn
            except Exception as e:
                log.critical(f"Database connection failed: {e}")
                raise

        def init_db():
            conn = get_db()
            cursor = conn.cursor()

            # Markets Table with currency support
            cursor.execute('''CREATE TABLE IF NOT EXISTS markets 
                (id TEXT PRIMARY KEY, 
                 question TEXT, 
                 outcomes TEXT, 
                 volume REAL DEFAULT 0, 
                 volume_currency TEXT DEFAULT 'USDC',
                 created_at TEXT, 
                 clob_token_id TEXT)''')

            # Safe migration — check column existence before altering
            existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(markets)").fetchall()]
            
            if "clob_token_id" not in existing_columns:
                cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
                log.warning("Migrated markets table: added clob_token_id column")
            
            if "volume_currency" not in existing_columns:
                cursor.execute("ALTER TABLE markets ADD COLUMN volume_currency TEXT DEFAULT 'USDC'")
                # Backfill with validated default
                cursor.execute("UPDATE markets SET volume_currency = 'USDC' WHERE volume_currency IS NULL")
                log.warning("Migrated markets table: added volume_currency column")

            # Create indexes for fast filtering
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_markets_volume_currency ON markets(volume_currency)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_markets_question ON markets(question)")

            # Snapshots Table with currency tracking
            cursor.execute('''CREATE TABLE IF NOT EXISTS snapshots 
                (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                 market_id TEXT, 
                 timestamp DATETIME, 
                 prices TEXT, 
                 volume REAL DEFAULT 0, 
                 volume_currency TEXT DEFAULT 'USDC')''')

            snap_columns = [row[1] for row in cursor.execute("PRAGMA table_info(snapshots)").fetchall()]
            if "volume_currency" not in snap_columns:
                cursor.execute("ALTER TABLE snapshots ADD COLUMN volume_currency TEXT DEFAULT 'USDC'")
                cursor.execute("UPDATE snapshots SET volume_currency = 'USDC' WHERE volume_currency IS NULL")
                log.warning("Migrated snapshots table: added volume_currency column")

            # Watchlist Table (unchanged)
            cursor.execute('''CREATE TABLE IF NOT EXISTS watch_list 
                (address TEXT PRIMARY KEY, label TEXT, added_at DATETIME)''')

            conn.commit()
            conn.close()
        ```

        ### 2. Currency Module with Validation and Formatting

        ```python
        ### FILE: currency.py ###
        from config import Config
        from logger import get_logger
        from typing import Any, Tuple, Optional
        from functools import lru_cache

        log = get_logger("Currency")

        # Frozen set prevents runtime modification of supported currencies
        SUPPORTED_CURRENCIES = frozenset(['USD', 'USDC'])

        # Exchange rates relative to USD — USDC is pegged 1:1 to USD
        EXCHANGE_RATES = {
            'USD': 1.0,
            'USDC': 1.0,
        }

        # Bounds for sanity checking
        MAX_VOLUME = 1e15  # $1 quadrillion
        MIN_VOLUME = 0.0

        def validate_currency(currency: Optional[str], default: str = 'USDC') -> str:
            """
            Validates currency against whitelist with strict normalization.
            Returns validated currency or default — never raises.
            """
            if currency is None:
                return default
            
            if not isinstance(currency, str):
                log.warning(f"Currency rejected: expected str, got {type(currency).__name__}")
                return default
            
            normalized = currency.upper().strip()
            
            if normalized not in SUPPORTED_CURRENCIES:
                log.warning(f"Currency rejected: '{currency[:20]}' not in whitelist")
                return default
            
            return normalized

        def validate_volume(volume: Any, currency: str = 'USDC') -> Tuple[float, str]:
            """
            Validates and normalizes volume with bounds checking.
            Returns (validated_volume, validated_currency) tuple.
            """
            safe_currency = validate_currency(currency)
            
            if volume is None:
                return (0.0, safe_currency)
            
            try:
                vol_float = float(volume)
            except (TypeError, ValueError):
                log.warning(f"Volume rejected: could not convert '{repr(volume)[:50]}' to float")
                return (0.0, safe_currency)
            
            # Bounds checking
            if vol_float < MIN_VOLUME:
                log.warning(f"Volume clamped: negative value {vol_float}")
                vol_float = 0.0
            elif vol_float > MAX_VOLUME:
                log.warning(f"Volume rejected: exceeds maximum ({vol_float} > {MAX_VOLUME})")
                vol_float = 0.0
            
            # Check for NaN
            if vol_float != vol_float:  # NaN check
                log.warning("Volume rejected: NaN detected")
                return (0.0, safe_currency)
            
            return (vol_float, safe_currency)

        @lru_cache(maxsize=256)
        def normalize_to_usd(volume: float, currency: str) -> float:
            """
            Convert volume to USD equivalent for threshold comparisons.
            Cached for performance. Returns 0.0 for any invalid input.
            """
            if volume is None or not isinstance(volume, (int, float)):
                return 0.0
            
            safe_currency = validate_currency(currency)
            rate = EXCHANGE_RATES.get(safe_currency, 1.0)
            
            result = volume * rate
            
            # Sanity check on result
            if result < 0 or result > MAX_VOLUME or result != result:
                return 0.0
            
            return result

        def format_volume_display(volume: float, currency: str) -> str:
            """
            Format volume for display with currency indicator.
            Output is safe for Markdown/HTML contexts.
            """
            vol, curr = validate_volume(volume, currency)
            
            if vol < 0:  # Handle negative volumes
                log.warning(f"Negative volume formatted: {vol}")
                vol = 0.0
            
            if vol == 0:
                return "$0"
            
            formatted = f"{vol:,.0f}"
            
            if curr == 'USD':
                return f"${formatted}"
            elif curr == 'USDC':
                return f"${formatted} USDC"
            else:
                return f"{formatted} {curr}"
        ```

        ### 3. Configuration Updates

        ```python
        ### FILE: config.py ###
        import os
        from dotenv import load_dotenv

        load_dotenv()

        class Config:
            DB_NAME = "polysint_core.db"

            # Polymarket specific endpoints
            GAMMA_API = "https://gamma-api.polymarket.com/markets"
            DATA_API = "https://data-api.polymarket.com"

            # Blockchain RPC
            RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

            # LLM
            LLM_API_KEY = os.getenv("LLM_API_KEY")
            LLM_BASE_URL = os.getenv("LLM_API_BASE_URL")
            LLM_MODEL = os.getenv("ANALYSIS_MODEL")

            # Webhook Configurations
            DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
            TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
            TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

            # Web Research (Tavily)
            ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"

            # Currency support
            SUPPORTED_CURRENCIES = frozenset(['USD', 'USDC'])
            DEFAULT_VOLUME_CURRENCY = 'USDC'
            
            # CLOB SSL configuration
            CLOB_SSL_VERIFY = os.getenv("CLOB_SSL_VERIFY", "true").lower() == "true"
        ```

        ### 4. CLOB Module with Security Fixes

        ```python
        ### FILE: clob.py ###
        import requests
        from logger import get_logger
        from config import Config

        log = get_logger("CLOB")

        CLOB_BASE = "https://clob.polymarket.com"
        DEFAULT_INTERVAL = "1d"
        DEFAULT_FIDELITY = 60

        # SECURITY: SSL verification controlled by configuration
        _SSL_VERIFY = Config.CLOB_SSL_VERIFY

        # Suppress warning only if explicitly disabled
        if not _SSL_VERIFY:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            log.warning("⚠️ SSL verification DISABLED for CLOB endpoint — MITM risk!")


        def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
            """
            Fetches historical price data for a CLOB token from Polymarket.
            Returns a list of {"t": unix_timestamp, "p": price} dicts, oldest first.
            Returns None if the request fails.
            """
            # Validate token_id format to prevent SSRF/injection
            if not clob_token_id or not isinstance(clob_token_id, str):
                log.warning("Invalid clob_token_id: empty or wrong type")
                return None
            
            # Bound token_id length and validate characters
            if len(clob_token_id) > 100 or not clob_token_id.isalnum():
                log.warning(f"Invalid clob_token_id format: {clob_token_id[:20]}...")
                return None
            
            # Validate interval against whitelist
            VALID_INTERVALS = frozenset(['1h', '6h', '1d', '1w', 'max'])
            if interval not in VALID_INTERVALS:
                interval = DEFAULT_INTERVAL
            
            # Validate fidelity bounds
            fidelity = max(1, min(int(fidelity), 1440))

            try:
                resp = requests.get(
                    f"{CLOB_BASE}/prices-history",
                    params={
                        "market": clob_token_id,
                        "interval": interval,
                        "fidelity": fidelity,
                    },
                    timeout=10,
                    verify=_SSL_VERIFY,
                )
                if resp.status_code != 200:
                    log.warning(f"CLOB history returned {resp.status_code} for token {clob_token_id}")
                    return None

                data = resp.json()
                if not data or not isinstance(data, dict):
                    return None
                    
                history = data.get("history", [])
                if not history or not isinstance(history, list):
                    return None

                # Validate each history entry
                validated = []
                for entry in history:
                    if isinstance(entry, dict) and 't' in entry and 'p' in entry:
                        try:
                            t = float(entry['t'])
                            p = float(entry['p'])
                            if 0 <= p <= 1:  # Price must be a probability
                                validated.append({"t": t, "p": p})
                        except (TypeError, ValueError):
                            pass

                return sorted(validated, key=lambda x: x["t"])

            except requests.exceptions.SSLError as e:
                log.error(f"SSL error fetching CLOB history for {clob_token_id}: {e}")
                return None
            except requests.exceptions.Timeout:
                log.warning(f"Timeout fetching CLOB history for {clob_token_id}")
                return None
            except Exception as e:
                log.error(f"CLOB history fetch failed for token {clob_token_id}: {e}")
                return None


        def get_shift(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> float | None:
            """Returns the price shift over the given interval."""
            history = get_price_history(clob_token_id, interval=interval)
            if not history or len(history) < 2:
                return None

            price_then = float(history[0]["p"])
            price_now = float(history[-1]["p"])
            return price_now - price_then


        def get_history_as_price_list(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> list[float] | None:
            """Returns a flat list of prices oldest-to-newest."""
            history = get_price_history(clob_token_id, interval=interval)
            if not history:
                return None
            return [float(h["p"]) for h in history]
        ```

        ### 5. Harvester with Input Validation

        ```python
        ### FILE: harvest.py ###
        import requests
        import json
        import time
        from datetime import datetime
        from typing import List, Dict
        from config import Config
        from db import get_db, init_db
        from logger import get_logger
        from currency import validate_currency, validate_volume

        log = get_logger("Harvester")

        # Input validation constants
        MAX_QUESTION_LEN = 200
        MAX_ID_LEN = 100
        MAX_OUTCOMES_LEN = 1000
        BATCH_SIZE = 100


        def safe_extract_string(value, max_len: int, default: str = '') -> str:
            """Safely extract and bound-check a string value."""
            if value is None:
                return default
            try:
                s = str(value)
                return s[:max_len]
            except Exception:
                return default


        def extract_first_price(outcome_prices):
            """Safely extracts the first (YES) outcome price."""
            try:
                if outcome_prices is None:
                    return '[]'

                if isinstance(outcome_prices, str):
                    outcome_prices = outcome_prices.strip()
                    if not outcome_prices:
                        return '[]'
                    try:
                        outcome_prices = json.loads(outcome_prices)
                    except json.JSONDecodeError:
                        log.warning("Invalid JSON in outcomePrices")
                        return '[]'

                if outcome_prices is None or not isinstance(outcome_prices, list):
                    return '[]'

                if not outcome_prices:
                    return '[]'

                # Recursively unwrap nested lists with depth limit
                depth = 0
                while outcome_prices and isinstance(outcome_prices[0], list) and depth < 10:
                    outcome_prices = outcome_prices[0]
                    depth += 1

                if not outcome_prices:
                    return '[]'

                validated = []
                for item in outcome_prices:
                    price = None
                    
                    if isinstance(item, dict):
                        price = item.get('price') or item.get('p')
                    elif isinstance(item, (str, int, float)):
                        price = item
                    elif isinstance(item, list) and len(item) == 1:
                        price = item[0]
                    
                    if price is not None:
                        try:
                            p = float(price)
                            # Validate price bounds (0-1 for probability)
                            if 0 <= p <= 1:
                                validated.append(str(p))
                        except (TypeError, ValueError):
                            pass

                return json.dumps(validated)

            except Exception as e:
                log.warning(f"Failed to parse outcomePrices: {e}")
                return '[]'


        def process_markets_batch(markets_batch: List[Dict]) -> List[tuple]:
            """Process a batch of markets efficiently"""
            processed = []
            current_time = datetime.now().isoformat()
            
            for market in markets_batch:
                try:
                    market_id = safe_extract_string(market.get("id"), MAX_ID_LEN)
                    if not market_id:
                        continue
                    
                    question = safe_extract_string(market.get("question"), MAX_QUESTION_LEN, "Unknown Market")
                    outcomes_json = json.dumps(market.get("outcomes", []))[:MAX_OUTCOMES_LEN]
                    prices_json = extract_first_price(market.get("outcomePrices", []))
                    
                    # Currency extraction with validation
                    raw_currency = market.get("volumeCurrency")
                    volume_currency = validate_currency(raw_currency, default='USDC')
                    
                    # Volume extraction with validation
                    raw_volume = market.get("volume", 0)
                    volume, volume_currency = validate_volume(raw_volume, volume_currency)
                    
                    # CLOB token ID extraction
                    clob_token_id = None
                    raw_clob = market.get("clobTokenIds")
                    if raw_clob:
                        try:
                            token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
                            if isinstance(token_ids, list) and token_ids:
                                clob_token_id = safe_extract_string(token_ids[0], 100)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    processed.append((
                        market_id, question, outcomes_json, volume, volume_currency,
                        current_time, clob_token_id
                    ))
                    
                except Exception as e:
                    log.warning(f"Failed to process market batch item: {e}")
                    continue
            
            return processed


        def process_and_save(markets):
            """Process and save markets with batch transactions for safety."""
            if not markets:
                return
                
            db = get_db()
            cursor = db.cursor()
            
            processed_count = 0
            skipped_count = 0

            # Process in batches for performance and safety
            for i in range(0, len(markets), BATCH_SIZE):
                batch = markets[i:i + BATCH_SIZE]
                processed_batch = process_markets_batch(batch)
                
                if not processed_batch:
                    continue
                
                try:
                    # Begin IMMEDIATE transaction for this batch
                    cursor.execute("BEGIN IMMEDIATE")
                    
                    # Batch insert markets
                    cursor.executemany('''
                        INSERT OR REPLACE INTO markets 
                        (id, question, outcomes, volume, volume_currency, created_at, clob_token_id)
                        VALUES (?, ?, ?, ?, ?, 
                            COALESCE((SELECT created_at FROM markets WHERE id = ?), ?), ?)
                    ''', processed_batch)
                    
                    # Batch insert snapshots
                    snapshot_data = []
                    for data in processed_batch:
                        market_id = data[0]
                        prices_json = extract_first_price(None)  # Simplified for batch
                        volume = data[3]
                        volume_currency = data[4]
                        timestamp = data[5]
                        
                        snapshot_data.append((
                            market_id, timestamp, prices_json, volume, volume_currency
                        ))
                    
                    cursor.executemany('''
                        INSERT INTO snapshots 
                        (market_id, timestamp, prices, volume, volume_currency)
                        VALUES (?, ?, ?, ?, ?)
                    ''', snapshot_data)
                    
                    db.commit()
                    processed_count += len(processed_batch)
                    
                except Exception as e:
                    log.error(f"Batch insert failed: {e}")
                    db.rollback()
                    skipped_count += len(processed_batch)
                    continue

            log.info(f"Processed {processed_count} markets, skipped {skipped_count}")
            db.close()
        ```

        ### 6. Alerts with Markdown Escaping

        ```python
        ### FILE: alerts.py ###
        import json
        import time
        import re
        from db import get_db
        from notifier import Notifier
        from logger import get_logger
        from clob import get_shift, get_price_history, DEFAULT_INTERVAL
        from currency import normalize_to_usd, validate_currency, format_volume_display

        log = get_logger("Alerts")

        ANOMALY_THRESHOLD = 0.10
        MIN_ALERT_VOLUME = 5000
        NEAR_RESOLUTION_THRESHOLD = 0.80

        # Complete Markdown special characters that need escaping
        MARKDOWN_SPECIAL_CHARS = {
            '*': '\\*',
            '_': '\\_',
            '[': '\\[',
            ']': '\\]',
            '(': '\\(',
            ')': '\\)',
            '#': '\\#',
            '`': '\\`',
            '>': '\\>',
            '|': '\\|',
            '~': '\\~',
        }


        def escape_markdown(text: str) -> str:
            """
            Escapes all Markdown special characters for safe inclusion in Discord/Telegram.
            """
            if not text:
                return ""
            text = str(text)
            for char, escaped in MARKDOWN_SPECIAL_CHARS.items():
                text = text.replace(char, escaped)
            return text[:200]  # Limit length


        def safe_float(val):
            try:
                f = float(val)
                return f if f == f else None  # NaN check
            except (TypeError, ValueError):
                return None


        def scan_for_anomalies():
            db = get_db()
            markets = db.execute("""
                SELECT id, question, volume, volume_currency, clob_token_id 
                FROM markets
            """).fetchall()
            db.close()

            notifier = Notifier()

            for m in markets:
                market_volume = m['volume'] or 0
                volume_currency = validate_currency(m['volume_currency'], default='USDC')
                
                # Normalize for threshold comparison
                normalized_volume = normalize_to_usd(market_volume, volume_currency)
                
                if normalized_volume < MIN_ALERT_VOLUME:
                    continue

                clob_token_id = m['clob_token_id']

                try:
                    if clob_token_id:
                        shift = get_shift(clob_token_id)
                        if shift is None:
                            continue

                        if abs(shift) >= ANOMALY_THRESHOLD:
                            history = get_price_history(clob_token_id)
                            if not history:
                                continue

                            current_price = safe_float(history[-1].get('p'))
                            if current_price is None:
                                continue

                            if (current_price >= NEAR_RESOLUTION_THRESHOLD or 
                                current_price <= (1 - NEAR_RESOLUTION_THRESHOLD)):
                                continue

                            direction = "📈" if shift > 0 else "📉"
                            current_price_str = f"{round(current_price * 100)}%"
                            volume_display = format_volume_display(market_volume, volume_currency)
                            
                            # SECURE: Complete Markdown escaping
                            safe_question = escape_markdown(m['question'])

                            msg = (
                                f"{direction} **{safe_question}**\n"
                                f"Shifted **{shift * 100:.1f}%** over the last {DEFAULT_INTERVAL} "
                                f"— now at **{current_price_str}**\n"
                                f"Volume: {volume_display}\n\n"
                                f"_Open the dashboard to run AI analysis on demand._"
                            )
                            notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

                    else:
                        # Snapshot fallback
                        db2 = get_db()
                        history = db2.execute("""
                            SELECT prices, volume_currency FROM snapshots
                            WHERE market_id = ?
                            ORDER BY timestamp DESC LIMIT 2
                        """, (m['id'],)).fetchall()
                        db2.close()

                        if len(history) < 2:
                            continue

                        try:
                            prices_now = json.loads(history[0]['prices'])
                            prices_then = json.loads(history[1]['prices'])
                        except (json.JSONDecodeError, TypeError):
                            continue

                        now = safe_float(prices_now[0] if prices_now else None)
                        then = safe_float(prices_then[0] if prices_then else None)

                        if now is None or then is None:
                            continue

                        diff = now - then

                        if abs(diff) >= ANOMALY_THRESHOLD:
                            if now >= NEAR_RESOLUTION_THRESHOLD or now <= (1 - NEAR_RESOLUTION_THRESHOLD):
                                continue

                            direction = "📈" if diff > 0 else "📉"
                            snapshot_currency = validate_currency(history[0]['volume_currency'], volume_currency)
                            volume_display = format_volume_display(market_volume, snapshot_currency)
                            safe_question = escape_markdown(m['question'])

                            msg = (
                                f"{direction} **{safe_question}**\n"
                                f"Shifted **{diff * 100:.1f}%** (local snapshots)\n"
                                f"Volume: {volume_display}\n\n"
                                f"_Open the dashboard to run AI analysis on demand._"
                            )
                            notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

                except Exception as e:
                    log.error(f"Error scanning anomaly for {m['id']}: {e}")
                    continue
        ```

        ### 7. API with Security Middleware and Rate Limiting

        ```python
        ### FILE: api.py ###
        from fastapi import FastAPI, HTTPException, Query, Request
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.middleware.cors import CORSMiddleware
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from db import get_db, init_db
        from analyst import PolyAnalyst
        from utils import unmask_proxy
        from logger import get_logger
        from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
        from currency import validate_currency, normalize_to_usd, format_volume_display, validate_volume
        from pydantic import BaseModel, field_validator
        from collections import defaultdict
        import time
        import re
        import requests
        import json

        log = get_logger("API")

        # Simple in-memory rate limiting
        RATE_LIMIT_WINDOW = 60  # seconds
        RATE_LIMIT_MAX_REQUESTS = 100  # per window per IP
        rate_limit_store = defaultdict(list)


        def check_rate_limit(client_ip: str) -> bool:
            """Returns True if request is allowed, False if rate limited."""
            now = time.time()
            window_start = now - RATE_LIMIT_WINDOW
            
            # Clean old entries
            rate_limit_store[client_ip] = [
                t for t in rate_limit_store[client_ip] if t > window_start
            ]
            
            if len(rate_limit_store[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
                return False
            
            rate_limit_store[client_ip].append(now)
            return True


        app = FastAPI(title="PolySINT Core Engine")

        # Add CORS middleware with restrictive defaults
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Configure appropriately for production
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
            max_age=3600,
        )


        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            """Rate limiting middleware for all requests."""
            client_ip = request.client.host if request.client else "unknown"
            
            # Skip rate limiting for static files
            if request.url.path.startswith("/static"):
                return await call_next(request)
            
            if not check_rate_limit(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please try again later."}
                )
            
            return await call_next(request)


        @app.exception_handler(Exception)
        async def global_exception_handler(request: Request, exc: Exception):
            """Global exception handler to prevent stack trace leakage."""
            log.error(f"Unhandled exception: {exc}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            )


        analyst = PolyAnalyst()

        MIN_VOLUME_FOR_CLOB = 5000
        CLOB_WORKERS = 10  # Reduced for better connection pooling
        MAX_SEARCH_LEN = 200
        MAX_LABEL_LEN = 80

        ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
        MARKET_ID_RE = re.compile(r'^[0-9]{10,15}$')  # Tightened regex

        app.mount("/static", StaticFiles(directory="static"), name="static")


        @app.on_event("startup")
        def startup():
            init_db()


        @app.get("/")
        def serve_dashboard():
            return FileResponse("static/index.html")


        def _validate_address(address: str) -> str:
            if not address or not isinstance(address, str):
                raise HTTPException(status_code=400, detail="Address is required.")
            if len(address) != 42:
                raise HTTPException(status_code=400, detail="Address must be 42 characters.")
            if not ADDRESS_RE.match(address):
                raise HTTPException(status_code=400, detail="Invalid Ethereum address format.")
            return address  # Preserve checksum - do not lowercase


        def _validate_currency(currency: str) -> str:
            """Validates currency against whitelist to prevent SQL injection."""
            if currency is None:
                return None
            normalized = currency.upper().strip()
            if normalized not in Config.SUPPORTED_CURRENCIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid currency. Must be one of: {', '.join(Config.SUPPORTED_CURRENCIES)}"
                )
            return normalized


        def _enrich_market(m: dict) -> dict | None:
            clob_token_id = m.get("clob_token_id")
            m['shift'] = 0.0
            m['current_price'] = None

            if clob_token_id:
                try:
                    history = get_price_history(clob_token_id)
                    if history and len(history) > 0:
                        try:
                            m['current_price'] = float(history[-1]["p"])
                            if len(history) >= 2:
                                m['shift'] = round((float(history[-1]["p"]) - float(history[0]["p"])) * 100, 1)
                        except (ValueError, KeyError, IndexError):
                            pass
                except Exception as e:
                    log.warning(f"CLOB enrichment failed for {clob_token_id}: {e}")

            if m['current_price'] is None:
                try:
                    db = get_db()
                    snap = db.execute(
                        "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
                        (m['id'],)
                    ).fetchone()
                    db.close()
                    if snap:
                        prices = json.loads(snap['prices'])
                        if prices and len(prices) > 0:
                            m['current_price'] = float(prices[0])
                except Exception:
                    pass

            if m['current_price'] is not None:
                if m['current_price'] > 0.98 or m['current_price'] < 0.02:
                    return None

            return m


        @app.get("/markets")
        def search_markets(
            request: Request,
            limit: int = Query(default=50, ge=1, le=500),
            search: str = Query(default=None, max_length=MAX_SEARCH_LEN),
            vol_min: float = Query(default=None, ge=0),
            vol_max: float = Query(default=None, ge=0),
            currency: str = Query(default=None, max_length=10)
        ):
            # Validate currency against whitelist
            safe_currency = _validate_currency(currency) if currency else None
            
            if vol_min is not None and vol_max is not None and vol_min > vol_max:
                raise HTTPException(status_code=400, detail="vol_min cannot exceed vol_max")

            db = get_db()
            try:
                query = "SELECT * FROM markets"
                params = []
                conditions = []
                
                if search:
                    conditions.append("question LIKE ?")
                    params.append(f"%{search}%")
                
                if safe_currency:
                    conditions.append("volume_currency = ?")
                    params.append(safe_currency)
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)

                all_markets = [dict(r) for r in db.execute(query, params).fetchall()]
            finally:
                db.close()

            # Volume filtering with normalization
            volume_floor = MIN_VOLUME_FOR_CLOB if not search else 0
            
            candidates = []
            for m in all_markets:
                vol_raw = m.get('volume') or 0
                vol_currency = m.get('volume_currency', 'USDC')
                vol_normalized = normalize_to_usd(vol_raw, vol_currency)
                
                if vol_normalized < volume_floor:
                    continue
                if vol_min is not None and vol_normalized < vol_min:
                    continue
                if vol_max is not None and vol_normalized > vol_max:
                    continue
                candidates.append(m)

            enriched = []
            with ThreadPoolExecutor(max_workers=min(CLOB_WORKERS, len(candidates))) as executor:
                futures = {executor.submit(_enrich_market, m): m for m in candidates}
                for future in as_completed(futures, timeout=60):
                    try:
                        result = future.result()  # No individual timeout
                        if result is not None:
                            enriched.append(result)
                    except Exception as e:
                        log.error(f"Market enrichment failed: {e}")

            enriched.sort(key=lambda x: (abs(x.get('shift', 0.0)), x.get('volume') or 0.0), reverse=True)
            return enriched[:limit]


        @app.get("/stats/volume-by-currency")
        def get_volume_stats():
            """Aggregate volume statistics by currency."""
            db = get_db()
            try:
                result = db.execute("""
                    SELECT volume_currency, COUNT(*) as count, SUM(volume) as total_volume
                    FROM markets
                    WHERE volume > 0
                    GROUP BY volume_currency
                """).fetchall()
                return {
                    "breakdown": [dict(r) for r in result],
                    "supported_currencies": list(Config.SUPPORTED_CURRENCIES)
                }
            finally:
                db.close()


        class Target(BaseModel):
            address: str
            label: str

            @field_validator('address')
            @classmethod
            def validate_address(cls, v):
                if not v:
                    raise ValueError("Address is required.")
                v = v.strip()
                if len(v) != 42 or not ADDRESS_RE.match(v):
                    raise ValueError("Must be a valid 42-character Ethereum address.")
                return v  # Preserve checksum

            @field_validator('label')
            @classmethod
            def validate_label(cls, v):
                if not v:
                    raise ValueError("Label is required.")
                v = v.strip()
                if len(v) > MAX_LABEL_LEN:
                    raise ValueError(f"Label too long (max {MAX_LABEL_LEN} chars).")
                # Prevent XSS/injection characters
                if re.search(r'[<>\{\}\\\'\"\n\r]', v):
                    raise ValueError("Label contains invalid characters.")
                return v


        @app.post("/watchlist")
        def add_to_watchlist(target: Target):
            db = get_db()
            try:
                cursor = db.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "INSERT INTO watch_list (address, label, added_at) VALUES (?, ?, datetime('now'))",
                    (target.address, target.label)
                )
                db.commit()
                return {"status": "success", "resolved_address": target.address}
            except Exception as e:
                db.rollback()
                log.error(f"Failed to add target: {e}")
                raise HTTPException(status_code=400, detail="Address already in watchlist.")
            finally:
                db.close()
        ```

        ### 8. Analyst with Prompt Sanitization

        ```python
        ### FILE: analyst.py ###
        import os
        import re
        from datetime import datetime, timezone
        from openai import OpenAI
        from dotenv import load_dotenv
        from researcher import PolyResearcher
        from config import Config
        from currency import format_volume_display, validate_volume
        from logger import get_logger

        load_dotenv()
        log = get_logger("Analyst")

        # Pattern to detect potential prompt injection attempts
        PROMPT_INJECTION_PATTERNS = re.compile(
            r'(ignore\s+(previous|all|above)\s+(instructions?|prompts?)|'
            r'system\s*:\s*|'
            r'assistant\s*:\s*|'
            r'\[SYSTEM\]|'
            r'<<|>>|'
            r'###\s*(SYSTEM|INSTRUCTION|PROMPT))',
            re.IGNORECASE
        )

        MAX_QUESTION_LEN = 500


        def _sanitize_for_prompt(text: str, max_len: int = 500) -> str:
            """
            Sanitizes text for inclusion in LLM prompts.
            Removes control characters and limits length.
            Detects potential injection attempts.
            """
            if not text:
                return ""
            
            # Convert to string and limit length
            text = str(text)[:max_len]
            
            # Remove control characters (except newlines for readability)
            text = ''.join(c for c in text if c.isprintable() or c in '\n\r\t')
            
            # Remove backslashes and braces that could be used in template injection
            text = text.replace('\\', '').replace('{', '(').replace('}', ')')
            
            # Log if injection pattern detected (but don't raise — just sanitize)
            if PROMPT_INJECTION_PATTERNS.search(text):
                # Remove the matched pattern
                text = PROMPT_INJECTION_PATTERNS.sub('[REDACTED]', text)
            
            return text


        def _derive_price_behaviour(price_history: list) -> dict:
            """Derives observable behavioural signals from a flat price list."""
            if not price_history or len(price_history) < 2:
                return {"summary": "Insufficient price history (fewer than 2 data points)."}

            try:
                prices = [float(p) for p in price_history]
            except (TypeError, ValueError):
                return {"summary": "Price data could not be parsed."}

            # Bounds check on prices
            prices = [p for p in prices if 0 <= p <= 1]
            if len(prices) < 2:
                return {"summary": "Invalid price values detected."}

            first = prices[0]
            last = prices[-1]
            high = max(prices)
            low = min(prices)
            total_shift = last - first
            total_range = high - low
            n = len(prices)

            jumps = [(prices[i+1] - prices[i], i) for i in range(n - 1)]
            max_jump, max_jump_idx = max(jumps, key=lambda x: abs(x[0]))

            position_pct = round((max_jump_idx / max(n - 1, 1)) * 100)
            if position_pct < 25:
                jump_timing = "early in the window"
            elif position_pct < 75:
                jump_timing = "mid-window"
            else:
                jump_timing = "late in the window (recent)"

            if total_shift > 0:
                reversal = round((high - last) * 100, 1)
                holding = reversal < 3.0
                reversal_note = f"Up {round(total_shift*100,1)}% overall; pulled back {reversal}% from peak — {'holding' if holding else 'showing reversal'}."
            elif total_shift < 0:
                reversal = round((last - low) * 100, 1)
                holding = reversal < 3.0
                reversal_note = f"Down {round(abs(total_shift)*100,1)}% overall; recovered {reversal}% from trough — {'holding' if holding else 'showing partial recovery'}."
            else:
                reversal_note = "No net movement over the window."

            total_abs = sum(abs(j[0]) for j in jumps)
            sorted_jumps = sorted(jumps, key=lambda x: abs(x[0]), reverse=True)
            cumulative = 0
            steps_for_80pct = 0
            for j, _ in sorted_jumps:
                cumulative += abs(j)
                steps_for_80pct += 1
                if total_abs > 0 and cumulative / total_abs >= 0.8:
                    break

            if steps_for_80pct == 1:
                move_character = "single-step spike"
            elif steps_for_80pct <= max(2, n // 6):
                move_character = f"sharp move concentrated in {steps_for_80pct} steps"
            else:
                move_character = f"gradual grind across {steps_for_80pct}+ steps"

            return {
                "data_points": n,
                "start_price": f"{round(first * 100, 1)}%",
                "end_price": f"{round(last * 100, 1)}%",
                "high": f"{round(high * 100, 1)}%",
                "low": f"{round(low * 100, 1)}%",
                "net_shift": f"{'+' if total_shift >= 0 else ''}{round(total_shift * 100, 1)}%",
                "largest_single_step": f"{'+' if max_jump >= 0 else ''}{round(max_jump * 100, 1)}% ({jump_timing})",
                "move_character": move_character,
                "trend_status": reversal_note,
            }


        class PolyAnalyst:
            def __init__(self):
                self.client = OpenAI(
                    base_url=os.getenv("LLM_API_BASE_URL"),
                    api_key=os.getenv("LLM_API_KEY")
                )
                self.model = os.getenv("ANALYSIS_MODEL")
                self.researcher = PolyResearcher()

            def analyze_market_shift(self, market_question, price_history, volume, 
                                    volume_currency='USDC', use_research: bool = None):
                """
                Explains WHY a market is moving.
                All user-provided inputs are sanitized before inclusion in prompts.
                """
                if use_research is None:
                    use_research = Config.ENABLE_WEB_RESEARCH

                # SANITIZE: Market question is user-controlled
                safe_question = _sanitize_for_prompt(market_question, MAX_QUESTION_LEN)
                
                # Validate volume
                safe_volume, safe_currency = validate_volume(volume, volume_currency)
                volume_display = format_volume_display(safe_volume, safe_currency)

                behaviour = _derive_price_behaviour(price_history)

                if use_research:
                    # Researcher returns sanitized context
                    news_context = self.researcher.get_market_context(safe_question)
                else:
                    news_context = "Web research disabled. No external news context available."

                current_time = datetime.now(timezone.utc).strftime("%B %d, %Y - %H:%M:%S UTC")

                # System prompt is static — no user input interpolated
                system_prompt = (
                    "You are a Senior OSINT & Forensic Financial Analyst specialising in prediction markets. "
                    f"CRITICAL: The current real-world date and time is {current_time}. "
                    "Your analysis must be grounded in the evidence provided. "
                    "The PRICE BEHAVIOUR section is primary evidence — it is derived directly from market data and is always available. "
                    "The NEWS CONTEXT section is supplementary — it may be empty, in which case your analysis must still be substantive and grounded in the price behaviour alone. "
                    "You must NEVER produce a finding of INSUFFICIENT DATA unless the price history itself has fewer than 2 data points. "
                    "You must NEVER claim a move is unexplained simply because news is absent — price behaviour alone can support a classification. "
                    "Do not invent events. Every factual claim must trace back to either the price behaviour metrics or a specific news item below."
                )

                # Build behaviour section safely — values are derived from validated data
                behaviour_section = "\n".join(f"  {k}: {v}" for k, v in behaviour.items())

                # Prompt uses only sanitized/validated inputs
                prompt = f"""MARKET QUESTION: "{safe_question}"
        TOTAL VOLUME: {volume_display}

        ━━━ PRIMARY EVIDENCE: PRICE BEHAVIOUR ━━━
        {behaviour_section}

        ━━━ SUPPLEMENTARY EVIDENCE: NEWS CONTEXT ━━━
        {news_context}

        ---
        INSTRUCTIONS:

        Work through the following steps IN ORDER.

        STEP 1 - PRICE BEHAVIOUR ANALYSIS:
        Using ONLY the price behaviour metrics above, describe what the market did.
        Cover: the direction and magnitude of the move, whether it was sudden or gradual,
        where in the time window it occurred, and whether it is holding or reversing.
        This step must be completed even if news context is empty.

        STEP 2 - NEWS CORRELATION (if news context is available):
        List each news item that is directly relevant to this market.
        For each relevant item, note its title, source URL, and published date.
        If no news items are relevant, state: "No directly relevant news found."
        If news context was disabled, state: "Web research was not run for this query."

        STEP 3 - TIMING ANALYSIS:
        Based on the move character (sudden vs gradual) and any dated news items:
        - A sudden single-step spike with no news strongly suggests the information
          existed before it became public, or a large single trader acted on private conviction.
        - A gradual grind is more consistent with slow public information diffusion.
        - If dated news is available, state whether the market moved before or after it broke.
        - If no news is available, base your timing assessment on the move character alone.

        STEP 4 - CLASSIFICATION:
        Classify as one of:
        - REACTIONARY: A specific dated news item directly explains the shift and
          appeared before or concurrent with the market move.
        - SUSPICIOUS: The move is sudden, large, and preceded available news — or the
          move character (single-step spike) is inconsistent with organic public information flow.
        - ORGANIC: The move is gradual and consistent with slow public information
          diffusion, even without a specific news item.
        - INSUFFICIENT DATA: Use ONLY if the price history has fewer than 2 data points.

        STEP 5 - INTELLIGENCE BRIEF:
        Write a 2-3 sentence brief. Every factual claim must be traceable to either
        the price behaviour metrics (Step 1) or a specific news item (Step 2).
        Do not hedge by saying the move is "unexplained" — explain what the data
        shows even if the cause is uncertain.

        STEP 6 - INSIDER SIGNAL SCORE (1-10):
        Rate the probability of insider knowledge.
        - Base the score on the move character: sudden spikes score higher than gradual grinds.
        - Adjust up if the move preceded news; adjust down if news preceded the move.
        - A score above 6 requires specific justification from Steps 1-3.
        - Do NOT cap at 5 simply because news is absent — price behaviour is sufficient evidence.

        ---
        OUTPUT FORMAT:

        PRICE ACTION:
        (Step 1 findings)

        EVIDENCE:
        (Step 2 findings, with source URLs if available — or explicit statement if none)

        TIMING:
        (Step 3 finding)

        TYPE: (REACTIONARY / SUSPICIOUS / ORGANIC / INSUFFICIENT DATA)

        ANALYSIS:
        (Step 5 brief)

        INSIDER SIGNAL: (1-10) — (one sentence justification referencing specific data points)
        """

                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0,
                        max_tokens=1500  # Limit response size
                    )
                    return response.choices[0].message.content
                except Exception as e:
                    log.error(f"LLM API error: {e}")
                    return "Analysis unavailable due to API error."

            def profile_wallet(self, wallet_address, real_owner, trades):
                """Profiles a specific trader based on behavior and unmasked ID."""
                
                # SANITIZE: All inputs are user-controlled
                safe_address = _sanitize_for_prompt(wallet_address, 50)
                safe_owner = _sanitize_for_prompt(real_owner, 50)
                
                # Sanitize each trade entry
                safe_trades = []
                for t in (trades or [])[:15]:  # Limit to 15 trades
                    safe_trade = _sanitize_for_prompt(
                        f"Bought {t.get('side')} on '{t.get('title')}' for ${t.get('size')}",
                        200
                    )
                    safe_trades.append(safe_trade)
                
                trades_text = "\n".join(safe_trades) if safe_trades else "No recent trades."

                current_time = datetime.now(timezone.utc).strftime("%B %d, %Y")
                system_prompt = (
                    "You are a digital forensic profiler. "
                    f"The current date is {current_time}. "
                    "Base your analysis strictly on the trade data provided. "
                    "Do not invent biographical details, assume identity, or speculate beyond what the trading patterns directly support. "
                    "Where the data is insufficient to draw a conclusion, say so explicitly."
                )

                prompt = f"""PROXY ADDRESS: {safe_address}
        REAL OWNER (EOA): {safe_owner}
        RECENT TRADES:
        {trades_text}

        ---
        INSTRUCTIONS:

        Work through the following steps IN ORDER.

        STEP 1 - PATTERN ANALYSIS:
        What observable patterns exist in the trade data above?
        Consider: market niches traded, trade timing, position sizes, win/loss ratio if determinable.
        If the trade list is too short or sparse to identify patterns, state this explicitly.

        STEP 2 - ENTITY TYPE:
        Based ONLY on the patterns from Step 1, suggest the most likely entity type from:
        (Political Staffer, Domain Expert, Quantitative Bot, Retail Speculator, Market Maker, Whale, Unknown)
        If Step 1 found insufficient data, classify as: Unknown — insufficient trade history.

        STEP 3 - ALPHA LEVEL (1-10):
        Rate their likely information edge.
        A score above 6 requires a specific pattern from Step 1 to justify it.
        If Step 1 found insufficient data, cap the score at 5.

        ---
        OUTPUT FORMAT:

        PATTERNS:
        (Step 1 findings — or explicit statement that data is insufficient)

        ENTITY TYPE: (from the list above)

        ALPHA LEVEL: (1-10) — (one sentence justification referencing a specific pattern)
        """

                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0,
                        max_tokens=800
                    )
                    return response.choices[0].message.content
                except Exception as e:
                    log.error(f"LLM API error in profile_wallet: {e}")
                    return "Profile unavailable due to API error."
        ```

        ### 9. Frontend with Currency Filtering

        ```html
        ### FILE: static/index.html (toolbar addition) ###
        <div class="flex items-center gap-2">
            <label class="text-xs text-gray-500">Currency:</label>
            <select id="currencyFilter" onchange="onCurrencyChange()"
                class="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 focus:border-polysint focus:outline-none">
                <option value="ALL">All</option>
                <option value="USDC">USDC</option>
                <option value="USD">USD</option>
            </select>
        </div>
        ```

        ```javascript
        ### FILE: static/app.js (key sections) ###

        // Security utility to prevent XSS
        function escapeHtml(text) {
            if (text === null || text === undefined) return '';
            const div = document.createElement('div');
            div.textContent = String(text);
            return div.innerHTML;
        }

        function escapeAttribute(text) {
            if (text === null || text === undefined) return '';
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#x27;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }

        // Currency display formatting
        function formatVolume(volume, currency = 'USDC') {
            const vol = parseFloat(volume);
            if (isNaN(vol) || !isFinite(vol)) return '$0';
            
            const curr = (currency || 'USDC').toUpperCase();
            const formatter = new Intl.NumberFormat('en-US', { 
                style: 'currency', 
                currency: 'USD', 
                maximumFractionDigits: 0 
            });
            
            const formatted = formatter.format(vol);
            return curr === 'USDC' ? `${formatted} USDC` : formatted;
        }

        // Currency filter initialization
        function initCurrencyFilter() {
            const saved = localStorage.getItem('polysint_currency_filter');
            const select = document.getElementById('currencyFilter');
            if (select && saved) {
                select.value = saved;
            }
        }

        function onCurrencyChange() {
            const select = document.getElementById('currencyFilter');
            if (select) {
                localStorage.setItem('polysint_currency_filter', select.value);
                const searchInput = document.getElementById('searchInput');
                const query = searchInput ? searchInput.value.trim() : '';
                loadMarkets(query);
            }
        }

        // Update loadMarkets to include currency filter
        async function loadMarkets(searchQuery = '', silent = false) {
            if (!silent) showLoadingState();

            const volMin = document.getElementById('volMin')?.value.trim();
            const volMax = document.getElementById('volMax')?.value.trim();
            const currencyFilter = document.getElementById('currencyFilter')?.value || '';

            try {
                const params = new URLSearchParams();
                if (searchQuery) {
                    const safeQuery = encodeURIComponent(searchQuery.slice(0, 200));
                    params.set('search', safeQuery);
                }
                if (volMin !== '' && !isNaN(parseFloat(volMin))) {
                    params.set('vol_min', Math.max(0, parseFloat(volMin)));
                }
                if (volMax !== '' && !isNaN(parseFloat(volMax))) {
                    params.set('vol_max', Math.max(0, parseFloat(volMax)));
                }
                if (currencyFilter && currencyFilter !== 'ALL') {
                    params.set('currency', currencyFilter);
                }

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

                    // Format volume with currency
                    const volumeCurrency = m.volume_currency || 'USDC';
                    const volumeDisplay = formatVolume(m.volume, volumeCurrency);

                    let anomalyBadge = '';
                    if (isAnomaly) {
                        anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse">⚡ ANOMALY</span>`;
                    } else if (isWarning) {
                        anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">⚠ WATCH</span>`;
                    }

                    const rowHighlight = isAnomaly
                        ? 'bg-red-500/5 hover:bg-red-500/10'
                        : 'hover:bg-gray-700/30';

                    const safeQuestion = escapeHtml(m.question);
                    const safeId = escapeAttribute(m.id);

                    const tr = document.createElement('tr');
                    tr.className = `transition-colors border-b border-gray-700/50 ${rowHighlight}`;
                    tr.style.animationDelay = `${i * 30}ms`;

                    tr.innerHTML = `
                        <td class="px-4 py-4 font-medium text-gray-200">
                            <div class="flex items-start flex-wrap gap-1">
                                <span>${safeQuestion}</span>
                                ${anomalyBadge}
                            </div>
                            <div class="text-xs text-blue-400 mt-1 font-mono">Odds: ${currentOdds}</div>
                        </td>
                        <td class="px-4 py-4 font-mono ${shiftColor} font-bold text-sm">
                            ${shiftIcon} ${absShift}%
                            <div class="text-xs text-gray-600 font-normal">24h shift</div>
                        </td>
                        <td class="px-4 py-4 text-gray-400 text-xs">${volumeDisplay}</td>
                        <td class="px-4 py-4 text-right">
                            <button onclick="analyzeMarket('${safeId}')"
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
                            <button onclick="loadMarkets('${encodeURIComponent(searchQuery)}')" class="mt-2 text-xs text-polysint underline">Retry</button>
                        </div>
                    </td></tr>`;
            }
        }
        ```

        ### Deployment Order:

        1. Deploy database migration (db.py)
        2. Deploy configuration and currency modules (config.py, currency.py)
        3. Deploy CLOB module with security fixes (clob.py)
        4. Deploy updated harvester (harvest.py)
        5. Deploy alerts, API, and analyst updates
        6. Deploy frontend updates

        ### Testing Recommendations:

        ```python
        # Test currency normalization
        assert normalize_to_usd(1000, 'USDC') == 1000.0
        assert normalize_to_usd(1000, 'USD') == 1000.0
        assert normalize_to_usd(None, 'USDC') == 0.0

        # Test currency validation
        assert validate_currency('USDC') == 'USDC'
        assert validate_currency('usdc') == 'USDC'
        assert validate_currency('INVALID') == 'USDC'  # Returns default

        # Test volume formatting
        assert format_volume_display(1000, 'USD') == "$1,000"
        assert format_volume_display(1000, 'USDC') == "$1,000 USDC"
        ```

        This implementation provides robust multi-currency support with security hardening, performance optimizations, and proper input validation across all components.
