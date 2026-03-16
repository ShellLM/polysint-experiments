# Updated `clob.py` with Retry Logic

Here's the complete updated file with robust exponential backoff retry logic:

```python
import requests
import time
import random
from logger import get_logger

log = get_logger("CLOB")

CLOB_BASE = "https://clob.polymarket.com"

# How far back to look when calculating shift.
# "1d" gives a meaningful window even on a freshly restarted instance.
# Options: "1h", "6h", "1d", "1w", "max"
DEFAULT_INTERVAL = "1d"

# Resolution in minutes — 60 gives ~24 data points over 1d, enough for trend without hammering the API
DEFAULT_FIDELITY = 60

# Polymarket's CLOB endpoint uses a self-signed cert in its chain — disable verification
_SSL_VERIFY = False

# Suppress the urllib3 warning that fires when verify=False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Retry Configuration ───────────────────────────────────────────────────────
MAX_RETRIES = 3           # Maximum retry attempts (so MAX_RETRIES + 1 total requests)
BASE_DELAY = 1.0          # Initial backoff delay in seconds
MAX_DELAY = 30.0          # Maximum backoff delay cap in seconds
BACKOFF_FACTOR = 2.0      # Exponential multiplier for each retry
JITTER = 0.1              # Randomization factor (±10%) to avoid thundering herd


def _calculate_backoff(attempt: int) -> float:
    """
    Calculate exponential backoff delay with jitter.
    
    Formula: min(base_delay * (backoff_factor ^ attempt), max_delay) + random_jitter
    
    The jitter prevents synchronized retry storms when multiple clients
    encounter the same failure simultaneously.
    
    Args:
        attempt: Current attempt number (0-indexed)
    
    Returns:
        Delay in seconds, guaranteed to be at least 0.1s
    """
    # Exponential backoff: base_delay * (backoff_factor ^ attempt)
    delay = BASE_DELAY * (BACKOFF_FACTOR ** attempt)
    
    # Cap at maximum delay
    delay = min(delay, MAX_DELAY)
    
    # Add jitter: ±JITTER% randomization
    jitter_amount = delay * JITTER * random.uniform(-1, 1)
    delay += jitter_amount
    
    # Ensure minimum delay of 100ms
    return max(delay, 0.1)


def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
    """
    Fetches historical price data for a CLOB token from Polymarket.
    
    Implements exponential backoff retry logic for transient failures:
    - HTTP 429 (Rate Limited)
    - HTTP 5xx (Server Errors)
    - Connection timeouts
    - Network connection errors
    
    Non-retryable errors (4xx client errors, malformed responses) fail immediately.
    
    Returns a list of {"t": unix_timestamp, "p": price} dicts, oldest first.
    Returns None if all retries are exhausted or a non-retryable error occurs.
    """
    for attempt in range(MAX_RETRIES + 1):
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
            
            # ── Success Path ─────────────────────────────────────────────────────
            if resp.status_code == 200:
                history = resp.json().get("history", [])
                if not history:
                    return None
                return sorted(history, key=lambda x: x["t"])
            
            # ── Rate Limited (429) ────────────────────────────────────────────────
            # Always retry with exponential backoff - rate limits are transient
            if resp.status_code == 429:
                if attempt < MAX_RETRIES:
                    wait_time = _calculate_backoff(attempt)
                    log.warning(
                        f"Rate limited for token {clob_token_id}. "
                        f"Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{MAX_RETRIES + 1})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    log.warning(
                        f"CLOB history rate limited for token {clob_token_id} "
                        f"after {MAX_RETRIES + 1} attempts"
                    )
                    return None
            
            # ── Server Error (5xx) ────────────────────────────────────────────────
            # Retry with exponential backoff - these are typically transient
            if 500 <= resp.status_code < 600:
                if attempt < MAX_RETRIES:
                    wait_time = _calculate_backoff(attempt)
                    log.warning(
                        f"CLOB history server error {resp.status_code} for token {clob_token_id}. "
                        f"Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{MAX_RETRIES + 1})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    log.warning(
                        f"CLOB history returned {resp.status_code} for token {clob_token_id} "
                        f"after {MAX_RETRIES + 1} attempts"
                    )
                    return None
            
            # ── Client Error (4xx except 429) ──────────────────────────────────────
            # Don't retry - these indicate a problem with our request, not the server
            log.warning(
                f"CLOB history returned {resp.status_code} for token {clob_token_id} "
                f"(non-retryable client error)"
            )
            return None
            
        # ── Timeout Error ─────────────────────────────────────────────────────────
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                wait_time = _calculate_backoff(attempt)
                log.warning(
                    f"CLOB history request timed out for token {clob_token_id}. "
                    f"Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{MAX_RETRIES + 1})"
                )
                time.sleep(wait_time)
                continue
            else:
                log.error(
                    f"CLOB history fetch timed out for token {clob_token_id} "
                    f"after {MAX_RETRIES + 1} attempts"
                )
                return None
                
        # ── Connection Error ──────────────────────────────────────────────────────
        except requests.exceptions.ConnectionError as e:
            if attempt < MAX_RETRIES:
                wait_time = _calculate_backoff(attempt)
                log.warning(
                    f"CLOB history connection error for token {clob_token_id}: {e}. "
                    f"Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{MAX_RETRIES + 1})"
                )
                time.sleep(wait_time)
                continue
            else:
                log.error(
                    f"CLOB history connection failed for token {clob_token_id} "
                    f"after {MAX_RETRIES + 1} attempts"
                )
                return None
                
        # ── Catch-all for Unexpected Errors ───────────────────────────────────────
        # Includes JSONDecodeError, KeyError, etc. - don't retry these
        except Exception as e:
            log.error(f"CLOB history fetch failed for token {clob_token_id}: {e}")
            return None
    
    # Should never reach here, but return None for safety
    return None


def get_shift(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> float | None:
    """
    Returns the price shift (as a float, e.g. 0.12 = 12%) over the given interval.
    Compares the oldest and newest data points in the history window.
    Returns None if history is unavailable or too short.
    """
    history = get_price_history(clob_token_id, interval=interval)
    if not history or len(history) < 2:
        return None

    price_then = float(history[0]["p"])
    price_now = float(history[-1]["p"])
    return price_now - price_then


def get_history_as_price_list(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> list[float] | None:
    """
    Returns a flat list of prices oldest-to-newest, suitable for passing to the LLM analyst.
    """
    history = get_price_history(clob_token_id, interval=interval)
    if not history:
        return None
    return [float(h["p"]) for h in history]
```

