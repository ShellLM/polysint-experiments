[36m[i] LLM Safety Audit...[0m [31mREJECTED[0m
[31mREASON:[0m Dangerous – it overwrites existing files such as static/app.js and static/index.html (and potentially other modules) without any backup or confirmation, which can irreversibly destroy existing project data.
[31m[!] Human rejected or timeout[0m
[33m[!] Attempting to heal command...[0m
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 4: Please: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 6: **Safe: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 7: 1.: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 8: 2.: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 9: *.new: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 9: *.v2: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 9: 3.: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 10: 4.: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 11: 5.: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 13: Could: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 14: 1.: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 15: static/app.js: No such file or directory
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 15: static/index.html: No such file or directory
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 15: 2.: command not found
/tmp/ai_code_7bb5704b-160e-4951-be60-9dfeef72aae9.sh: line 17: With: command not found
[35mEXIT CODE:[0m 127
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
total 56
drwxr-xr-x 1 thomas thomas   202 Mar 15 11:41 .
drwxr-xr-x 1 thomas thomas  3606 Mar 15 04:23 ..
-rw-r--r-- 1 thomas thomas  5278 Mar 15 11:41 clob.py
-rw-r--r-- 1 thomas thomas  1037 Mar 15 02:41 experiment_run.log
drwxr-xr-x 1 thomas thomas  3100 Mar 15 12:12 results
-rw-r--r-- 1 thomas thomas     7 Mar 15 02:37 run.pid
-rwxr-xr-x 1 thomas thomas 12843 Mar 15 02:35 run_polysint_100.sh
-rw-r--r-- 1 thomas thomas 13414 Mar 15 11:12 test_output.md
-rwxr-xr-x 1 thomas thomas  1345 Mar 15 02:36 test_runner.sh
-rw-r--r-- 1 thomas thomas  3916 Mar 15 12:12 test_single.log
/home/thomas/ai/experiments/polysint_100
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
.
./results
# PolySINT Security Audit & Authentication Implementation

        ## Critical Finding
        The `api.py` file implements **zero authentication mechanisms** on any endpoint, representing a severe security vulnerability that exposes the entire system to:
        - Financial abuse via unlimited LLM/Tavily API calls
        - Data manipulation through unauthorized watchlist operations
        - Information disclosure of surveillance targets
        - Service degradation through resource exhaustion

        ## Recommended Authentication Implementation

        ### 1. Backend Authentication Module (`auth.py`)
        ```python
        import secrets
        from datetime import datetime, timedelta
        from collections import defaultdict, deque
        from fastapi import Security, HTTPException, status, Request, Depends
        from fastapi.security import APIKeyHeader
        from slowapi import Limiter
        from slowapi.util import get_remote_address
        from logger import get_logger
        from config import Config

        log = get_logger("Auth")
        
        # Rate limiter with proxy-aware IP extraction
        def get_real_ip(request: Request) -> str:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return request.client.host if request.client else "unknown"

        limiter = Limiter(key_func=get_real_ip)

        # Security headers
        API_KEY_NAME = "X-API-Key"
        ADMIN_API_KEY_NAME = "X-Admin-Key"
        api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
        admin_key_header = APIKeyHeader(name=ADMIN_API_KEY_NAME, auto_error=False)

        # Security monitor for tracking failed attempts
        class SecurityMonitor:
            def __init__(self):
                self.failed_attempts = defaultdict(deque)
                self.alert_threshold = 5
                self.window_minutes = 60
                
            def log_failed_auth(self, ip: str, endpoint: str):
                now = datetime.now()
                self.failed_attempts[ip].append((now, endpoint))
                
                # Clean old entries
                cutoff = now - timedelta(minutes=self.window_minutes)
                self.failed_attempts[ip] = deque(
                    [(t, e) for t, e in self.failed_attempts[ip] if t > cutoff],
                    maxlen=100
                )
                
                # Alert on threshold breach
                if len(self.failed_attempts[ip]) >= self.alert_threshold:
                    from notifier import Notifier
                    notifier = Notifier()
                    notifier.broadcast(
                        f"**{len(self.failed_attempts[ip])} failed auth attempts** from `{ip}`\n"
                        f"Endpoints: {', '.join(set(e for _, e in self.failed_attempts[ip]))}",
                        title="⚠️ Security Alert"
                    )

        security_monitor = SecurityMonitor()

        # Authentication dependencies
        async def verify_api_key(request: Request, api_key: str = Security(api_key_header)) -> str:
            if not api_key:
                security_monitor.log_failed_auth(get_real_ip(request), request.url.path)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing API Key"
                )
            
            if not secrets.compare_digest(api_key, Config.API_KEY):
                security_monitor.log_failed_auth(get_real_ip(request), request.url.path)
                log.warning(f"Invalid API key from {get_real_ip(request)}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API Key"
                )
            
            return api_key

        async def verify_admin_key(request: Request, admin_key: str = Security(admin_key_header)) -> str:
            if not admin_key:
                security_monitor.log_failed_auth(get_real_ip(request), request.url.path)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin Key Required"
                )
            
            if not secrets.compare_digest(admin_key, Config.ADMIN_API_KEY):
                security_monitor.log_failed_auth(get_real_ip(request), request.url.path)
                raise HTTPException(
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
total 644
-rw-r--r-- 1 thomas thomas      0 Mar 11 04:34 -
drwxr-xr-x 1 thomas thomas   3612 Mar 15 02:38 .
drwxr-xr-x 1 thomas thomas   2774 Feb 21 18:24 ..
-rw-r--r-- 1 thomas thomas      0 Mar 12 22:58 ...
drwxr-xr-x 1 thomas thomas    194 Mar 14 14:21 activity_journal
-rwxr-xr-x 1 thomas thomas   2327 Mar 14 01:02 activity_journal_control.sh
-rwxr-xr-x 1 thomas thomas   4715 Mar 14 13:04 activity_journal_daemon.sh
-rw-r--r-- 1 thomas thomas    801 Mar 14 01:06 ACTIVITY_JOURNAL_GUIDE.md
-rwxr-xr-x 1 thomas thomas   1999 Mar 14 01:35 activity_journal.sh
-rwxr-xr-x 1 thomas thomas   1051 Mar 14 01:06 activity_journal_stop.sh
drwxr-xr-x 1 thomas thomas     44 Mar 11 04:49 .agent8
-rwxr-xr-x 1 thomas thomas    341 Mar 10 16:34 agent8_pre_fix.sh
-rwxr-xr-x 1 thomas thomas   3412 Mar 11 04:34 agent8.sh
-rwxr-xr-x 1 thomas thomas    935 Mar 14 19:49 agent8-stateless.sh
drwxr-xr-x 1 thomas thomas     76 Mar 11 15:18 agent8_v8.1
drwxr-xr-x 1 thomas thomas    388 Mar 14 04:19 agora-marketplace
-rw-r--r-- 1 thomas thomas   5358 Mar 12 23:15 ai_hooks.sh
-rw-r--r-- 1 thomas thomas   4694 Mar  9 15:07 ai_hooks.sh.bak
-rw-r--r-- 1 thomas thomas   4694 Mar  9 15:09 ai_hooks.sh.bak.20260309
-rw-r--r-- 1 thomas thomas   5130 Mar  9 20:14 ai_hooks.sh.bak.20260309_201410
-rwxr-xr-x 1 thomas thomas   9738 Mar 14 13:04 ai_tools.sh
-rwxr-xr-x 1 thomas thomas   8313 Mar 10 16:27 ai_tools.sh.bak
-rw-r--r-- 1 thomas thomas   8383 Mar 10 16:33 ai_tools.sh.bak2
-rwxr-xr-x 1 thomas thomas   9707 Mar 14 13:04 ai_tools.sh.bak.20260314
-rw-r--r-- 1 thomas thomas   8520 Mar 10 16:54 ai_tools.sh.bak3
-rw-r--r-- 1 thomas thomas   8645 Mar 10 16:57 ai_tools.sh.bak4
-rw-r--r-- 1 thomas thomas    125 Mar 11 05:04 aliases.sh
-rwxr-xr-x 1 thomas thomas    500 Mar 11 04:50 backup_important.sh
drwxr-xr-x 1 thomas thomas    158 Mar 11 04:58 backups
        # Exception handlers
        @app.exception_handler(RateLimitExceeded)
        async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded: {str(exc)}"}
            )

        # Public endpoints
        @app.get("/")
        def serve_dashboard():
            return FileResponse("static/index.html")

        @app.get("/health")
        def health_check():
            return {"status": "healthy", "auth_enabled": bool(Config.API_KEY)}

        # Protected endpoints - Read operations
        @app.get("/markets", dependencies=[Depends(verify_api_key)])
        @limiter.limit(Config.DEFAULT_RATE_LIMIT)
        def search_markets(request: Request, ...):
            # Existing logic with input validation
            if search and len(search) > 200:
                raise HTTPException(status_code=400, detail="Search query too long")
            # ...

        @app.get("/markets/{market_id}/ai-analysis", dependencies=[Depends(verify_api_key)])
        @limiter.limit(Config.AI_ANALYSIS_RATE_LIMIT)
        def get_ai_analysis(request: Request, ...):
            # Prompt injection protection - XML isolation
            safe_question = market_question.replace("</user_input>", "")
            # Use isolated prompt structure
            # ...

        # Protected endpoints - Write operations (Admin key required)
        @app.post("/watchlist", dependencies=[Depends(verify_admin_key)])
        @limiter.limit(Config.WRITE_RATE_LIMIT)
        def add_to_watchlist(request: Request, ...):
            # Existing logic with validation
            # ...

        @app.delete("/watchlist/{address}", dependencies=[Depends(verify_admin_key)])
        def remove_from_watchlist(request: Request, ...):
            # Existing logic
            # ...
        ```

        ### 4. Enhanced Analyst with Input Sanitization (`analyst.py`)
        ```python
        def sanitize_for_prompt(text: str, max_length: int = 500) -> str:
            """Sanitize text to prevent prompt injection attacks."""
            if not text:
                return ""
            
            # Truncate to prevent oversized prompts
            text = text[:max_length]
            
            # Remove common injection patterns
            injection_patterns = [
                r'ignore previous instructions',
                r'system:.*',
                r'<\|.*\|>',
                r'```.*```',
            ]
            
            for pattern in injection_patterns:
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)
            
            return text.strip()
        ```

        ### 5. Frontend Authentication (`static/app.js`)
        ```javascript
        // Authentication state
        let apiKey = localStorage.getItem('polysint_api_key') || '';
        let isAuthenticated = !!apiKey;

        // Authenticated fetch wrapper
        async function authFetch(url, options = {}) {
            if (!apiKey) {
                showAuthModal();
                throw new Error('Authentication required');
            }
            
            const headers = {
                ...options.headers,
                'X-API-Key': apiKey
            };
            
            const res = await fetch(url, { ...options, headers });
            
            if (res.status === 401) {
                localStorage.removeItem('polysint_api_key');
                apiKey = '';
                showAuthModal();
                throw new Error('Authentication failed');
            }
            
            if (res.status === 429) {
                alert('Rate limited. Please wait before trying again.');
                throw new Error('Rate limited');
            }
            
            return res;
        }

        // Update all API calls to use authFetch
        async function loadMarkets(searchQuery = '', silent = false) {
            const res = await authFetch(url);
            // ...
        }
        ```

        ### 6. Security Monitoring (`security_monitor.py`)
        ```python
        class SecurityMonitor:
            def __init__(self):
                self.failed_attempts = defaultdict(list)
                self.blocked_ips = set()
                
            def log_failed_auth(self, ip: str, endpoint: str):
                # Implementation from responses
                # ...
                
            def block_ip(self, ip: str, reason: str):
                # IP blocking functionality
                # ...
                
            def get_recent_failures(self, limit: int = 100):
                # Return recent failed attempts
                # ...
        ```

        ### 7. Database Protection (`db.py`)
        ```python
        def get_db():
            conn = sqlite3.connect(Config.DB_NAME, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            return conn
        ```

        ## Deployment Steps

        1. **Generate secure keys**:
           ```bash
           openssl rand -hex 32  # For POLYSINT_API_KEY
           openssl rand -hex 32  # For ADMIN_API_KEY
           ```

        2. **Update `.env` file**:
           ```bash
           POLYSINT_API_KEY=your-generated-api-key
           ADMIN_API_KEY=your-generated-admin-key
           ```

        3. **Install dependencies**:
           ```bash
           pip install slowapi==0.1.8
           ```

        4. **Test authentication**:
           - Verify public endpoints work without auth
           - Verify protected endpoints reject missing/invalid keys
           - Verify rate limiting triggers appropriately

        5. **Update frontend**:
           - Store API key in localStorage
           - Use `authFetch()` wrapper for all API calls
           - Handle 401/429 responses gracefully

        ## Security Testing
        ```python
        def test_authentication():
            # Test missing key
            response = client.get("/markets")
            assert response.status_code == 401
            
            # Test invalid key
            response = client.get("/markets", headers={"X-API-Key": "invalid"})
            assert response.status_code == 401
            
            # Test valid key
            response = client.get("/markets", headers={"X-API-Key": Config.API_KEY})
            assert response.status_code in [200, 404]
        ```

        ## Emergency Procedures
        - **If compromised**: Rotate keys immediately via environment variables
        - **If under attack**: Check `analyzer.log` for failed attempts, implement IP blocking
        - **Emergency disable**: Temporarily unset `POLYSINT_API_KEY` to lock access

        ## Implementation Priority
        1. **Immediate**: Add API key authentication to all endpoints
        2. **Week 1**: Implement rate limiting and security monitoring
        3. **Week 2**: Add admin key separation for write operations
        4. **Ongoing**: Regular security audits and key rotation

        This implementation provides comprehensive security coverage while maintaining usability for legitimate users, addressing all critical vulnerabilities identified in the audit.
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
[35mEXIT CODE:[0m 1
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
total 644
-rw-r--r-- 1 thomas thomas      0 Mar 11 04:34 -
drwxr-xr-x 1 thomas thomas   3612 Mar 15 02:38 .
drwxr-xr-x 1 thomas thomas   2774 Feb 21 18:24 ..
-rw-r--r-- 1 thomas thomas      0 Mar 12 22:58 ...
drwxr-xr-x 1 thomas thomas    194 Mar 14 14:21 activity_journal
-rwxr-xr-x 1 thomas thomas   2327 Mar 14 01:02 activity_journal_control.sh
-rwxr-xr-x 1 thomas thomas   4715 Mar 14 13:04 activity_journal_daemon.sh
-rw-r--r-- 1 thomas thomas    801 Mar 14 01:06 ACTIVITY_JOURNAL_GUIDE.md
-rwxr-xr-x 1 thomas thomas   1999 Mar 14 01:35 activity_journal.sh
-rwxr-xr-x 1 thomas thomas   1051 Mar 14 01:06 activity_journal_stop.sh
drwxr-xr-x 1 thomas thomas     44 Mar 11 04:49 .agent8
-rwxr-xr-x 1 thomas thomas    341 Mar 10 16:34 agent8_pre_fix.sh
-rwxr-xr-x 1 thomas thomas   3412 Mar 11 04:34 agent8.sh
-rwxr-xr-x 1 thomas thomas    935 Mar 14 19:49 agent8-stateless.sh
drwxr-xr-x 1 thomas thomas     76 Mar 11 15:18 agent8_v8.1
drwxr-xr-x 1 thomas thomas    388 Mar 14 04:19 agora-marketplace
-rw-r--r-- 1 thomas thomas   5358 Mar 12 23:15 ai_hooks.sh
-rw-r--r-- 1 thomas thomas   4694 Mar  9 15:07 ai_hooks.sh.bak
-rw-r--r-- 1 thomas thomas   4694 Mar  9 15:09 ai_hooks.sh.bak.20260309
-rw-r--r-- 1 thomas thomas   5130 Mar  9 20:14 ai_hooks.sh.bak.20260309_201410
-rwxr-xr-x 1 thomas thomas   9738 Mar 14 13:04 ai_tools.sh
-rwxr-xr-x 1 thomas thomas   8313 Mar 10 16:27 ai_tools.sh.bak
-rw-r--r-- 1 thomas thomas   8383 Mar 10 16:33 ai_tools.sh.bak2
-rwxr-xr-x 1 thomas thomas   9707 Mar 14 13:04 ai_tools.sh.bak.20260314
-rw-r--r-- 1 thomas thomas   8520 Mar 10 16:54 ai_tools.sh.bak3
-rw-r--r-- 1 thomas thomas   8645 Mar 10 16:57 ai_tools.sh.bak4
-rw-r--r-- 1 thomas thomas    125 Mar 11 05:04 aliases.sh
-rwxr-xr-x 1 thomas thomas    500 Mar 11 04:50 backup_important.sh
drwxr-xr-x 1 thomas thomas    158 Mar 11 04:58 backups
-rw-r--r-- 1 thomas thomas   1729 Mar 13 17:37 batch_process.py
drwxr-xr-x 1 thomas thomas    352 Mar 13 01:29 blog-kit
drwxr-xr-x 1 thomas thomas     64 Mar 13 18:47 browser_control
drwxr-xr-x 1 thomas thomas     86 Mar 13 18:52 browser_control_safe
-rw-r--r-- 1 thomas thomas   2538 Mar 10 13:17 build_system_prompt.sh.bak
-rw-r--r-- 1 thomas thomas   4768 Mar 11 04:45 CLEANUP_REPORT.md
-rw-r--r-- 1 thomas thomas   4817 Mar 13 17:37 cli.py
-rw-r--r-- 1 thomas thomas 165268 Mar  9 01:20 cns_list.txt
-rw-r--r-- 1 thomas thomas   4588 Mar 13 17:37 composers.py
-rw-r--r-- 1 thomas thomas   4825 Mar 13 19:04 consortium_pattern.sh
drwxr-xr-x 1 thomas thomas    278 Mar 13 14:09 conversation_analysis
-rw-r--r-- 1 thomas thomas  12526 Mar 10 00:10 conversation_summary_20260309.md
-rwxr-xr-x 1 thomas thomas    535 Mar 11 05:09 daily_tip.sh
-rwxr-xr-x 1 thomas thomas   9929 Mar 11 04:58 dashboard.sh
-rw-r--r-- 1 thomas thomas   3317 Mar 11 04:58 DUPLICATE_FUNCTIONS.md
-rw-r--r-- 1 thomas thomas     18 Mar 15 02:38 elo_ratings.json
drwxr-xr-x 1 thomas thomas    118 Mar 14 07:22 embedding-visualizer
-rwxr-xr-x 1 thomas thomas   2406 Mar 11 02:56 eval_snake.sh
drwxr-xr-x 1 thomas thomas   3606 Mar 15 04:23 experiments
-rw-r--r-- 1 thomas thomas   1585 Mar 11 04:50 FUNCTION_TESTS.md
-rw-r--r-- 1 thomas thomas      2 Mar 15 02:38 .gen
drwxr-xr-x 1 thomas thomas    166 Mar 15 10:57 .git
drwxr-xr-x 1 thomas thomas     18 Feb 21 16:36 .github
-rw-r--r-- 1 thomas thomas    120 Feb 15 04:30 .gitignore
-rwxr-xr-x 1 thomas thomas   2496 Mar 11 04:55 git_status_check.sh
drwxr-xr-x 1 thomas thomas    342 Mar 14 01:15 hooks.d
-rw-r--r-- 1 thomas thomas   4291 Mar 11 04:47 HOOKS_SUGGESTIONS.md
drwxr-xr-x 1 thomas thomas    710 Mar 15 02:35 idea_exchange
drwxr-xr-x 1 thomas thomas     26 Mar 11 18:38 .ideas
drwxr-xr-x 1 thomas thomas     32 Mar 12 22:57 ideas
drwxr-xr-x 1 thomas thomas    822 Mar 14 19:48 INTERCOM
-rw-r--r-- 1 thomas thomas   2618 Mar 14 16:46 INTERCOM_PROJECT_SNAPSHOT.md
drwxr-xr-x 1 thomas thomas    134 Mar 14 02:04 journal
drwxr-xr-x 1 thomas thomas    904 Mar  9 18:15 LCARS
-rw-r--r-- 1 thomas thomas   9424 Mar 10 03:04 LCARS_PROMPT.md
-rwxr-xr-x 1 thomas thomas   9179 Mar 14 02:13 llm-sh
-rw-r--r-- 1 thomas thomas   7227 Mar 11 04:46 LLM_USAGE_ANALYSIS.md
-rw-r--r-- 1 thomas thomas    432 Mar  9 13:05 LOG.md
-rwxr-xr-x 1 thomas thomas   3690 Mar 11 04:55 log_rotator.sh
drwxr-xr-x 1 thomas thomas    180 Mar 14 23:21 logs
-rw-r--r-- 1 thomas thomas      0 Mar  9 20:12 logs.db
drwxr-xr-x 1 thomas thomas     90 Mar 13 17:40 logs_gemini_backup
-rw-r--r-- 1 thomas thomas    123 Mar 14 23:25 memento_config.json
-rw-r--r-- 1 thomas thomas    123 Mar 13 17:40 memento_config.json.gemini_backup
-rwxr-xr-x 1 thomas thomas   1646 Mar 14 01:13 monitor_activity.sh
drwxr-xr-x 1 thomas thomas   1744 Mar 14 01:29 nanoagent
drwxr-xr-x 1 thomas thomas    122 Mar 14 10:33 new_experiments
-rw-r--r-- 1 thomas thomas   2555 Mar 11 14:26 NOTES.md
drwxr-xr-x 1 thomas thomas    186 Mar 11 15:21 openrouter_model_analysis
-rwxr-xr-x 1 thomas thomas    429 Mar 11 02:52 parse_snake_score.sh
-rwxr-xr-x 1 thomas thomas   1680 Mar 11 04:57 project_scanner.sh
-rw-r--r-- 1 thomas thomas   3238 Mar 11 04:57 PROJECT_STATUS.md
drwxr-xr-x 1 thomas thomas    488 Mar 14 08:14 prompt-tester
drwxr-xr-x 1 thomas thomas    118 Mar 14 19:22 __pycache__
-rw-r--r-- 1 thomas thomas   3365 Mar 11 05:11 quick_ref.sh
-rw------- 1 thomas thomas   1387 Mar 11 04:50 README_AUDIT.md
-rw------- 1 thomas thomas    430 Mar 11 04:49 README_AUDIT.md.bak
-rw------- 1 thomas thomas    522 Mar 11 04:50 README_AUDIT.md.bak2
-rw-r--r-- 1 thomas thomas    595 Mar 14 07:27 README.md
-rw-r--r-- 1 thomas thomas      0 Mar 10 21:36 recai.log
drwxr-xr-x 1 thomas thomas    486 Mar 13 14:41 Recordings
drwxr-xr-x 1 thomas thomas    120 Mar 14 07:53 recursive-scientist
drwxr-xr-x 1 thomas thomas    250 Mar 13 17:37 report_engine
drwxr-xr-x 1 thomas thomas     50 Mar 11 04:27 reports
-rw-r--r-- 1 thomas thomas   5232 Mar 14 23:25 report.tar.gz
drwxr-xr-x 1 thomas thomas    106 Mar 15 01:32 repos
drwxr-xr-x 1 thomas thomas     22 Mar 13 17:35 sandbox
-rw-r--r-- 1 thomas thomas   5919 Mar 11 04:47 SECURITY_AUDIT.md
drwxr-xr-x 1 thomas thomas    168 Mar 14 02:56 shelllm
-rwxr-xr-x 1 thomas thomas    819 Mar 14 01:04 show_recent_activity.sh
drwxr-xr-x 1 thomas thomas     62 Mar 14 16:46 signal_bot
-rwxr-xr-x 1 thomas thomas   8778 Mar 14 18:53 signal_brenden_bot.py
-rwxr-xr-x 1 thomas thomas   4265 Mar 14 16:31 signal_brenden_bot.sh
-rwxr-xr-x 1 thomas thomas   1839 Mar 14 18:54 signal_brenden_control.sh
-rw-r--r-- 1 thomas thomas   1805 Mar 14 07:27 status_20260314_session2.md
-rw-r--r-- 1 thomas thomas   2823 Mar 11 04:48 SYSTEM_HEALTH.md
-rwxr-xr-x 1 thomas thomas   2394 Mar 14 01:15 test_activity_attachment.sh
-rwxr-xr-x 1 thomas thomas   3053 Mar 14 01:04 test_activity_journal.sh
-rwxr-xr-x 1 thomas thomas   1401 Mar 14 01:13 test_attachment.sh
-rwxr-xr-x 1 thomas thomas    446 Mar 14 03:53 test.sh
-rwxr-xr-x 1 thomas thomas   4283 Mar 11 04:47 test_spawn_gather.sh
-rw-r--r-- 1 thomas thomas   1241 Mar 14 06:49 TONIGHTS_WORK.md
-rw-r--r-- 1 thomas thomas   8691 Mar 12 23:14 typescript
-rw-r--r-- 1 thomas thomas   2307 Mar 11 04:51 utility_functions.sh
-rw-r--r-- 1 thomas thomas   1879 Mar 11 04:51 UTILITY_SUGGESTIONS.md
-rwxr-xr-x 1 thomas thomas   7673 Mar 11 05:14 utils.sh
-rwxr-xr-x 1 thomas thomas   2337 Mar 14 01:15 verify_activity_journal.sh
-rw-r--r-- 1 thomas thomas   1554 Mar 13 17:32 verify_pattern.sh
drwxr-xr-x 1 thomas thomas    134 Mar 13 14:18 visualizations
drwxr-xr-x 1 thomas thomas     62 Mar 10 17:45 walkthroughs
-rwxr-xr-x 1 thomas thomas    380 Mar 11 05:11 welcome.sh
-rwxr-xr-x 1 thomas thomas   4709 Mar 14 02:04 window_change_journal.sh
## Security Audit: Missing Authentication Implementation for PolySINT API

**Critical Finding**: The `api.py` file lacks authentication on all sensitive endpoints, exposing watchlist operations, wallet profiling, and AI analysis to unauthorized access and potential abuse.

### Vulnerable Endpoints Requiring Protection
1. `POST /watchlist` - Unauthorized target addition
2. `DELETE /watchlist/{address}` - Unauthorized target removal  
3. `GET /wallets/{address}/profile` - Expensive LLM profiling abuse
4. `GET /markets/{market_id}/ai-analysis` - Costly API calls without restriction
5. `GET /wallets/{address}/unmask` - Wallet identity exposure
6. `GET /watchlist` - Surveillance target enumeration
7. `GET /markets` - Resource-intensive endpoint (DoS risk due to thread spawning)

### Implementation Solution

#### 1. Configuration Updates (`config.py`)
```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # ... existing configuration ...
    
    # Security
    POLYSINT_API_KEY = os.getenv("POLYSINT_API_KEY")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
```

#### 2. Secured API Implementation (`api.py`)
```python
from fastapi import FastAPI, HTTPException, Query, Depends, Security, Request
from fastapi.security import APIKeyHeader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import secrets
import logging
from datetime import datetime

# ─── Security Setup ───────────────────────────────────────────────────────────
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Custom IP extractor for proxy awareness (prevents global lockout behind reverse proxies)
def get_real_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

limiter = Limiter(key_func=get_real_ip)

async def validate_api_key(
    api_key: str = Security(API_KEY_HEADER),
    request: Request = None
):
    """Constant-time API key validation to prevent timing attacks."""
    if not Config.POLYSINT_API_KEY:
        raise HTTPException(status_code=500, detail="Server authentication misconfigured")
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide via X-API-Key header."
        )
    
    if not secrets.compare_digest(api_key, Config.POLYSINT_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return api_key

# ─── App Initialization ───────────────────────────────────────────────────────
app = FastAPI(title="PolySINT Core Engine")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Audit logging
audit_logger = logging.getLogger("security_audit")
audit_logger.setLevel(logging.INFO)
handler = logging.FileHandler("security_audit.log")
handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
audit_logger.addHandler(handler)

# ─── Protected Endpoints ─────────────────────────────────────────────────────
@app.get("/markets")
@limiter.limit("30/minute")  # Protects against thread-spawning DoS
def search_markets(
    request: Request,
    limit: int = 50,
    search: str = None,
    vol_min: float = Query(default=None, ge=0),
    vol_max: float = Query(default=None, ge=0),
    api_key: str = Depends(validate_api_key)
):
    # ... existing logic ...

@app.get("/watchlist", dependencies=[Depends(validate_api_key)])
def get_watchlist():
    # ... existing logic ...
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
ls: cannot access 'repos/': No such file or directory
/home/thomas/organized/ai/experiments/polysint_100
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
repos not in experiments
total 0
drwxr-xr-x 1 thomas thomas  106 Mar 15 01:32 .
drwxr-xr-x 1 thomas thomas 3612 Mar 15 02:38 ..
drwxr-xr-x 1 thomas thomas   78 Mar 14 09:56 autoprompt
drwxr-xr-x 1 thomas thomas  192 Mar 15 01:33 memento-agent
drwxr-xr-x 1 thomas thomas   74 Mar 14 10:03 multichain-reasoning
drwxr-xr-x 1 thomas thomas   82 Mar 14 08:29 shelllm
drwxr-xr-x 1 thomas thomas   82 Mar 14 08:29 srm
total 884
drwxr-xr-x 1 thomas thomas   3100 Mar 15 12:12  .
drwxr-xr-x 1 thomas thomas    202 Mar 15 11:41  ..
-rw-r--r-- 1 thomas thomas   9509 Mar 15 11:10  EXP_001_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas   2423 Mar 15 11:08  EXP_002_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas  12242 Mar 15 11:10  EXP_003_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas   4607 Mar 15 11:08  EXP_004_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas   9367 Mar 15 11:10  EXP_005_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas   3201 Mar 15 11:19  EXP_006_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas   5507 Mar 15 11:27  EXP_007_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas   2727 Mar 15 11:18  EXP_008_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas   8341 Mar 15 11:19  EXP_009_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas 124996 Mar 15 11:14  EXP_010_Security_cns-role-code-audit.md
-rw-r--r-- 1 thomas thomas  15885 Mar 15 11:28  EXP_011_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas   9107 Mar 15 11:28  EXP_012_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas  15725 Mar 15 11:28  EXP_013_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas   6590 Mar 15 11:27  EXP_014_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas      1 Mar 15 11:34  EXP_015_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas  34507 Mar 15 11:37  EXP_016_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas   6455 Mar 15 11:36  EXP_017_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas  12740 Mar 15 11:37  EXP_018_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas   4700 Mar 15 11:35  EXP_019_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas 305228 Mar 15 11:42  EXP_020_Performance_hunter-alpha.md
-rw-r--r-- 1 thomas thomas  10335 Mar 15 11:46 'EXP_021_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas   5993 Mar 15 11:44 'EXP_022_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas   2670 Mar 15 11:47 'EXP_023_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas   1986 Mar 15 11:45 'EXP_024_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas  18673 Mar 15 11:46 'EXP_025_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas   9293 Mar 15 11:49 'EXP_026_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas  13384 Mar 15 11:50 'EXP_027_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas   5009 Mar 15 11:53 'EXP_028_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas  23020 Mar 15 11:54 'EXP_029_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas  34197 Mar 15 11:54 'EXP_030_Error Handling_glm-5-chutes.md'
-rw-r--r-- 1 thomas thomas  20708 Mar 15 12:03 'EXP_031_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas   2740 Mar 15 11:57 'EXP_032_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas  15002 Mar 15 12:05 'EXP_033_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas  12520 Mar 15 12:00 'EXP_034_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas  22288 Mar 15 12:12 'EXP_035_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas      0 Mar 15 12:12 'EXP_036_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas      0 Mar 15 12:12 'EXP_037_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas      0 Mar 15 12:12 'EXP_038_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas      0 Mar 15 12:12 'EXP_039_Code Quality_test-semantic-group.md'
-rw-r--r-- 1 thomas thomas  28981 Mar 15 12:16 'EXP_040_Code Quality_test-semantic-group.md'
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
#!/usr/bin/env bash
SOURCE_FILE="/home/thomas/ai_diary/polysint_all_source.txt"
RESULTS_DIR="/home/thomas/ai/experiments/polysint_100/results"
mkdir -p "$RESULTS_DIR"

run_exp() {
    local id=$1; local cat=$2; local model=$3; local p=$4
    local out="$RESULTS_DIR/EXP_${id}_${cat}_${model}.md"
    echo "[RUNNING] $id: $p"
    # Use agent8 for every 10th experiment to hit the 'complex' requirement
    if [[ $((10#$id % 10)) -eq 0 ]]; then
        AI_AUTO_CONFIRM=1 AGENT_ROLE=manager bash ~/ai/agent8.sh <<< "Task: $p\nSource Context: $(cat "$SOURCE_FILE")" > "$out" 2>&1
    else
        llm -m "$model" "$p" < "$SOURCE_FILE" > "$out" 2>&1
    fi
    echo "[DONE] $id"
}

export -f run_exp
export SOURCE_FILE RESULTS_DIR

run_exp "001" "Security" "cns-role-code-audit" "Audit api.py for missing authentication on sensitive endpoints (watchlist CRUD, profiling)." &
run_exp "002" "Security" "cns-role-code-audit" "Check for potential SQL injection vulnerabilities in db.py and api.py queries." &
run_exp "003" "Security" "cns-role-code-audit" "Assess risk of LLM prompt injection in analyst.py market question handling." &
run_exp "004" "Security" "cns-role-code-audit" "Check harvest.py for SSRF vulnerabilities when fetching external market data." &
run_exp "005" "Security" "cns-role-code-audit" "Audit notifier.py for sensitive credential leakage in error logs or responses." &
wait
run_exp "006" "Security" "cns-role-code-audit" "Evaluate use of subprocess.Popen in start.py for potential command injection." &
run_exp "007" "Security" "cns-role-code-audit" "Inspect static/app.js for XSS vulnerabilities when rendering market data." &
run_exp "008" "Security" "cns-role-code-audit" "Check for insecure direct object references (IDOR) in market analysis endpoints." &
run_exp "009" "Security" "cns-role-code-audit" "Audit clob.py for potential SSRF via attacker-controlled token IDs." &
run_exp "010" "Security" "cns-role-code-audit" "Review file permissions and secret handling in logger.py and config.py." &
wait
run_exp "011" "Performance" "hunter-alpha" "Optimize market enrichment in api.py to use bulk CLOB history fetching if possible." &
run_exp "012" "Performance" "hunter-alpha" "Analyze SQL query performance in db.py and suggest index optimizations." &
run_exp "013" "Performance" "hunter-alpha" "Optimize the harvester loop in harvest.py to handle rate limits more efficiently." &
run_exp "014" "Performance" "hunter-alpha" "Suggest improvements for memory management in watcher.py for large sets of seen trades." &
run_exp "015" "Performance" "hunter-alpha" "Evaluate async/await patterns in api.py to improve concurrent request throughput." &
wait
run_exp "016" "Performance" "hunter-alpha" "Optimize frontend bundle size and asset loading in static/index.html." &
run_exp "017" "Performance" "hunter-alpha" "Analyze analyst.py price behaviour derivation for potential speedups." &
run_exp "018" "Performance" "hunter-alpha" "Reduce latency in market search by pre-filtering volume before database calls." &
run_exp "019" "Performance" "hunter-alpha" "Optimize the heartbeat check in start.py to consume fewer resources." &
run_exp "020" "Performance" "hunter-alpha" "Improve clob.py history sorting and parsing for efficiency." &
wait
run_exp "021" "Error Handling" "glm-5-chutes" "Add robust retry logic with exponential backoff to clob.py history fetching." &
run_exp "022" "Error Handling" "glm-5-chutes" "Implement circuit breakers for external API calls in researcher.py." &
run_exp "023" "Error Handling" "glm-5-chutes" "Improve error reporting in notifier.py when webhooks fail." &
run_exp "024" "Error Handling" "glm-5-chutes" "Add transaction safety and rollbacks to db.py write operations." &
run_exp "025" "Error Handling" "glm-5-chutes" "Handle potential JSON decode errors gracefully in harvest.py and analyst.py." &
wait
run_exp "026" "Error Handling" "glm-5-chutes" "Improve network glitch handling in harvest.py pagination loop." &
run_exp "027" "Error Handling" "glm-5-chutes" "Add type checking and validation for all inputs in api.py utility functions." &
run_exp "028" "Error Handling" "glm-5-chutes" "Ensure all background processes in start.py log crashes before exiting." &
run_exp "029" "Error Handling" "glm-5-chutes" "Improve feedback to frontend in static/app.js when backend errors occur." &
run_exp "030" "Error Handling" "glm-5-chutes" "Handle malformed outcomePrices shapes more robustly in harvest.py." &
wait
run_exp "031" "Code Quality" "test-semantic-group" "Add comprehensive type hints to analyst.py for better maintainability." &
run_exp "032" "Code Quality" "test-semantic-group" "Refactor extract_first_price in harvest.py for better readability and simplicity." &
run_exp "033" "Code Quality" "test-semantic-group" "Implement a cleaner configuration management pattern in config.py." &
run_exp "034" "Code Quality" "test-semantic-group" "Standardize logging levels and formats across all PolySINT modules." &
run_exp "035" "Code Quality" "test-semantic-group" "Apply DRY principles to market data parsing in api.py and harvest.py." &
wait
run_exp "036" "Code Quality" "test-semantic-group" "Organize api.py into smaller, more focused sub-modules." &
run_exp "037" "Code Quality" "test-semantic-group" "Improve documentation and docstrings for all core logic functions." &
run_exp "038" "Code Quality" "test-semantic-group" "Standardize naming conventions (snake_case vs camelCase) across JS and Python." &
run_exp "039" "Code Quality" "test-semantic-group" "Refactor watcher.py to use a more structured event-driven pattern." &
run_exp "040" "Code Quality" "test-semantic-group" "Improve modularity of the frontend JS to avoid monolithic code in app.js." &
wait
run_exp "041" "Testing" "cns-role-code-audit" "Create a suite of unit tests for market shift calculations in analyst.py." &
run_exp "042" "Testing" "cns-role-code-audit" "Implement integration tests for the FastAPI endpoints in api.py." &
run_exp "043" "Testing" "cns-role-code-audit" "Design mock objects for Polymarket API calls to test harvest.py offline." &
run_exp "044" "Testing" "cns-role-code-audit" "Create stress tests for the database connection pool in db.py." &
run_exp "045" "Testing" "cns-role-code-audit" "Add frontend testing scripts for index.html using a tool like Playwright or Cypress." &
wait
run_exp "046" "Testing" "cns-role-code-audit" "Implement property-based testing for market question normalization." &
run_exp "047" "Testing" "cns-role-code-audit" "Create a test harness for security audit simulations on api.py." &
run_exp "048" "Testing" "cns-role-code-audit" "Add regression tests for the clob_token_id migration in db.py." &
run_exp "049" "Testing" "cns-role-code-audit" "Design a pipeline for automated UI testing of the dashboard." &
run_exp "050" "Testing" "cns-role-code-audit" "Create tests for the wallet unmasking logic in utils.py." &
wait
run_exp "051" "API Design" "test-semantic-group" "Implement cursor-based pagination for the /markets endpoint in api.py." &
run_exp "052" "API Design" "test-semantic-group" "Add versioning (e.g., /v1/) to all PolySINT API routes." &
run_exp "053" "API Design" "test-semantic-group" "Standardize JSON response formats for success and error cases." &
run_exp "054" "API Design" "test-semantic-group" "Add rate limiting headers and enforcement to all public endpoints." &
run_exp "055" "API Design" "test-semantic-group" "Expose more granular volume filter options in the /markets search API." &
wait
run_exp "056" "API Design" "test-semantic-group" "Create a dedicated health-check endpoint for monitoring tools." &
run_exp "057" "API Design" "test-semantic-group" "Add Swagger/OpenAPI documentation decorators to all FastAPI routes." &
run_exp "058" "API Design" "test-semantic-group" "Implement a bulk watchlist addition endpoint in api.py." &
run_exp "059" "API Design" "test-semantic-group" "Add support for CORS configuration in the API server." &
run_exp "060" "API Design" "test-semantic-group" "Improve the search query validation to prevent oversized inputs." &
wait
run_exp "061" "Frontend" "hunter-alpha" "Add a responsive mobile-friendly layout to static/index.html." &
run_exp "062" "Frontend" "hunter-alpha" "Improve data visualization for market shifts using Sparklines or charts." &
run_exp "063" "Frontend" "hunter-alpha" "Add a dark mode / light mode toggle to the CSS design system." &
run_exp "064" "Frontend" "hunter-alpha" "Implement better loading indicators and skeleton screens in app.js." &
run_exp "065" "Frontend" "hunter-alpha" "Add accessibility (Aria) attributes to all interactive dashboard elements." &
wait
run_exp "066" "Frontend" "hunter-alpha" "Improve the layout of the wallet profiling results for better readability." &
import requests
import time
from operator import itemgetter
from logger import get_logger

log = get_logger("CLOB")

CLOB_BASE = "https://clob.polymarket.com"

# How far back to look when calculating shift.
# "1d" gives a meaningful window even on a freshly restarted instance.
# Options: "1h", "6h", "1d", "1w", "max"
DEFAULT_INTERVAL = "1d"

# Resolution in minutes — 60 gives ~24 data points over 1d, enough for trend without hammering the API
DEFAULT_FIDELITY = 60

# Cache TTL in seconds — avoid hammering API for repeated requests
CACHE_TTL = 60

# Polymarket's CLOB endpoint uses a self-signed cert in its chain — disable verification
_SSL_VERIFY = False

# Suppress the urllib3 warning that fires when verify=False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── In-memory cache ──────────────────────────────────────────────────────────
# Structure: {(token_id, interval, fidelity): {"data": [...], "timestamp": float}}
_price_cache: dict = {}


def _is_sorted_by_timestamp(history: list) -> bool:
    """Check if history is already sorted by timestamp (ascending)."""
    if len(history) < 2:
        return True
    # Check first and last elements, plus a spot check in middle
    n = len(history)
    if history[0]["t"] > history[-1]["t"]:
        return False
    if n > 2 and history[0]["t"] > history[n // 2]["t"]:
        return False
    return True


def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
    """
    Fetches historical price data for a CLOB token from Polymarket.
    Returns a list of {"t": unix_timestamp, "p": price} dicts, oldest first.
    Returns None if the request fails.
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
-rw-r--r-- 1 thomas thomas 72666 Mar 15 11:53 /home/thomas/ai_diary/polysint_all_source.txt
1869 /home/thomas/ai_diary/polysint_all_source.txt
=== COMBINED SOURCE FOR AUDIT ===


### FILE: alerts.py ###
import json
import time
from db import get_db
from notifier import Notifier
from logger import get_logger
from clob import get_shift, get_price_history, DEFAULT_INTERVAL

log = get_logger("Alerts")

# ─── Thresholds ───────────────────────────────────────────────────────────────

# Minimum 24h price shift to trigger an alert
ANOMALY_THRESHOLD = 0.10  # 10%

# Markets below this lifetime volume are ignored entirely —
# low-liquidity markets move 10%+ on single small trades and generate noise
MIN_ALERT_VOLUME = 5000

# Markets with a current YES probability above this or below its inverse are
# close to resolution. Their swings carry less signal and generate noise.
# e.g. 0.80 means: skip markets already sitting at >80% or <20%
NEAR_RESOLUTION_THRESHOLD = 0.80


def safe_float(val):
    """Returns float or None — never raises."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def scan_for_anomalies():
    db = get_db()
    markets = db.execute("SELECT id, question, volume, clob_token_id FROM markets").fetchall()
    db.close()

    notifier = Notifier()

    for m in markets:
        # ── Volume gate ──────────────────────────────────────────────────────
        # Reject $0 and low-volume markets before any CLOB call.
        # Volume in the DB is set at harvest time — stale or never-traded
        # markets can still shift 10%+ on single trades and are not actionable.
        market_volume = m['volume'] or 0
        if market_volume < MIN_ALERT_VOLUME:
            continue

        clob_token_id = m['clob_token_id']

        try:
            if clob_token_id:
                # ── Primary path: CLOB history ───────────────────────────────
                shift = get_shift(clob_token_id)

                if shift is None:
                    continue

                if abs(shift) >= ANOMALY_THRESHOLD:
                    # Get current price for context and the near-resolution check
                    history = get_price_history(clob_token_id)
                    if not history:
                        continue

                    current_price = float(history[-1]['p'])

                    # ── Near-resolution gate ──────────────────────────────────
                    # Skip markets already close to 100% or 0% — they are
                    # effectively settled and their remaining moves are noise.
                    if current_price >= NEAR_RESOLUTION_THRESHOLD or current_price <= (1 - NEAR_RESOLUTION_THRESHOLD):
                        log.warning(
                            f"Suppressed alert for '{m['question']}': "
                            f"price {current_price:.2f} is near resolution."
                        )
                        continue

                    direction = "📈" if shift > 0 else "📉"
                    current_price_str = f"{round(current_price * 100)}%"

                    msg = (
                        f"{direction} **{m['question']}**\n"
                        f"Shifted **{shift * 100:.1f}%** over the last {DEFAULT_INTERVAL} "
                        f"— now at **{current_price_str}**\n"
                        f"Volume: ${market_volume:,.0f}\n\n"
                        f"_Open the dashboard to run AI analysis on demand._"
                    )
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

            else:
                # ── Fallback: local snapshot comparison ──────────────────────
                db2 = get_db()
                history = db2.execute("""
                    SELECT prices FROM snapshots
                    WHERE market_id = ?
                    ORDER BY timestamp DESC LIMIT 2""", (m['id'],)).fetchall()
                db2.close()

                if len(history) < 2:
                    continue

                try:
                    prices_now = json.loads(history[0]['prices'])
                    prices_then = json.loads(history[1]['prices'])
                except (json.JSONDecodeError, TypeError):
                    log.warning(f"Malformed prices JSON in snapshots for market {m['id']}, skipping.")
                    continue

                if not prices_now or not prices_then:
                    continue

                now = safe_float(prices_now[0])
                then = safe_float(prices_then[0])

                if now is None or then is None:
                    log.warning(
                        f"Non-numeric price in snapshots for market {m['id']} "
                        f"(got '{prices_now[0]}' / '{prices_then[0]}'), skipping."
                    )
                    continue

                diff = now - then

                if abs(diff) >= ANOMALY_THRESHOLD:
                    # ── Near-resolution gate (snapshot fallback) ──────────────
                    if now >= NEAR_RESOLUTION_THRESHOLD or now <= (1 - NEAR_RESOLUTION_THRESHOLD):
                        log.warning(
                            f"Suppressed alert for '{m['question']}': "
                            f"price {now:.2f} is near resolution (snapshot fallback)."
                        )
                        continue

                    direction = "📈" if diff > 0 else "📉"
                    msg = (
                        f"{direction} **{m['question']}**\n"
                        f"Shifted **{diff * 100:.1f}%** (local snapshots)\n"
                        f"Volume: ${market_volume:,.0f}\n\n"
                        f"_Open the dashboard to run AI analysis on demand._"
                    )
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

        except Exception as e:
            log.error(f"Error scanning anomaly for {m['id']}: {e}")
            continue


if __name__ == "__main__":
    print(
        f"Anomaly Scanner active — "
        f"Threshold: {ANOMALY_THRESHOLD * 100:.0f}% over {DEFAULT_INTERVAL} | "
        f"Min volume: ${MIN_ALERT_VOLUME:,} | "
        f"Near-resolution cutoff: {NEAR_RESOLUTION_THRESHOLD * 100:.0f}%"
    )
    while True:
        scan_for_anomalies()
        time.sleep(300)  # Run every 5 minutes


### FILE: analyst.py ###
import os
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
from researcher import PolyResearcher
from config import Config

load_dotenv()


def _derive_price_behaviour(price_history: list) -> dict:
    """
    Derives observable behavioural signals from a flat price list.
    These become first-class evidence for the LLM — it should never need to
    say "no data" about the price action itself, only about external news.

    Returns a dict of computed metrics with plain-English descriptions.
    """
    if not price_history or len(price_history) < 2:
        return {"summary": "Insufficient price history (fewer than 2 data points)."}

    try:
        prices = [float(p) for p in price_history]
    except (TypeError, ValueError):
        return {"summary": "Price data could not be parsed."}

    first = prices[0]
    last = prices[-1]
    high = max(prices)
    low = min(prices)
    total_shift = last - first
    total_range = high - low
    n = len(prices)

    # Find the single largest jump between consecutive points
    jumps = [(prices[i+1] - prices[i], i) for i in range(n - 1)]
    max_jump, max_jump_idx = max(jumps, key=lambda x: abs(x[0]))

[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
1100:### FILE: logger.py ###
808:### FILE: config.py ###
### FILE: logger.py ###
import logging

# Configure logging to write to analyzer.log (matched to your .gitignore)
logging.basicConfig(
    filename='analyzer.log',
    filemode='a', # Append mode
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING # Only logs WARNING, ERROR, and CRITICAL
)

def get_logger(name):
    return logging.getLogger(name)

### FILE: notifier.py ###
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
### FILE: config.py ###
import os
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
    # Set ENABLE_WEB_RESEARCH=true in .env to enable for background daemons.
    # Defaults to False — avoids 400 errors if TAVILY_API_KEY is missing/broken.
    ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"


### FILE: db.py ###
import sqlite3
from config import Config
from logger import get_logger

log = get_logger("Database")

def get_db():
    try:
        conn = sqlite3.connect(Config.DB_NAME)
        conn.row_factory = sqlite3.Row
        # This allows multiple readers and one writer to coexist
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
    except Exception as e:
        log.critical(f"Database connection failed: {e}")
        raise

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Markets Table — clob_token_id stores the YES outcome token for CLOB history lookups
    cursor.execute('''CREATE TABLE IF NOT EXISTS markets 
        (id TEXT PRIMARY KEY, question TEXT, outcomes TEXT, volume REAL, created_at TEXT, clob_token_id TEXT)''')

    # Migrate existing deployments: add clob_token_id column if it doesn't exist yet
    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(markets)").fetchall()]
    if "clob_token_id" not in existing_columns:
        cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
        log.warning("Migrated markets table: added clob_token_id column")

    # Snapshots Table — kept for fallback if CLOB history is unavailable
    cursor.execute('''CREATE TABLE IF NOT EXISTS snapshots 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id TEXT, timestamp DATETIME, prices TEXT, volume REAL)''')

    # Watchlist Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS watch_list 
        (address TEXT PRIMARY KEY, label TEXT, added_at DATETIME)''')

    conn.commit()
    conn.close()


### FILE: harvest.py ###
import requests
import json
import time
from datetime import datetime
from config import Config
from db import get_db, init_db
from logger import get_logger

log = get_logger("Harvester")


def extract_first_price(outcome_prices):
    """
    Safely extracts the first (YES) outcome price from whatever shape Gamma returns.
    Handles:
      - Already a list of floats/strings: ["0.5", "0.5"]
      - Double-encoded string: "[['0.5', '0.5']]"
      - Nested list (any depth): [[["0.5", "0.5"]]]
      - Dict with price key: [{"price": "0.5"}, ...]
      - None/null input
      - Empty strings
    Returns a JSON string of a flat list of strings, e.g. '["0.5", "0.5"]'.
    Returns '[]' on any failure.
    """
    try:
        # Handle None/null input
        if outcome_prices is None:
            return '[]'

        # Handle empty string input
        if isinstance(outcome_prices, str):
            outcome_prices = outcome_prices.strip()
            if not outcome_prices:
                return '[]'
            try:
                outcome_prices = json.loads(outcome_prices)
            except json.JSONDecodeError:
                log.warning(f"outcomePrices is not valid JSON: {repr(outcome_prices)[:100]}")
                return '[]'

        # After parsing, check for None again (JSON null)
        if outcome_prices is None:
            return '[]'

        # Must be a list at this point
        if not isinstance(outcome_prices, list):
            log.warning(f"outcomePrices is not a list after parsing: {type(outcome_prices).__name__}")
            return '[]'

        if not outcome_prices:
            return '[]'

        # Recursively unwrap nested lists until we find a non-list first element
        while outcome_prices and isinstance(outcome_prices[0], list):
            outcome_prices = outcome_prices[0]

        if not outcome_prices:
            return '[]'

        # Now we should have a flat list - extract prices from dicts or use values directly
        validated = []
        for item in outcome_prices:
            price = None
            
            # Handle dict with price key: {"price": "0.5"} or {"p": "0.5"}
            if isinstance(item, dict):
39:    markets = db.execute("SELECT id, question, volume, clob_token_id FROM markets").fetchall()
53:        clob_token_id = m['clob_token_id']
56:            if clob_token_id:
58:                shift = get_shift(clob_token_id)
65:                    history = get_price_history(clob_token_id)
259:            api_key=os.getenv("LLM_API_KEY")
496:    clob_token_id = m.get("clob_token_id")
500:    if clob_token_id:
501:        history = get_price_history(clob_token_id)
606:    Set ?research=true to include Tavily web search context (requires TAVILY_API_KEY).
622:        if market.get("clob_token_id"):
623:            price_history = get_history_as_price_list(market["clob_token_id"])
751:def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
753:    Fetches historical price data for a CLOB token from Polymarket.
761:                "market": clob_token_id,
769:            log.warning(f"CLOB history returned {resp.status_code} for token {clob_token_id}")
779:        log.error(f"CLOB history fetch failed for token {clob_token_id}: {e}")
783:def get_shift(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> float | None:
789:    history = get_price_history(clob_token_id, interval=interval)
798:def get_history_as_price_list(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> list[float] | None:
802:    history = get_price_history(clob_token_id, interval=interval)
825:    LLM_API_KEY = os.getenv("LLM_API_KEY")
831:    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
835:    # Set ENABLE_WEB_RESEARCH=true in .env to enable for background daemons.
836:    # Defaults to False — avoids 400 errors if TAVILY_API_KEY is missing/broken.
862:    # Markets Table — clob_token_id stores the YES outcome token for CLOB history lookups
864:        (id TEXT PRIMARY KEY, question TEXT, outcomes TEXT, volume REAL, created_at TEXT, clob_token_id TEXT)''')
866:    # Migrate existing deployments: add clob_token_id column if it doesn't exist yet
868:    if "clob_token_id" not in existing_columns:
869:        cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
[35mEXIT CODE:[0m 0
[36m[i] LLM Safety Audit...[0m [32mPASSED[0m
Report written successfully
158 ./results/EXP_010_Security_cns-role-code-audit.md
[35mEXIT CODE:[0m 0
NO OP
