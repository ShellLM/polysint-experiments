### FILE: logger.py ###
```python
import logging
import json
from datetime import datetime, timezone

# Custom JSON Formatter
class JsonFormatter(logging.Formatter):
    def format(self, record):
        # Base log record
        log_object = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_object["exception"] = self.formatException(record.exc_info)

        # Add extra fields passed via extra={...}
        # We filter out standard LogRecord attributes to keep things clean
        standard_attrs = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName',
            'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'message', 'pathname', 'process', 'processName',
            'relativeCreated', 'thread', 'threadName', 'exc_info',
            'exc_text', 'stack_info', 'taskName'
        }
        
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                log_object[key] = value

        return json.dumps(log_object)

def get_logger(name):
    logger = logging.getLogger(name)
    
    # Prevent adding multiple handlers if get_logger is called repeatedly
    if not logger.handlers:
        handler = logging.FileHandler('analyzer.log')
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING) # Preserve existing level
    
    return logger
```

### FILE: alerts.py ###
```python
import json
import time
from db import get_db
from notifier import Notifier
from logger import get_logger
from clob import get_shift, get_price_history, DEFAULT_INTERVAL

log = get_logger("Alerts")

# ... [Constants and helper functions remain unchanged] ...

def scan_for_anomies():
    db = get_db()
    markets = db.execute("SELECT id, question, volume, clob_token_id FROM markets").fetchall()
    db.close()

    notifier = Notifier()

    for m in markets:
        market_volume = m['volume'] or 0
        if market_volume < MIN_ALERT_VOLUME:
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

                    current_price = float(history[-1]['p'])

                    if current_price >= NEAR_RESOLUTION_THRESHOLD or current_price <= (1 - NEAR_RESOLUTION_THRESHOLD):
                        log.warning(
                            f"Suppressed alert: price near resolution",
                            extra={
                                "market_id": m['id'],
                                "question": m['question'],
                                "current_price": current_price,
                                "threshold": NEAR_RESOLUTION_THRESHOLD
                            }
                        )
                        continue

                    direction = "📈" if shift > 0 else "📉"
                    current_price_str = f"{round(current_price * 100)}%"
                    msg = (
                        f"{direction} **{m['question']}**\n"
                        f"Shifted **{shift * 100:.1f}%** over the last {DEFAULT_INTERVAL} "
                        f"— now at **{current_price_str}**\n"
                        f"Volume: ${market_volume:,.0f}\n\n"
                        f"_Open the dashboard to run AI analysis on demand._"
                    )
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

            else:
                # Fallback logic
                db2 = get_db()
                history = db2.execute("""
                    SELECT prices FROM snapshots
                    WHERE market_id = ?
                    ORDER BY timestamp DESC LIMIT 2""", (m['id'],)).fetchall()
                db2.close()

                if len(history) < 2:
                    continue

                try:
                    prices_now = json.loads(history[0]['prices'])
                    prices_then = json.loads(history[1]['prices'])
                except (json.JSONDecodeError, TypeError):
                    log.warning(
                        "Malformed prices JSON in snapshots",
                        extra={"market_id": m['id']}
                    )
                    continue

                if not prices_now or not prices_then:
                    continue

                now = safe_float(prices_now[0])
                then = safe_float(prices_then[0])

                if now is None or then is None:
                    log.warning(
                        "Non-numeric price in snapshots",
                        extra={
                            "market_id": m['id'],
                            "raw_now": prices_now[0],
                            "raw_then": prices_then[0]
                        }
                    )
                    continue

                diff = now - then

                if abs(diff) >= ANOMALY_THRESHOLD:
                    if now >= NEAR_RESOLUTION_THRESHOLD or now <= (1 - NEAR_RESOLUTION_THRESHOLD):
                        log.warning(
                            "Suppressed alert: price near resolution (snapshot fallback)",
                            extra={
                                "market_id": m['id'],
                                "question": m['question'],
                                "current_price": now
                            }
                        )
                        continue

                    direction = "📈" if diff > 0 else "📉"
                    msg = (
                        f"{direction} **{m['question']}**\n"
                        f"Shifted **{diff * 100:.1f}%** (local snapshots)\n"
                        f"Volume: ${market_volume:,.0f}\n\n"
                        f"_Open the dashboard to run AI analysis on demand._"
                    )
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

        except Exception as e:
            log.error(
                f"Error scanning anomaly",
                extra={
                    "market_id": m['id'],
                    "error": str(e)
                }
            )
            continue

# ... [Main block remains unchanged] ...
```

