"""
Abstract base class for all data source plugins.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Dict, List, Callable, TypeVar, Generic
import asyncio
import time
import logging

log = logging.getLogger("PluginSystem")


class PluginState(Enum):
    """Lifecycle states of a plugin."""
    UNREGISTERED = "unregistered"
    REGISTERED = "registered"
    INITIALIZING = "initializing"
    READY = "ready"
    ERROR = "error"
    DISABLED = "disabled"
    CLEANING = "cleaning"


@dataclass
class PluginMetadata:
    """Metadata describing a plugin."""
    name: str
    version: str
    description: str
    author: str = ""
    homepage: str = ""
    license: str = "MIT"
    tags: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)  # Dependencies on other plugins
    config_schema: Dict[str, Any] = field(default_factory=dict)  # JSON Schema for config
    priority: int = 100  # Lower = higher priority for execution order
    

@dataclass
class PluginMetrics:
    """Runtime metrics for a plugin."""
    fetch_count: int = 0
    error_count: int = 0
    last_fetch_time: Optional[float] = None
    last_error: Optional[str] = None
    avg_response_time_ms: float = 0.0
    total_response_time_ms: float = 0.0
    

T = TypeVar('T')


class DataSourcePlugin(ABC, Generic[T]):
    """
    Abstract base class for all data source plugins.
    
    Each plugin represents an external data source that can be:
    - Initialized with configuration
    - Queried for data
    - Monitored for health
    - Cleaned up on shutdown
    
    Plugins can be sync or async - the base class handles both.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._state = PluginState.UNREGISTERED
        self._metadata: Optional[PluginMetadata] = None
        self._metrics = PluginMetrics()
        self._rate_limiter: Optional[Callable] = None
        self._cache: Optional[Dict[str, Any]] = None
        self._last_error: Optional[Exception] = None
        
    @property
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata. Must be implemented by subclasses."""
        if self._metadata is None:
            self._metadata = self._define_metadata()
        return self._metadata
    
    @property
    def state(self) -> PluginState:
        return self._state
    
    @property
    def metrics(self) -> PluginMetrics:
        return self._metrics
    
    @property
    def name(self) -> str:
        return self.metadata.name
    
    @property
    def is_ready(self) -> bool:
        return self._state == PluginState.READY
    
    @property
    def is_enabled(self) -> bool:
        return self._state not in (PluginState.DISABLED, PluginState.UNREGISTERED)
    
    # ─── Abstract Methods (must be implemented) ───────────────────────────────
    
    @abstractmethod
    def _define_metadata(self) -> PluginMetadata:
        """Define plugin metadata. Called once on first access."""
        pass
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize the plugin (sync version).
        Called after registration and config validation.
        Return True on success, False on failure.
        """
        pass
    
    @abstractmethod
    def fetch(self, *args, **kwargs) -> T:
        """
        Fetch data from the source (sync version).
        This is the main data retrieval method.
        """
        pass
    
    # ─── Optional Methods (can be overridden) ─────────────────────────────────
    
    def cleanup(self) -> None:
        """Clean up resources on shutdown. Default: no-op."""
        pass
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check if the plugin is healthy.
        Returns a dict with 'healthy': bool and optional details.
        """
        return {
            "healthy": self.is_ready,
            "state": self._state.value,
            "error_count": self._metrics.error_count,
            "last_error": str(self._last_error) if self._last_error else None,
        }
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """
        Validate configuration against schema.
        Override for custom validation logic.
        """
        # Basic validation: check required keys from schema
        schema = self.metadata.config_schema
        if not schema:
            return True
            
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        
        for key in required:
            if key not in config:
                log.error(f"[{self.name}] Missing required config: {key}")
                return False
            # Type check if type is specified
            prop_def = properties.get(key, {})
            expected_type = prop_def.get("type")
            if expected_type:
                if not self._check_type(config[key], expected_type):
                    log.error(f"[{self.name}] Config {key} has wrong type")
                    return False
        return True
    
    def _check_type(self, value: Any, type_str: str) -> bool:
        """Helper for type checking."""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected = type_map.get(type_str)
        return isinstance(value, expected) if expected else True
    
    # ─── Async Support ─────────────────────────────────────────────────────────
    
    async def initialize_async(self) -> bool:
        """Async version of initialize. Default: calls sync version."""
        return self.initialize()
    
    async def fetch_async(self, *args, **kwargs) -> T:
        """Async version of fetch. Default: runs sync in executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.fetch(*args, **kwargs))
    
    async def cleanup_async(self) -> None:
        """Async version of cleanup. Default: calls sync version."""
        self.cleanup()
    
    # ─── State Management ──────────────────────────────────────────────────────
    
    def set_state(self, state: PluginState) -> None:
        """Update plugin state."""
        old_state = self._state
        self._state = state
        log.info(f"[{self.name}] State changed: {old_state.value} -> {state.value}")
    
    def disable(self, reason: str = "") -> None:
        """Disable the plugin."""
        log.warning(f"[{self.name}] Disabling plugin: {reason}")
        self.set_state(PluginState.DISABLED)
    
    # ─── Rate Limiting ─────────────────────────────────────────────────────────
    
    def set_rate_limiter(self, limiter: Callable) -> None:
        """Set a rate limiting function that blocks when limits are exceeded."""
        self._rate_limiter = limiter
    
    def _apply_rate_limit(self) -> None:
        """Apply rate limiting before a fetch."""
        if self._rate_limiter:
            self._rate_limiter()
    
    # ─── Metrics Collection ────────────────────────────────────────────────────
    
    def record_fetch(self, response_time_ms: float, success: bool, error: Optional[str] = None) -> None:
        """Record metrics for a fetch operation."""
        self._metrics.fetch_count += 1
        self._metrics.last_fetch_time = time.time()
        self._metrics.total_response_time_ms += response_time_ms
        self._metrics.avg_response_time_ms = (
            self._metrics.total_response_time_ms / self._metrics.fetch_count
        )
        
        if not success:
            self._metrics.error_count += 1
            self._metrics.last_error = error
    
    # ─── Configuration Access ──────────────────────────────────────────────────
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a config value with optional default."""
        return self._config.get(key, default)
    
    def set_config(self, key: str, value: Any) -> None:
        """Set a config value at runtime."""
        self._config[key] = value
    
    def update_config(self, config: Dict[str, Any]) -> None:
        """Update multiple config values."""
        self._config.update(config)
    
    # ─── Wrapper Methods (with metrics & rate limiting) ────────────────────────
    
    def safe_fetch(self, *args, **kwargs) -> T:
        """
        Fetch with automatic error handling, metrics, and rate limiting.
        Use this for production calls.
        """
        if not self.is_ready:
            raise RuntimeError(f"Plugin {self.name} is not ready (state: {self._state.value})")
        
        self._apply_rate_limit()
        start = time.time()
        
        try:
            result = self.fetch(*args, **kwargs)
            elapsed_ms = (time.time() - start) * 1000
            self.record_fetch(elapsed_ms, success=True)
            return result
            
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            self.record_fetch(elapsed_ms, success=False, error=str(e))
            self._last_error = e
            raise
