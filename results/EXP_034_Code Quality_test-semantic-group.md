I'll standardize logging across all PolySINT modules by creating a unified logging infrastructure with consistent levels, formats, and proper error handling.

First, update `config.py` to include logging configuration:

```python:config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_NAME = "polysint_core.db"
    
    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

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
```

Now update `logger.py` with a robust, configurable logging setup:

```python:logger.py
import logging
import logging.handlers
import sys
from config import Config

def get_logger(name):
    """
    Creates a standardized logger with rotating file handler and colored console output.
    """
    # Get log level from config
    log_level = getattr(logging, Config.LOG_LEVEL, logging.INFO)
    
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    logger.setLevel(log_level)
    
    # File handler with rotation (10MB max, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        'polysint.log',
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)  # File gets all details
    
    # Console handler with color coding
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    # Standard format
    formatter = logging.Formatter(
        '%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Color formatter for console
    class ColorFormatter(logging.Formatter):
        COLORS = {
            'DEBUG': '\033[94m',    # Blue
            'INFO': '\033[92m',     # Green
            'WARNING': '\033[93m',  # Yellow
            'ERROR': '\033[91m',    # Red
            'CRITICAL': '\033[41m', # White on red
            'RESET': '\033[0m'
        }
        
        def format(self, record):
            if record.levelname in self.COLORS:
                record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"
            return super().format(record)
    
    console_formatter = ColorFormatter(
        '%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
```

Update all modules to use standardized logging. Here are the key changes:

**alerts.py** - Replace print statements and add detailed logging:
```python:alerts.py
import json
import time
from db import get_db
from notifier import Notifier
from logger import get_logger
from clob import get_shift, get_price_history, DEFAULT_INTERVAL

log = get_logger("Alerts")

# ... existing threshold constants ...

def scan_for_anomalies():
    db = get_db()
    markets = db.execute("SELECT id, question, volume, clob_token_id FROM markets").fetchall()
    db.close()

    notifier = Notifier()
    log.info(f"Starting anomaly scan for {len(markets)} markets")
    alerts_generated = 0

    for m in markets:
        # ... existing logic ...
        
        try:
            # ... existing logic ...
            
            if abs(shift) >= ANOMALY_THRESHOLD:
                # ... existing near-resolution check ...
                log.info(f"Anomaly detected: {m['question'][:50]}... (shift: {shift*100:.1f}%)")
                notifier.broadcast(msg, title="🚨 Market Anomaly Detected")
                alerts_generated += 1
                
        except Exception as e:
            log.error(f"Error scanning market {m['id']}: {e}", exc_info=True)
            continue

    log.info(f"Anomaly scan complete: {alerts_generated} alerts generated")

if __name__ == "__main__":
    log.info(f"Anomaly Scanner active - Threshold: {ANOMALY_THRESHOLD*100:.0f}% over {DEFAULT_INTERVAL}")
    # ... rest of main ...
```

**harvest.py** - Standardize logging and remove print statements:
```python:harvest.py
import requests
import json
import time
from datetime import datetime
from config import Config
from db import get_db, init_db
from logger import get_logger

log = get_logger("Harvester")

def extract_first_price(outcome_prices):
    # ... existing logic with improved logging ...
    except Exception as e:
        log.warning(f"Failed to parse outcomePrices: {e}")
        return '[]'

def fetch_active_markets(session):
    log.info("Starting market fetch from Polymarket API")
    all_markets = []
    # ... existing pagination logic ...
    log.info(f"Successfully fetched {len(all_markets)} active markets")
    return all_markets

def process_and_save(markets):
    log.info(f"Processing and saving {len(markets)} markets")
    # ... existing logic with debug logging ...
    log.info(f"Successfully processed {len(markets)} markets")

if __name__ == "__main__":
    log.info("Starting PolySINT Data Harvester")
    # ... rest of main ...
```

**start.py** - Replace print statements with logging:
```python:start.py
import subprocess
import sys
import time
from logger import get_logger
from notifier import Notifier

log = get_logger("System")
HEARTBEAT_INTERVAL = 21600  # 6 hours

def start_engine():
    log.info("🚀 Starting PolySINT Engine...")
    processes = []
    notifier = Notifier()

    try:
        # Launch all services with logging
        log.info("Launching API Server (Port 9000)...")
        api_proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--port", "9000"])
        processes.append(("API Server", api_proc))
        time.sleep(2)
        
        # ... launch other services ...
        
        log.info("✅ All systems nominal! PolySINT is fully operational.")
        log.info("🛑 Press Ctrl+C to safely shut down all systems.")
        
        # ... rest of function with proper logging ...
        
    except KeyboardInterrupt:
        log.warning("Shutting down PolySINT Engine...")
        # ... shutdown logic with logging ...
```

