```python
        """
        PolySINT API Security Audit Test Harness v4.0
        Comprehensive security testing with AST analysis, adversarial fuzzing, and CI/CD integration
        
        Combines the best elements from multiple analysis approaches:
        - Comprehensive payload generation (SQLi, XSS, SSRF, command injection, etc.)
        - Advanced AST-based static analysis
        - Adversarial simulation and logic flaw detection
        - OWASP Top 10 (2021) compliance mapping
        - Multiple report formats (text, JSON, HTML)
        - CI/CD ready with proper exit codes
        
        Usage:
          pytest security_audit.py -v                    # Run all tests
          python security_audit.py --full                # Complete audit with reports
          python security_audit.py --static              # Static analysis only
          python security_audit.py --dynamic             # Dynamic tests only
          python security_audit.py --ci                  # CI/CD mode (exit with code)
        """
        
        import pytest
        import json
        import re
        import ast
        import hashlib
        import threading
        import os
        import sys
        import random
        import string
        import time
        import math
        from typing import Dict, List, Optional, Any, Set, Tuple
        from dataclasses import dataclass, field, asdict
        from enum import Enum
        from pathlib import Path
        from datetime import datetime
        from unittest.mock import patch, MagicMock
        
        # FastAPI testing imports
        from fastapi.testclient import TestClient
        
        # Ensure imports work
        sys.path.insert(0, '.')
        try:
            from api import app, ADDRESS_RE, MARKET_ID_RE, MAX_SEARCH_LEN, MAX_LABEL_LEN
            from clob import _SSL_VERIFY
        except ImportError:
            pytest.skip("Application modules not found", allow_module_level=True)
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # CONFIGURATION & DATA STRUCTURES
        # ═══════════════════════════════════════════════════════════════════════════════
        
        class SecuritySeverity(Enum):
            """CVSS-based severity levels with scoring."""
            CRITICAL = ("CRITICAL", 9.0, 10.0, 30)
            HIGH = ("HIGH", 7.0, 8.9, 20)
            MEDIUM = ("MEDIUM", 4.0, 6.9, 10)
            LOW = ("LOW", 0.1, 3.9, 5)
            INFO = ("INFO", 0.0, 0.0, 1)
            
            @classmethod
            def from_cvss(cls, cvss_score: float) -> 'SecuritySeverity':
                """Determine severity from CVSS score."""
                for severity in cls:
                    label, min_cvss, max_cvss, deduction = severity.value
                    if min_cvss <= cvss_score <= max_cvss:
                        return severity
                return cls.INFO
        
        class OWASPCategory(Enum):
            """OWASP Top 10 (2021) with CWE mappings."""
            A01_BROKEN_ACCESS = ("A01:2021-Broken Access Control", "CWE-284")
            A02_CRYPTO_FAILURES = ("A02:2021-Cryptographic Failures", "CWE-310")
            A03_INJECTION = ("A03:2021-Injection", "CWE-74")
            A04_INSECURE_DESIGN = ("A04:2021-Insecure Design", "CWE-840")
            A05_SECURITY_MISCONFIG = ("A05:2021-Security Misconfiguration", "CWE-16")
            A06_VULN_COMPONENTS = ("A06:2021-Vulnerable and Outdated Components", "CWE-1104")
            A07_AUTH_FAILURES = ("A07:2021-Identification and Authentication Failures", "CWE-287")
            A08_DATA_INTEGRITY = ("A08:2021-Software and Data Integrity Failures", "CWE-345")
            A09_LOGGING_FAILURES = ("A09:2021-Security Logging and Monitoring Failures", "CWE-778")
            A10_SSRF = ("A10:2021-Server-Side Request Forgery", "CWE-918")
        
        @dataclass
        class SecurityFinding:
            """Structured security finding with CVSS scoring."""
            id: str
            severity: SecuritySeverity
            owasp_category: OWASPCategory
            title: str
            description: str
            location: str
            remediation: str
            evidence: Optional[str] = None
            cwe_id: Optional[str] = None
            cvss_score: Optional[float] = None
            timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
        
        @dataclass
        class AuditResult:
            """Container for audit results with scoring."""
            findings: List[SecurityFinding] = field(default_factory=list)
            security_score: int = 100
            audit_duration: float = 0.0
            timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
            
            def add_finding(self, finding: SecurityFinding):
                """Add finding and adjust security score."""
                self.findings.append(finding)
                _, _, _, deduction = finding.severity.value
                self.security_score = max(0, self.security_score - deduction)
        
        # Global audit result
        audit_result = AuditResult()
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # PAYLOAD GENERATORS
        # ═══════════════════════════════════════════════════════════════════════════════
        
        class PayloadGenerator:
            """Generate adversarial payloads for security testing."""
            
            SQLI_PAYLOADS = [
                "' OR '1'='1", "' OR '1'='1'--", "' OR '1'='1'/*",
                "admin'--", "admin' #", "' UNION SELECT NULL--",
                "' UNION SELECT NULL,NULL--", "1 UNION SELECT 1--",
                "' AND '1'='1", "' AND '1'='2", "1' AND 1=1--",
                "'; WAITFOR DELAY '0:0:5'--", "' OR SLEEP(5)--",
                "'; DROP TABLE users--", "1; DROP TABLE users--",
                "0x27204f52202731273d2731",  # Hex encoded
                "%27%20OR%20%271%27%3D%271",  # URL encoded
            ]
            
            XSS_PAYLOADS = [
                "<script>alert('XSS')</script>", "<script>alert(document.cookie)</script>",
                "<SCRIPT>alert('XSS')</SCRIPT>", "<scr<script>ipt>alert('XSS')</scr</script>ipt>",
                "<img src=x onerror=alert('XSS')>", "<svg onload=alert('XSS')>",
                "<body onload=alert('XSS')>", "<input onfocus=alert('XSS') autofocus>",
                "javascript:alert('XSS')", "javascript:alert(document.domain)",
                "data:text/html,<script>alert('XSS')</script>",
                "{{7*7}}", "${7*7}", "#{7*7}",
                "\"-alert(1)-\"", "' onmouseover=alert(1) '",
                "<div style=\"background-image: url(javascript:alert(1))\">",
            ]
            
            PATH_TRAVERSAL_PAYLOADS = [
                "../../etc/passwd", "..\\..\\windows\\system32\\config\\sam",
                "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "....//....//....//etc/passwd",
                "/etc/passwd", "..%c0%af..%c0%af..%c0%afetc/passwd",
                "../../../etc/passwd%00", "../../../etc/passwd%00.txt",
            ]
            
            SSRF_PAYLOADS = [
                "http://169.254.169.254/latest/meta-data/",
                "http://metadata.google.internal/computeMetadata/v1/",
                "http://127.0.0.1:22", "http://127.0.0.1:3306",
                "http://[::1]:22", "http://0x7f000001:22",
                "http://10.0.0.1/", "http://192.168.1.1/",
                "file:///etc/passwd", "gopher://localhost:6379/_INFO",
            ]
            
            COMMAND_INJECTION_PAYLOADS = [
                "; ls -la", "| cat /etc/passwd", "&& whoami", "|| id",
                "`whoami`", "$(whoami)", "& dir", "| dir",
                "\ncat /etc/passwd\n", "%0acat /etc/passwd%0a",
                "; sleep 5", "| sleep 5", "&& sleep 5",
            ]
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # AST-BASED STATIC ANALYSIS ENGINE
        # ═══════════════════════════════════════════════════════════════════════════════
        
        class ASTSecurityAnalyzer:
            """Advanced AST-based security analysis with pattern matching."""
            
            def __init__(self, project_root: str = "."):
                self.project_root = Path(project_root)
                self.findings: List[SecurityFinding] = []
                self.ast_cache = {}
            
            def analyze(self) -> List[SecurityFinding]:
                """Run comprehensive AST-based analysis."""
                checks = [
                    self._check_sql_injection,
                    self._check_ssl_verification,
                    self._check_hardcoded_secrets,
                    self._check_input_validation,
                    self._check_ssrf_vectors,
                    self._check_command_injection,
                    self._check_path_traversal,
                    self._check_prompt_injection,
                    self._check_logic_flaws,
                ]
                
                for check in checks:
                    try:
                        check()
                    except Exception as e:
                        print(f"Warning: Analysis {check.__name__} failed: {e}")
                
                return self.findings
            
            def _check_sql_injection(self):
                """Detect SQL injection patterns using AST."""
                for file_path in self.project_root.glob("*.py"):
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        tree = ast.parse(content, filename=str(file_path))
                        
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                                if node.func.attr == 'execute':
                                    for arg in node.args:
                                        if isinstance(arg, ast.JoinedStr) or \
                                           (isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod)):
                                            self.findings.append(SecurityFinding(
                                                id=self._generate_id("SQL_INJECTION"),
                                                severity=SecuritySeverity.CRITICAL,
                                                owasp_category=OWASPCategory.A03_INJECTION,
                                                title="SQL Injection via String Formatting",
                                                description=f"SQL query uses string formatting in {file_path.name}:{node.lineno}",
                                                location=f"{file_path.name}:{node.lineno}",
                                                remediation="Use parameterized queries with '?' placeholders",
                                                cwe_id="CWE-89",
                                                cvss_score=9.8,
                                                evidence=f"AST node: {type(arg).__name__}"
                                            ))
                    except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
                        pass
            
            def _check_ssl_verification(self):
                """Check for disabled SSL verification."""
                for file_path in self.project_root.glob("*.py"):
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        if '_SSL_VERIFY = False' in content or 'verify=False' in content:
                            self.findings.append(SecurityFinding(
                                id=self._generate_id("SSL_DISABLED"),
                                severity=SecuritySeverity.HIGH,
                                owasp_category=OWASPCategory.A02_CRYPTO_FAILURES,
                                title="SSL Verification Disabled",
                                description=f"SSL verification disabled in {file_path.name}",
                                location=str(file_path.name),
                                remediation="Enable SSL verification or implement certificate pinning",
                                cwe_id="CWE-295",
                                cvss_score=7.4,
                                evidence="Found 'verify=False' or '_SSL_VERIFY = False'"
                            ))
                    except (FileNotFoundError, PermissionError):
                        pass
            
            def _check_hardcoded_secrets(self):
                """Scan for hardcoded credentials with entropy analysis."""
                def calculate_entropy(s: str) -> float:
                    if not s:
                        return 0.0
                    entropy = 0.0
                    for char in set(s):
                        p_x = s.count(char) / len(s)
                        if p_x > 0:
                            entropy += -p_x * math.log2(p_x)
                    return entropy
                
                secret_patterns = [
                    (r'(?i)api_key\s*=\s*["\']([a-zA-Z0-9]{32,})["\']', "API Key", 9.0),
                    (r'(?i)secret\s*=\s*["\']([^"\']{8,})["\']', "Secret", 9.5),
                    (r'(?i)password\s*=\s*["\']([^"\']{4,})["\']', "Password", 8.5),
                ]
                
                for file_path in self.project_root.glob("*.py"):
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        for pattern, secret_type, cvss in secret_patterns:
                            matches = re.finditer(pattern, content)
                            for match in matches:
                                secret_value = match.group(1) if match.groups() else match.group(0)
                                
                                # Skip placeholders
                                if any(p in secret_value.lower() for p in ['your_', 'test_', 'example', 'xxx']):
                                    continue
                                
                                entropy = calculate_entropy(secret_value)
                                if entropy > 3.5:  # High entropy suggests real secret
                                    self.findings.append(SecurityFinding(
                                        id=self._generate_id("HARDCODED_SECRET"),
                                        severity=SecuritySeverity.CRITICAL,
                                        owasp_category=OWASPCategory.A02_CRYPTO_FAILURES,
                                        title=f"Hardcoded {secret_type}",
                                        description=f"Potential hardcoded {secret_type} in {file_path.name}",
                                        location=str(file_path.name),
                                        remediation="Move secrets to environment variables or secure vault",
                                        cwe_id="CWE-798",
                                        cvss_score=cvss,
                                        evidence=f"Entropy: {entropy:.2f}"
                                    ))
                    except Exception:
                        continue
            
            def _check_input_validation(self):
                """Verify input validation patterns."""
                api_file = self.project_root / "api.py"
                if not api_file.exists():
                    return
                
                content = api_file.read_text(encoding='utf-8')
                required_validators = {
                    'ADDRESS_RE': ('Ethereum address regex', SecuritySeverity.MEDIUM),
                    'MARKET_ID_RE': ('Market ID regex', SecuritySeverity.MEDIUM),
                    'MAX_SEARCH_LEN': ('Search input length limit', SecuritySeverity.MEDIUM),
                    'MAX_LABEL_LEN': ('Label input length limit', SecuritySeverity.MEDIUM),
                }
                
                for validator, (description, severity) in required_validators.items():
                    if validator not in content:
                        self.findings.append(SecurityFinding(
                            id=self._generate_id("MISSING_VALIDATION"),
                            severity=severity,
                            owasp_category=OWASPCategory.A03_INJECTION,
                            title=f"Missing Input Validation: {validator}",
                            description=f"{description} not found in api.py",
                            location="api.py",
                            remediation=f"Define and enforce {validator}",
                            cwe_id="CWE-20"
                        ))
            
            def _check_ssrf_vectors(self):
                """Check for SSRF vulnerabilities in external API calls."""
                researcher_file = self.project_root / "researcher.py"
                if not researcher_file.exists():
                    return
                
                content = researcher_file.read_text(encoding='utf-8')
                if 'market_question' in content and 'tavily' in content.lower():
                    if not re.search(r'(?:validate|sanitize|clean).*market_question', content, re.IGNORECASE):
                        self.findings.append(SecurityFinding(
                            id=self._generate_id("SSRF_RISK"),
                            severity=SecuritySeverity.MEDIUM,
                            owasp_category=OWASPCategory.A10_SSRF,
                            title="Potential SSRF via Researcher",
                            description="Market questions passed to external API without validation",
                            location="researcher.py",
                            remediation="Validate and sanitize market_question before external API calls",
                            cwe_id="CWE-918",
                            cvss_score=6.5
                        ))
            
            def _check_command_injection(self):
                """Detect command injection vulnerabilities."""
                dangerous_calls = [
                    ('subprocess', ['call', 'run', 'Popen', 'check_output']),
                    ('os', ['system', 'popen']),
                ]
                
                for file_path in self.project_root.glob("*.py"):
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        tree = ast.parse(content, filename=str(file_path))
                        
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Call):
                                if isinstance(node.func, ast.Attribute):
                                    if isinstance(node.func.value, ast.Name):
                                        module_name = node.func.value.id
                                        func_name = node.func.attr
                                        
                                        for dangerous_module, funcs in dangerous_calls:
                                            if module_name == dangerous_module and func_name in funcs:
                                                if node.args and self._is_user_controlled(node.args[0]):
                                                    self.findings.append(SecurityFinding(
                                                        id=self._generate_id("COMMAND_INJECTION"),
                                                        severity=SecuritySeverity.CRITICAL,
                                                        owasp_category=OWASPCategory.A03_INJECTION,
                                                        title="Command Injection Vulnerability",
                                                        description=f"User input in {module_name}.{func_name} at {file_path.name}:{node.lineno}",
                                                        location=f"{file_path.name}:{node.lineno}",
                                                        remediation="Use subprocess with list arguments and validate inputs",
                                                        cwe_id="CWE-78",
                                                        cvss_score=9.8
                                                    ))
                    except (SyntaxError, UnicodeDecodeError):
                        pass
            
            def _check_path_traversal(self):
                """Detect path traversal vulnerabilities."""
                for file_path in self.project_root.glob("*.py"):
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        tree = ast.parse(content, filename=str(file_path))
                        
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Call):
                                if isinstance(node.func, ast.Attribute):
                                    dangerous_methods = ['open', 'read', 'write', 'read_text', 'write_text']
                                    if node.func.attr in dangerous_methods:
                                        if node.args and self._is_user_controlled(node.args[0]):
                                            self.findings.append(SecurityFinding(
                                                id=self._generate_id("PATH_TRAVERSAL"),
                                                severity=SecuritySeverity.HIGH,
                                                owasp_category=OWASPCategory.A01_BROKEN_ACCESS,
                                                title="Path Traversal Vulnerability",
                                                description=f"User-controlled file path in {node.func.attr} at {file_path.name}:{node.lineno}",
                                                location=f"{file_path.name}:{node.lineno}",
                                                remediation="Use os.path.basename() and validate paths",
                                                cwe_id="CWE-22",
                                                cvss_score=7.5
                                            ))
                    except (SyntaxError, UnicodeDecodeError):
                        pass
            
            def _check_prompt_injection(self):
                """Check for prompt injection vulnerabilities in LLM analyst."""
                analyst_file = self.project_root / "analyst.py"
                if not analyst_file.exists():
                    return
                
                content = analyst_file.read_text(encoding='utf-8')
                if 'market_question' in content and ('f"""' in content or 'f"' in content):
                    if not re.search(r'(?:sanitize|escape|clean).*market_question', content, re.IGNORECASE):
                        self.findings.append(SecurityFinding(
                            id=self._generate_id("PROMPT_INJECTION"),
                            severity=SecuritySeverity.MEDIUM,
                            owasp_category=OWASPCategory.A03_INJECTION,
                            title="Potential LLM Prompt Injection",
                            description="Market questions directly interpolated into LLM prompts without sanitization",
                            location="analyst.py",
                            remediation="Sanitize market_question to remove prompt-breaking syntax",
                            cwe_id="CWE-94",
                            cvss_score=6.5
                        ))
            
            def _check_logic_flaws(self):
                """Check for business logic flaws."""
                api_file = self.project_root / "api.py"
                if not api_file.exists():
                    return
                
                content = api_file.read_text(encoding='utf-8')
                
                # Check for enrichment DOS vulnerability
                if "enriched[:limit]" in content and "candidates" in content:
                    # Check if enrichment happens before slicing
                    if "ThreadPoolExecutor" in content and "candidates" in content:
                        self.findings.append(SecurityFinding(
                            id=self._generate_id("LOGIC_FLAW"),
                            severity=SecuritySeverity.MEDIUM,
                            owasp_category=OWASPCategory.A04_INSECURE_DESIGN,
                            title="Resource Exhaustion via Enrichment",
                            description="Search endpoint enriches all candidates before slicing results",
                            location="api.py:search_markets",
                            remediation="Apply limit/offset in SQL query BEFORE enrichment",
                            cvss_score=5.3
                        ))
            
            def _is_user_controlled(self, node: ast.AST) -> bool:
                """Heuristic to determine if a node contains user-controlled data."""
                if isinstance(node, ast.Name):
                    user_input_names = ['request', 'req', 'input', 'data', 'params', 'args']
                    return node.id.lower() in user_input_names
                
                if isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name):
                        if node.value.id.lower() in ['request', 'req']:
                            user_attrs = ['args', 'form', 'json', 'data', 'params', 'files']
                            return node.attr.lower() in user_attrs
                
                return False
            
            def _generate_id(self, prefix: str) -> str:
                """Generate a unique finding ID."""
                return f"{prefix}-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8].upper()}"
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # PYTEST FIXTURES
        # ═══════════════════════════════════════════════════════════════════════════════
        
        @pytest.fixture(scope="session")
        def client():
            """FastAPI test client with mocked external services."""
            with patch('clob.get_price_history') as mock_history, \
                 patch('clob.get_shift') as mock_shift, \
                 patch('requests.get') as mock_requests_get, \
                 patch('requests.post') as mock_requests_post:
                
                mock_history.return_value = [{"t": 1234567890, "p": "0.5"}]
                mock_shift.return_value = 0.12
                mock_requests_get.return_value.status_code = 200
                mock_requests_get.return_value.json.return_value = {"history": []}
                mock_requests_post.return_value.status_code = 200
                
                yield TestClient(app)
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # DYNAMIC SECURITY TESTS
        # ═══════════════════════════════════════════════════════════════════════════════
        
        @pytest.mark.dynamic
        @pytest.mark.security
        class TestSQLInjection:
            """SQL injection prevention tests."""
            
            @pytest.mark.parametrize("payload", PayloadGenerator.SQLI_PAYLOADS[:6])
            def test_search_sql_injection(self, client, payload):
                """Test SQL injection in search parameter."""
                response = client.get(f"/markets?search={payload}")
                assert response.status_code != 500, f"Server error with SQLi payload: {payload[:30]}..."
                
                response_lower = response.text.lower()
                sql_errors = ['sql', 'syntax error', 'sqlite', 'mysql', 'postgresql']
                for error in sql_errors:
                    assert error not in response_lower, f"SQL error exposed for: {payload[:30]}..."
        
        @pytest.mark.dynamic
        @pytest.mark.security
        class TestXSSPrevention:
            """Cross-site scripting prevention tests."""
            
            @pytest.mark.parametrize("payload", PayloadGenerator.XSS_PAYLOADS[:6])
            def test_search_xss(self, client, payload):
                """Test XSS in search parameter."""
                import urllib.parse
                encoded = urllib.parse.quote(payload)
                response = client.get(f"/markets?search={encoded}")
                
                if response.status_code == 200:
                    assert "<script>" not in response.text, f"XSS payload not encoded: {payload[:30]}..."
                    assert "onerror=" not in response.text.lower(), f"Event handler not encoded: {payload[:30]}..."
        
        @pytest.mark.dynamic
        @pytest.mark.security
        class TestInputValidation:
            """Input validation and sanitization tests."""
            
            @pytest.mark.parametrize("address", [
                "0x123",  # Too short
                "0x" + "g" * 40,  # Invalid hex
                "1x" + "0" * 40,  # Wrong prefix
                "",  # Empty
                "0x" + "0" * 41,  # Too long
            ])
            def test_ethereum_address_validation(self, client, address):
                """Test Ethereum address validation."""
                response = client.get(f"/wallets/{address}/unmask")
                assert response.status_code == 400, f"Invalid address not rejected: {address}"
            
            @pytest.mark.parametrize("market_id", [
                "abc",  # Non-numeric
                "123abc",  # Mixed
                "12.34",  # Decimal
                "-123",  # Negative
                "0" * 100,  # Too long
            ])
            def test_market_id_validation(self, client, market_id):
                """Test market ID validation."""
                response = client.get(f"/markets/{market_id}/ai-analysis")
                assert response.status_code == 400, f"Invalid market ID not rejected: {market_id}"
            
            def test_oversized_inputs(self, client):
                """Test input length restrictions."""
                long_search = "A" * (MAX_SEARCH_LEN + 100)
                response = client.get(f"/markets?search={long_search}")
                assert response.status_code == 400, "Oversized search not rejected"
                
                long_label = "B" * (MAX_LABEL_LEN + 100)
                test_address = "0x" + "0" * 40
                response = client.post("/watchlist", json={
                    "address": test_address,
                    "label": long_label
                })
                assert response.status_code == 422, "Oversized label not rejected"
        
        @pytest.mark.dynamic
        @pytest.mark.security
        class TestBusinessLogic:
            """Business logic and race condition tests."""
            
            def test_duplicate_prevention(self, client):
                """Test duplicate watchlist entries are prevented."""
                test_addr = "0x" + "a" * 40
                response1 = client.post("/watchlist", json={"address": test_addr, "label": "First"})
                response2 = client.post("/watchlist", json={"address": test_addr, "label": "Second"})
                assert response2.status_code == 400, "Duplicate entries allowed"
                client.delete(f"/watchlist/{test_addr}")
            
            def test_race_condition_resistance(self, client):
                """Test for race conditions in concurrent writes."""
                test_addr = "0x" + "b" * 40
                results = []
                
                def add_target():
                    try:
                        resp = client.post("/watchlist", json={
                            "address": test_addr,
                            "label": f"Thread-{threading.get_ident()}"
                        })
                        results.append(resp.status_code)
                    except:
                        results.append(500)
                
                threads = [threading.Thread(target=add_target) for _ in range(10)]
                [t.start() for t in threads]
                [t.join() for t in threads]
                
                success_count = results.count(200)
                assert success_count <= 1, f"Race condition: {success_count} concurrent successes"
                
                client.delete(f"/watchlist/{test_addr}")
        
        @pytest.mark.dynamic
        @pytest.mark.security
        class TestAuthentication:
            """Authentication and authorization tests."""
            
            def test_missing_authentication(self, client):
                """Test that endpoints require authentication."""
                endpoints = [
                    ("GET", "/markets"),
                    ("POST", "/watchlist"),
                    ("DELETE", "/watchlist/0x123"),
                    ("GET", "/wallets/0x123/unmask"),
                ]
                
                for method, endpoint in endpoints:
                    if method == "GET":
                        response = client.get(endpoint)
                    elif method == "POST":
                        response = client.post(endpoint, json={})
                    elif method == "DELETE":
                        response = client.delete(endpoint)
                    
                    if response.status_code not in [401, 403]:
                        audit_result.add_finding(SecurityFinding(
                            id=f"NO_AUTH-{endpoint.replace('/', '_')}",
                            severity=SecuritySeverity.HIGH,
                            owasp_category=OWASPCategory.A01_BROKEN_ACCESS,
                            title="Missing Authentication",
                            description=f"{method} {endpoint} accessible without authentication",
                            location=f"{method} {endpoint}",
                            remediation="Implement JWT or API key authentication",
                            cwe_id="CWE-306",
                            cvss_score=8.1
                        ))
        
        @pytest.mark.dynamic
        @pytest.mark.security
        class TestRateLimiting:
            """Rate limiting and DoS protection tests."""
            
            def test_rate_limiting_absent(self, client):
                """Test for missing rate limiting."""
                responses = []
                for i in range(50):
                    response = client.get("/markets")
                    responses.append(response.status_code)
                
                if 429 not in responses:
                    audit_result.add_finding(SecurityFinding(
                        id="NO_RATE_LIMITING",
                        severity=SecuritySeverity.MEDIUM,
                        owasp_category=OWASPCategory.A04_INSECURE_DESIGN,
                        title="Missing Rate Limiting",
                        description="No rate limiting detected on API endpoints",
                        location="All endpoints",
                        remediation="Implement rate limiting (e.g., 100 requests/minute)",
                        cwe_id="CWE-770",
                        cvss_score=5.3
                    ))
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # OWASP COMPLIANCE & REPORTING
        # ═══════════════════════════════════════════════════════════════════════════════
        
        class OWASPComplianceReporter:
            """Generate OWASP Top 10 compliance reports."""
            
            def __init__(self, findings: List[SecurityFinding]):
                self.findings = findings
            
            def generate_report(self) -> Dict[str, Any]:
                """Generate comprehensive compliance report."""
                report = {
                    "summary": {
                        "total_findings": len(self.findings),
                        "by_severity": {},
                        "owasp_compliance": {}
                    },
                    "recommendations": []
                }
                
                # Count by severity
                for severity in SecuritySeverity:
                    count = sum(1 for f in self.findings if f.severity == severity)
                    report["summary"]["by_severity"][severity.value[0]] = count
                
                # OWASP compliance
                for category in OWASPCategory:
                    findings_in_cat = [f for f in self.findings if f.owasp_category == category]
                    report["summary"]["owasp_compliance"][category.value[0]] = {
                        "status": "FAIL" if findings_in_cat else "PASS",
                        "findings_count": len(findings_in_cat)
                    }
                
                # Prioritized recommendations
                critical_findings = [f for f in self.findings 
                                   if f.severity in [SecuritySeverity.CRITICAL, SecuritySeverity.HIGH]]
                critical_findings.sort(key=lambda x: x.cvss_score or 0, reverse=True)
                
                for finding in critical_findings[:10]:
                    report["recommendations"].append({
                        "priority": "IMMEDIATE" if finding.severity == SecuritySeverity.CRITICAL else "HIGH",
                        "title": finding.title,
                        "remediation": finding.remediation,
                        "cvss": finding.cvss_score
                    })
                
                return report
        
        class ReportGenerator:
            """Generate audit reports in multiple formats."""
            
            def __init__(self, result: AuditResult):
                self.result = result
            
            def generate_text_report(self) -> str:
                """Generate human-readable text report."""
                lines = [
                    "=" * 80,
                    "POLYSINT API SECURITY AUDIT REPORT",
                    "=" * 80,
                    f"Timestamp: {self.result.timestamp}",
                    f"Security Score: {self.result.security_score}/100",
                    f"Total Findings: {len(self.result.findings)}",
                    "",
                    "SEVERITY BREAKDOWN:",
                    "-" * 40
                ]
                
                for severity in SecuritySeverity:
                    count = sum(1 for f in self.result.findings if f.severity == severity)
                    bar = "█" * count + "░" * (20 - min(count, 20))
                    lines.append(f"  {severity.value[0]:8s} [{bar}] {count}")
                
                lines.extend(["", "DETAILED FINDINGS:", "-" * 40])
                
                for severity in [SecuritySeverity.CRITICAL, SecuritySeverity.HIGH,
                                SecuritySeverity.MEDIUM, SecuritySeverity.LOW, SecuritySeverity.INFO]:
                    findings = [f for f in self.result.findings if f.severity == severity]
                    if findings:
                        lines.extend([
                            "",
                            f"{'='*60}",
                            f"{severity.value[0]} FINDINGS ({len(findings)})",
                            f"{'='*60}"
                        ])
                        for i, finding in enumerate(findings, 1):
                            lines.extend([
                                "",
                                f"  [{i}] {finding.title}",
                                f"      OWASP: {finding.owasp_category.value[0]}",
                                f"      Location: {finding.location}",
                                f"      CWE: {finding.cwe_id or 'N/A'}",
                                f"      CVSS: {finding.cvss_score:.1f}" if finding.cvss_score else "",
                                f"      Description: {finding.description}",
                                f"      Remediation: {finding.remediation}",
                            ])
                
                return "\n".join(lines)
            
            def generate_json_report(self) -> Dict[str, Any]:
                """Generate machine-readable JSON report."""
                return {
                    "metadata": {
                        "timestamp": self.result.timestamp,
                        "security_score": self.result.security_score,
                        "total_findings": len(self.result.findings)
                    },
                    "findings": [asdict(f) for f in self.result.findings]
                }
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # MAIN AUDIT RUNNER
        # ═══════════════════════════════════════════════════════════════════════════════
        
        def run_security_audit(static_only: bool = False, dynamic_only: bool = False) -> AuditResult:
            """Run complete security audit."""
            print("🛡️  Starting PolySINT API Security Audit...")
            print("=" * 60)
            
            start_time = time.time()
            
            if not dynamic_only:
                # Static analysis
                print("\n1. STATIC ANALYSIS")
                print("-" * 40)
                analyzer = ASTSecurityAnalyzer()
                static_findings = analyzer.analyze()
                for finding in static_findings:
                    audit_result.add_finding(finding)
                print(f"   Found {len(static_findings)} static issues.")
            
            if not static_only:
                # Dynamic tests via pytest
                print("\n2. DYNAMIC TESTING")
                print("-" * 40)
                import pytest
                pytest.main(["-v", "--tb=short", "-p", "no:warnings", __file__])
            
            # Generate reports
            print("\n3. GENERATING REPORTS")
            print("-" * 40)
            
            audit_result.audit_duration = time.time() - start_time
            
            report_generator = ReportGenerator(audit_result)
            
            # Text report
            text_report = report_generator.generate_text_report()
            with open("security_audit_report.txt", "w", encoding='utf-8') as f:
                f.write(text_report)
            
            # JSON report
            json_report = report_generator.generate_json_report()
            with open("security_audit_report.json", "w", encoding='utf-8') as f:
                json.dump(json_report, f, indent=2, ensure_ascii=False)
            
            # Print summary
            print(f"\n✅ Audit complete!")
            print(f"📊 Security Score: {audit_result.security_score}/100")
            print(f"⏱️  Duration: {audit_result.audit_duration:.2f} seconds")
            print(f"📝 Reports saved to:")
            print(f"   - security_audit_report.txt")
            print(f"   - security_audit_report.json")
            
            # Print critical findings
            critical_findings = [f for f in audit_result.findings if f.severity == SecuritySeverity.CRITICAL]
            if critical_findings:
                print(f"\n🚨 CRITICAL FINDINGS:")
                for i, finding in enumerate(critical_findings[:3], 1):
                    print(f"   {i}. {finding.title}")
                    print(f"      Location: {finding.location}")
            
            return audit_result
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # CLI INTERFACE
        # ═══════════════════════════════════════════════════════════════════════════════
        
        if __name__ == "__main__":
            import argparse
            
            parser = argparse.ArgumentParser(
                description="PolySINT API Security Audit Tool",
                formatter_class=argparse.RawDescriptionHelpFormatter,
                epilog="""
Examples:
  python security_audit.py --full           # Complete audit with reports
  python security_audit.py --static         # AST static analysis only
  python security_audit.py --dynamic        # Dynamic tests only
  python security_audit.py --ci             # CI/CD mode (exit with code)
                """
            )
            
            parser.add_argument("--full", action="store_true", help="Run complete audit")
            parser.add_argument("--static", action="store_true", help="Static analysis only")
            parser.add_argument("--dynamic", action="store_true", help="Dynamic tests only")
            parser.add_argument("--ci", action="store_true", help="CI/CD integration mode")
            parser.add_argument("--output", type=str, help="Output file for JSON report")
            
            args = parser.parse_args()
            
            if args.full or (not args.static and not args.dynamic and not args.ci):
                result = run_security_audit()
                
                if args.output:
                    with open(args.output, 'w') as f:
                        json.dump(asdict(result), f, indent=2)
                
                # Exit with appropriate code for CI/CD
                if args.ci:
                    critical_count = sum(1 for f in result.findings 
                                       if f.severity in [SecuritySeverity.CRITICAL, SecuritySeverity.HIGH])
                    sys.exit(1 if critical_count > 0 else 0)
            
            elif args.static:
                analyzer = ASTSecurityAnalyzer()
                findings = analyzer.analyze()
                print(f"\n🔍 Static analysis complete. Found {len(findings)} issues.")
            
            elif args.dynamic:
                import pytest
                pytest.main(["-v", __file__])
            
            else:
                parser.print_help()
        ```
