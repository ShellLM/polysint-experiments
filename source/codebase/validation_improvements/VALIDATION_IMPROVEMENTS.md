# Search Query Validation Improvements

## Executive Summary

Three components require validation improvements to prevent oversized/malicious inputs:

| Component | Current State | Risk Level |
|-----------|---------------|------------|
| api.py | Length check only (200 chars) | Medium |
| researcher.py | Silent truncation (100 chars) | Low |
| static/app.js | No client-side validation | Medium |

---

## 1. api.py - Backend Search Validation

### Location
Lines 26-31 (constants) and line 84 (search_markets function)

### Current Code

### Proposed Changes

Add after line 31 (after existing constants):


Replace line 84-85 with:

---

## 2. researcher.py - Tavily Query Validation

### Location
Lines 6 and 16-18

### Current Code

### Proposed Changes

Add after line 6:

Replace get_market_context opening (lines 12-18) with:

---

## 3. static/app.js - Client-Side Validation

### Location
Lines 8 (state) and 14-18 (event listener)

### Current Code

### Proposed Changes

Add after line 8:

Replace lines 14-18 with:

---

## Testing Recommendations

1. **api.py**: Test with inputs like:
   - `'; DROP TABLE markets;--` → Should return 400
   - 250-character string → Should return 400
   - Normal query "election" → Should pass

2. **researcher.py**: Test with:
   - Empty string → Should return early
   - Single character "a" → Should reject
   - 150-character market question → Should truncate with warning

3. **app.js**: Test with:
   - 250-character input → Should show error, not fetch
   - `; DROP` → Should show error
   - Normal "trump" → Should fetch normally

---

## Summary

| File | Lines Added | Risk Mitigated |
|------|-------------|----------------|
| api.py | ~25 | SQL injection, oversized inputs |
| researcher.py | ~15 | API errors, noise queries |
| static/app.js | ~35 | Client-side filtering, UX feedback |

Total: ~75 lines across 3 files
