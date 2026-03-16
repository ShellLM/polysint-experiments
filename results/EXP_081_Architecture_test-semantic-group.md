## Celery Task Queue Migration for PolySINT

        Here's a production-ready migration to Celery with Redis that maintains all original functionality while adding scalability, monitoring, and better error handling.

        ### 1. **Updated Dependencies** (`requirements.txt`)
        ```txt
        # Core dependencies
        fastapi==0.115.0
        uvicorn==0.30.6
        python-dotenv==1.0.1
        requests==2.32.3
        web3==7.2.0
        openai==1.40.0
        pydantic==2.9.2
        tavily-python==0.3.0

        # Task Queue
        celery[redis]>=5.4.0
        redis>=5.0.0
        flower>=2.0.0  # Monitoring dashboard
        ```

        ### 2. **Configuration** (`config.py`)
        Add Redis and Celery configuration:
        ```python
        import os
        from dotenv import load_dotenv

        load_dotenv()

        class Config:
            DB_NAME = "polysint_core.db"
            
            # Polymarket endpoints
            GAMMA_API = "https://gamma-api.polymarket.com/markets"
            DATA_API = "https://data-api.polymarket.com"
            
            # Blockchain RPC
            RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
            
            # LLM
            LLM_API_KEY = os.getenv("LLM_API_KEY")
            LLM_BASE_URL = os.getenv("LLM_API_BASE_URL")
            LLM_MODEL = os.getenv("ANALYSIS_MODEL")
            
            # Webhooks
            DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
            TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
            TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
            
            # Web Research
            ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"
            
            # Redis/Celery Configuration
            REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
            
            # Queue Names
            QUEUE_HARVEST = "harvest"
            QUEUE_MONITOR = "monitor"
            QUEUE_ALERTS = "alerts"
            
            # Monitoring
            FLOWER_PORT = int(os.getenv("FLOWER_PORT", "5555"))
            CELERY_WORKER_CONCURRENCY = int(os.getenv("CELERY_WORKER_CONCURRENCY", "4"))
            
            # Anomaly Thresholds (centralized)
            ANOMALY_THRESHOLD = 0.10  # 10%
            MIN_ALERT_VOLUME = 5000
            NEAR_RESOLUTION_THRESHOLD = 0.80
        ```

        ### 3. **Celery Application** (`celery_app.py`)
        ```python
        from celery import Celery
        from config import Config

        celery_app = Celery(
            "polysint",
            broker=Config.REDIS_URL,
            backend=Config.CELERY_RESULT_BACKEND,
            include=["tasks_harvest", "tasks_monitor"]
        )

        celery_app.conf.update(
            # Serialization
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            
            # Timezone
            timezone="UTC",
            enable_utc=True,
            
            # Reliability
            task_acks_late=True,  # Acknowledge after completion
            worker_prefetch_multiplier=1,  # Fair task distribution
            task_reject_on_worker_lost=True,
            broker_connection_retry_on_startup=True,
            
            # Task Routing
            task_routes={
                "tasks_harvest.*": {"queue": Config.QUEUE_HARVEST},
                "tasks_monitor.*": {"queue": Config.QUEUE_MONITOR},
            },
            
            # Beat Schedule (replaces while-true loops)
            beat_schedule={
                "harvest-markets": {
                    "task": "tasks_harvest.harvest_cycle",
                    "schedule": 900.0,  # 15 minutes
                    "options": {"queue": Config.QUEUE_HARVEST},
                },
                "scan-anomalies": {
                    "task": "tasks_monitor.scan_anomalies",
                    "schedule": 300.0,  # 5 minutes
                    "options": {"queue": Config.QUEUE_MONITOR},
                },
                "watch-wallets": {
                    "task": "tasks_monitor.watch_wallets",
                    "schedule": 300.0,  # 5 minutes
                    "options": {"queue": Config.QUEUE_MONITOR},
                },
            }
        )

        # Task base class with automatic retries
        class BaseTask(celery_app.Task):
            abstract = True
            autoretry_for = (Exception,)
            retry_backoff = True
            retry_backoff_max = 600
            max_retries = 3
            
            def on_failure(self, exc, task_id, args, kwargs, einfo):
                # Log task failures
                from logger import get_logger
                log = get_logger("Celery")
                log.error(f"Task {self.name} failed: {exc}")
                super().on_failure(exc, task_id, args, kwargs, einfo)

        celery_app.Task = BaseTask
        ```

        ### 4. **Harvest Tasks** (`tasks_harvest.py`)
        ```python
        import json
        import time
        import requests
        from datetime import datetime, timezone
        from celery import group
        from celery_app import celery_app
        from config import Config
        from db import get_db, init_db
        from logger import get_logger

        log = get_logger("Tasks.Harvest")

        # Helper: Create configured session
        def _gamma_session():
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            })
            return session

        # Helper: Extract prices (migrated from harvest.py)
        def extract_first_price(outcome_prices):
            """Safely extracts the first (YES) outcome price."""
            try:
                if outcome_prices is None: return '[]'
                if isinstance(outcome_prices, str):
                    if not outcome_prices.strip(): return '[]'
                    try: outcome_prices = json.loads(outcome_prices)
                    except: return '[]'
                
                if not isinstance(outcome_prices, list) or not outcome_prices: return '[]'
                
                # Unwrap nested lists
                while outcome_prices and isinstance(outcome_prices[0], list):
                    outcome_prices = outcome_prices[0]
                    
                validated = []
                for item in outcome_prices:
                    price = None
                    if isinstance(item, dict): price = item.get('price') or item.get('p')
                    elif isinstance(item, (str, int, float)): price = item
                    
                    if price is not None:
                        try:
                            float(price)
                            validated.append(str(price))
                        except: pass
                
                return json.dumps(validated)
            except Exception as e:
                log.warning(f"Failed to parse outcomePrices: {e}")
                return '[]'

        @celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
        def fetch_all_markets(self):
            """Fetch all active markets from Polymarket API."""
            session = _gamma_session()
            all_markets = []
            limit = 100
            offset = 0
            
            log.info("Starting market fetch...")
            while True:
                try:
                    resp = session.get(
                        Config.GAMMA_API,
                        params={"active": "true", "closed": "false", "limit": limit, "offset": offset},
                        timeout=15,
                    )
                    
                    if resp.status_code == 429:
                        log.warning(f"Rate limited at offset {offset}. Sleeping 10s...")
                        time.sleep(10)
                        continue
                    
                    if resp.status_code != 200:
                        log.error(f"API returned {resp.status_code} at offset {offset}")
                        break
                    
                    data = resp.json()
                    if not data: break
                    
                    all_markets.extend(data)
                    offset += limit
                    time.sleep(0.5)  # Polite delay
                    
                except Exception as e:
                    log.error(f"Network error at offset {offset}: {e}")
                    break
            
            log.info(f"Fetched {len(all_markets)} markets.")
            return all_markets

        @celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
        def process_batch(self, markets, batch_num=1, total_batches=1):
            """Process a batch of markets."""
            if not markets: return 0
            
            init_db()
            db = get_db()
            cursor = db.cursor()
            current_time = datetime.now(timezone.utc).isoformat()
            processed = 0
            
            try:
                for market in markets:
                    outcomes_json = json.dumps(market.get("outcomes", []))
                    prices_json = extract_first_price(market.get("outcomePrices", []))
                    
                    # Extract CLOB token ID
                    clob_token_id = None
                    raw_clob = market.get("clobTokenIds")
                    if raw_clob:
                        try:
                            token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
                            if token_ids and len(token_ids) > 0:
                                clob_token_id = token_ids[0]
                        except: pass
                    
                    # Upsert market
                    cursor.execute('''
                        INSERT OR REPLACE INTO markets 
                        (id, question, outcomes, volume, created_at, clob_token_id)
                        VALUES (?, ?, ?, ?, 
                            COALESCE((SELECT created_at FROM markets WHERE id = ?), ?), ?)
                    ''', (
                        market.get("id"),
                        market.get("question"),
                        outcomes_json,
                        float(market.get("volume", 0)),
                        market.get("id"),
                        current_time,
                        clob_token_id,
                    ))
                    
                    # Insert snapshot
                    cursor.execute('''
                        INSERT INTO snapshots (market_id, timestamp, prices, volume)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        market.get("id"),
                        current_time,
                        prices_json,
                        float(market.get("volume", 0)),
                    ))
                    processed += 1
                
                db.commit()
                log.info(f"Batch {batch_num}/{total_batches}: Processed {processed} markets.")
                
            except Exception as e:
                db.rollback()
                log.error(f"Batch {batch_num} processing failed: {e}")
                raise self.retry(exc=e)
            finally:
                db.close()
            
            return processed

        @celery_app.task(name="tasks_harvest.harvest_cycle")
        def harvest_cycle():
            """Main harvest cycle - fetch and process markets in parallel batches."""
            markets = fetch_all_markets.apply().result
            if not markets: return 0
            
            # Process in parallel batches
            BATCH_SIZE = 50
            batches = [markets[i:i+BATCH_SIZE] for i in range(0, len(markets), BATCH_SIZE)]
            
            log.info(f"Dispatching {len(batches)} batches for parallel processing...")
            job = group(process_batch.s(batch, idx+1, len(batches)) for idx, batch in enumerate(batches))
            result = job.apply_async()
            
            # Wait for completion with timeout
            batch_results = result.get(timeout=600)
            total_processed = sum(r for r in batch_results if isinstance(r, int))
            
            log.info(f"Harvest complete: {total_processed} markets processed.")
            return total_processed
        ```

        ### 5. **Monitor Tasks** (`tasks_monitor.py`)
        ```python
        import json
        import time
        import requests
        from celery_app import celery_app
        from db import get_db
        from notifier import Notifier
        from logger import get_logger
        from config import Config
        from clob import get_shift, get_price_history, DEFAULT_INTERVAL

        log = get_logger("Tasks.Monitor")

        # Module-level cache for trade deduplication
        seen_trades = set()

        @celery_app.task(name="tasks_monitor.scan_anomalies")
        def scan_anomalies():
            """Scan markets for anomalous price shifts (migrated from alerts.py)."""
            db = get_db()
            markets = db.execute(
                "SELECT id, question, volume, clob_token_id FROM markets WHERE volume >= ?",
                (Config.MIN_ALERT_VOLUME,)
            ).fetchall()
            db.close()
            
            notifier = Notifier()
            alerts_sent = 0
            
            for m in markets:
                try:
                    clob_token_id = m['clob_token_id']
                    if not clob_token_id: continue
                    
                    shift = get_shift(clob_token_id)
                    if shift is None or abs(shift) < Config.ANOMALY_THRESHOLD:
                        continue
                    
                    history = get_price_history(clob_token_id)
                    if not history: continue
                    
                    current_price = float(history[-1]['p'])
                    
                    # Near-resolution gate
                    if (current_price >= Config.NEAR_RESOLUTION_THRESHOLD or 
                        current_price <= (1 - Config.NEAR_RESOLUTION_THRESHOLD)):
                        continue
                    
                    direction = "📈" if shift > 0 else "📉"
                    current_price_str = f"{round(current_price * 100)}%"
                    
                    msg = (
                        f"{direction} **{m['question']}**\n"
                        f"Shifted **{shift * 100:.1f}%** over the last {DEFAULT_INTERVAL} "
                        f"— now at **{current_price_str}**\n"
                        f"Volume: ${m['volume']:,.0f}\n\n"
                        f"_Open the dashboard to run AI analysis on demand._"
                    )
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")
                    alerts_sent += 1
                    
                except Exception as e:
                    log.error(f"Error scanning market {m['id']}: {e}")
            
            return alerts_sent

        @celery_app.task(name="tasks_monitor.watch_wallets")
        def watch_wallets():
            """Watch tracked wallets for new trades (migrated from watcher.py)."""
            db = get_db()
            tracked = db.execute("SELECT address, label FROM watch_list").fetchall()
            db.close()
            
            notifier = Notifier()
            notifications = 0
            
            for row in tracked:
                address = row['address']
                label = row['label']
                
                try:
                    url = f"{Config.DATA_API}/trades?user={address}&limit=5"
                    resp = requests.get(url, timeout=10)
                    
                    if resp.status_code == 200:
                        trades = resp.json()
                        for trade in trades:
                            trade_id = trade.get('transactionHash')
                            
                            if trade_id and trade_id not in seen_trades:
                                seen_trades.add(trade_id)
                                
                                market_title = trade.get('title', 'Unknown Market')
                                msg = (
                                    f"**Entity:** `{label}`\n"
                                    f"**Proxy Wallet:** `{address}`\n"
                                    f"**Action:** Traded on _{market_title}_"
                                )
                                notifier.broadcast(msg, title="🐳 OSINT Target Activity")
                                notifications += 1
                    
                    time.sleep(1)  # Polite API spacing
                    
                except Exception as e:
                    log.error(f"Failed to watch wallet {address}: {e}")
            
            return notifications
        ```

        ### 6. **Updated Startup** (`start.py`)
        ```python
        import subprocess
        import sys
        import time
        import signal
        from datetime import datetime
        from logger import get_logger
        from notifier import Notifier
        from config import Config

        log = get_logger("System")

        class ProcessManager:
            """Manage subprocesses with graceful shutdown."""
            def __init__(self):
                self.processes = []
                self.shutdown_requested = False
            
            def add_process(self, name, command, **kwargs):
                proc = subprocess.Popen(command, **kwargs)
                self.processes.append((name, proc))
                return proc
            
            def stop_all(self):
                self.shutdown_requested = True
                
                for name, proc in self.processes:
                    if proc.poll() is None:
                        print(f" -> Stopping {name}...")
                        proc.terminate()
                
                # Wait for graceful shutdown
                for name, proc in self.processes:
                    if proc.poll() is None:
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            print(f"    Force killing {name}...")
                            proc.kill()
            
            def check_health(self):
                status = {}
                all_healthy = True
                for name, proc in self.processes:
                    if proc.poll() is None:
                        status[name] = "online"
                    else:
                        status[name] = "offline"
                        all_healthy = False
                return status, all_healthy

        def start_engine():
            print("🚀 Starting PolySINT Engine with Celery Task Queue...")
            
            # Pre-flight: Check Redis connection
            try:
                import redis
                r = redis.Redis.from_url(Config.REDIS_URL, socket_connect_timeout=3)
                r.ping()
                print("  ✅ Redis is reachable")
            except Exception as e:
                print(f"  ❌ Redis not reachable: {e}")
                print("     Please start Redis first: redis-server")
                sys.exit(1)
            
            manager = ProcessManager()
            notifier = Notifier()
            
            try:
                # 1. API Server
                print("\n -> Launching API Server (port 9000)...")
                api_proc = manager.add_process(
                    "API Server",
                    [sys.executable, "-m", "uvicorn", "api:app", "--port", "9000", "--host", "0.0.0.0"]
                )
                time.sleep(2)
                
                # 2. Celery Worker
                print(" -> Launching Celery Worker...")
                worker_cmd = [
                    sys.executable, "-m", "celery",
                    "-A", "celery_app", "worker",
                    "--loglevel=info",
                    "--concurrency", str(Config.CELERY_WORKER_CONCURRENCY),
                    "-Q", f"{Config.QUEUE_HARVEST},{Config.QUEUE_MONITOR}",
                    "--hostname", "polyworker@%h"
                ]
                worker_proc = manager.add_process("Celery Worker", worker_cmd)
                time.sleep(3)
                
                # 3. Celery Beat (Scheduler)
                print(" -> Launching Celery Beat Scheduler...")
                beat_cmd = [
                    sys.executable, "-m", "celery",
                    "-A", "celery_app", "beat",
                    "--loglevel=info",
                    "--schedule", "/tmp/celerybeat-polysint.schedule"
                ]
                beat_proc = manager.add_process("Celery Beat", beat_cmd)
                
                # 4. Flower Monitoring (Optional)
                print(f" -> Launching Flower Dashboard (port {Config.FLOWER_PORT})...")
                flower_cmd = [
                    sys.executable, "-m", "flower",
                    "-A", "celery_app",
                    f"--port={Config.FLOWER_PORT}",
                    "--broker_api=redis"
                ]
                flower_proc = manager.add_process("Flower Monitor", flower_cmd)
                
                print("\n" + "="*60)
                print("✅ All systems operational!")
                print("📊 API Dashboard: http://localhost:9000")
                print(f"🌸 Celery Monitor: http://localhost:{Config.FLOWER_PORT}")
                print("="*60 + "\n")
                
                notifier.broadcast(
                    message="**PolySINT Celery system launched.**\n"
                            "• Harvest worker processing market data\n"
                            "• Beat scheduler managing periodic tasks\n"
                            "• All queues operational",
                    title="🚀 System Boot: Online"
                )
                
                # Setup graceful shutdown
                def signal_handler(signum, frame):
                    print(f"\n⚠️ Received signal {signum}, shutting down...")
                    manager.stop_all()
                    sys.exit(0)
                
                signal.signal(signal.SIGINT, signal_handler)
                signal.signal(signal.SIGTERM, signal_handler)
                
                # Heartbeat monitoring loop
                last_heartbeat = time.time()
                HEARTBEAT_INTERVAL = 21600  # 6 hours
                
                while True:
                    time.sleep(10)
                    
                    if manager.shutdown_requested:
                        break
                    
                    status, all_healthy = manager.check_health()
                    current_time = time.time()
                    
                    if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                        status_msg = "**Periodic Health Check:**\n"
                        for name, state in status.items():
                            emoji = "🟢" if state == "online" else "🔴"
                            status_msg += f"{emoji} **{name}**: {state.capitalize()}\n"
                        
                        title = "💚 System Heartbeat" if all_healthy else "⚠️ System Degraded"
                        notifier.broadcast(message=status_msg, title=title)
                        last_heartbeat = current_time
                        
            except Exception as e:
                print(f"\n❌ Fatal error: {e}")
                manager.stop_all()
                notifier.broadcast(
                    message=f"System failed: {str(e)[:200]}",
                    title="❌ Startup Failed"
                )
                sys.exit(1)

        if __name__ == "__main__":
            start_engine()
        ```

        ### 7. **Migration Steps**
        ```bash
        # 1. Install Redis (if not already installed)
        # Ubuntu/Debian
        sudo apt-get install redis-server
        sudo systemctl start redis-server
        
        # macOS
        brew install redis
        brew services start redis
        
        # Or use Docker
        docker run -d -p 6379:6379 --name polysint-redis redis:7-alpine

        # 2. Install Python dependencies
        pip install celery[redis] redis flower

        # 3. Update .env file
        echo "REDIS_URL=redis://localhost:6379/0" >> .env
        echo "CELERY_RESULT_BACKEND=redis://localhost:6379/1" >> .env
        echo "CELERY_WORKER_CONCURRENCY=4" >> .env

        # 4. Start the system
        python start.py

        # 5. Monitor the system
        # API: http://localhost:9000
        # Flower: http://localhost:5555
        ```

        ### 8. **Optional: Docker Compose**
        ```yaml
        version: '3.8'
        
        services:
          redis:
            image: redis:7-alpine
            ports:
              - "6379:6379"
            volumes:
              - redis_data:/data
            command: redis-server --appendonly yes
        
          api:
            build: .
            command: uvicorn api:app --host 0.0.0.0 --port 9000
            ports:
              - "9000:9000"
            volumes:
              - .:/app
            environment:
              - REDIS_URL=redis://redis:6379/0
            depends_on:
              - redis
        
          worker:
            build: .
            command: celery -A celery_app worker --loglevel=info --concurrency=4 -Q harvest,monitor
            volumes:
              - .:/app
            environment:
              - REDIS_URL=redis://redis:6379/0
            depends_on:
              - redis
        
          beat:
            build: .
            command: celery -A celery_app beat --loglevel=info
            volumes:
              - .:/app
            environment:
              - REDIS_URL=redis://redis:6379/0
            depends_on:
              - redis
        
          flower:
            build: .
            command: flower -A celery_app --port=5555
            ports:
              - "5555:5555"
            volumes:
              - .:/app
            environment:
              - REDIS_URL=redis://redis:6379/0
            depends_on:
              - redis
        
        volumes:
          redis_data:
        ```

        ### **Key Benefits of This Migration**
        1. **Scalability**: Horizontal scaling by adding more workers
        2. **Reliability**: Automatic retries, task acknowledgment, and crash recovery
        3. **Monitoring**: Flower dashboard for real-time task monitoring
        4. **Separation of Concerns**: Dedicated queues for harvest vs. monitoring
        5. **Parallel Processing**: Batch processing for efficient market data ingestion
        6. **Backward Compatibility**: Original scripts can still be run manually
        7. **Production Ready**: Graceful shutdown, health checks, and error handling

        This migration maintains all original functionality while providing a robust, scalable task queue architecture. The system now handles failures gracefully, processes data in parallel, and includes comprehensive monitoring.
