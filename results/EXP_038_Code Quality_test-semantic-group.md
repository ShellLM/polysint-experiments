Here's the standardized implementation for naming conventions across JS and Python:

## 1. Python API Layer (`api.py`)

Add key normalization to convert snake_case (Python/DB) to camelCase (JavaScript/frontend):

```python
def _normalize_keys_for_api(data: dict) -> dict:
    """
    Converts snake_case keys to camelCase for API responses.
    Operates on a copy to avoid side effects.
    """
    if not data:
        return data
    
    key_map = {
        "clob_token_id": "clobTokenId",
        "current_price": "currentPrice",
        "created_at": "createdAt",
        "added_at": "addedAt",
        "real_owner": "realOwner",
        "research_used": "researchUsed"
    }
    
    normalized = {}
    for key, value in data.items():
        normalized_key = key_map.get(key, key)
        normalized[normalized_key] = value
    
    return normalized
```

Apply this normalization to all API endpoints:
- `/markets` endpoint: Normalize each market dict
- `/watchlist` GET: Normalize each watchlist item
- `/wallets/{address}/unmask`: Return `{"proxy": address, "realOwner": real_owner}`
- `/markets/{market_id}/ai-analysis`: Return `{"analysis": analysis, "researchUsed": research}`
- `/wallets/{address}/profile`: Return `{"profile": profile, "realOwner": real_owner}`
- `/watchlist` POST: Return `{"status": "success", "resolvedAddress": target.address}`

## 2. JavaScript Frontend (`static/app.js`)

Standardize all variables and functions to camelCase:

```javascript
// Key naming changes:
// - refreshTimer → autoRefreshTimer
// - formatter → currencyFormatter  
// - initResearchToggle → setupResearchToggle
// - onResearchToggle → handleResearchToggle
// - showIdleState → renderIdleState
// - showLoadingState → renderLoadingState
// - showEmptySearchState → renderNoResults

// Access API responses with camelCase:
// - m.currentPrice (not m.current_price)
// - data.realOwner (not data.real_owner)
// - data.researchUsed (not data.research_used)

// Update localStorage key:
// - polysint_research_enabled → polysintResearchEnabled
```

## 3. HTML Updates (`static/index.html`)

Update element IDs and event handlers to camelCase:

```html
<!-- Change these IDs: -->
<!-- id="vol_min" → id="volMin" -->
<!-- id="vol_max" → id="volMax" -->
<!-- id="addError" → id="addErrorMsg" -->

<!-- Update event handler: -->
<!-- onchange="onResearchToggle()" → onchange="handleResearchToggle()" -->
```

## 4. Important Notes

1. **Query parameters remain snake_case** (e.g., `vol_min`, `vol_max` in API calls)
2. **Python internal code stays snake_case** (no changes needed to alerts.py, analyst.py, etc.)
3. **CSS classes remain unchanged** (Tailwind's hyphenated convention is appropriate)
4. **Database schema remains unchanged** (SQLite uses snake_case)

## 5. Summary of Changes

| Layer | Convention | What Changes |
|-------|-----------|--------------|
| Python internals | snake_case | No change - already correct |
| API query params | snake_case | No change (vol_min, vol_max) |
| API response keys | camelCase | New normalization function |
| JavaScript variables | camelCase | All vars/functions converted |
| HTML element IDs | camelCase | Updated to match JS expectations |
| localStorage keys | camelCase | polysintResearchEnabled |

The boundary is now clean: Python speaks snake_case internally, converts to camelCase at the API response layer, and JavaScript receives everything in camelCase.