**researcher.py** - Add proper logging configuration check:
```python:researcher.py
import os
import requests
from dotenv import load_dotenv
from logger import get_logger

load_dotenv()
log = get_logger("Researcher")

class PolyResearcher:
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            log.warning("No TAVILY_API_KEY found - web research will be unavailable")

    def get_market_context(self, market_question):
        if not self.api_key:
            log.warning("Tavily API key not configured - skipping web search")
            return "No search API key configured. Context unavailable."
        
        log.info(f"Searching for market context: '{query_text[:50]}...'")
        # ... rest of method with proper logging ...
```

**watcher.py** - Standardize logging with counts:
```python:watcher.py
import requests
import time
from config import Config
from db import get_db
from notifier import Notifier
from logger import get_logger

log = get_logger("Watcher")
seen_trades = set()

def watch_wallets():
    db = get_db()
    tracked = db.execute("SELECT address, label FROM watch_list").fetchall()
    db.close()
    
    log.info(f"Monitoring {len(tracked)} wallets in watchlist")
    notifier = Notifier()
    activity_count = 0
    
    for row in tracked:
        # ... existing logic ...
        if trade_id and trade_id not in seen_trades:
            # ... existing notification ...
            activity_count += 1
            log.info(f"Detected activity: {label} traded on {market_title[:50]}...")
    
    if activity_count > 0:
        log.info(f"Watchlist scan complete: {activity_count} new activities detected")

if __name__ == "__main__":
    log.info("Wallet Watcher starting...")
    # ... rest of main ...
```

**notifier.py** - Add configuration logging:
```python:notifier.py
import requests
from config import Config
from logger import get_logger

log = get_logger("Notifier")

class Notifier:
    def __init__(self):
        self.discord_url = Config.DISCORD_WEBHOOK_URL
        self.tg_token = Config.TELEGRAM_BOT_TOKEN
        self.tg_chat_id = Config.TELEGRAM_CHAT_ID
        
        # Log configuration status
        if self.discord_url:
            log.info("Discord notifier configured")
        if self.tg_token and self.tg_chat_id:
            log.info("Telegram notifier configured")
        if not self.discord_url and not (self.tg_token and self.tg_chat_id):
            log.warning("No external notifiers configured")

    def broadcast(self, message, title="PolySINT Alert"):
        log.info(f"Broadcasting: {title}")
        self.send_discord(message, title)
        self.send_telegram(message, title)
```

**api.py** - Add startup logging and improve error handling:
```python:api.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
# ... other imports ...

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

@app.on_event("startup")
def startup():
    log.info("Initializing PolySINT API...")
    init_db()
    log.info("API initialized successfully")

@app.get("/markets")
def search_markets(limit: int = 50, search: str = None, vol_min: float = None, vol_max: float = None):
    log.info(f"Market search: search='{search}', vol_min={vol_min}, vol_max={vol_max}, limit={limit}")
    # ... rest of endpoint with proper logging ...
```

**analyst.py** - Add analysis logging:
```python:analyst.py
import os
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
from researcher import PolyResearcher
from config import Config
from logger import get_logger

load_dotenv()
log = get_logger("Analyst")

class PolyAnalyst:
    def analyze_market_shift(self, market_question, price_history, volume, use_research=None):
        log.info(f"Analyzing market shift: {market_question[:50]}...")
        # ... existing logic ...
        log.info(f"Analysis complete for: {market_question[:50]}...")
        return response.choices[0].message.content
```

Create a `.env.example` file with logging configuration:
```env
# PolySINT Environment Configuration

# Logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# API Configuration
LLM_API_BASE_URL=your_api_base_url
LLM_API_KEY=your_api_key
ANALYSIS_MODEL=your_model

# Webhooks
DISCORD_WEBHOOK_URL=your_webhook_url
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Web Research
TAVILY_API_KEY=your_tavily_key
ENABLE_WEB_RESEARCH=false

# Blockchain
POLYGON_RPC_URL=https://polygon-rpc.com
```

Key standardization changes:
1. **Consistent format**: `YYYY-MM-DD HH:MM:SS | Module | LEVEL | Message`
2. **Dual output**: File (detailed) + Console (color-coded, configurable level)
3. **Proper levels**: DEBUG for details, INFO for operations, WARNING for recoverable issues, ERROR for failures
4. **Error context**: All exceptions logged with `exc_info=True`
5. **Operational visibility**: Counts and status updates for monitoring
6. **Configuration**: Environment variable for log level control
7. **Rotation**: Prevents log files from growing indefinitely
8. **Module identification**: Each module uses its name for clear tracing
9. **Removed print statements**: All replaced with appropriate logging
10. **Startup/shutdown logging**: Clear system state indicators