### FILE: analyst.py ###
```python
import os
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
from researcher import PolyResearcher
from config import Config
from logger import get_logger

load_dotenv()
log = get_logger("Analyst")

# ... [_derive_price_behaviour remains unchanged] ...

class PolyAnalyst:
    def __init__(self):
        self.client = OpenAI(
            base_url=os.getenv("LLM_API_BASE_URL"),
            api_key=os.getenv("LLM_API_KEY")
        )
        self.model = os.getenv("ANALYSIS_MODEL")
        self.researcher = PolyResearcher()

    def analyze_market_shift(self, market_question, price_history, volume, use_research: bool = None):
        if use_research is None:
            use_research = Config.ENABLE_WEB_RESEARCH

        log.info(
            "Initiating market shift analysis",
            extra={
                "question": market_question,
                "volume": volume,
                "research_enabled": use_research
            }
        )

        behaviour = _derive_price_behaviour(price_history)

        if use_research:
            news_context = self.researcher.get_market_context(market_question)
        else:
            news_context = "Web research disabled. No external news context available."

        current_time = datetime.now(timezone.utc).strftime("%B %d, %Y - %H:%M:%S UTC")
        
        # ... [Prompt construction and LLM call remain unchanged] ...
        
        system_prompt = (...)
        prompt = f"""..."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
            log.info(
                "Market shift analysis complete",
                extra={"question": market_question}
            )
            return response.choices[0].message.content
        except Exception as e:
            log.error(
                "LLM analysis failed",
                extra={
                    "question": market_question,
                    "error": str(e)
                }
            )
            raise

    def profile_wallet(self, wallet_address, real_owner, trades):
        log.info(
            "Initiating wallet profiling",
            extra={
                "proxy": wallet_address,
                "owner": real_owner,
                "trade_count": len(trades)
            }
        )
        
        # ... [Prompt construction and LLM call remain unchanged] ...
        
        current_time = datetime.now(timezone.utc).strftime("%B %d, %Y")
        system_prompt = (...)
        prompt = f"""..."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
            log.info(
                "Wallet profiling complete",
                extra={"proxy": wallet_address}
            )
            return response.choices[0].message.content
        except Exception as e:
            log.error(
                "Wallet profiling failed",
                extra={
                    "proxy": wallet_address,
                    "error": str(e)
                }
            )
            raise
```

### FILE: api.py ###
```python
# ... [Imports] ...
from logger import get_logger
# ...

log = get_logger("API")

# ... [Setup and validators] ...

def _enrich_market(m: dict) -> dict | None:
    # ... [Logic] ...
    try:
        # ...
    except Exception as e:
        log.error(
            "Market enrichment failed",
            extra={
                "market_id": m.get('id'),
                "error": str(e)
            }
        )
        return None

# ... [Endpoints] ...

@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis(market_id: str, research: bool = Query(default=False, ...)):
    # ...
    try:
        # ...
        analysis = analyst.analyze_market_shift(...)
        return {"analysis": analysis, "research_used": research}
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "AI Analysis endpoint failed",
            extra={
                "market_id": market_id,
                "research": research,
                "error": str(e)
            }
        )
        raise HTTPException(status_code=500, detail="AI analysis failed.")
    finally:
        db.close()

# ... [Other endpoints] ...

@app.get("/wallets/{address}/profile")
def profile_wallet_api(address: str):
    _validate_address(address)
    try:
        # ...
        profile = analyst.profile_wallet(address, real_owner, simplified_trades)
        return {"profile": profile, "real_owner": real_owner}
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Wallet profile endpoint failed",
            extra={
                "address": address,
                "error": str(e)
            }
        )
        raise HTTPException(status_code=500, detail="AI Profiling failed.")

# ...
```

### FILE: clob.py ###
```python
import requests
from logger import get_logger

log = get_logger("CLOB")

# ... [Constants] ...

def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
    try:
        resp = requests.get(...)
        if resp.status_code != 200:
            log.warning(
                f"CLOB history returned non-200",
                extra={
                    "token_id": clob_token_id,
                    "status_code": resp.status_code
                }
            )
            return None
        # ...
    except Exception as e:
        log.error(
            f"CLOB history fetch failed",
            extra={
                "token_id": clob_token_id,
                "error": str(e)
            }
        )
        return None

# ...
```

