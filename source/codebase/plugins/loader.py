"""
Plugin loader for auto-discovery and initialization.
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type, Any
import logging
import inspect

from .base import DataSourcePlugin, PluginState
from .registry import PluginRegistry, get_registry
from .config import load_plugin_configs

log = logging.getLogger("PluginSystem")


class PluginLoader:
    """
    Auto-discovers and loads plugins from a directory.
    
    Discovers plugins by:
    1. Scanning for manifest.json files
    2. Loading the Python module specified in manifest
    3. Instantiating the plugin class
    4. Registering with the registry
    """
    
    def __init__(
        self,
        plugins_dir: Optional[Path] = None,
        registry: Optional[PluginRegistry] = None
    ):
        self.plugins_dir = plugins_dir or Path(__file__).parent / "sources"
        self.registry = registry or get_registry()
        self._discovered: Dict[str, Dict[str, Any]] = {}
    
    def discover(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover all plugins in the plugins directory.
        
        Returns:
            Dict mapping plugin names to discovery info
        """
        self._discovered = {}
        
        if not self.plugins_dir.exists():
            log.warning(f"Plugins directory does not exist: {self.plugins_dir}")
            return self._discovered
        
        # Scan for plugin directories
        for item in self.plugins_dir.iterdir():
            if item.is_dir():
                manifest_path = item / "manifest.json"
                if manifest_path.exists():
                    self._load_manifest(item, manifest_path)
            
            # Also check for single-file plugins (*.plugin.py)
            elif item.is_file() and item.suffix == ".py":
                self._load_single_file_plugin(item)
        
        return self._discovered
    
    def _load_manifest(self, plugin_dir: Path, manifest_path: Path) -> Optional[str]:
        """Load a plugin manifest and validate it."""
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            
            # Validate required fields
            required = ["name", "version", "module"]
            for field in required:
                if field not in manifest:
                    log.error(f"Manifest missing required field: {field}")
                    return None
            
            name = manifest["name"]
            self._discovered[name] = {
                "manifest": manifest,
                "path": plugin_dir,
                "module_path": plugin_dir / manifest["module"],
            }
            
            log.debug(f"Discovered plugin: {name} v{manifest['version']}")
            return name
            
        except Exception as e:
            log.error(f"Failed to load manifest {manifest_path}: {e}")
            return None
    
    def _load_single_file_plugin(self, file_path: Path) -> Optional[str]:
        """Load a single-file plugin (for simple plugins)."""
        try:
            # Import the module
            spec = importlib.util.spec_from_file_location(
                f"plugin_{file_path.stem}",
                file_path
            )
            if spec is None or spec.loader is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"plugin_{file_path.stem}"] = module
            spec.loader.exec_module(module)
            
            # Find plugin class (class ending with Plugin or with @plugin decorator)
            plugin_class = None
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, DataSourcePlugin) and 
                    obj is not DataSourcePlugin):
                    plugin_class = obj
                    break
            
            if plugin_class is None:
                log.warning(f"No plugin class found in {file_path}")
                return None
            
            # Create temp instance for metadata
            temp = plugin_class()
            plugin_name = temp.name
            
            self._discovered[plugin_name] = {
                "manifest": {
                    "name": plugin_name,
                    "version": temp.metadata.version,
                },
                "path": file_path,
                "module": module,
                "plugin_class": plugin_class,
            }
            
            return plugin_name
            
        except Exception as e:
            log.error(f"Failed to load single-file plugin {file_path}: {e}")
            return None
    
    def load(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None
    ) -> Optional[DataSourcePlugin]:
        """
        Load a specific plugin by name.
        
        Args:
            name: Plugin name
            config: Optional configuration dict
            
        Returns:
            Loaded plugin instance or None on failure
        """
        if name not in self._discovered:
            log.error(f"Plugin not discovered: {name}")
            return None
        
        discovery_info = self._discovered[name]
        
        try:
            # Get or import module
            if "plugin_class" in discovery_info:
                plugin_class = discovery_info["plugin_class"]
            else:
                module_path = discovery_info["module_path"]
                spec = importlib.util.spec_from_file_location(
                    f"plugin_{name}",
                    module_path
                )
                if spec is None or spec.loader is None:
                    return None
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Find plugin class
                plugin_class = None
                for n, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, DataSourcePlugin) and 
                        obj is not DataSourcePlugin):
                        plugin_class = obj
                        break
                
                if plugin_class is None:
                    log.error(f"No plugin class found for {name}")
                    return None
            
            # Instantiate plugin
            plugin = plugin_class(config)
            
            # Register
            self.registry.register(plugin)
            
            return plugin
            
        except Exception as e:
            log.error(f"Failed to load plugin {name}: {e}")
            return None
    
    def load_all(
        self,
        configs: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, DataSourcePlugin]:
        """
        Load all discovered plugins.
        
        Args:
            configs: Dict mapping plugin names to configs
            
        Returns:
            Dict of successfully loaded plugins
        """
        configs = configs or {}
        loaded = {}
        
        for name in self._discovered:
            config = configs.get(name)
            plugin = self.load(name, config)
            if plugin:
                loaded[name] = plugin
        
        return loaded


def load_all_plugins(
    plugins_dir: Optional[Path] = None,
    auto_initialize: bool = True,
    config_dir: Optional[Path] = None
) -> Dict[str, DataSourcePlugin]:
    """
    Convenience function to discover, load, and initialize all plugins.
    
    Args:
        plugins_dir: Directory containing plugins
        auto_initialize: Whether to initialize plugins after loading
        config_dir: Directory containing plugin configs
        
    Returns:
        Dict of loaded plugins
    """
    loader = PluginLoader(plugins_dir)
    
    # Discover
    discovered = loader.discover()
    log.info(f"Discovered {len(discovered)} plugins")
    
    # Load configs
    configs = load_plugin_configs(list(discovered.keys()), config_dir)
    
    # Load plugins
    loaded = loader.load_all(configs)
    log.info(f"Loaded {len(loaded)} plugins")
    
    # Initialize
    if auto_initialize:
        registry = get_registry()
        results = registry.initialize_all(configs)
        success_count = sum(1 for v in results.values() if v)
        log.info(f"Initialized {success_count}/{len(results)} plugins")
    
    return loaded
