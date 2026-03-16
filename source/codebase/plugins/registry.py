"""
Plugin registry for discovery, registration, and lifecycle management.
"""

from typing import Dict, List, Optional, Type, Any
import logging
import threading
from .base import DataSourcePlugin, PluginState, PluginMetadata

log = logging.getLogger("PluginSystem")


class PluginRegistry:
    """
    Central registry for all plugins.
    
    Handles:
    - Plugin registration and deregistration
    - Plugin discovery by name, tag, or capability
    - Lifecycle management (initialize, cleanup)
    - Dependency resolution
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._plugins: Dict[str, DataSourcePlugin] = {}
                    cls._instance._plugin_classes: Dict[str, Type[DataSourcePlugin]] = {}
                    cls._instance._initialized = False
        return cls._instance
    
    def register(self, plugin: DataSourcePlugin) -> bool:
        """Register a plugin instance."""
        name = plugin.name
        
        if name in self._plugins:
            log.warning(f"Plugin '{name}' already registered, replacing")
            
        self._plugins[name] = plugin
        plugin.set_state(PluginState.REGISTERED)
        log.info(f"Registered plugin: {name} v{plugin.metadata.version}")
        return True
    
    def register_class(self, plugin_class: Type[DataSourcePlugin]) -> bool:
        """Register a plugin class (instantiated later)."""
        # Create temp instance to get metadata
        temp = plugin_class()
        name = temp.name
        self._plugin_classes[name] = plugin_class
        log.debug(f"Registered plugin class: {name}")
        return True
    
    def unregister(self, name: str) -> bool:
        """Unregister and cleanup a plugin."""
        if name not in self._plugins:
            return False
            
        plugin = self._plugins[name]
        if plugin.is_enabled:
            plugin.cleanup()
            
        del self._plugins[name]
        log.info(f"Unregistered plugin: {name}")
        return True
    
    def get(self, name: str) -> Optional[DataSourcePlugin]:
        """Get a plugin by name."""
        return self._plugins.get(name)
    
    def get_all(self) -> Dict[str, DataSourcePlugin]:
        """Get all registered plugins."""
        return dict(self._plugins)
    
    def get_by_tag(self, tag: str) -> List[DataSourcePlugin]:
        """Get plugins matching a tag."""
        return [
            p for p in self._plugins.values()
            if tag in p.metadata.tags
        ]
    
    def get_ready(self) -> List[DataSourcePlugin]:
        """Get all plugins in READY state."""
        return [p for p in self._plugins.values() if p.is_ready]
    
    def get_enabled(self) -> List[DataSourcePlugin]:
        """Get all enabled plugins."""
        return [p for p in self._plugins.values() if p.is_enabled]
    
    def names(self) -> List[str]:
        """Get all plugin names."""
        return list(self._plugins.keys())
    
    # ─── Lifecycle Management ──────────────────────────────────────────────────
    
    def initialize_all(self, configs: Optional[Dict[str, Dict]] = None) -> Dict[str, bool]:
        """
        Initialize all registered plugins.
        
        Args:
            configs: Dict mapping plugin names to their config dicts
            
        Returns:
            Dict mapping plugin names to success/failure
        """
        configs = configs or {}
        results = {}
        
        # Sort by priority (lower = higher priority)
        plugins = sorted(
            self._plugins.values(),
            key=lambda p: p.metadata.priority
        )
        
        for plugin in plugins:
            if plugin.state == PluginState.DISABLED:
                results[plugin.name] = False
                continue
                
            try:
                plugin.set_state(PluginState.INITIALIZING)
                config = configs.get(plugin.name, {})
                
                if config:
                    plugin.update_config(config)
                
                if plugin.validate_config(plugin._config):
                    success = plugin.initialize()
                else:
                    log.error(f"[{plugin.name}] Config validation failed")
                    success = False
                
                if success:
                    plugin.set_state(PluginState.READY)
                    results[plugin.name] = True
                else:
                    plugin.set_state(PluginState.ERROR)
                    results[plugin.name] = False
                    
            except Exception as e:
                log.error(f"[{plugin.name}] Initialization failed: {e}")
                plugin.set_state(PluginState.ERROR)
                results[plugin.name] = False
        
        self._initialized = True
        return results
    
    def cleanup_all(self) -> None:
        """Cleanup all plugins."""
        for name, plugin in self._plugins.items():
            try:
                plugin.set_state(PluginState.CLEANING)
                plugin.cleanup()
                log.info(f"[{name}] Cleaned up")
            except Exception as e:
                log.error(f"[{name}] Cleanup failed: {e}")
        
        self._plugins.clear()
        self._initialized = False
    
    def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """Run health checks on all plugins."""
        return {
            name: plugin.health_check()
            for name, plugin in self._plugins.items()
        }
    
    # ─── Dependency Resolution ─────────────────────────────────────────────────
    
    def resolve_dependencies(self) -> List[str]:
        """
        Resolve plugin dependencies and return initialization order.
        Raises ValueError if circular dependencies detected.
        """
        # Build dependency graph
        deps = {
            name: set(plugin.metadata.requires)
            for name, plugin in self._plugins.items()
        }
        
        # Topological sort (Kahn's algorithm)
        order = []
        in_degree = {name: 0 for name in deps}
        
        for name, reqs in deps.items():
            for req in reqs:
                if req in in_degree:
                    in_degree[name] += 1
        
        queue = [n for n, d in in_degree.items() if d == 0]
        
        while queue:
            node = queue.pop(0)
            order.append(node)
            
            for name, reqs in deps.items():
                if node in reqs:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)
        
        if len(order) != len(deps):
            raise ValueError("Circular dependency detected in plugins")
        
        return order


def get_registry() -> PluginRegistry:
    """Get the singleton registry instance."""
    return PluginRegistry()
