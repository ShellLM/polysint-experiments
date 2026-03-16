2026-03-15 16:21:29,367 - llm_consortium.orchestrator - ERROR - Automatic response error for healer-alpha: Network connection lost.
2026-03-15 16:34:22,156 - llm_consortium.orchestrator - ERROR - Automatic response error for glm-5: Error code: 429 - {'detail': 'Infrastructure is at maximum capacity, try again later'}
Here's the implementation for adding multi-outcome support to alerts.py with a focus on correctness, security, and backward compatibility:

### Core alerts.py Implementation
```python
### FILE: alerts.py ###
import json
import time
import re
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db
from notifier import Notifier
from logger import get_logger
from clob import get_shift, get_price_history, DEFAULT_INTERVAL
from config import Config

log = get_logger("Alerts")

# ─── Thresholds ───────────────────────────────────────────────────────────────
ANOMALY_THRESHOLD = 0.10  # 10%
MIN_ALERT_VOLUME = 5000
NEAR_RESOLUTION_THRESHOLD = 0.80
MAX_OUTCOMES = Config.MAX_OUTCOMES_PER_MARKET

# Security: Token ID validation pattern (Polymarket uses alphanumeric)
_TOKEN_ID_PATTERN = re.compile(r'^[a-zA-Z0-9]+$')
MAX_WORKERS = 8  # Concurrent API fetches


def safe_float(val) -> Optional[float]:
    """Returns float or None — never raises."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _sanitize_outcome_name(name: str, idx: int) -> str:
    """Sanitize outcome name for logging/alert display."""
    if not name:
        return f"Outcome_{idx + 1}"
    
    # Remove control characters and non-printables
    clean = ''.join(c for c in str(name) if c.isprintable())
    clean = clean[:50].strip()
    
    return clean if clean else f"Outcome_{idx + 1}"


def _validate_token_id(token: str) -> bool:
    """Validate token ID format."""
    if not token or not isinstance(token, str):
        return False
    token = token.strip()
    return bool(_TOKEN_ID_PATTERN.match(token)) if token else False


def parse_outcome_data(raw_outcomes: Optional[str], raw_token_ids: Optional[str]) -> List[Tuple[str, str]]:
    """
    Safely parse and validate outcome data with token IDs.
    Returns list of (outcome_name, token_id) tuples.
    Handles both legacy single-token and new multi-token formats.
    """
    outcomes = []
    tokens = []
    
    # Parse outcome names
    if raw_outcomes:
        try:
            parsed = json.loads(raw_outcomes)
            if isinstance(parsed, list):
                for i, o in enumerate(parsed[:MAX_OUTCOMES]):
                    outcomes.append(_sanitize_outcome_name(str(o) if o else "", i))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    
    # Parse token IDs
    if raw_token_ids:
        try:
            raw_str = str(raw_token_ids).strip()
            
            if raw_str.startswith('['):
                # New format: JSON array
                parsed = json.loads(raw_str)
                if isinstance(parsed, list):
                    for t in parsed[:MAX_OUTCOMES]:
                        t_str = str(t).strip() if t else ""
                        if _validate_token_id(t_str):
                            tokens.append(t_str)
            elif raw_str:
                # Legacy format: single token
                if _validate_token_id(raw_str):
                    tokens.append(raw_str)
                    
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    
    if not tokens:
        return []
    
    # Ensure matching counts
    while len(outcomes) < len(tokens):
        outcomes.append(f"Outcome_{len(outcomes) + 1}")
    
    return list(zip(outcomes[:len(tokens)], tokens))


def _fetch_outcome_data(token_id: str) -> Tuple[str, Optional[float], Optional[float]]:
    """Fetch price data for a single token with validation."""
    try:
        shift = get_shift(token_id)
        if shift is None:
            return token_id, None, None
        
        history = get_price_history(token_id)
        if not history:
            return token_id, None, None
        
        # Validate price
        try:
            current_price = float(history[-1]['p'])
            if not (0 <= current_price <= 1):
                log.warning(f"Invalid price {current_price} for token {token_id}")
                return token_id, None, None
        except (KeyError, ValueError, TypeError, IndexError) as e:
            log.warning(f"Malformed price history for token {token_id}: {e}")
            return token_id, None, None
        
        return token_id, shift, current_price
    except Exception as e:
        log.debug(f"Failed to fetch price for {token_id}: {e}")
        return token_id, None, None


def _format_alert_message(market_question: str, market_volume: float, alerts: list) -> str:
    """Format alert message with markdown escaping."""
    # Escape markdown special chars (*, _, `)
    safe_question = str(market_question)[:200].replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
    
    if len(alerts) == 1:
        a = alerts[0]
        safe_outcome = a['outcome'].replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
        return (
            f"{a['direction']} **{safe_question}** — Outcome: **{safe_outcome}**\n"
            f"Shifted **{a['shift'] * 100:.1f}%** over the last {DEFAULT_INTERVAL} "
            f"— now at **{a['price']}**\n"
            f"Volume: ${market_volume:,.0f}\n\n"
            f"_Open the dashboard to run AI analysis on demand._"
        )
    
    # Multiple outcomes
    outcome_lines = []
    for a in alerts:
        safe_outcome = a['outcome'].replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
        outcome_lines.append(
            f"  {a['direction']} **{safe_outcome}**: {a['shift'] * 100:.1f}% → {a['price']}"
        )
    
    return (
        f"⚠️ **{safe_question}**\n"
        f"Multiple outcomes with significant shifts:\n"
        f"{chr(10).join(outcome_lines)}\n"
        f"Volume: ${market_volume:,.0f}\n\n"
        f"_Open the dashboard to run AI analysis on demand._"
    )


