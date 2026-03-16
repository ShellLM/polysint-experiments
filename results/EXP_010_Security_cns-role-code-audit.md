# Security Audit: File Permissions and Secret Handling in logger.py and config.py

## Executive Summary

**Overall Risk Level: MEDIUM**

The PolySINT codebase demonstrates good foundational practices for secret management (using environment variables via dotenv), but several security improvements are recommended to harden the configuration layer.

---

## 1. config.py Analysis

### Current Implementation

### ✅ Strengths

1. **Environment Variable Usage**: Secrets are loaded from environment variables, not hardcoded
2. **dotenv Integration**: Uses `python-dotenv` for local development convenience
3. **No Secret Logging**: Config values are not printed or logged anywhere in the codebase
4. **Reasonable Defaults**: Non-sensitive defaults (e.g., public RPC URL) are provided where appropriate

### ⚠️ Vulnerabilities and Recommendations

#### Issue 1: No Validation of Critical Secrets
**Severity: MEDIUM**

The configuration loads secrets but never validates their presence or format. A missing `LLM_API_KEY` would cause runtime failures deep in execution.

**Recommendation:**

#### Issue 2: No `.env` File Protection Guidance
**Severity: LOW**

No documentation or enforcement that `.env` should be in `.gitignore`.

**Recommendation:** Add to project README or create a `.env.example`:

#### Issue 3: Telegram Credentials Stored in Plain Text
**Severity: MEDIUM**

`TELEGRAM_BOT_TOKEN` provides full control over the bot. If compromised, an attacker could:
- Send messages as the bot
- Intercept all messages sent to the bot
- Modify bot settings

**Recommendation:** Consider using a secrets manager for production deployments:

---

## 2. logger.py Analysis

### Current Implementation

### ✅ Strengths

1. **Appropriate Log Level**: Uses `WARNING` as the default level, avoiding verbose logging
2. **Simple and Clean**: No complex logging logic that could introduce vulnerabilities
3. **Append Mode**: Uses append mode, preserving audit trail

### ⚠️ Vulnerabilities and Recommendations

#### Issue 1: No Log Rotation - Disk Exhaustion Risk
**Severity: MEDIUM**

The logger writes to `analyzer.log` indefinitely with no rotation. An attacker triggering repeated errors could fill the disk.

**Recommendation:**

#### Issue 2: No Protection Against Log Injection
**Severity: LOW**

User-controlled input (market questions, wallet addresses) could contain newlines that inject fake log entries.

**Example Attack:**

**Recommendation:** Sanitize logged data:

#### Issue 3: Logs May Contain Sensitive Data
**Severity: MEDIUM**

While the codebase doesn't explicitly log secrets, there's no filter to prevent accidental logging of sensitive values.

**Recommendation:** Add a logging filter:

---

## 3. File Permission Recommendations

### Critical Files Requiring Restricted Permissions

| File | Recommended Mode | Reason |
|------|-----------------|--------|
| `.env` | `0600` | Contains all secrets |
| `analyzer.log` | `0640` | May contain sensitive operational data |
| `polysint_core.db` | `0600` | Contains watchlist and market data |

### Implementation Script


---

## 4. Additional Observations from Codebase Scan

### Secrets Exposure Risk in Other Modules

During the audit, I observed these patterns that relate to secret handling:

1. **researcher.py** (line 259): 
   ```python
   api_key=os.getenv("LLM_API_KEY")
   ```
   - Good: Loads from environment
   - Risk: Passed directly to OpenAI client; errors could leak in stack traces

2. **api.py** (lines 825-836):
   - Multiple `os.getenv()` calls scattered throughout
   - **Recommendation**: Centralize all config access through `Config` class

3. **Missing `TAVILY_API_KEY` reference**:
   - `ENABLE_WEB_RESEARCH` flag exists but `TAVILY_API_KEY` is never defined in `config.py`
   - Check if it's accessed elsewhere via direct `os.getenv()`

---

## 5. Summary of Recommendations

| Priority | Issue | Action |
|----------|-------|--------|
| **HIGH** | No startup validation of secrets | Add `Config.validate()` method |
| **HIGH** | `.env` may not be gitignored | Verify `.gitignore` entry |
| **MEDIUM** | No log rotation | Implement `RotatingFileHandler` |
| **MEDIUM** | Potential log injection | Add message sanitization |
| **MEDIUM** | No file permission enforcement | Add setup script with `chmod` |
| **LOW** | No sensitive data filter | Add `SensitiveDataFilter` |
| **LOW** | Scattered `os.getenv()` calls | Centralize in `Config` class |

---

## 6. Files That Should Be in .gitignore

Verify these entries exist:

---

## Conclusion

The PolySINT codebase follows reasonable secret management practices by using environment variables rather than hardcoding credentials. The primary risks are:

1. **Operational**: Missing secrets cause late failures
2. **Infrastructure**: Log files can grow unbounded
3. **Defensive**: No protection against accidental secret logging or log injection

Implementing the recommendations above would raise the security posture from "adequate" to "production-ready" for the configuration and logging subsystems.

---

*Audit completed: 2026-03-15*
*Auditor: agent8 (manager mode) - EXP_010*
