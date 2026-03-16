```python
import os
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    Final,
    List,
    Literal,
    Optional,
    Tuple,
    TypedDict,
    Union,
)

from openai import OpenAI
from dotenv import load_dotenv
from researcher import PolyResearcher
from config import Config

load_dotenv()

# ─── Type Aliases ──────────────────────────────────────────────────────────────

# CLOB prices arrive as floats; snapshot prices may be strings or ints.
# The conversion to float happens inside _derive_price_behaviour.
PriceHistory = List[Union[float, str, int]]

# Classification categories for market analysis
Classification = Literal["REACTIONARY", "SUSPICIOUS", "ORGANIC", "INSUFFICIENT DATA"]

# Entity type classifications for wallet profiling
EntityType = Literal[
    "Political Staffer",
    "Domain Expert",
    "Quantitative Bot",
    "Retail Speculator",
    "Market Maker",
    "Whale",
    "Unknown",
]

# Internal type for jump analysis tuples: (price_delta, starting_index)
JumpTuple = Tuple[float, int]


class PriceBehaviour(TypedDict, total=False):
    """
    Typed dictionary for price behaviour analysis results.

    When total=False, all keys are optional — the "summary" key is only
    present when insufficient data prevents full analysis.

    Attributes:
        summary: Human-readable explanation (only present on failure).
        data_points: Number of valid price observations.
        start_price: First price formatted as percentage string (e.g., "45.0%").
        end_price: Last price formatted as percentage string.
        high: Maximum price in the window as percentage string.
        low: Minimum price in the window as percentage string.
        net_shift: Total change as signed percentage string (e.g., "+12.5%").
        largest_single_step: Biggest consecutive jump with timing context.
        move_character: Description of move pattern (spike, sharp, gradual).
        trend_status: Whether move is holding or showing reversal.
    """

    summary: str
    data_points: int
    start_price: str
    end_price: str
    high: str
    low: str
    net_shift: str
    largest_single_step: str
    move_character: str
    trend_status: str


# ─── Constants ─────────────────────────────────────────────────────────────────

_GRADUAL_THRESHOLD: Final[float] = 0.8  # 80% of total move
_EARLY_POSITION: Final[int] = 25  # percent
_MID_POSITION: Final[int] = 75  # percent
_REVERSAL_THRESHOLD: Final[float] = 3.0  # percent from peak/trough

# Required environment variables for PolyAnalyst initialization
_REQUIRED_ENV_VARS: Final[Tuple[str, ...]] = (
    "LLM_API_BASE_URL",
    "LLM_API_KEY",
    "ANALYSIS_MODEL",
)


def _derive_price_behaviour(price_history: PriceHistory) -> PriceBehaviour:
    """
    Derives observable behavioural signals from a flat price list.

    These become first-class evidence for the LLM — it should never need to
    say "no data" about the price action itself, only about external news.

    The function computes:
    - Direction and magnitude of the overall move
    - Whether the move was sudden (single spike) or gradual
    - Where in the window the largest move occurred
    - Whether the move is holding or showing reversal

    Args:
        price_history: Chronological list of price values (oldest first).
            Accepts floats, strings, or integers.

    Returns:
        PriceBehaviour dictionary. On insufficient data or parse failure,
        returns only a "summary" key describing the issue.

    Examples:
        >>> _derive_price_behaviour([0.45, 0.48, 0.52, 0.55])
        {'data_points': 4, 'start_price': '45.0%', ...}

        >>> _derive_price_behaviour([0.5])
        {'summary': 'Insufficient price history (fewer than 2 data points).'}
    """
    if not price_history or len(price_history) < 2:
        return {"summary": "Insufficient price history (fewer than 2 data points)."}

    try:
        prices: List[float] = [float(p) for p in price_history]
    except (TypeError, ValueError):
        return {"summary": "Price data could not be parsed."}

    first: float = prices[0]
    last: float = prices[-1]
    high: float = max(prices)
    low: float = min(prices)
    total_shift: float = last - first
    n: int = len(prices)

    # Find the single largest jump between consecutive points
    jumps: List[JumpTuple] = [
        (prices[i + 1] - prices[i], i) for i in range(n - 1)
    ]
    max_jump: float
    max_jump_idx: int
    max_jump, max_jump_idx = max(jumps, key=lambda j: abs(j[0]))

    # Characterise temporal position of the biggest move
    position_pct: int = round((max_jump_idx / max(n - 1, 1)) * 100)
    jump_timing: str
    if position_pct < _EARLY_POSITION:
        jump_timing = "early in the window"
    elif position_pct < _MID_POSITION:
        jump_timing = "mid-window"
    else:
        jump_timing = "late in the window (recent)"

    # Is the move holding or reversing?
    reversal_note: str
    if total_shift > 0:
        reversal_pct: float = round((high - last) * 100, 1)
        holding: bool = reversal_pct < _REVERSAL_THRESHOLD
        reversal_note = (
            f"Up {round(total_shift * 100, 1)}% overall; "
            f"pulled back {reversal_pct}% from peak — "
            f"{'holding' if holding else 'showing reversal'}."
        )
    elif total_shift < 0:
        recovery_pct: float = round((last - low) * 100, 1)
        holding = recovery_pct < _REVERSAL_THRESHOLD
        reversal_note = (
            f"Down {round(abs(total_shift) * 100, 1)}% overall; "
            f"recovered {recovery_pct}% from trough — "
            f"{'holding' if holding else 'showing partial recovery'}."
        )
    else:
        reversal_note = "No net movement over the window."

    # Count how many steps account for 80% of total absolute movement
    total_abs: float = sum(abs(jump[0]) for jump in jumps)
    sorted_jumps: List[JumpTuple] = sorted(
        jumps, key=lambda j: abs(j[0]), reverse=True
    )

    cumulative: float = 0.0
    steps_for_80pct: int = 0
    for jump_delta, _ in sorted_jumps:
        cumulative += abs(jump_delta)
        steps_for_80pct += 1
        if total_abs > 0 and cumulative / total_abs >= _GRADUAL_THRESHOLD:
            break

    move_character: str
    if steps_for_80pct == 1:
        move_character = "single-step spike (one candle accounts for 80%+ of the move)"
    elif steps_for_80pct <= max(2, n // 6):
        move_character = f"sharp move concentrated in {steps_for_80pct} steps"
    else:
        move_character = f"gradual grind across {steps_for_80pct}+ steps"

    return PriceBehaviour(
        data_points=n,
        start_price=f"{round(first * 100, 1)}%",
        end_price=f"{round(last * 100, 1)}%",
        high=f"{round(high * 100, 1)}%",
        low=f"{round(low * 100, 1)}%",
        net_shift=f"{'+' if total_shift >= 0 else ''}{round(total_shift * 100, 1)}%",
        largest_single_step=(
            f"{'+' if max_jump >= 0 else ''}{round(max_jump * 100, 1)}% ({jump_timing})"
        ),
        move_character=move_character,
        trend_status=reversal_note,
    )


class PolyAnalyst:
    """
    AI-powered prediction market analyst using LLM for intelligence synthesis.

    Combines price behaviour analysis with optional web research to explain
    market movements and classify them as reactionary, suspicious, or organic.
    Also profiles wallet addresses based on trading patterns.

    Attributes:
        client: OpenAI-compatible client for LLM API calls.
        model: Model identifier for analysis (e.g., "gpt-4", "claude-3-opus").
        researcher: PolyResearcher instance for Tavily-backed web research.

    Example:
        >>> analyst = PolyAnalyst()
        >>> result = analyst.analyze_market_shift(
        ...     market_question="Will BTC exceed $100k by June 2025?",
        ...     price_history=["0.45", "0.52", "0.58"],
        ...     volume=50000,
        ...     use_research=True,
        ... )
    """

    def __init__(self) -> None:
        """
        Initialize the analyst with API clients.

        Reads configuration from environment variables:
            - LLM_API_BASE_URL: Base URL for LLM API endpoint
            - LLM_API_KEY: Authentication key for API access
            - ANALYSIS_MODEL: Model identifier for analysis

        Raises:
            ValueError: If required environment variables are missing.
        """
        missing: List[str] = [
            var for var in _REQUIRED_ENV_VARS if not os.getenv(var)
        ]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        self.client: OpenAI = OpenAI(
            base_url=os.getenv("LLM_API_BASE_URL"),
            api_key=os.getenv("LLM_API_KEY"),
        )
        self.model: str = os.getenv("ANALYSIS_MODEL", "")
        self.researcher: PolyResearcher = PolyResearcher()

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        """
        Internal helper for LLM API calls with consistent error handling.

        Args:
            system_prompt: System message defining assistant behavior.
            user_prompt: User message with analysis request.
            temperature: Sampling temperature (0.0 = deterministic).

        Returns:
            Generated response content as string.

        Raises:
            RuntimeError: If LLM API call fails or returns empty content.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            content: Optional[str] = response.choices[0].message.content
            if not content:
                raise RuntimeError("LLM returned empty content")
            return content
        except Exception as exc:
            raise RuntimeError(f"LLM API call failed: {exc}") from exc

    def analyze_market_shift(
        self,
        market_question: str,
        price_history: Optional[PriceHistory],
        volume: Union[int, float],
        use_research: Optional[bool] = None,
    ) -> str:
        """
        Explains WHY a prediction market is moving.

        Grounded first in price-behaviour metrics (always available), then
        optionally enriched with Tavily news context via web research.

        Args:
            market_question: The prediction market question.
                Example: "Will the Fed cut rates in March 2025?"
            price_history: Chronological price data (oldest first).
                Can be None; analysis will note insufficient data.
            volume: Total trading volume in USD.
            use_research: Enable Tavily web research for news context.
                If None, falls back to Config.ENABLE_WEB_RESEARCH.

        Returns:
            Formatted analysis string with sections:
                - PRICE ACTION: Price behaviour description
                - EVIDENCE: News items with sources (if research enabled)
                - TIMING: Correlation analysis
                - TYPE: Classification (REACTIONARY/SUSPICIOUS/ORGANIC/INSUFFICIENT DATA)
                - ANALYSIS: 2-3 sentence intelligence brief
                - INSIDER SIGNAL: Score 1-10 with justification

        Raises:
            RuntimeError: If LLM analysis fails.

        Example:
            >>> analysis = analyst.analyze_market_shift(
            ...     "Will Fed cut rates in March 2025?",
            ...     ["0.65", "0.68", "0.72"],
            ...     volume=25000,
            ...     use_research=False,
            ... )
            >>> "REACTIONARY" in analysis or "SUSPICIOUS" in analysis
            True
        """
        research_enabled: bool = (
            use_research if use_research is not None
            else Config.ENABLE_WEB_RESEARCH
        )

        behaviour: PriceBehaviour = _derive_price_behaviour(
            price_history if price_history is not None else []
        )

        news_context: str
        if research_enabled:
            news_context = self.researcher.get_market_context(market_question)
        else:
            news_context = "Web research disabled. No external news context available."

        current_time: str = datetime.now(timezone.utc).strftime(
            "%B %d, %Y - %H:%M:%S UTC"
        )

        system_prompt: str = (
            "You are a Senior OSINT & Forensic Financial Analyst "
            "specialising in prediction markets. "
            f"CRITICAL: The current real-world date and time is {current_time}. "
            "Your analysis must be grounded in the evidence provided. "
            "The PRICE BEHAVIOUR section is primary evidence — it is derived "
            "directly from market data and is always available. "
            "The NEWS CONTEXT section is supplementary — it may be empty, "
            "in which case your analysis must still be substantive and "
            "grounded in the price behaviour alone. "
            "You must NEVER produce a finding of INSUFFICIENT DATA unless "
            "the price history itself has fewer than 2 data points. "
            "You must NEVER claim a move is unexplained simply because news "
            "is absent — price behaviour alone can support a classification. "
            "Do not invent events. Every factual claim must trace back to "
            "either the price behaviour metrics or a specific news item below."
        )

        behaviour_block: str = "\n".join(
            f"  {k}: {v}" for k, v in behaviour.items()
        )

        prompt: str = f"""
MARKET QUESTION: "{market_question}"
TOTAL VOLUME: ${volume:,.0f}

━━━ PRIMARY EVIDENCE: PRICE BEHAVIOUR ━━━
{behaviour_block}

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

        return self._call_llm(system_prompt, prompt, temperature=0.0)

    def profile_wallet(
        self,
        wallet_address: str,
        real_owner: str,
        trades: List[str],
    ) -> str:
        """
        Profile a wallet's trading behavior and classify the entity type.

        Analyzes trading patterns to determine market niches, timing patterns,
        position sizing, and information edge.

        Args:
            wallet_address: 0x Ethereum proxy wallet address.
                Must be a valid 42-character address.
            real_owner: Unmasked EOA address from on-chain lookup.
                May be "Direct Wallet (Not a Proxy)" for non-contract wallets.
            trades: List of human-readable trade descriptions.
                Example: ["Bought YES on 'BTC > 100k' for $500", ...]

        Returns:
            Formatted profile string with sections:
                - PATTERNS: Observable trading patterns (or data limit note)
                - ENTITY TYPE: Classification from predefined categories
                - ALPHA LEVEL: Score 1-10 with justification

        Raises:
            RuntimeError: If LLM profiling fails.

        Example:
            >>> profile = analyst.profile_wallet(
            ...     wallet_address="0x1234...abcd",
            ...     real_owner="0xabcd...1234",
            ...     trades=["Bought YES on election market for $10000"],
            ... )
            >>> "Whale" in profile or "Domain Expert" in profile
            True
        """
        current_time: str = datetime.now(timezone.utc).strftime("%B %d, %Y")

        system_prompt: str = (
            "You are a digital forensic profiler. "
            f"The current date is {current_time}. "
            "Base your analysis strictly on the trade data provided. "
            "Do not invent biographical details, assume identity, or "
            "speculate beyond what the trading patterns directly support. "
            "Where the data is insufficient to draw a conclusion, say so explicitly."
        )

        trades_block: str = (
            "\n".join(f"- {trade}" for trade in trades)
            if trades
            else "(no trades available)"
        )

        prompt: str = f"""
PROXY ADDRESS: {wallet_address}
REAL OWNER (EOA): {real_owner}
RECENT TRADES:
{trades_block}

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

        return self._call_llm(system_prompt, prompt, temperature=0.0)
```
