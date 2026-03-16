The `static/app.js` file contains multiple critical stored XSS vulnerabilities due to unsafe rendering of untrusted data from the database and API responses. The primary issues are:

1. **Direct HTML Injection**: Using `innerHTML` with user-controlled data like market questions (`m.question`) and watchlist labels (`w.label`).
2. **Attribute Injection**: Inline `onclick` handlers with unsanitized interpolated strings allow breaking out of string context.
3. **Unsafe LLM Output**: AI-generated analysis is rendered as HTML after only basic markdown conversion, risking script injection.
4. **DOM ID Injection**: User data used in element IDs could lead to invalid markup or script execution.

**Remediation Strategy:**

### 1. Frontend Security Overhaul (`static/app.js`)

Implement a `Security` utility namespace to centralize safe DOM operations:

```javascript
const Security = {
    escapeHTML(str) {
        if (typeof str !== 'string') return '';
        const map = {
            '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#039;', '/': '&#x2F;',
            '`': '&#x60;', '=': '&#x3D;'
        };
        return str.replace(/[&<>"'`=/]/g, c => map[c]);
    },
    
    createElement(tag, attrs = {}, children = []) {
        const el = document.createElement(tag);
        Object.entries(attrs).forEach(([key, value]) => {
            if (key === 'className') el.className = value;
            else if (key === 'dataset') {
                Object.entries(value).forEach(([dk, dv]) => el.dataset[dk] = dv);
            }
            else if (key.startsWith('on') && typeof value === 'function') {
                el.addEventListener(key.slice(2).toLowerCase(), value);
            }
            else el.setAttribute(key, value);
        });
        children.forEach(child => {
            if (typeof child === 'string') el.appendChild(document.createTextNode(child));
            else if (child instanceof Node) el.appendChild(child);
        });
        return el;
    }
};
```

**Critical Fixes:**
- **Replace all `innerHTML` with `textContent`** for user data:
  ```javascript
  // Instead of: table.innerHTML = `<span>${m.question}</span>`;
  const span = Security.createElement('span');
  span.textContent = m.question; // Safe
  ```
- **Convert inline event handlers to data attributes and event delegation**:
  ```javascript
  // Instead of: <button onclick="analyzeMarket('${m.id}')">
  const btn = Security.createElement('button', {
      dataset: { marketId: m.id, action: 'analyze' }
  }, ['🤖 Analyze']);
  
  // Single delegated listener (attach once during DOMContentLoaded)
  document.getElementById('marketsTable').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action="analyze"]');
      if (btn) analyzeMarket(btn.dataset.marketId);
  });
  ```
- **Sanitize LLM output** using DOMPurify:
  ```javascript
  // Load DOMPurify via CDN in index.html
  // <script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>
  
  async function analyzeMarket(marketId) {
      // ... fetch data ...
      const html = data.analysis
          .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
          .replace(/\n/g, '<br>');
      
      const sanitized = typeof DOMPurify !== 'undefined'
          ? DOMPurify.sanitize(html, { ALLOWED_TAGS: ['strong', 'br'], ALLOWED_ATTR: ['class'] })
          : Security.escapeHTML(data.analysis);
      
      content.innerHTML = `<div>${sanitized}</div>`;
  }
  ```

### 2. Backend Security Enhancements (`api.py`)

Add a Content Security Policy (CSP) middleware and strengthen input validation:

```python
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://clob.polymarket.com https://data-api.polymarket.com; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# In watchlist endpoint, validate but do NOT escape before storage:
@app.post("/watchlist")
def add_to_watchlist(target: Target):
    raw_label = target.label.strip()
    # Validate for XSS patterns (reject, don't sanitize)
    dangerous_patterns = [r'<script', r'javascript:', r'on\w+\s*=', r'eval\s*\(']
    for pattern in dangerous_patterns:
        if re.search(pattern, raw_label, re.IGNORECASE):
            raise HTTPException(status_code=400, detail="Invalid label content")
    # Store RAW data for integrity
    db.execute("INSERT INTO watch_list VALUES (?, ?, ...)", (target.address, raw_label, ...))
```

### 3. Additional Recommendations
- Add DOMPurify CDN script to `index.html`.
- Implement event delegation for all dynamic buttons (watchlist actions, market analysis).
- Use `document.createDocumentFragment()` for batch DOM insertion to improve performance.
- Cache DOM elements to avoid repeated queries.
- Add a `beforeunload` listener to clean up event listeners and prevent memory leaks.
