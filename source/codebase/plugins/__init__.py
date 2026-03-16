"""
PolySINT Plugin System

A plugin architecture for extensible data sources.
"""

from .base import DataSourcePlugin, PluginMetadata, PluginState
from .registry import PluginRegistry, get_registry
from .config import PluginConfig
from .loader import PluginLoader, load_all_plugins
from .middleware import PluginMiddleware, CachedPluginWrapper

__all__ = [
    'DataSourcePlugin',
    'PluginMetadata', 
    'PluginState',
    'PluginRegistry',
    'get_registry',
    'PluginConfig',
    'PluginLoader',
    'load_all_plugins',
    'PluginMiddleware',
    'CachedPluginWrapper',
]

__version__ = '1.0.0'
