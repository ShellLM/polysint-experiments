```python
"""
watcher.py — Async Event-Driven Wallet Watcher

Architecture:
    WalletMonitor → EventBus → NotificationHandler → Notifier
                           → LogHandler → Logger
                           → StatsReporter → Heartbeat

Features:
    - Event-driven with typed payloads
    - File-backed deduplication with TTL
    - Circuit breaker per wallet
    - Warm-up phase on startup
    - Graceful shutdown with signal handling
    - Debounced saves for performance
"""

import asyncio
import aiohttp
import json
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Set
from collections import defaultdict
from pathlib import Path

from config import Config
from db import get_db
from notifier import Notifier
from logger import get_logger

log = get_logger("Watcher")

# ─── Configuration Constants ─────────────────────────────────────────────────

POLL_INTERVAL = 300          # 5 minutes between cycles
TRADE_FETCH_LIMIT = 5        # Trades per wallet per poll
API_TIMEOUT = 10             # Seconds before timeout
MAX_CONCURRENT_REQUESTS = 10 # Limit concurrent API calls
DEDUP_PATH = "watcher_seen.json"
MAX_SEEN_AGE_HOURS = 48      # Expire old trade IDs
CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_COOLDOWN_SECONDS = 300  # 5 minutes
DEBOUNCE_SAVE_SECONDS = 0.5    # Batch dedup saves


def _utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# ─── Event Model ──────────────────────────────────────────────────────────────

class EventType(str, Enum):
    NEW_TRADE = "new_trade"
    WALLET_ERROR = "wallet_error"
    CIRCUIT_OPENED = "circuit_opened"
    CIRCUIT_CLOSED = "circuit_closed"
    HEARTBEAT = "heartbeat"


@dataclass(frozen=True)
class TradeEvent:
    """Structured trade data."""
    address: str
    label: str
    transaction_hash: str
    market_title: str
    side: str
    size: float
    timestamp: str


@dataclass(frozen=True)
class WalletError:
    """Error payload for wallet polling failures."""
    address: str
    label: str
    error: str
    retry_count: int


@dataclass(frozen=True)
class CircuitEvent:
    """Circuit breaker state change event."""
    address: str
    label: str
    failure_count: int
    cooldown_seconds: int


@dataclass(frozen=True)
class Heartbeat:
    """Heartbeat event payload."""
    wallets_polled: int
    new_trades: int
    total_known: int
    cycle_duration_ms: int
    errors_this_cycle: int
    circuits_open: int
    uptime: str


@dataclass(frozen=True)
class Event:
    """Base event container."""
    type: EventType
    payload: Any
    timestamp: str = field(default_factory=lambda: _utcnow().isoformat())


# ─── Circuit Breaker ──────────────────────────────────────────────────────────

class CircuitBreaker:
    """Per-wallet failure tracking with cooldown period."""

    def __init__(self, threshold: int = CIRCUIT_FAILURE_THRESHOLD, 
                 cooldown: int = CIRCUIT_COOLDOWN_SECONDS):
        self._threshold = threshold
        self._cooldown = cooldown
        self._failures: Dict[str, int] = defaultdict(int)
        self._opened_at: Dict[str, datetime] = {}

    def is_open(self, key: str) -> bool:
        if key not in self._opened_at:
            return False
        
        elapsed = (_utcnow() - self._opened_at[key]).total_seconds()
        if elapsed >= self._cooldown:
            del self._opened_at[key]
            self._failures[key] = 0
            return False
        return True

    @property
    def open_count(self) -> int:
        return len(self._opened_at)

    def record_failure(self, key: str) -> bool:
        """Returns True if circuit just opened."""
        self._failures[key] += 1
        if self._failures[key] >= self._threshold and key not in self._opened_at:
            self._opened_at[key] = _utcnow()
            return True
        return False

    def record_success(self, key: str) -> bool:
        """Returns True if circuit was open and just closed."""
        self._failures[key] = 0
        was_open = key in self._opened_at
        self._opened_at.pop(key, None)
        return was_open


# ─── File-backed Deduplication ────────────────────────────────────────────────

class DedupStore:
    """File-backed set of seen transaction hashes with debounced saves."""

    def __init__(self, path: str = DEDUP_PATH):
        self._path = Path(path)
        self._seen: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        self._dirty = False
        self._save_task: Optional[asyncio.Task] = None
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        
        try:
            with open(self._path) as f:
                raw = json.load(f)
            
            cutoff = _utcnow() - timedelta(hours=MAX_SEEN_AGE_HOURS)
            loaded = 0
            
            for tx_hash, ts_str in raw.items():
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts > cutoff:
                        self._seen[tx_hash] = ts
                        loaded += 1
                except (ValueError, TypeError):
                    continue
            
            log.info(f"DedupStore loaded {loaded} recent trade IDs")
        except (json.JSONDecodeError, OSError):
            log.warning("DedupStore file corrupted — starting fresh.")
            self._seen = {}

    async def is_new(self, tx_hash: str) -> bool:
        async with self._lock:
            if tx_hash in self._seen:
                return False
            
            self._seen[tx_hash] = _utcnow()
            self._dirty = True
            self._schedule_save()
            return True

    def _schedule_save(self) -> None:
        """Debounced save — cancels previous pending save and reschedules."""
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = asyncio.ensure_future(self._debounced_save())

    async def _debounced_save(self) -> None:
        try:
            await asyncio.sleep(DEBOUNCE_SAVE_SECONDS)
            self._flush()
        except asyncio.CancelledError:
            pass

    def _flush(self) -> None:
        """Immediate save to disk."""
        if not self._dirty:
            return
        
        try:
            # Prune expired entries before saving
            cutoff = _utcnow() - timedelta(hours=MAX_SEEN_AGE_HOURS)
            pruned = {tx: ts.isoformat() for tx, ts in self._seen.items() if ts > cutoff}
            
            # Atomic write via temp file
            temp_path = self._path.with_suffix('.tmp')
            with open(temp_path, "w") as f:
                json.dump(pruned, f)
            temp_path.replace(self._path)
            
            self._dirty = False
        except OSError as e:
            log.error(f"DedupStore failed to persist: {e}")

    async def flush(self) -> None:
        """Force save — called during shutdown."""
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
        self._flush()

    @property
    def size(self) -> int:
        return len(self._seen)


# ─── Event Bus ────────────────────────────────────────────────────────────────

Handler = Any  # sync or async callable


class EventBus:
    """Simple pub-sub with error isolation per handler."""

    def __init__(self):
        self._handlers: Dict[EventType, List[Handler]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        for handler in self._handlers.get(event.type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception:
                log.exception(f"Handler failed on {event.type.value}")


# ─── Wallet Monitor ───────────────────────────────────────────────────────────

class WalletMonitor:
    """Polls wallets, applies circuit breaker, dedup, emits events."""

    def __init__(self, bus: EventBus, dedup: DedupStore):
        self._bus = bus
        self._dedup = dedup
        self._session: Optional[aiohttp.ClientSession] = None
        self._breaker = CircuitBreaker()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self._start_time = _utcnow()
        self._warmed_up = False

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={"User-Agent": "PolySINT-Watcher/2.0", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        )

    async def stop(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _fetch_watchlist_sync(self) -> List[Dict[str, str]]:
        db = get_db()
        try:
            rows = db.execute("SELECT address, label FROM watch_list").fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    async def warm_up(self) -> None:
        """Warm-up phase: record existing trades without notifying."""
        if self._warmed_up:
            return
        
        loop = asyncio.get_running_loop()
        watchlist = await loop.run_in_executor(None, self._fetch_watchlist_sync)
        
        if not watchlist:
            self._warmed_up = True
            return
        
        log.info(f"Warming up with {len(watchlist)} wallets...")
        
        # Fetch current trades without emitting events
        tasks = []
        for w in watchlist:
            task = asyncio.create_task(self._warm_up_wallet(w["address"], w["label"]))
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        self._warmed_up = True
        log.info(f"Warm-up complete: {self._dedup.size} baseline trades recorded")

    async def _warm_up_wallet(self, address: str, label: str) -> None:
        """Fetch trades silently during warm-up."""
        if not self._session or self._breaker.is_open(address):
            return
        
        async with self._semaphore:
            url = f"{Config.DATA_API}/trades"
            params = {"user": address, "limit": TRADE_FETCH_LIMIT}
            
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status == 200:
                        trades = await resp.json()
                        for trade in trades:
                            tx_hash = trade.get("transactionHash")
                            if tx_hash:
                                await self._dedup.is_new(tx_hash)
            except Exception as e:
                log.warning(f"Warm-up fetch failed for {label}: {e}")

    async def poll_cycle(self) -> None:
        if not self._warmed_up:
            await self.warm_up()
            return
        
        loop = asyncio.get_running_loop()
        watchlist = await loop.run_in_executor(None, self._fetch_watchlist_sync)
        
        if not watchlist:
            return
        
        cycle_start = time.monotonic()
        new_trades = 0
        errors = 0
        
        async def check(entry: Dict) -> None:
            nonlocal new_trades, errors
            result = await self._check_wallet(entry["address"], entry["label"])
            new_trades += result["new_trades"]
            if result["had_error"]:
                errors += 1
        
        await asyncio.gather(*[check(w) for w in watchlist])
        
        cycle_ms = round((time.monotonic() - cycle_start) * 1000)
        uptime = str(_utcnow() - self._start_time).split(".")[0]
        
        await self._bus.publish(Event(
            type=EventType.HEARTBEAT,
            payload=Heartbeat(
                wallets_polled=len(watchlist),
                new_trades=new_trades,
                total_known=self._dedup.size,
                cycle_duration_ms=cycle_ms,
                errors_this_cycle=errors,
                circuits_open=self._breaker.open_count,
                uptime=uptime,
            ),
        ))

    async def _check_wallet(self, address: str, label: str) -> Dict:
        if not self._session:
            return {"new_trades": 0, "had_error": True}
        
        if self._breaker.is_open(address):
            return {"new_trades": 0, "had_error": False}
        
        async with self._semaphore:
            url = f"{Config.DATA_API}/trades"
            params = {"user": address, "limit": TRADE_FETCH_LIMIT}
            
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status == 200:
                        trades = await resp.json()
                        was_open = self._breaker.record_success(address)
                        if was_open:
                            await self._bus.publish(Event(
                                type=EventType.CIRCUIT_CLOSED,
                                payload=CircuitEvent(address, label, 0, 0),
                            ))
                        return await self._process_trades(trades, address, label)
                    
                    if resp.status == 429:
                        error_msg = "Rate limited (429)"
                    else:
                        error_msg = f"HTTP {resp.status}"
                    
                    return await self._handle_error(address, label, error_msg)
            
            except asyncio.TimeoutError:
                return await self._handle_error(address, label, "Request timed out")
            except aiohttp.ClientError as e:
                return await self._handle_error(address, label, str(e))
            except Exception as e:
                return await self._handle_error(address, label, f"Unexpected: {e}")

    async def _process_trades(self, trades: List[Dict], address: str, label: str) -> Dict:
        new_trades = 0
        
        for trade in trades:
            tx_hash = trade.get("transactionHash")
            if not tx_hash or not await self._dedup.is_new(tx_hash):
                continue
            
            new_trades += 1
            
            # Parse timestamp safely
            ts = trade.get('timestamp', '')
            try:
                if ts and 'T' in ts:
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00')).isoformat()
                else:
                    ts = _utcnow().isoformat()
            except ValueError:
                ts = _utcnow().isoformat()
            
            await self._bus.publish(Event(
                type=EventType.NEW_TRADE,
                payload=TradeEvent(
                    address=address,
                    label=label,
                    transaction_hash=tx_hash,
                    market_title=trade.get("title", "Unknown Market"),
                    side=trade.get("side", "?"),
                    size=float(trade.get("size", 0)),
                    timestamp=ts,
                ),
            ))
        
        return {"new_trades": new_trades, "had_error": False}

    async def _handle_error(self, address: str, label: str, error: str) -> Dict:
        retry_count = self._breaker._failures.get(address, 0)
        just_opened = self._breaker.record_failure(address)
        
        if just_opened:
            await self._bus.publish(Event(
                type=EventType.CIRCUIT_OPENED,
                payload=CircuitEvent(address, label, CIRCUIT_FAILURE_THRESHOLD, CIRCUIT_COOLDOWN_SECONDS),
            ))
        
        await self._bus.publish(Event(
            type=EventType.WALLET_ERROR,
            payload=WalletError(address, label, error, retry_count),
        ))
        
        return {"new_trades": 0, "had_error": True}


# ─── Handlers ─────────────────────────────────────────────────────────────────

class NotificationHandler:
    """Forwards NEW_TRADE events to Discord / Telegram."""

    def __init__(self):
        self._notifier = Notifier()
        self._trade_counts: Dict[str, int] = defaultdict(int)

    async def __call__(self, event: Event) -> None:
        if event.type != EventType.NEW_TRADE:
            return
        
        t: TradeEvent = event.payload
        self._trade_counts[t.address] += 1
        
        short_addr = f"{t.address[:10]}...{t.address[-6:]}"
        size_str = f"${t.size:,.0f}" if t.size >= 100 else f"${t.size:.2f}"
        
        msg = (
            f"**Entity:** `{t.label}`\n"
            f"**Proxy:** `{short_addr}`\n"
            f"**Action:** {t.side} on _{t.market_title}_\n"
            f"**Size:** {size_str}\n"
            f"**Trade #{self._trade_counts[t.address]}** for this wallet"
        )
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._notifier.broadcast, msg, "🐳 OSINT Target Activity")


class LogHandler:
    """Structured logging for all event types."""

    async def __call__(self, event: Event) -> None:
        if event.type == EventType.NEW_TRADE:
            t: TradeEvent = event.payload
            log.info(f"Trade: {t.label} ({t.address[:10]}…) → {t.market_title} [{t.side} ${t.size:.2f}]")
        
        elif event.type == EventType.WALLET_ERROR:
            e: WalletError = event.payload
            log.warning(f"Wallet error: {e.label} ({e.address[:10]}…): {e.error} (retry #{e.retry_count})")
        
        elif event.type == EventType.CIRCUIT_OPENED:
            c: CircuitEvent = event.payload
            log.warning(f"Circuit OPENED: {c.label} ({c.address[:10]}…) — {c.failure_count} failures, cooling down {c.cooldown_seconds}s")
        
        elif event.type == EventType.CIRCUIT_CLOSED:
            c: CircuitEvent = event.payload
            log.info(f"Circuit CLOSED: {c.label} ({c.address[:10]}…) — recovered")
        
        elif event.type == EventType.HEARTBEAT:
            h: Heartbeat = event.payload
            log.info(f"Heartbeat: {h.wallets_polled} wallets, {h.new_trades} new, {h.total_known} known, {h.cycle_duration_ms}ms")


class StatsReporter:
    """Sends heartbeat summaries — only on cycles with activity or errors."""

    def __init__(self):
        self._notifier = Notifier()

    async def __call__(self, event: Event) -> None:
        if event.type != EventType.HEARTBEAT:
            return
        
        h: Heartbeat = event.payload
        
        # Skip silent cycles
        if h.new_trades == 0 and h.errors_this_cycle == 0 and h.circuits_open == 0:
            return
        
        lines = [
            f"**Watcher Stats:**",
            f"• Wallets: {h.wallets_polled}",
            f"• New Trades: {h.new_trades}",
            f"• Known Trades: {h.total_known}",
            f"• Cycle: {h.cycle_duration_ms}ms",
            f"• Uptime: {h.uptime}",
        ]
        
        if h.errors_this_cycle > 0:
            lines.append(f"• ⚠️ Errors: {h.errors_this_cycle}")
        if h.circuits_open > 0:
            lines.append(f"• 🔴 Circuits Open: {h.circuits_open}")
        
        msg = "\n".join(lines)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._notifier.broadcast, msg, "📊 Watcher Heartbeat")


class CircuitAlertHandler:
    """Sends alerts when circuit breakers trip or recover."""

    def __init__(self):
        self._notifier = Notifier()

    async def __call__(self, event: Event) -> None:
        if event.type == EventType.CIRCUIT_OPENED:
            c: CircuitEvent = event.payload
            msg = (
                f"**`{c.label}`** has failed {c.failure_count} consecutive times.\n"
                f"Circuit breaker opened — wallet will be skipped for {c.cooldown_seconds // 60}min.\n"
                f"Address: `{c.address}`"
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._notifier.broadcast, msg, "🔴 Circuit Breaker Tripped")
        
        elif event.type == EventType.CIRCUIT_CLOSED:
            c: CircuitEvent = event.payload
            msg = f"**`{c.label}`** recovered — circuit breaker closed, monitoring resumed."
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._notifier.broadcast, msg, "🟢 Circuit Breaker Recovered")


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class AsyncWatcher:
    """Wires bus, monitor, and handlers. Entry point for the watcher process."""

    def __init__(self, poll_interval: int = POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._bus = EventBus()
        self._dedup = DedupStore()
        self._monitor = WalletMonitor(self._bus, self._dedup)
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        # Wire handlers
        self._bus.subscribe(EventType.NEW_TRADE, NotificationHandler())
        self._bus.subscribe(EventType.WALLET_ERROR, LogHandler())
        self._bus.subscribe(EventType.CIRCUIT_OPENED, CircuitAlertHandler())
        self._bus.subscribe(EventType.CIRCUIT_OPENED, LogHandler())
        self._bus.subscribe(EventType.CIRCUIT_CLOSED, CircuitAlertHandler())
        self._bus.subscribe(EventType.CIRCUIT_CLOSED, LogHandler())
        self._bus.subscribe(EventType.HEARTBEAT, LogHandler())
        self._bus.subscribe(EventType.HEARTBEAT, StatsReporter())

    async def start(self) -> None:
        """Main loop — runs until stop() is called."""
        self._running = True
        await self._monitor.start()
        
        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                pass  # Windows
        
        print(f"🔍 Wallet Watcher starting (poll every {self._poll_interval}s, {self._dedup.size} known trades)...")
        
        try:
            while self._running:
                cycle_start = time.monotonic()
                
                try:
                    await self._monitor.poll_cycle()
                except Exception:
                    log.exception("Poll cycle failed unexpectedly")
                
                elapsed = time.monotonic() - cycle_start
                sleep_time = max(1.0, self._poll_interval - elapsed)
                
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=sleep_time)
                    break
                except asyncio.TimeoutError:
                    pass
        
        except asyncio.CancelledError:
            log.info("Watcher task cancelled.")
        finally:
            await self._shutdown()

    def stop(self) -> None:
        """Signal the loop to exit cleanly."""
        self._running = False
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """Clean teardown — flush dedup store, close session."""
        log.info("Shutting down watcher...")
        await self._dedup.flush()
        await self._monitor.stop()
        print("✅ Watcher stopped cleanly.")


# ─── Entry Point ──────────────────────────────────────────────────────────────

def watch_wallets():
    """Legacy entry point. Use AsyncWatcher directly for new code."""
    import warnings
    warnings.warn("watch_wallets() is deprecated. Use AsyncWatcher.", DeprecationWarning)
    
    watcher = AsyncWatcher()
    asyncio.run(watcher.start())


if __name__ == "__main__":
    watcher = AsyncWatcher()
    
    try:
        asyncio.run(watcher.start())
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
```

