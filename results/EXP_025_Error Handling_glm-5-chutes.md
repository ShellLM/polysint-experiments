### REASONING SUMMARY
The audit identified `json.loads` calls in `harvest.py` wrapped in broad `except Exception` blocks. While this prevents crashes, it is best practice to catch specific exceptions (`json.JSONDecodeError`, `TypeError`) to avoid masking unrelated logic errors. I updated `harvest.py` to use these specific exception handlers.

Additionally, `analyst.py` receives data that may be raw JSON strings when falling back to local database snapshots (as seen in `api.py`). The current implementation crashes or fails to parse these strings because it expects floats. I updated `_derive_price_behaviour` in `analyst.py` to import `json` and gracefully handle these JSON strings by decoding them before conversion, ensuring the analyst can process data from all sources.

### FILE: harvest.py
```python
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
      - Nested list: [["0.5", "0.5"]]
    Returns a JSON string of a flat list of strings, e.g. '["0.5", "0.5"]'.
    Returns '[]' on any failure.
    """
    try:
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)

        if not outcome_prices:
            return '[]'

        # Unwrap nested list if needed: [["0.5", "0.5"]] -> ["0.5", "0.5"]
        first = outcome_prices[0]
        if isinstance(first, list):
            outcome_prices = first

        # At this point we expect a flat list of price strings/floats
        # Validate each element is float-castable before storing
        validated = []
        for p in outcome_prices:
            try:
                float(p)
                validated.append(str(p))
            except (TypeError, ValueError):
                pass  # skip malformed entries

        return json.dumps(validated)

    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        log.warning(f"Failed to parse outcomePrices '{outcome_prices}': {e}")
        return '[]'


def fetch_active_markets(session):
    """Paginates through the Polymarket API to get all active markets."""
    print(f"[{datetime.now()}] Fetching active markets from Polymarket...")
    all_markets = []
    limit = 100
    offset = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    session = requests.Session()
    session.headers.update(headers)

    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset
        }

        try:
            response = session.get(Config.GAMMA_API, params=params, timeout=15)

            if response.status_code == 429:
                print(f"Rate limited at offset {offset}. Sleeping for 10 seconds...")
                time.sleep(10)
                continue

            if response.status_code != 200:
                print(f"Error fetching data at offset {offset}: HTTP {response.status_code}")
                break

            data = response.json()
            if not data:
                break

            all_markets.extend(data)
            offset += limit

            if offset % 1000 == 0:
                print(f" -> Fetched {offset} markets...")

            time.sleep(0.5)

        except requests.exceptions.SSLError:
            print(f"\n[!] SSL Error at offset {offset}. Try adding verify=False to session.get()")
            break

        except Exception as e:
            log.warning(f"Network glitch at offset {offset}: {e}")
            print(f"\n[!] Network glitch at offset {offset}: {e}. Retrying in 5 seconds...")
            time.sleep(5)
            continue

    print(f"[{datetime.now()}] Successfully fetched {len(all_markets)} active markets.")
    return all_markets


def process_and_save(markets):
    db = get_db()
    cursor = db.cursor()
    current_time = datetime.now().isoformat()

    for market in markets:
        outcomes_json = json.dumps(market.get("outcomes", []))

        # Normalise outcomePrices into a clean flat JSON array before storing
        prices_json = extract_first_price(market.get("outcomePrices", []))

        # clobTokenIds comes back as a stringified JSON array e.g. '["111...","222..."]'
        # Index 0 is the YES outcome token used for CLOB price history lookups
        clob_token_id = None
        raw_clob = market.get("clobTokenIds")
        if raw_clob:
            try:
                token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
                if token_ids and len(token_ids) > 0:
                    clob_token_id = token_ids[0]
            except (json.JSONDecodeError, TypeError) as e:
                log.warning(f"Failed to parse clobTokenIds for market {market.get('id')}: {e}")

        # INSERT OR REPLACE so clob_token_id gets backfilled on restarts.
        # COALESCE preserves the original created_at timestamp.
        cursor.execute('''
            INSERT OR REPLACE INTO markets (id, question, outcomes, volume, created_at, clob_token_id)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM markets WHERE id = ?), ?), ?)
        ''', (
            market.get("id"),
            market.get("question"),
            outcomes_json,
            float(market.get("volume", 0)),
            market.get("id"),
            current_time,
            clob_token_id
        ))

        cursor.execute('''
            INSERT INTO snapshots (market_id, timestamp, prices, volume)
            VALUES (?, ?, ?, ?)
        ''', (market.get("id"), current_time, prices_json, float(market.get("volume", 0))))

    db.commit()
    db.close()


if __name__ == "__main__":
    init_db()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })

    try:
        while True:
            data = fetch_active_markets(session)
            process_and_save(data)
            time.sleep(900)
    except KeyboardInterrupt:
        print("Stopped.")
```

