# PolySINT Plugin Architecture

## Overview

This plugin architecture enables extensible data sources for the PolySINT prediction market intelligence system. It supports auto-discovery, lifecycle management, configuration, and cross-cutting concerns like caching and rate limiting.

## Directory Structure


## Core Components

### 1. DataSourcePlugin (base.py)

Abstract base class that all plugins must implement:


Key features:
- **Metadata**: Name, version, description, tags, priority, dependencies
- **Lifecycle**: initialize(), fetch(), cleanup()
- **Health checking**: health_check() for monitoring
- **Metrics**: Automatic tracking of fetches, errors, response times
- **Async support**: initialize_async(), fetch_async(), cleanup_async()
- **Rate limiting**: Built-in hooks for rate limiters

### 2. PluginRegistry (registry.py)

Singleton registry for managing plugins:


Features:
- Plugin registration and lookup
- Lifecycle management
- Dependency resolution (topological sort)
- Health check aggregation

### 3. PluginLoader (loader.py)

Auto-discovers and loads plugins:


Discovery process:
1. Scan for `manifest.json` files in subdirectories
2. Load single-file plugins (`*.plugin.py`)
3. Import module and find plugin class
4. Register with registry

### 4. PluginConfig (config.py)

Configuration management with priority:

1. Explicit values passed to load()
2. Environment variables (`PLUGIN_{NAME}_{KEY}`)
3. JSON config file (`~/.polysint/plugins/{name}.json`)
4. Default values from schema


### 5. PluginMiddleware (middleware.py)

Cross-cutting concerns:


Features:
- **Caching**: TTL-based, LRU eviction, thread-safe
- **Rate limiting**: Token bucket algorithm
- **Metrics**: Hit rates, response times

## Creating a New Plugin

### Option 1: Single File Plugin

Create `plugins/sources/my_source.py`:


### Option 2: Directory with Manifest

Create `plugins/sources/my_source/` with:
- `manifest.json` - Metadata
- `my_source.py` - Implementation

## Configuration

### Environment Variables


### Config Files

Create `~/.polysint/plugins/my_source.json`:


## Integration with Existing Code

The plugin system is designed for backward compatibility. Existing code can migrate incrementally:

### Before (hardcoded imports)

### After (plugin-based)

### Shims for backward compatibility
Create a compatibility layer:


## Plugin States


## Best Practices

1. **Graceful degradation**: Plugins should handle missing config gracefully
2. **Health checks**: Implement meaningful health_check() for monitoring
3. **Rate limiting**: Respect API limits; use built-in rate limiter
4. **Caching**: Cache expensive fetches; set appropriate TTL
5. **Logging**: Use the standard logging module
6. **Error handling**: Catch exceptions, record in metrics, re-raise or return None
7. **Dependencies**: Declare dependencies in metadata for proper init order

## Future Extensions

- Plugin API endpoints (`/api/plugins/status`)
- Hot-reload for development
- Plugin marketplace/registry
- Plugin-specific webhooks
- Distributed caching backend
