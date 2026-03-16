# Security Audit & Remediation for SSRF in clob.py

        ## Critical Vulnerability Identified

        The `clob.py` module contains a **critical indirect SSRF vulnerability** stemming from disabled SSL verification (`_SSL_VERIFY = False`) combined with default redirect-following behavior. This creates a dangerous attack vector:

        1. **MITM Attack**: An attacker intercepts the connection to `clob.polymarket.com`
        2. **Redirect to Internal Resources**: The attacker returns a 302 redirect to internal services (e.g., `http://169.254.169.254/` for cloud metadata)
        3. **Data Exfiltration**: The application follows the redirect, potentially exposing sensitive credentials

        While direct SSRF via token ID manipulation is mitigated by parameter encoding, this indirect path is highly exploitable in cloud/container environments.

        ## Required Security Fixes

        ### 1. Enable SSL Verification
        ```python
        # CRITICAL: Enable SSL verification
        _SSL_VERIFY = True  # Changed from False
        ```

        ### 2. Disable Redirect Following
        ```python
        resp = requests.get(
            # ... parameters ...
            verify=_SSL_VERIFY,
            allow_redirects=False  # Prevents redirect-based SSRF
        )
        ```

        ### 3. Add Token ID Validation
        ```python
        import re
        
        # Token ID pattern (64 hex chars with optional 0x prefix)
        _TOKEN_ID_RE = re.compile(r'^0x?[0-9a-fA-F]{1,128}$')
        
        def _validate_token_id(token_id: str) -> bool:
            """Validate token ID format before network requests."""
            if not token_id or not isinstance(token_id, str):
                return False
            if len(token_id) > 128:  # Prevent DoS
                return False
            return bool(_TOKEN_ID_RE.match(token_id))
        ```

        ### 4. Sanitize Log Output
        ```python
        def _sanitize_for_log(val: str) -> str:
            """Remove control characters to prevent log injection."""
            if not isinstance(val, str):
                return str(val)
            return val.replace('\n', '').replace('\r', '').replace('\t', '')[:128]
        ```

        ### 5. Configure Secure Session
        ```python
        # Create persistent session with security settings
        _session = requests.Session()
        _session.verify = _SSL_VERIFY
        _session.trust_env = False  # Ignore system proxy settings
        ```

        ## Complete Secure Implementation

        ```python
        ### FILE: clob.py ###
        import os
        import requests
        import re
        from typing import List, Dict, Optional
        from logger import get_logger
        
        log = get_logger("CLOB")
        
        CLOB_BASE = "https://clob.polymarket.com"
        DEFAULT_INTERVAL = "1d"
        DEFAULT_FIDELITY = 60
        
        # Security configuration
        _SSL_VERIFY = os.getenv("CLOB_SSL_VERIFY", "true").lower() == "true"
        _TOKEN_ID_RE = re.compile(r'^0x?[0-9a-fA-F]{1,128}$')
        
        # Secure session with hardened configuration
        _session = requests.Session()
        _session.verify = _SSL_VERIFY
        _session.trust_env = False
        _session.headers.update({"User-Agent": "PolySINT-Secure/1.0"})
        
        def _sanitize_for_log(val: str) -> str:
            """Sanitize values for safe logging."""
            if not isinstance(val, str):
                return str(val)
            return val.replace('\n', '').replace('\r', '').replace('\t', '')[:128]
        
        def _validate_token_id(token_id: Optional[str]) -> bool:
            """Validate token ID format."""
            if not token_id or not isinstance(token_id, str):
                return False
            if len(token_id) > 128:
                return False
            return bool(_TOKEN_ID_RE.match(token_id))
        
        def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, 
                             fidelity: int = DEFAULT_FIDELITY) -> Optional[List[Dict]]:
            """Fetch price history with SSRF protections."""
            # Input validation before network call
            if not _validate_token_id(clob_token_id):
                log.error(f"Invalid token ID format: {_sanitize_for_log(clob_token_id)}")
                return None
            
            try:
                resp = _session.get(
                    f"{CLOB_BASE}/prices-history",
                    params={
                        "market": clob_token_id,
                        "interval": interval,
                        "fidelity": fidelity,
                    },
                    timeout=10,
                    allow_redirects=False  # SSRF protection
                )
                
                if resp.status_code != 200:
                    log.warning(f"CLOB API error {resp.status_code} for token {_sanitize_for_log(clob_token_id)}")
                    return None
                
                data = resp.json()
                history = data.get("history", [])
                
                if not history:
                    return None
                
                return sorted(history, key=lambda x: x.get("t", 0))
                
            except requests.exceptions.SSLError as e:
                log.critical(f"SSL verification failed - potential MITM: {e}")
                return None
            except requests.exceptions.RequestException as e:
                log.error(f"Request failed: {e}")
                return None
            except Exception as e:
                log.error(f"Unexpected error: {e}")
                return None
        
        def get_shift(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> Optional[float]:
            """Calculate price shift with SSRF protections."""
            history = get_price_history(clob_token_id, interval=interval)
            
            if not history or len(history) < 2:
                return None
            
            try:
                price_then = float(history[0].get("p", 0))
                price_now = float(history[-1].get("p", 0))
                return price_now - price_then
            except (TypeError, ValueError) as e:
                log.warning(f"Non-numeric price data: {e}")
                return None
        
        def get_history_as_price_list(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> Optional[List[float]]:
            """Return flat price list with SSRF protections."""
            history = get_price_history(clob_token_id, interval=interval)
            if not history:
                return None
            
            try:
                return [float(h.get("p", 0)) for h in history]
            except (TypeError, ValueError) as e:
                log.warning(f"Error converting prices: {e}")
                return None
        ```

        ## Verification Checklist

        - [x] SSL verification enabled by default (`CLOB_SSL_VERIFY` env var available)
        - [x] Redirects disabled (`allow_redirects=False`)
        - [x] Token ID validation before network calls
        - [x] Log output sanitization
        - [x] System proxy settings ignored (`trust_env=False`)
        - [x] Persistent session for connection reuse
        - [x] Comprehensive error handling with specific SSL failure logging

        ## Additional Security Recommendations

        1. **Monitoring**: Alert on SSL verification failures to detect potential MITM attacks
        2. **Configuration**: Use environment variables for security settings (`CLOB_SSL_VERIFY`)
        3. **Testing**: Add unit tests for validation logic and error paths
        4. **Documentation**: Update security configuration documentation

        ## Future Maintainability Improvements

        For long-term maintainability, consider refactoring toward:
        - Single Responsibility Principle: Separate validation, HTTP client, and business logic
        - Dependency Injection: Abstract HTTP client for testability
        - Configuration Management: Centralized configuration with validation
        - Enhanced Testing: Unit tests for security controls and integration tests

        However, these are secondary to addressing the immediate critical SSRF vulnerability.
