"""
Polymarket CLOB Data Source Plugin

Provides price history and market data from Polymarket's CLOB API.
"""

import os
import time
import requests
from typing import Any, Dict, List, Optional

from plugins.base import DataSourcePlugin, PluginMetadata

# Suppress SSL warnings (Polymarket uses self-signed cert in chain)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class PolymarketCLOBPlugin(DataSourcePlugin):
    """
    Plugin for fetching data from Polymarket's CLOB (Central Limit Order Book) API.
    
    Provides:
    - Historical price data
    - Price shift calculations
    - Market status checks
    """
    
    # Default configuration
    DEFAULT_BASE_URL = "https://clob.polymarket.com"
    DEFAULT_INTERVAL = "1d"
    DEFAULT_FIDELITY = 60
    DEFAULT_TIMEOUT = 10
    DEFAULT_VERIFY_SSL = False
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._base_url: str = self.DEFAULT_BASE_URL
        self._timeout: int = self.DEFAULT_TIMEOUT
        self._verify_ssl: bool = self.DEFAULT_VERIFY_SSL
        self._default_interval: str = self.DEFAULT_INTERVAL
        self._default_fidelity: int = self.DEFAULT_FIDELITY
        self._session: Optional[requests.Session] = None
    
    def _define_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="polymarket_clob",
            version="1.0.0",
            description="Polymarket CLOB API data source for price history and market data",
            author="PolySINT Team",
            tags=["polymarket", "clob", "prices", "market-data"],
            priority=10,  # High priority - core data source
            config_schema={
                "type": "object",
                "properties": {
                    "base_url": {
                        "type": "string",
                        "description": "CLOB API base URL",
                        "default": self.DEFAULT_BASE_URL,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Request timeout in seconds",
                        "default": self.DEFAULT_TIMEOUT,
                    },
                    "verify_ssl": {
                        "type": "boolean",
                        "description": "Verify SSL certificates",
                        "default": self.DEFAULT_VERIFY_SSL,
                    },
                    "default_interval": {
                        "type": "string",
                        "description": "Default time interval for history (1h, 6h, 1d, 1w, max)",
                        "default": self.DEFAULT_INTERVAL,
                    },
                    "default_fidelity": {
                        "type": "integer",
                        "description": "Default resolution in minutes",
                        "default": self.DEFAULT_FIDELITY,
                    },
                    "rate_limit": {
                        "type": "number",
                        "description": "Max requests per second",
                        "default": 10.0,
                    },
                },
            },
        )
    
    def initialize(self) -> bool:
        """Initialize the plugin with configuration."""
        try:
            # Load configuration
            self._base_url = self.get_config("base_url", self.DEFAULT_BASE_URL)
            self._timeout = self.get_config("timeout", self.DEFAULT_TIMEOUT)
            self._verify_ssl = self.get_config("verify_ssl", self.DEFAULT_VERIFY_SSL)
            self._default_interval = self.get_config("default_interval", self.DEFAULT_INTERVAL)
            self._default_fidelity = self.get_config("default_fidelity", self.DEFAULT_FIDELITY)
            
            # Create session
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "PolySINT/1.0",
                "Accept": "application/json",
            })
            
            return True
            
        except Exception:
            return False
    
    def cleanup(self) -> None:
        """Clean up resources."""
        if self._session:
            self._session.close()
            self._session = None
    
    def health_check(self) -> Dict[str, Any]:
        """Check if the CLOB API is reachable."""
        base_health = super().health_check()
        
        try:
            if not self._session:
                return {**base_health, "healthy": False, "error": "Session not initialized"}
            
            # Try to reach the API
            resp = self._session.get(
                f"{self._base_url}/markets",
                timeout=5,
                verify=self._verify_ssl,
            )
            
            return {
                **base_health,
                "healthy": resp.status_code == 200,
                "status_code": resp.status_code,
                "base_url": self._base_url,
            }
            
        except Exception as e:
            return {**base_health, "healthy": False, "error": str(e)}
    
    # ─── Core Fetch Methods ─────────────────────────────────────────────────────
    
    def fetch(self, clob_token_id: str, **kwargs) -> Optional[List[Dict]]:
        """
        Main fetch method - returns price history by default.
        
        Args:
            clob_token_id: The CLOB token ID for the market
            **kwargs: Additional options (interval, fidelity)
            
        Returns:
            Price history list or None on failure
        """
        return self.get_price_history(clob_token_id, **kwargs)
    
    def get_price_history(
        self,
        clob_token_id: str,
        interval: Optional[str] = None,
        fidelity: Optional[int] = None,
    ) -> Optional[List[Dict]]:
        """
        Fetch historical price data for a CLOB token.
        
        Args:
            clob_token_id: The CLOB token ID
            interval: Time interval (1h, 6h, 1d, 1w, max)
            fidelity: Resolution in minutes
            
        Returns:
            List of {"t": timestamp, "p": price} dicts, oldest first
        """
        if not self._session:
            raise RuntimeError("Plugin not initialized")
        
        interval = interval or self._default_interval
        fidelity = fidelity or self._default_fidelity
        
        try:
            resp = self._session.get(
                f"{self._base_url}/prices-history",
                params={
                    "market": clob_token_id,
                    "interval": interval,
                    "fidelity": fidelity,
                },
                timeout=self._timeout,
                verify=self._verify_ssl,
            )
            
            if resp.status_code != 200:
                return None
            
            history = resp.json().get("history", [])
            if not history:
                return None
            
            return sorted(history, key=lambda x: x["t"])
            
        except Exception as e:
            self._last_error = e
            return None
    
    def get_shift(
        self,
        clob_token_id: str,
        interval: Optional[str] = None
    ) -> Optional[float]:
        """
        Calculate price shift over the interval.
        
        Args:
            clob_token_id: The CLOB token ID
            interval: Time interval
            
        Returns:
            Price shift as float (e.g., 0.12 = 12% increase)
        """
        history = self.get_price_history(clob_token_id, interval=interval)
        
        if not history or len(history) < 2:
            return None
        
        price_then = float(history[0]["p"])
        price_now = float(history[-1]["p"])
        
        return price_now - price_then
    
    def get_history_as_price_list(
        self,
        clob_token_id: str,
        interval: Optional[str] = None
    ) -> Optional[List[float]]:
        """
        Get price history as a flat list of prices.
        
        Args:
            clob_token_id: The CLOB token ID
            interval: Time interval
            
        Returns:
            List of prices (floats), oldest to newest
        """
        history = self.get_price_history(clob_token_id, interval=interval)
        
        if not history:
            return None
        
        return [float(h["p"]) for h in history]
    
    def get_order_book(self, clob_token_id: str) -> Optional[Dict]:
        """
        Fetch current order book for a token.
        
        Args:
            clob_token_id: The CLOB token ID
            
        Returns:
            Order book dict with 'bids' and 'asks'
        """
        if not self._session:
            raise RuntimeError("Plugin not initialized")
        
        try:
            resp = self._session.get(
                f"{self._base_url}/book",
                params={"token_id": clob_token_id},
                timeout=self._timeout,
                verify=self._verify_ssl,
            )
            
            if resp.status_code != 200:
                return None
            
            return resp.json()
            
        except Exception as e:
            self._last_error = e
            return None


# Plugin entry point
def create_plugin(config: Optional[Dict[str, Any]] = None) -> PolymarketCLOBPlugin:
    """Factory function for the plugin loader."""
    return PolymarketCLOBPlugin(config)


# Export for backward compatibility
__all__ = [
    "PolymarketCLOBPlugin",
    "create_plugin",
]