## Key Changes

| Feature | Description |
|---------|-------------|
| **Retry Configuration** | Module-level constants for `MAX_RETRIES` (3), `BASE_DELAY` (1s), `MAX_DELAY` (30s), `BACKOFF_FACTOR` (2x), and `JITTER` (±10%) |
| **Exponential Backoff** | `_calculate_backoff()` function computes delay as `base × factor^attempt` with jitter |
| **Retryable Errors** | HTTP 429 (rate limit), HTTP 5xx (server errors), `Timeout`, `ConnectionError` |
| **Non-Retryable Errors** | HTTP 4xx (except 429), JSON decode failures, other exceptions |
| **Logging** | Warnings on each retry with delay time; errors when all retries exhausted |

## Backoff Timing Example

With default settings (`BASE_DELAY=1.0`, `BACKOFF_FACTOR=2.0`, `MAX_DELAY=30.0`):

| Attempt | Base Delay | With ±10% Jitter |
|---------|------------|------------------|
| 0 (first) | 1.0s | 0.9s – 1.1s |
| 1 (retry) | 2.0s | 1.8s – 2.2s |
| 2 (retry) | 4.0s | 3.6s – 4.4s |
| 3 (retry) | 8.0s | 7.2s – 8.8s |

Total worst-case wait: ~16 seconds across all retries.