### FILE: harvest.py ###
```python
# ... [Imports] ...
from logger import get_logger

log = get_logger("Harvester")

# ... [extract_first_price logic with logging added] ...

def extract_first_price(outcome_prices):
    try:
        # ...
        if isinstance(outcome_prices, str):
            # ...
            except json.JSONDecodeError:
                log.warning(
                    "outcomePrices is not valid JSON",
                    extra={"preview": repr(outcome_prices)[:100]}
                )
                return '[]'
        # ...
    except Exception as e:
        preview = repr(outcome_prices)[:100] if outcome_prices else 'None'
        log.warning(
            f"Failed to parse outcomePrices",
            extra={
                "preview": preview,
                "error": str(e)
            }
        )
        return '[]'

def fetch_active_markets(session):
    # ...
    try:
        # ...
    except Exception as e:
        log.warning(
            f"Network glitch during fetch",
            extra={
                "offset": offset,
                "error": str(e)
            }
        )
        # ...

def process_and_save(markets):
    # ...
    for market in markets:
        # ...
        if raw_clob:
            try:
                # ...
            except Exception as e:
                log.warning(
                    f"Failed to parse clobTokenIds",
                    extra={
                        "market_id": market.get('id'),
                        "error": str(e)
                    }
                )
    # ...

# ...
```

### FILE: notifier.py ###
```python
# ... [Imports] ...
from logger import get_logger

log = get_logger("Notifier")

class Notifier:
    # ...

    def send_discord(self, message: str, title: str = "PolySINT Alert"):
        if not self.discord_url:
            return
        # ...
        try:
            # ...
        except Exception as e:
            log.error(
                "Discord broadcast failed",
                extra={"error": str(e)}
            )

    def send_telegram(self, message: str, title: str = "PolySINT Alert"):
        if not self.tg_token or not self.tg_chat_id:
            return
        # ...
        try:
            # ...
        except Exception as e:
            log.error(
                "Telegram broadcast failed",
                extra={"error": str(e)}
            )
    
    # ...
```

### FILE: researcher.py ###
```python
# ... [Imports] ...
from logger import get_logger

log = get_logger("Researcher")

# ...

class PolyResearcher:
    # ...
    def get_market_context(self, market_question):
        # ...
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                # ...
            log.error(
                f"Tavily API error",
                extra={
                    "query": query_text,
                    "status_code": resp.status_code,
                    "response": resp.text[:200]
                }
            )
            return "Search failed (API Error)."
        except Exception as e:
            log.error(
                f"Search failed",
                extra={
                    "query": query_text,
                    "error": str(e)
                }
            )
            return "Search failed (Network Error)."
```

### FILE: db.py ###
```python
# ... [Imports] ...
from logger import get_logger

log = get_logger("Database")

def get_db():
    try:
        # ...
    except Exception as e:
        log.critical(
            "Database connection failed",
            extra={"error": str(e)}
        )
        raise

def init_db():
    # ...
    if "clob_token_id" not in existing_columns:
        cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
        log.warning(
            "Migrated markets table",
            extra={"change": "added clob_token_id column"}
        )
    # ...
```

### FILE: utils.py ###
```python
# ... [Imports] ...
from logger import get_logger
log = get_logger("Blockchain")

# ...

def unmask_proxy(proxy_address):
    try:
        # ...
        owner = w3.to_checksum_address("0x" + response.hex()[-40:])
        log.info(
            "Proxy unmasked",
            extra={
                "proxy": proxy_address,
                "owner": owner
            }
        )
        return owner
    except Exception as e:
        # ...
        log.info(
            "Unmask check failed (likely EOA)",
            extra={
                "proxy": proxy_address,
                "error": str(e)
            }
        )
        return "Direct Wallet (Not a Proxy)"
```

### FILE: watcher.py ###
```python
# ... [Imports] ...
from logger import get_logger

log = get_logger("Watcher")

# ...

def watch_wallets():
    # ...
    for row in tracked:
        # ...
        try:
            # ...
        except Exception as e:
            log.error(
                f"Failed to fetch trades for watched wallet",
                extra={
                    "address": address,
                    "label": label,
                    "error": str(e)
                }
            )
        # ...
```
