Looking at `watcher.py`, the `seen_trades` set will grow indefinitely as more trades are observed. Here are specific improvements for memory management:

## **Primary Issue**
The in-memory `seen_trades` set persists across runs and grows unbounded. If the watcher runs continuously, it could eventually consume significant memory.

## **Recommended Solutions**

### **1. Time-based Expiration (TTL Cache)**
Replace the unbounded set with a time-based cache that automatically removes old entries:

```python
# In watcher.py
import time
from collections import OrderedDict

class TTLSet:
    """Set that automatically removes entries after a specified TTL."""
    
    def __init__(self, ttl_seconds=3600):  # Default: 1 hour TTL
        self.ttl = ttl_seconds
        self._data = OrderedDict()
    
    def add(self, item):
        self._data[item] = time.time()
        self._cleanup()
    
    def __contains__(self, item):
        if item not in self._data:
            return False
        # Check if expired
        if time.time() - self._data[item] > self.ttl:
            del self._data[item]
            return False
        return True
    
    def _cleanup(self):
        """Remove expired entries and enforce max size."""
        current_time = time.time()
        # Remove expired entries
        expired = [k for k, v in self._data.items() 
                  if current_time - v > self.ttl]
        for k in expired:
            del self._data[k]
        
        # Enforce maximum size (optional)
        max_size = 10000  # Adjust based on expected volume
        if len(self._data) > max_size:
            # Remove oldest entries
            remove_count = len(self._data) - max_size
            for _ in range(remove_count):
                self._data.popitem(last=False)

# Replace the global set
seen_trades = TTLSet(ttl_seconds=86400)  # 24-hour TTL
```

### **2. Database-backed Approach (For Long-term Persistence)**
If you need to persist seen trades across restarts and handle large volumes:

```python
# Add to db.py
def init_seen_trades_table():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS seen_trades (
            trade_id TEXT PRIMARY KEY,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_seen_trades_ts ON seen_trades(last_seen)')
    conn.commit()
    conn.close()

def is_trade_seen(trade_id):
    conn = get_db()
    result = conn.execute(
        'SELECT 1 FROM seen_trades WHERE trade_id = ?', 
        (trade_id,)
    ).fetchone()
    conn.close()
    return result is not None

def mark_trade_seen(trade_id):
    conn = get_db()
    conn.execute('''
        INSERT OR REPLACE INTO seen_trades (trade_id, last_seen) 
        VALUES (?, CURRENT_TIMESTAMP)
    ''', (trade_id,))
    conn.commit()
    conn.close()

def cleanup_old_seen_trades(days_to_keep=7):
    """Periodically clean up old entries."""
    conn = get_db()
    conn.execute('''
        DELETE FROM seen_trades 
        WHERE last_seen < datetime('now', ?)
    ''', (f'-{days_to_keep} days',))
    deleted = conn.total_changes
    conn.commit()
    conn.close()
    return deleted
```

Then in `watcher.py`:
```python
def watch_wallets():
    # ... existing code ...
    
    for trade in trades:
        trade_id = trade.get('transactionHash')
        
        if trade_id and not is_trade_seen(trade_id):
            mark_trade_seen(trade_id)
            
            # Process and notify
            # ... existing notification code ...
```

### **3. Hybrid Approach (Recommended)**
Combine in-memory cache with database persistence for best performance:

```python
class TradeTracker:
    def __init__(self, db_enabled=True, ttl_seconds=3600):
        self.db_enabled = db_enabled
        self.memory_cache = set()
        self.ttl = ttl_seconds
        self.last_cleanup = time.time()
        
        if db_enabled:
            init_seen_trades_table()
    
    def is_seen(self, trade_id):
        # Check memory cache first (fast)
        if trade_id in self.memory_cache:
            return True
        
        # Check database if enabled
        if self.db_enabled:
            if is_trade_seen(trade_id):
                # Add to memory cache for faster future lookups
                self.memory_cache.add(trade_id)
                return True
        
        return False
    
    def mark_seen(self, trade_id):
        # Add to memory cache
        self.memory_cache.add(trade_id)
        
        # Persist to database if enabled
        if self.db_enabled:
            mark_trade_seen(trade_id)
        
        # Periodic cleanup
        if time.time() - self.last_cleanup > 300:  # Every 5 minutes
            self._cleanup()
    
    def _cleanup(self):
        # Clean memory cache
        if len(self.memory_cache) > 10000:
            # Remove oldest half (approximate)
            self.memory_cache = set(list(self.memory_cache)[5000:])
        
        # Clean database
        if self.db_enabled:
            deleted = cleanup_old_seen_trades(days_to_keep=1)
            if deleted > 0:
                log.info(f"Cleaned {deleted} old trade records")
        
        self.last_cleanup = time.time()

# Global instance
trade_tracker = TradeTracker(db_enabled=True, ttl_seconds=86400)
```

### **4. Minimal Quick Fix**
If you just want a quick fix without major changes:

```python
# Add size limit and periodic reset
MAX_SEEN_TRADES = 50000
seen_trades = set()

def watch_wallets():
    global seen_trades
    
    # Reset if set gets too large
    if len(seen_trades) > MAX_SEEN_TRADES:
        log.warning(f"Clearing seen_trades cache ({len(seen_trades)} entries)")
        seen_trades.clear()
    
    # ... rest of existing code ...
```

## **Additional Recommendations**

1. **Add logging** when trades are skipped due to being seen:
```python
if trade_id and trade_id in seen_trades:
    log.debug(f"Skipping duplicate trade {trade_id[:16]}...")
```

2. **Use transaction hashes with caution** - they're unique per blockchain transaction, but if the same trade appears in multiple API responses (different endpoints), you might still get duplicates. Consider a composite key:
```python
trade_key = f"{trade_id}_{trade.get('timestamp', '')}"
```

3. **Monitor memory usage** and adjust TTL/size limits based on your actual trade volume.

The **hybrid approach (#3)** is recommended for production use as it provides both performance and persistence while keeping memory usage bounded.
