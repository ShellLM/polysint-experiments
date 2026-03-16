import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_NAME = "polysint_core.db"

    # Polymarket specific endpoints
    GAMMA_API = "https://gamma-api.polymarket.com/markets"
    DATA_API = "https://data-api.polymarket.com"

    # Blockchain RPC
    RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

    # LLM
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_API_BASE_URL")
    LLM_MODEL = os.getenv("ANALYSIS_MODEL")

    # Webhook Configurations
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # Web Research (Tavily)
    ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"

    # ─── Plugin System Configuration ─────────────────────────────────────────────
    
    # Enable/disable plugin system entirely
    PLUGINS_ENABLED = os.getenv("PLUGINS_ENABLED", "true").lower() == "true"
    
    # Directory containing plugins (relative to project root or absolute)
    PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR", "plugins/sources"))
    
    # Directory for plugin configuration files
    PLUGIN_CONFIG_DIR = Path(os.getenv("PLUGIN_CONFIG_DIR", "~/.polysint/plugins")).expanduser()
    
    # Auto-discover plugins on startup
    PLUGINS_AUTO_DISCOVER = os.getenv("PLUGINS_AUTO_DISCOVER", "true").lower() == "true"
    
    # Default cache TTL for all plugins (seconds)
    PLUGIN_DEFAULT_CACHE_TTL = int(os.getenv("PLUGIN_DEFAULT_CACHE_TTL", "60"))
    
    # Default rate limit (requests per second)
    PLUGIN_DEFAULT_RATE_LIMIT = float(os.getenv("PLUGIN_DEFAULT_RATE_LIMIT", "10.0"))
    
    # Disabled plugins (comma-separated list)
    PLUGINS_DISABLED = [
        p.strip() 
        for p in os.getenv("PLUGINS_DISABLED", "").split(",") 
        if p.strip()
    ]
    
    # Plugin-specific environment variable shortcuts
    # These map to plugin configs automatically
    PLUGIN_ENV_MAPPINGS = {
        "polymarket_clob": {
            "base_url": "CLOB_BASE_URL",
            "timeout": "CLOB_TIMEOUT",
        },
        "tavily_research": {
            "api_key": "TAVILY_API_KEY",
            "search_depth": "TAVILY_SEARCH_DEPTH",
        },
    }
