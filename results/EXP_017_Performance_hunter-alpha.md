# Speedup Analysis: `_derive_price_behaviour`

The function is O(N log N) due to sorting, but there are several concrete waste points and a few O(N) refactors that can make it significantly faster — especially if price histories grow beyond the typical ~24 points.

---

## 1. Dead code: `total_range` is never used

```python
total_range = high - low  # computed, never referenced
```

**Fix:** Delete it. Saves one subtraction per call, but more importantly signals the function was over-computed.

---

## 2. The `jumps` list allocates O(N) then immediately feeds `max()`

```python
jumps = [(prices[i+1] - prices[i], i) for i in range(n - 1)]  # allocates full list
max_jump, max_jump_idx = max(jumps, key=lambda x: abs(x[0]))  # scans again
```

This builds an entire list of tuples just to find one maximum. For a 24-point history it's ~23 tuples; for a 1-day history at fidelity=5 that's ~288 tuples — all thrown away after `max()`.

**Fix:** Inline the max-finding into the first pass. This also lets you compute `total_abs` at the same time:

```python
max_jump = 0.0
max_jump_idx = 0
total_abs = 0.0

for i in range(n - 1):
    jump = prices[i + 1] - prices[i]
    abs_jump = abs(jump)
    total_abs += abs_jump
    if abs_jump > abs(max_jump):
        max_jump = jump
        max_jump_idx = i
```

This replaces two allocations (list + list-of-tuples from `sorted`) with zero extra memory and is O(N) instead of O(N) + allocation overhead.

---

## 3. The 80%-threshold sort is O(N log N) but only needs O(N)

The current approach:

```python
sorted_jumps = sorted(jumps, key=lambda x: abs(x[0]), reverse=True)  # O(N log N)
cumulative = 0
steps_for_80pct = 0
for j, _ in sorted_jumps:
    cumulative += abs(j)
    steps_for_80pct += 1
    if total_abs > 0 and cumulative / total_abs >= 0.8:
        break
```

Since `total_abs` is known, you only need to count how many of the **largest** jumps you need to reach 80%. You can't avoid knowing which jumps are largest, so sorting seems necessary — **but you don't need a full sort**.

For the purpose of "how many steps cover 80%?", you only need the jumps ranked by magnitude. If there are N-1 jumps and you only ever break out at the 80% threshold, you'd typically need the top K where K << N. This is a **partial sort** problem.

However, in practice with N ≈ 24, the sort is ~46 comparisons — negligible. **For small N, this is fine as-is.** For N > 100, you could use `heapq.nlargest` or `numpy.partition` to get the top K without sorting everything.

**Fix (pragmatic for small N):** Leave it, but combine with fix #2 so you don't have to re-derive jumps:

```python
# From fix #2, you'd collect jumps as (abs_jump, jump_value) in a list
# only if total_abs > 0 and you need the 80% calculation.
# For the common case where it's clearly a single-step or gradual, 
# you can short-circuit.

if total_abs > 0:
    jumps_sorted = sorted(jumps_with_abs, reverse=True)  # only runs when needed
    cumulative = 0
    steps_for_80pct = 0
    for abs_j, j in jumps_sorted:
        cumulative += abs_j
        steps_for_80pct += 1
        if cumulative / total_abs >= 0.8:
            break
```

But you'd only collect `jumps_with_abs` if you actually need this metric (which you always do in current code). The real question is: can you skip it?

---

## 4. Move character classification is always computed, but could short-circuit

```python
if steps_for_80pct == 1:
    move_character = "single-step spike..."
elif steps_for_80pct <= max(2, n // 6):
    move_character = f"sharp move concentrated in {steps_for_80pct} steps"
else:
    move_character = f"gradual grind across {steps_for_80pct}+ steps"
```

This is computed on every call. The `max(2, n // 6)` threshold means for N=24, the breakpoint is at 4 steps. You can detect "definitely single-step" and "definitely gradual" without computing exact counts by checking ratios, but it's a micro-optimization.

---

## 5. The actual bottleneck: it doesn't matter here

The real cost of this function's caller (`analyze_market_shift`) is:

```
1. _derive_price_behaviour()   — Python, ~0.1ms
2. researcher.get_market_context()  — HTTP request, ~200-2000ms  (if enabled)
3. LLM API call                 — HTTP request, ~1000-10000ms
```

Fixing #1 saves maybe 0.05ms. The function is already fast enough that optimizing it is academic.

---

## Summary of actionable changes

| Issue | Cost | Fix |
|---|---|---|
| `total_range` dead code | 0 | Delete the line |
| `jumps` list allocation | O(N) alloc | Fold into single-pass loop with `max()` and `total_abs` |
| Two-pass (build then max) | 2×N | Single pass (see #2) |
| Sort for 80% threshold | O(N log N) | Acceptable for N<100; use `heapq.nlargest` for larger N |
| Reversal note math | minimal | Minor — `round()` calls are cheap |

**The highest-value change is #2:** collapsing the jumps list + max into a single pass. It eliminates an O(N) allocation, a second O(N) scan for `max()`, and lets you compute `total_abs` for free in the same loop. Here's what the refactored core would look like:

```python
# Single-pass: max jump, total_abs, jump timing
max_jump = 0.0
max_jump_idx = 0
total_abs = 0.0

for i in range(n - 1):
    jump = prices[i + 1] - prices[i]
    abs_jump = abs(jump)
    total_abs += abs_jump
    if abs_jump > abs(max_jump):
        max_jump = jump
        max_jump_idx = i

# Jump timing
position_pct = round((max_jump_idx / max(n - 1, 1)) * 100)
if position_pct < 25:
    jump_timing = "early in the window"
elif position_pct < 75:
    jump_timing = "mid-window"
else:
    jump_timing = "late in the window (recent)"

# For 80% threshold, we still need sorted jumps — collect in the same loop
# if we'll need them (which we always do with current logic)
if total_abs > 0:
    jumps_sorted = sorted(
        [(abs(prices[i+1] - prices[i]), prices[i+1] - prices[i]) for i in range(n - 1)],
        reverse=True
    )
    cumulative = 0
    steps_for_80pct = 0
    for abs_j, _ in jumps_sorted:
        cumulative += abs_j
        steps_for_80pct += 1
        if cumulative / total_abs >= 0.8:
            break
else:
    steps_for_80pct = n - 1
```

This trades a second loop (the `sorted`) for avoiding the intermediate `jumps` list in the max computation. If you wanted to go further, you could use `heapq.nlargest` to avoid sorting all N-1 jumps when you only need the top K, but for the data sizes this function actually sees, it's a wash.
