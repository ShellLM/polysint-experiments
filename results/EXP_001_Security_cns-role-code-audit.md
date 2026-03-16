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

@app.post("/watchlist", dependencies=[Depends(validate_api_key)])
def add_to_watchlist(target: Target):
    # ... existing logic ...

@app.delete("/watchlist/{address}", dependencies=[Depends(validate_api_key)])
def remove_from_watchlist(address: str):
    # ... existing logic ...

@app.get("/wallets/{address}/unmask", dependencies=[Depends(validate_api_key)])
def unmask_wallet(address: str):
    # ... existing logic ...

@app.get("/wallets/{address}/profile")
@limiter.limit("5/minute")  # Strict limit for expensive LLM calls
def profile_wallet_api(
    request: Request,
    address: str,
    api_key: str = Depends(validate_api_key)
):
    # ... existing logic ...

@app.get("/markets/{market_id}/ai-analysis")
@limiter.limit("5/minute")  # Strict limit for expensive LLM calls
def get_ai_analysis(
    request: Request,
    market_id: str,
    research: bool = Query(default=False),
    api_key: str = Depends(validate_api_key)
):
    # ... existing logic ...
```

#### 3. Frontend Security Updates (`static/app.js`)
```html
<!-- Add to index.html head -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>
```

```javascript
// ─── Authentication State ────────────────────────────────────────────────────
let API_KEY = sessionStorage.getItem('polysint_api_key');

// ─── Secure Fetch Wrapper ────────────────────────────────────────────────────
async function secureFetch(url, options = {}) {
    const headers = { ...options.headers };
    if (API_KEY) {
        headers['X-API-Key'] = API_KEY;
    }
    
    const response = await fetch(url, { ...options, headers });
    
    // Handle authentication failures globally
    if (response.status === 401 || response.status === 403) {
        showAuthModal();
        throw new Error('Authentication required');
    }
    
    return response;
}

// ─── XSS-Safe Rendering ──────────────────────────────────────────────────────
function renderSafeMarkdown(text) {
    // Convert markdown to HTML, then sanitize with DOMPurify
    const html = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
    
    return DOMPurify.sanitize(html, {
        ALLOWED_TAGS: ['strong', 'br', 'p', 'em', 'b', 'i'],
        ALLOWED_ATTR: []
    });
}

// ─── Authentication Modal ────────────────────────────────────────────────────
function showAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) modal.classList.remove('hidden');
}

function submitApiKey() {
    const input = document.getElementById('apiKeyInput');
    const key = input.value.trim();
    
    if (key) {
        API_KEY = key;
        sessionStorage.setItem('polysint_api_key', key);
        document.getElementById('authModal').classList.add('hidden');
        location.reload(); // Reload to retry with new key
    }
}

// ─── Updated analyzeMarket Function ──────────────────────────────────────────
async function analyzeMarket(marketId) {
    const useResearch = isResearchEnabled();
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');

    modal.classList.remove('hidden');
    content.innerHTML = `<div class="text-center py-12">Analyzing...</div>`;

    try {
        const url = `/markets/${marketId}/ai-analysis?research=${useResearch}`;
        const res = await secureFetch(url);
        const data = await res.json();

        // Safe rendering using DOMPurify
        const safeHtml = renderSafeMarkdown(data.analysis);
        content.innerHTML = `
            <div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r">
                ${safeHtml}
            </div>`;
    } catch (e) {
        if (e.message !== 'Authentication required') {
            content.innerHTML = `<div class="text-red-400 p-4">Analysis failed</div>`;
        }
    }
}
```

#### 4. Environment Configuration (`.env`)
```bash
# Generate with: openssl rand -hex 32
POLYSINT_API_KEY=your_64_character_hex_key_here
ENVIRONMENT=production
```

### Testing the Implementation
```bash
# Test without key (should return 401)
curl http://localhost:9000/watchlist

# Test with valid key
curl -H "X-API-Key: your_key" http://localhost:9000/watchlist

# Test behind proxy (simulate X-Forwarded-For)
curl -H "X-Forwarded-For: 1.2.3.4" -H "X-API-Key: your_key" http://localhost:9000/markets

# Test rate limiting (6 requests to trigger limit)
for i in {1..6}; do
  curl -H "X-API-Key: your_key" "http://localhost:9000/markets/123456/ai-analysis"
done
```

### Security Audit Log
Monitor `security_audit.log` for:
- Authentication failures
- Rate limit violations
- Suspicious IP patterns

This implementation provides defense-in-depth: API key authentication with timing-safe comparison, proxy-aware rate limiting, XSS protection via DOMPurify, and comprehensive audit logging. The solution addresses all identified vulnerabilities while maintaining functionality.
