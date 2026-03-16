Here's the refactored `extract_first_price` function with improved readability and simplicity:

```python
def extract_first_price(outcome_prices):
    """
    Normalises the 'outcomePrices' field from the Gamma API into a flat JSON
    array of price strings, e.g. '["0.5", "0.5"]'.

    Handles None, empty strings, double-encoded JSON, arbitrarily nested lists,
    and dicts with 'price' or 'p' keys. Returns '[]' on any failure.
    """
    prices = _parse_outcome_prices(outcome_prices)
    if prices is None:
        return "[]"

    prices = _flatten_nested_lists(prices)
    return json.dumps(_validate_price_items(prices))


def _parse_outcome_prices(raw):
    """Parse raw Gamma outcomePrices into a list, or None on failure."""
    if raw is None:
        return None

    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            log.warning(f"outcomePrices is not valid JSON: {repr(raw)[:100]}")
            return None

    return raw if isinstance(raw, list) else None


def _flatten_nested_lists(lst):
    """Recursively unwrap nested lists until the first element is not a list."""
    while lst and isinstance(lst[0], list):
        lst = lst[0]
    return lst or []


def _extract_price_from_item(item):
    """Extract a price value from a dict, string, number, or single-element list."""
    if isinstance(item, dict):
        return item.get("price") or item.get("p")
    if isinstance(item, (str, int, float)):
        return item
    if isinstance(item, list) and len(item) == 1:
        return item[0]
    return None


def _validate_price_items(items):
    """Filter items to only those that cast to float; return them as strings."""
    result = []
    for item in items:
        price = _extract_price_from_item(item)
        if price is None:
            continue
        try:
            float(price)
            result.append(str(price))
        except (TypeError, ValueError):
            pass
    return result
```

**Key improvements:**
- **Clear pipeline structure**: Parse → Flatten → Validate → Serialize
- **Focused helper functions**: Each handles one specific concern
- **Reduced nesting**: Linear flow in main function with early returns
- **Better documentation**: Docstrings explain purpose, not just mechanics
- **Preserved functionality**: All edge cases handled identically to original

**What changed:**
- Decomposed into 5 focused functions instead of one monolithic function
- Removed deeply nested conditionals in favor of guard clauses
- Improved naming to clearly indicate each function's purpose
- Maintained all existing error handling and logging
