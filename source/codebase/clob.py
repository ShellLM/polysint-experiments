import requests
import time
from operator import itemgetter
from logger import get_logger

log = get_logger("CLOB")

CLOB_BASE = "https://clob.polymarket.com"

# How far back to look when calculating shift.
# "1d" gives a meaningful window even on a freshly restarted instance.
# Options: "1h", "6h", "1d", "1w", "max"
DEFAULT_INTERVAL = "1d"

# Resolution in minutes — 60 gives ~24 data points over 1d, enough for trend without hammering the API
DEFAULT_FIDELITY = 60

# Cache TTL in seconds — avoid hammering API for repeated requests
CACHE_TTL = 60

# Polymarket's CLOB endpoint uses a self-signed cert in its chain — disable verification
_SSL_VERIFY = False

# Suppress the urllib3 warning that fires when verify=False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── In-memory cache ──────────────────────────────────────────────────────────
# Structure: {(token_id, interval, fidelity): {"data": [...], "timestamp": float}}
_price_cache: dict = {}


def _is_sorted_by_timestamp(history: list) -> bool:
    """Check if history is already sorted by timestamp (ascending)."""
    if len(history) < 2:
        return True
    # Check first and last elements, plus a spot check in middle
    n = len(history)
    if history[0]["t"] > history[-1]["t"]:
        return False
    if n > 2 and history[0]["t"] > history[n // 2]["t"]:
        return False
    return True


def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
    """
    Fetches historical price data for a CLOB token from Polymarket.
    Returns a list of {"t": unix_timestamp, "p": price} dicts, oldest first.
    Returns None if the request fails.
    
    Results are cached for CACHE_TTL seconds to avoid redundant API calls.
    """
    cache_key = (clob_token_id, interval, fidelity)
    now = time.time()
    
    # Check cache
    if cache_key in _price_cache:
        cached = _price_cache[cache_key]
        if now - cached["timestamp"] < CACHE_TTL:
            return cached["data"]
    
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

        history = resp.json().get("history", [])
        if not history:
            return None

        # Only sort if not already sorted (API usually returns chronological)
        if not _is_sorted_by_timestamp(history):
            history = sorted(history, key=itemgetter("t"))

        # Cache the result
        _price_cache[cache_key] = {"data": history, "timestamp": now}
        return history

    except Exception as e:
        log.error(f"CLOB history fetch failed for token {clob_token_id}: {e}")
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


def get_price_data(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY) -> dict | None:
    """
    Combined function that returns all price data in a single call.
    More efficient than calling get_shift() and get_history_as_price_list() separately.
    
    Returns a dict with keys:
      - "history": list of {"t": timestamp, "p": price} dicts
      - "prices": flat list of float prices (pre-parsed)
      - "shift": price shift over the interval (float or None if insufficient data)
    
    Returns None if the API request fails or returns no data.
    """
    history = get_price_history(clob_token_id, interval=interval, fidelity=fidelity)
    if not history:
        return None
    
    # Pre-parse prices once
    prices = [float(h["p"]) for h in history]
    
    # Calculate shift if we have enough data
    shift = None
    if len(prices) >= 2:
        shift = prices[-1] - prices[0]
    
    return {
        "history": history,
        "prices": prices,
        "shift": shift,
    }


def clear_cache():
    """Clear the price cache. Useful for testing or forced refresh."""
    global _price_cache
    _price_cache = {}