**Key Improvements Over Original Code:**

1. **Event-Driven Architecture**: Clear separation between monitoring, processing, and notification
2. **File-Backed Deduplication**: Persists across restarts with TTL and debounced saves
3. **Circuit Breaker**: Prevents cascading failures with proper state transitions
4. **Warm-up Phase**: Prevents startup notification spam
5. **Graceful Shutdown**: Proper signal handling and resource cleanup
6. **Typed Events**: Structured payloads for better maintainability
7. **Concurrency Control**: Semaphore limits concurrent API requests
8. **Atomic Writes**: Safe dedup file persistence

**To extend with new handlers:**

```python
class HighActivityHandler:
    """Alerts when a wallet trades 3+ times in one cycle."""
    
    def __init__(self):
        self._notifier = Notifier()
        self._cycle_counts: Dict[str, int] = defaultdict(int)
    
    async def __call__(self, event: Event) -> None:
        if event.type == EventType.HEARTBEAT:
            # Check and alert on high activity from this cycle
            for addr, count in self._cycle_counts.items():
                if count >= 3:
                    # Send alert
                    pass
            self._cycle_counts.clear()
            return
        
        if event.type == EventType.NEW_TRADE:
            t: TradeEvent = event.payload
            self._cycle_counts[t.address] += 1

# Wire it:
watcher._bus.subscribe(EventType.NEW_TRADE, HighActivityHandler())
watcher._bus.subscribe(EventType.HEARTBEAT, HighActivityHandler())
```