def scan_for_anomalies():
    """Scan markets for anomalies across all outcomes."""
    db = None
    try:
        db = get_db()
        markets = db.execute("""
            SELECT id, question, volume, clob_token_ids, outcomes 
            FROM markets
        """).fetchall()
    except Exception as e:
        log.error(f"Database query failed: {e}")
        return
    finally:
        if db:
            db.close()

    notifier = Notifier()

    for m in markets:
        market_volume = m['volume'] or 0
        if market_volume < MIN_ALERT_VOLUME:
            continue

        outcome_pairs = parse_outcome_data(m['outcomes'], m['clob_token_ids'])
        if not outcome_pairs:
            continue

        # Concurrent price fetching
        token_ids = [token_id for _, token_id in outcome_pairs]
        price_data = {}
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_fetch_outcome_data, tid): tid for tid in token_ids}
            
            for future in as_completed(futures, timeout=30):
                try:
                    token_id, shift, current_price = future.result(timeout=5)
                    if shift is not None and current_price is not None:
                        price_data[token_id] = (shift, current_price)
                except Exception as e:
                    log.debug(f"Price fetch failed: {e}")

        # Process anomalies
        market_alerts = []
        
        for outcome_name, token_id in outcome_pairs:
            if token_id not in price_data:
                continue
            
            shift, current_price = price_data[token_id]
            
            if abs(shift) < ANOMALY_THRESHOLD:
                continue
            
            # Near-resolution check per outcome
            if current_price >= NEAR_RESOLUTION_THRESHOLD or current_price <= (1 - NEAR_RESOLUTION_THRESHOLD):
                log.warning(
                    f"Suppressed alert for '{m['question']}' outcome '{outcome_name}': "
                    f"price {current_price:.2f} is near resolution."
                )
                continue
            
            direction = "📈" if shift > 0 else "📉"
            current_price_str = f"{round(current_price * 100)}%"
            
            market_alerts.append({
                'outcome': outcome_name,
                'shift': shift,
                'price': current_price_str,
                'direction': direction
            })
        
        # Send consolidated alert
        if market_alerts:
            try:
                msg = _format_alert_message(m['question'], market_volume, market_alerts)
                notifier.broadcast(msg, title="🚨 Market Anomaly Detected")
            except Exception as e:
                log.error(f"Failed to broadcast alert for {m['id']}: {e}")


if __name__ == "__main__":
    print(
        f"Anomaly Scanner active — "
        f"Threshold: {ANOMALY_THRESHOLD * 100:.0f}% over {DEFAULT_INTERVAL} | "
        f"Min volume: ${MIN_ALERT_VOLUME:,} | "
        f"Near-resolution cutoff: {NEAR_RESOLUTION_THRESHOLD * 100:.0f}%"
    )
    while True:
        scan_for_anomalies()
        time.sleep(300)
