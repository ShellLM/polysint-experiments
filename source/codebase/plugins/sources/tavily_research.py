"""
Tavily Web Research Plugin

Provides web search and research capabilities for market context.
"""

import os
import requests
from typing import Any, Dict, List, Optional

from plugins.base import DataSourcePlugin, PluginMetadata


class TavilyResearchPlugin(DataSourcePlugin):
    """
    Plugin for web research using the Tavily API.
    
    Provides:
    - Web search for market context
    - News aggregation
    - Domain-filtered searches
    
    This plugin is optional - it will disable itself if no API key is configured.
    """
    
    # Default configuration
    DEFAULT_API_URL = "https://api.tavily.com/search"
    DEFAULT_SEARCH_DEPTH = "basic"
    DEFAULT_MAX_RESULTS = 5
    DEFAULT_TIMEOUT = 15
    DEFAULT_MAX_QUERY_LENGTH = 100
    
    # Trusted news domains
    DEFAULT_DOMAINS = [
        "reuters.com",
        "apnews.com", 
        "bloomberg.com",
        "twitter.com",
    ]
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._api_key: Optional[str] = None
        self._api_url: str = self.DEFAULT_API_URL
        self._search_depth: str = self.DEFAULT_SEARCH_DEPTH
        self._max_results: int = self.DEFAULT_MAX_RESULTS
        self._timeout: int = self.DEFAULT_TIMEOUT
        self._include_domains: List[str] = self.DEFAULT_DOMAINS.copy()
    
    def _define_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="tavily_research",
            version="1.0.0",
            description="Tavily web research API for market news and context",
            author="PolySINT Team",
            tags=["research", "web", "news", "tavily", "search"],
            priority=50,  # Medium priority - supplementary data
            config_schema={
                "type": "object",
                "properties": {
                    "api_key": {
                        "type": "string",
                        "description": "Tavily API key (required)",
                    },
                    "api_url": {
                        "type": "string",
                        "description": "Tavily API URL",
                        "default": self.DEFAULT_API_URL,
                    },
                    "search_depth": {
                        "type": "string",
                        "description": "Search depth: ultra-fast, fast, basic, advanced",
                        "default": self.DEFAULT_SEARCH_DEPTH,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": self.DEFAULT_MAX_RESULTS,
                    },
                    "include_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Domains to include in search",
                        "default": self.DEFAULT_DOMAINS,
                    },
                },
                "required": ["api_key"],
            },
        )
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate that API key is present."""
        # This is acceptable - plugin will be disabled if no key
        return True
    
    def initialize(self) -> bool:
        """Initialize the plugin. Returns False if no API key (graceful disable)."""
        # Check for API key in config or environment
        self._api_key = self.get_config("api_key") or os.getenv("TAVILY_API_KEY")
        
        if not self._api_key:
            # Graceful disable - no API key configured
            self.disable("No TAVILY_API_KEY configured")
            return False
        
        # Load optional configuration
        self._api_url = self.get_config("api_url", self.DEFAULT_API_URL)
        self._search_depth = self.get_config("search_depth", self.DEFAULT_SEARCH_DEPTH)
        self._max_results = self.get_config("max_results", self.DEFAULT_MAX_RESULTS)
        self._timeout = self.get_config("timeout", self.DEFAULT_TIMEOUT)
        self._include_domains = self.get_config("include_domains", self.DEFAULT_DOMAINS)
        
        return True
    
    def health_check(self) -> Dict[str, Any]:
        """Check if the Tavily API is reachable and key is valid."""
        base_health = super().health_check()
        
        if not self._api_key:
            return {
                **base_health,
                "healthy": False,
                "error": "No API key configured",
                "hint": "Set TAVILY_API_KEY environment variable",
            }
        
        try:
            # Minimal test query
            resp = requests.post(
                self._api_url,
                json={
                    "api_key": self._api_key,
                    "query": "test",
                    "max_results": 1,
                },
                timeout=5,
            )
            
            if resp.status_code == 401:
                return {
                    **base_health,
                    "healthy": False,
                    "error": "Invalid API key",
                }
            
            return {
                **base_health,
                "healthy": resp.status_code == 200,
                "status_code": resp.status_code,
            }
            
        except Exception as e:
            return {**base_health, "healthy": False, "error": str(e)}
    
    # ─── Core Fetch Methods ─────────────────────────────────────────────────────
    
    def fetch(self, query: str, **kwargs) -> str:
        """
        Main fetch method - performs web search.
        
        Args:
            query: Search query
            **kwargs: Additional options
            
        Returns:
            Formatted search results string
        """
        return self.get_market_context(query, **kwargs)
    
    def get_market_context(
        self,
        market_question: str,
        search_depth: Optional[str] = None,
        max_results: Optional[int] = None,
        include_domains: Optional[List[str]] = None,
    ) -> str:
        """
        Search for context related to a market question.
        
        Args:
            market_question: The market question to research
            search_depth: Override default search depth
            max_results: Override default max results
            include_domains: Override default domains
            
        Returns:
            Formatted string with search results
        """
        if not self._api_key:
            return "Web research disabled: No TAVILY_API_KEY configured."
        
        # Truncate long queries
        query_text = market_question
        if len(query_text) > self.DEFAULT_MAX_QUERY_LENGTH:
            query_text = query_text[:self.DEFAULT_MAX_QUERY_LENGTH].rsplit(' ', 1)[0]
        
        search_depth = search_depth or self._search_depth
        max_results = max_results or self._max_results
        include_domains = include_domains or self._include_domains
        
        try:
            resp = requests.post(
                self._api_url,
                json={
                    "api_key": self._api_key,
                    "query": f"latest news: {query_text}",
                    "search_depth": search_depth,
                    "include_domains": include_domains,
                    "max_results": max_results,
                },
                timeout=self._timeout,
            )
            
            if resp.status_code != 200:
                return f"Search failed (API Error: {resp.status_code})."
            
            results = resp.json().get("results", [])
            
            if not results:
                return "No relevant news found."
            
            # Format results
            context_parts = []
            for r in results:
                title = r.get('title', 'Untitled')
                snippet = r.get('content', '')[:300]
                source_url = r.get('url', 'URL unavailable')
                published = r.get('published_date', 'Date unknown')
                
                context_parts.append(
                    f"- TITLE: {title}\n"
                    f"  DATE: {published}\n"
                    f"  SOURCE: {source_url}\n"
                    f"  SNIPPET: {snippet}..."
                )
            
            return "\n\n".join(context_parts)
            
        except Exception as e:
            self._last_error = e
            return f"Search failed (Network Error: {str(e)[:50]})."
    
    def search(
        self,
        query: str,
        search_depth: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform a raw search and return structured results.
        
        Args:
            query: Search query
            search_depth: Override default search depth
            max_results: Override default max results
            
        Returns:
            List of result dicts
        """
        if not self._api_key:
            return []
        
        try:
            resp = requests.post(
                self._api_url,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "search_depth": search_depth or self._search_depth,
                    "max_results": max_results or self._max_results,
                },
                timeout=self._timeout,
            )
            
            if resp.status_code != 200:
                return []
            
            return resp.json().get("results", [])
            
        except Exception as e:
            self._last_error = e
            return []


# Plugin entry point
def create_plugin(config: Optional[Dict[str, Any]] = None) -> TavilyResearchPlugin:
    """Factory function for the plugin loader."""
    return TavilyResearchPlugin(config)


# Export for backward compatibility
__all__ = [
    "TavilyResearchPlugin",
    "create_plugin",
]
