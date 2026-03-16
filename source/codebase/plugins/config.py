"""
Configuration management for plugins.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging

log = logging.getLogger("PluginSystem")


@dataclass
class PluginConfig:
    """
    Per-plugin configuration loader.
    
    Config sources (in order of priority):
    1. Explicit values passed to load()
    2. Environment variables (PLUGIN_{NAME}_{KEY})
    3. JSON config file (~/.polysint/plugins/{name}.json)
    4. Default values from schema
    """
    
    plugin_name: str
    config_dir: Optional[Path] = None
    
    def __post_init__(self):
        if self.config_dir is None:
            self.config_dir = Path.home() / ".polysint" / "plugins"
    
    def load(
        self,
        overrides: Optional[Dict[str, Any]] = None,
        env_prefix: str = "PLUGIN"
    ) -> Dict[str, Any]:
        """
        Load configuration from all sources.
        
        Args:
            overrides: Explicit values (highest priority)
            env_prefix: Prefix for environment variables
            
        Returns:
            Merged configuration dict
        """
        config = {}
        
        # 1. Load defaults from schema (if available) - handled by plugin
        
        # 2. Load from config file
        config = self._load_from_file()
        
        # 3. Load from environment variables
        env_config = self._load_from_env(env_prefix)
        config.update(env_config)
        
        # 4. Apply overrides
        if overrides:
            config.update(overrides)
        
        return config
    
    def _load_from_file(self) -> Dict[str, Any]:
        """Load config from JSON file."""
        config = {}
        
        if self.config_dir:
            config_file = self.config_dir / f"{self.plugin_name}.json"
            
            if config_file.exists():
                try:
                    with open(config_file) as f:
                        config = json.load(f)
                    log.debug(f"[{self.plugin_name}] Loaded config from {config_file}")
                except Exception as e:
                    log.warning(f"[{self.plugin_name}] Failed to load config file: {e}")
        
        return config
    
    def _load_from_env(self, prefix: str) -> Dict[str, Any]:
        """Load config from environment variables."""
        config = {}
        
        # Format: PLUGIN_{PLUGIN_NAME}_{KEY} or {PREFIX}_{PLUGIN_NAME}_{KEY}
        # Examples: PLUGIN_POLYMARKET_CLOB_BASE_URL, TAVILY_API_KEY
        
        # Try PLUGIN_{NAME}_{KEY}
        name_upper = self.plugin_name.upper().replace("-", "_")
        env_prefix = f"{prefix}_{name_upper}_"
        
        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                config_key = key[len(env_prefix):].lower()
                config[config_key] = self._parse_env_value(value)
        
        # Also check for plugin-specific env vars without prefix
        # e.g., TAVILY_API_KEY directly
        if self.plugin_name == "tavily_research":
            if "TAVILY_API_KEY" in os.environ:
                config["api_key"] = os.environ["TAVILY_API_KEY"]
        
        return config
    
    def _parse_env_value(self, value: str) -> Any:
        """Parse environment variable value to appropriate type."""
        # Boolean
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
        
        # Integer
        try:
            return int(value)
        except ValueError:
            pass
        
        # Float
        try:
            return float(value)
        except ValueError:
            pass
        
        # JSON
        if value.startswith(("{", "[")):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        
        # String
        return value
    
    def save(self, config: Dict[str, Any]) -> bool:
        """Save configuration to file."""
        if not self.config_dir:
            return False
        
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            config_file = self.config_dir / f"{self.plugin_name}.json"
            
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)
            
            log.info(f"[{self.plugin_name}] Saved config to {config_file}")
            return True
            
        except Exception as e:
            log.error(f"[{self.plugin_name}] Failed to save config: {e}")
            return False


def load_plugin_configs(
    plugin_names: List[str],
    config_dir: Optional[Path] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Load configurations for multiple plugins.
    
    Args:
        plugin_names: List of plugin names
        config_dir: Optional custom config directory
        
    Returns:
        Dict mapping plugin names to their configs
    """
    configs = {}
    
    for name in plugin_names:
        loader = PluginConfig(name, config_dir)
        configs[name] = loader.load()
    
    return configs