```

### Supporting Updates

**1. config.py - Centralized Constants**
```python
# Add to Config class
MAX_OUTCOMES_PER_MARKET = 10  # Prevents DoS via excessive outcome processing
```

**2. db.py - Safe Migration**
```python
import json

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Updated schema: clob_token_ids TEXT (stores JSON array or legacy single string)
    cursor.execute('''CREATE TABLE IF NOT EXISTS markets 
        (id TEXT PRIMARY KEY, question TEXT, outcomes TEXT, volume REAL, 
         created_at TEXT, clob_token_ids TEXT)''')

    # Migration Logic
    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(markets)").fetchall()]
    
    if "clob_token_ids" not in existing_columns:
        if "clob_token_id" in existing_columns:
            # Safe rename and migrate to JSON array
            cursor.execute("ALTER TABLE markets RENAME COLUMN clob_token_id TO clob_token_ids")
            
            rows = cursor.execute("SELECT id, clob_token_ids FROM markets WHERE clob_token_ids IS NOT NULL").fetchall()
            for row in rows:
                token = row['clob_token_ids']
                if token:
                    try:
                        cursor.execute(
                            "UPDATE markets SET clob_token_ids = ? WHERE id = ?",
                            (json.dumps([token]), row['id'])
                        )
                    except Exception as e:
                        log.error(f"Migration failed for market {row['id']}: {e}")
            
            log.warning("Migrated markets table: clob_token_id → clob_token_ids (JSON array)")
        else:
            cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_ids TEXT")
            log.warning("Added clob_token_ids column")

    # Add index for performance
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_markets_volume 
        ON markets(volume) WHERE volume IS NOT NULL
    ''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS snapshots 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id TEXT, timestamp DATETIME, prices TEXT, volume REAL)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS watch_list 
        (address TEXT PRIMARY KEY, label TEXT, added_at DATETIME)''')

    conn.commit()  # Critical: Ensure migration is saved
    conn.close()
```

**3. harvest.py - Store All Token IDs**
```python
# In process_and_save(), extract all token IDs:
clob_token_ids_json = None
raw_clob = market.get("clobTokenIds")

if raw_clob:
    try:
        token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
        if isinstance(token_ids, list):
            # Validate alphanumeric tokens and enforce limit
            validated = [str(t).strip() for t in token_ids 
                        if t and str(t).strip() and str(t).strip().isalnum()]
            if validated:
                clob_token_ids_json = json.dumps(validated[:Config.MAX_OUTCOMES_PER_MARKET])
    except Exception as e:
        log.warning(f"Failed to parse clobTokenIds for {market.get('id')}: {e}")

# Use clob_token_ids_json in INSERT statement
```

**4. api.py - Handle Multiple Outcomes**
```python
def _parse_token_ids(raw_tokens) -> list[str]:
    """Safely parse token IDs matching alerts.py logic."""
    if not raw_tokens:
        return []
    
    try:
        raw_str = str(raw_tokens).strip()
        if raw_str.startswith('['):
            parsed = json.loads(raw_str)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed[:Config.MAX_OUTCOMES_PER_MARKET] 
                       if t and str(t).strip().isalnum()]
        elif raw_str and raw_str.isalnum():
            return [raw_str]
    except (json.JSONDecodeError, TypeError):
        pass
    
    return []

def _enrich_market(m: dict) -> dict | None:
    """Enrich market with multi-outcome data."""
    clob_token_ids_raw = m.get("clob_token_ids")
    m['shift'] = 0.0
    m['current_price'] = None
    m['outcome_shifts'] = {}
    
    token_ids = _parse_token_ids(clob_token_ids_raw)

    if token_ids:
        # Use first token for primary display (backward compatibility)
        history = get_price_history(token_ids[0])
        if history:
            price_val = history[-1].get("p")
            if price_val is not None:
                m['current_price'] = float(price_val)
            
            if len(history) >= 2:
                first_val = history[0].get("p")
                last_val = history[-1].get("p")
                if first_val is not None and last_val is not None:
                    m['shift'] = round((float(last_val) - float(first_val)) * 100, 1)
        
        # Calculate shifts for all outcomes
        for idx, token in enumerate(token_ids):
            try:
                hist = get_price_history(token)
                if hist and len(hist) >= 2:
                    first_val = hist[0].get("p")
                    last_val = hist[-1].get("p")
                    if first_val is not None and last_val is not None:
                        shift = round((float(last_val) - float(first_val)) * 100, 1)
                        m['outcome_shifts'][str(idx)] = shift
            except Exception:
                pass

    # Drop settled markets
    if m['current_price'] is not None:
        if m['current_price'] > 0.98 or m['current_price'] < 0.02:
            return None

    return m
```

### Key Implementation Notes

1. **Backward Compatibility**: Handles both legacy single-token and new multi-outcome markets
2. **Security**: Input validation, markdown escaping, and DoS prevention via MAX_OUTCOMES
3. **Performance**: Concurrent price fetching with controlled parallelism
4. **Resource Safety**: Proper database connection handling with try/finally
5. **Error Handling**: Comprehensive validation and graceful degradation
6. **Maintainability**: Clear separation of concerns with well-documented functions

### Deployment Order
1. Update `config.py` with MAX_OUTCOMES_PER_MARKET
2. Run database migration via `init_db()`
3. Deploy updated `harvest.py` to start writing new format
4. Deploy updated `alerts.py` and `api.py` to read new format