### FILE: analyst.py
```python
import os
import json
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

    prices = []
    for p in price_history:
        try:
            # ── Robustness: Handle JSON strings from DB fallback ─────────────────
            # If the input is a string like '["0.55"]', parse it.
            if isinstance(p, str):
                # Try to decode JSON string (common in snapshot fallbacks)
                try:
                    decoded = json.loads(p)
                    # Expecting a list like ["0.55"], take the first element
                    if isinstance(decoded, list) and decoded:
                        p = decoded[0]
                    elif isinstance(decoded, (int, float)):
                        p = decoded
                except json.JSONDecodeError:
                    pass  # Not JSON, proceed to float conversion

            prices.append(float(p))
        except (TypeError, ValueError):
            # Skip non-numeric entries
            continue

    if len(prices) < 2:
        return {"summary": "Price data could not be parsed or had insufficient valid points."}

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

    # Characterise where in the window the big move happened
    position_pct = round((max_jump_idx / max(n - 1, 1)) * 100)
    if position_pct < 25:
        jump_timing = "early in the window"
    elif position_pct < 75:
        jump_timing = "mid-window"
    else:
        jump_timing = "late in the window (recent)"

    # Is the move holding or reversing?
    # Compare last price to the price at peak/trough
    if total_shift > 0:
        reversal = round((high - last) * 100, 1)
        holding = reversal < 3.0
        reversal_note = f"Up {round(total_shift*100,1)}% overall; pulled back {reversal}% from peak — {'holding' if holding else 'showing reversal'}."
    elif total_shift < 0:
        reversal = round((last - low) * 100, 1)
        holding = reversal < 3.0
        reversal_note = f"Down {round(abs(total_shift)*100,1)}% overall; recovered {reversal}% from trough — {'holding' if holding else 'showing partial recovery'}."
    else:
        reversal_note = "No net movement over the window."

    # Was the move gradual or sudden?
    # Count how many steps account for 80% of the total absolute move
    total_abs = sum(abs(j[0]) for j in jumps)
    sorted_jumps = sorted(jumps, key=lambda x: abs(x[0]), reverse=True)
    cumulative = 0
    steps_for_80pct = 0
    for j, _ in sorted_jumps:
        cumulative += abs(j)
        steps_for_80pct += 1
        if total_abs > 0 and cumulative / total_abs >= 0.8:
            break

    if steps_for_80pct == 1:
        move_character = "single-step spike (one candle accounts for 80%+ of the move)"
    elif steps_for_80pct <= max(2, n // 6):
        move_character = f"sharp move concentrated in {steps_for_80pct} steps"
    else:
        move_character = f"gradual grind across {steps_for_80pct}+ steps"

    return {
        "data_points": n,
        "start_price": f"{round(first * 100, 1)}%",
        "end_price": f"{round(last * 100, 1)}%",
        "high": f"{round(high * 100, 1)}%",
        "low": f"{round(low * 100, 1)}%",
        "net_shift": f"{'+' if total_shift >= 0 else ''}{round(total_shift * 100, 1)}%",
        "largest_single_step": f"{'+' if max_jump >= 0 else ''}{round(max_jump * 100, 1)}% ({jump_timing})",
        "move_character": move_character,
        "trend_status": reversal_note,
    }


class PolyAnalyst:
    def __init__(self):
        self.client = OpenAI(
            base_url=os.getenv("LLM_API_BASE_URL"),
            api_key=os.getenv("LLM_API_KEY")
        )
        self.model = os.getenv("ANALYSIS_MODEL")
        self.researcher = PolyResearcher()

    def analyze_market_shift(self, market_question, price_history, volume, use_research: bool = None):
        """Explains WHY a market is moving, grounded first in price behaviour, then optionally in news."""
        if use_research is None:
            use_research = Config.ENABLE_WEB_RESEARCH

        # Always derive price behaviour — this is the primary evidence source
        behaviour = _derive_price_behaviour(price_history)

        if use_research:
            news_context = self.researcher.get_market_context(market_question)
        else:
            news_context = "Web research disabled. No external news context available."

        current_time = datetime.now(timezone.utc).strftime("%B %d, %Y - %H:%M:%S UTC")

        system_prompt = (
            "You are a Senior OSINT & Forensic Financial Analyst specialising in prediction markets. "
            f"CRITICAL: The current real-world date and time is {current_time}. "
            "Your analysis must be grounded in the evidence provided. "
            "The PRICE BEHAVIOUR section is primary evidence — it is derived directly from market data and is always available. "
            "The NEWS CONTEXT section is supplementary — it may be empty, in which case your analysis must still be substantive and grounded in the price behaviour alone. "
            "You must NEVER produce a finding of INSUFFICIENT DATA unless the price history itself has fewer than 2 data points. "
            "You must NEVER claim a move is unexplained simply because news is absent — price behaviour alone can support a classification. "
            "Do not invent events. Every factual claim must trace back to either the price behaviour metrics or a specific news item below."
        )

        prompt = f"""
MARKET QUESTION: "{market_question}"
TOTAL VOLUME: ${volume:,.0f}

━━━ PRIMARY EVIDENCE: PRICE BEHAVIOUR ━━━
{chr(10).join(f"  {k}: {v}" for k, v in behaviour.items())}

━━━ SUPPLEMENTARY EVIDENCE: NEWS CONTEXT ━━━
{news_context}

---
INSTRUCTIONS:

Work through the following steps IN ORDER.

STEP 1 - PRICE BEHAVIOUR ANALYSIS:
Using ONLY the price behaviour metrics above, describe what the market did.
Cover: the direction and magnitude of the move, whether it was sudden or gradual,
where in the time window it occurred, and whether it is holding or reversing.
This step must be completed even if news context is empty.

STEP 2 - NEWS CORRELATION (if news context is available):
List each news item that is directly relevant to this market.
For each relevant item, note its title, source URL, and published date.
If no news items are relevant, state: "No directly relevant news found."
If news context was disabled, state: "Web research was not run for this query."

STEP 3 - TIMING ANALYSIS:
Based on the move character (sudden vs gradual) and any dated news items:
- A sudden single-step spike with no news strongly suggests the information
  existed before it became public, or a large single trader acted on private conviction.
- A gradual grind is more consistent with slow public information diffusion.
- If dated news is available, state whether the market moved before or after it broke.
- If no news is available, base your timing assessment on the move character alone.

STEP 4 - CLASSIFICATION:
Classify as one of:
- REACTIONARY: A specific dated news item directly explains the shift and
  appeared before or concurrent with the market move.
- SUSPICIOUS: The move is sudden, large, and preceded available news — or the
  move character (single-step spike) is inconsistent with organic public information flow.
- ORGANIC: The move is gradual and consistent with slow public information
  diffusion, even without a specific news item.
- INSUFFICIENT DATA: Use ONLY if the price history has fewer than 2 data points.

STEP 5 - INTELLIGENCE BRIEF:
Write a 2-3 sentence brief. Every factual claim must be traceable to either
the price behaviour metrics (Step 1) or a specific news item (Step 2).
Do not hedge by saying the move is "unexplained" — explain what the data
shows even if the cause is uncertain.

STEP 6 - INSIDER SIGNAL SCORE (1-10):
Rate the probability of insider knowledge.
- Base the score on the move character: sudden spikes score higher than gradual grinds.
- Adjust up if the move preceded news; adjust down if news preceded the move.
- A score above 6 requires specific justification from Steps 1-3.
- Do NOT cap at 5 simply because news is absent — price behaviour is sufficient evidence.

---
OUTPUT FORMAT:

PRICE ACTION:
(Step 1 findings)

EVIDENCE:
(Step 2 findings, with source URLs if available — or explicit statement if none)

TIMING:
(Step 3 finding)

TYPE: (REACTIONARY / SUSPICIOUS / ORGANIC / INSUFFICIENT DATA)

ANALYSIS:
(Step 5 brief)

INSIDER SIGNAL: (1-10) — (one sentence justification referencing specific data points)
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        return response.choices[0].message.content

    def profile_wallet(self, wallet_address, real_owner, trades):
        """Profiles a specific trader based on behavior and unmasked ID."""

        current_time = datetime.now(timezone.utc).strftime("%B %d, %Y")
        system_prompt = (
            "You are a digital forensic profiler. "
            f"The current date is {current_time}. "
            "Base your analysis strictly on the trade data provided. "
            "Do not invent biographical details, assume identity, or speculate beyond what the trading patterns directly support. "
            "Where the data is insufficient to draw a conclusion, say so explicitly."
        )

        prompt = f"""
PROXY ADDRESS: {wallet_address}
REAL OWNER (EOA): {real_owner}
RECENT TRADES: {trades}

---
INSTRUCTIONS:

Work through the following steps IN ORDER.

STEP 1 - PATTERN ANALYSIS:
What observable patterns exist in the trade data above?
Consider: market niches traded, trade timing, position sizes, win/loss ratio if determinable.
If the trade list is too short or sparse to identify patterns, state this explicitly.

STEP 2 - ENTITY TYPE:
Based ONLY on the patterns from Step 1, suggest the most likely entity type from:
(Political Staffer, Domain Expert, Quantitative Bot, Retail Speculator, Market Maker, Whale, Unknown)
If Step 1 found insufficient data, classify as: Unknown — insufficient trade history.

STEP 3 - ALPHA LEVEL (1-10):
Rate their likely information edge.
A score above 6 requires a specific pattern from Step 1 to justify it.
If Step 1 found insufficient data, cap the score at 5.

---
OUTPUT FORMAT:

PATTERNS:
(Step 1 findings — or explicit statement that data is insufficient)

ENTITY TYPE: (from the list above)

ALPHA LEVEL: (1-10) — (one sentence justification referencing a specific pattern, or acknowledgement of data limits)
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        return response.choices[0].message.content
```
