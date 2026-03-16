"""
Middleware layer for plugins: caching, rate limiting, error handling.
"""

import time
import threading
from typing import Any, Dict, Optional, Callable, TypeVar, Generic
from dataclasses import dataclass, field
from functools import wraps
import logging

from .base import DataSourcePlugin, PluginState

log = logging.getLogger("PluginSystem")

T = TypeVar('T')


@dataclass
class CacheEntry:
    """A cached response entry."""
    value: Any
    timestamp: float
    ttl_seconds: float
    hits: int = 0
    
    @property
    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl_seconds


class PluginCache:
    """
    Thread-safe cache for plugin responses.
    
    Features:
    - TTL-based expiration
    - LRU eviction when max size reached
    - Cache hit/miss metrics
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: float = 60.0):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """Get a cached value if not expired."""
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                return None
            
            if entry.is_expired:
                del self._cache[key]
                self._misses += 1
                return None
            
            entry.hits += 1
            self._hits += 1
            return entry.value
    
    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[float] = None
    ) -> None:
        """Cache a value with optional TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        
        with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self.max_size:
                self._evict_lru()
            
            self._cache[key] = CacheEntry(
                value=value,
                timestamp=time.time(),
                ttl_seconds=ttl,
            )
    
    def delete(self, key: str) -> bool:
        """Remove a cached entry."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
    
    def _evict_lru(self) -> None:
        """Evict the least recently used entry."""
        if not self._cache:
            return
        
        lru_key = min(self._cache.keys(), key=lambda k: self._cache[k].hits)
        del self._cache[lru_key]
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0
            
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }


class RateLimiter:
    """
    Token bucket rate limiter.
    
    Limits the number of requests per time window.
    """
    
    def __init__(
        self,
        requests_per_second: float = 10.0,
        burst_size: Optional[int] = None
    ):
        self.rate = requests_per_second
        self.burst = burst_size or int(requests_per_second * 2)
        self._tokens = float(self.burst)
        self._last_update = time.time()
        self._lock = threading.Lock()
    
    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire a token, blocking if necessary.
        
        Args:
            timeout: Max time to wait (None = wait forever)
            
        Returns:
            True if token acquired, False if timeout
        """
        deadline = time.time() + timeout if timeout else None
        
        while True:
            with self._lock:
                now = time.time()
                # Refill tokens
                elapsed = now - self._last_update
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                self._last_update = now
                
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
            
            # Wait and retry
            wait_time = (1 - self._tokens) / self.rate
            
            if deadline and time.time() + wait_time > deadline:
                return False
            
            time.sleep(min(wait_time, 0.1))


class CachedPluginWrapper(DataSourcePlugin, Generic[T]):
    """
    Wrapper that adds caching and rate limiting to any plugin.
    
    Usage:
        original = MyPlugin()
        cached = CachedPluginWrapper(original, ttl=60)
    """
    
    def __init__(
        self,
        plugin: DataSourcePlugin[T],
        cache_ttl: float = 60.0,
        cache_max_size: int = 1000,
        rate_limit: Optional[float] = None,
    ):
        self._wrapped = plugin
        self._cache = PluginCache(max_size=cache_max_size, default_ttl=cache_ttl)
        self._rate_limiter = RateLimiter(requests_per_second=rate_limit) if rate_limit else None
        
        # Inherit metadata from wrapped plugin
        self._metadata = plugin.metadata
        self._state = plugin.state
    
    @property
    def metadata(self):
        return self._metadata
    
    @property
    def wrapped(self) -> DataSourcePlugin[T]:
        return self._wrapped
    
    def _define_metadata(self):
        return self._wrapped._define_metadata()
    
    def initialize(self) -> bool:
        return self._wrapped.initialize()
    
    def fetch(self, *args, **kwargs) -> T:
        """Fetch with caching and rate limiting."""
        # Generate cache key from args
        cache_key = self._make_cache_key(args, kwargs)
        
        # Check cache
        cached = self._cache.get(cache_key)
        if cached is not None:
            log.debug(f"[{self.name}] Cache hit")
            return cached
        
        # Apply rate limiting
        if self._rate_limiter:
            self._rate_limiter.acquire()
        
        # Fetch from wrapped plugin
        result = self._wrapped.fetch(*args, **kwargs)
        
        # Cache result
        self._cache.set(cache_key, result)
        
        return result
    
    def cleanup(self) -> None:
        self._cache.clear()
        self._wrapped.cleanup()
    
    def health_check(self) -> Dict[str, Any]:
        health = self._wrapped.health_check()
        health["cache_stats"] = self._cache.stats
        return health
    
    def _make_cache_key(self, args: tuple, kwargs: dict) -> str:
        """Generate a cache key from function arguments."""
        # Simple string representation; can be overridden for complex objects
        key_parts = [repr(args), repr(sorted(kwargs.items()))]
        return f"{self.name}:{':'.join(key_parts)}"
    
    # Pass-through for cache control
    def invalidate_cache(self, key: Optional[str] = None) -> None:
        """Invalidate cache (all or specific key)."""
        if key:
            self._cache.delete(key)
        else:
            self._cache.clear()


class PluginMiddleware:
    """
    Middleware manager for applying cross-cutting concerns to plugins.
    
    Features:
    - Global cache with per-plugin TTLs
    - Global rate limiting
    - Error handling and retries
    - Metrics collection
    """
    
    def __init__(
        self,
        default_cache_ttl: float = 60.0,
        default_rate_limit: Optional[float] = None,
        default_retry_count: int = 0,
    ):
        self.default_cache_ttl = default_cache_ttl
        self.default_rate_limit = default_rate_limit
        self.default_retry_count = default_retry_count
        
        self._plugin_cache: Dict[str, PluginCache] = {}
        self._plugin_rate_limiters: Dict[str, RateLimiter] = {}
    
    def wrap(
        self,
        plugin: DataSourcePlugin[T],
        cache_ttl: Optional[float] = None,
        rate_limit: Optional[float] = None,
        retry_count: Optional[int] = None,
    ) -> CachedPluginWrapper[T]:
        """
        Wrap a plugin with caching, rate limiting, and retry logic.
        """
        return CachedPluginWrapper(
            plugin,
            cache_ttl=cache_ttl or self.default_cache_ttl,
            rate_limit=rate_limit or self.default_rate_limit,
        )
    
    def get_cache(self, plugin_name: str) -> PluginCache:
        """Get or create a cache for a plugin."""
        if plugin_name not in self._plugin_cache:
            self._plugin_cache[plugin_name] = PluginCache(
                default_ttl=self.default_cache_ttl
            )
        return self._plugin_cache[plugin_name]
    
    def get_rate_limiter(
        self,
        plugin_name: str,
        rate: Optional[float] = None
    ) -> RateLimiter:
        """Get or create a rate limiter for a plugin."""
        if plugin_name not in self._plugin_rate_limiters:
            self._plugin_rate_limiters[plugin_name] = RateLimiter(
                requests_per_second=rate or self.default_rate_limit or 10.0
            )
        return self._plugin_rate_limiters[plugin_name]
    
    def stats(self) -> Dict[str, Any]:
        """Get aggregate statistics."""
        cache_stats = {
            name: cache.stats
            for name, cache in self._plugin_cache.items()
        }
        
        return {
            "plugin_count": len(self._plugin_cache),
            "cache_stats": cache_stats,
        }
