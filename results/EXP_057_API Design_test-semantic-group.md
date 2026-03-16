```python
from fastapi import FastAPI, HTTPException, Query, Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
import re
import requests
import json

log = get_logger("API")

# ─── OpenAPI Configuration ───────────────────────────────────────────────────
tags_metadata = [
    {
        "name": "Dashboard",
        "description": "Frontend interface endpoints for serving the PolySINT dashboard."
    },
    {
        "name": "Markets",
        "description": "Prediction market search, filtering, and AI-powered forensic analysis operations."
    },
    {
        "name": "Wallets",
        "description": "Blockchain wallet unmasking and AI profiling endpoints for OSINT investigations."
    },
    {
        "name": "Watchlist",
        "description": "Management of monitored wallet addresses for continuous OSINT tracking and alerts."
    }
]

app = FastAPI(
    title="PolySINT Core Engine",
    description=(
        "OSINT intelligence platform for prediction market anomaly detection, "
        "wallet profiling, and AI-powered forensic analysis. "
        "Monitors Polymarket markets for unusual price movements and provides "
        "behavioral profiling of trading wallets."
    ),
    version="1.0.0",
    openapi_tags=tags_metadata,
    contact={"name": "PolySINT Support", "url": "https://github.com/polysint"},
    license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"}
)

analyst = PolyAnalyst()

# Pre-filter: only consider markets above this volume before hitting CLOB.
MIN_VOLUME_FOR_CLOB = 5000

# Max concurrent CLOB requests
CLOB_WORKERS = 20

# ─── Input limits ─────────────────────────────────────────────────────────────
MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
MARKET_ID_RE = re.compile(r'^[0-9]+$')

app.mount("/static", StaticFiles(directory="static"), name="static")

# ─── Pydantic Models ─────────────────────────────────────────────────────────
class ErrorResponse(BaseModel):
    """Standard error response model."""
    detail: str = Field(..., description="Human-readable error message")
    
    class Config:
        json_schema_extra = {
            "examples": [
                {"detail": "Invalid address. Must be a 42-character 0x Ethereum address."},
                {"detail": "Market not found"},
                {"detail": "AI analysis failed."}
            ]
        }

class MarketResponse(BaseModel):
    """Enriched market data with real-time price shift information."""
    id: str = Field(..., description="Unique Polymarket market identifier")
    question: str = Field(..., description="Market prediction question")
    outcomes: Optional[str] = Field(None, description="JSON string of possible outcomes")
    volume: Optional[float] = Field(None, description="Total trading volume in USD")
    created_at: Optional[str] = Field(None, description="Market creation timestamp in ISO format")
    clob_token_id: Optional[str] = Field(None, description="CLOB token ID for YES outcome price history")
    shift: float = Field(0.0, description="24-hour price shift as percentage (e.g., 12.5 = +12.5%)")
    current_price: Optional[float] = Field(None, description="Current YES probability (0.0-1.0)")

class WatchlistItem(BaseModel):
    """Wallet address on the monitoring watchlist."""
    address: str = Field(..., description="Ethereum proxy wallet address (42-character hex)")
    label: str = Field(..., description="Human-readable label for the wallet entity")
    added_at: Optional[str] = Field(None, description="ISO timestamp when added to watchlist")

class UnmaskResponse(BaseModel):
    """Result of proxy wallet unmasking."""
    proxy: str = Field(..., description="Original proxy wallet address supplied")
    real_owner: str = Field(..., description="Unmasked EOA address or 'Direct Wallet (Not a Proxy)'")

class AnalysisResponse(BaseModel):
    """AI-generated market analysis response."""
    analysis: str = Field(..., description="Structured forensic intelligence brief")
    research_used: bool = Field(..., description="Whether Tavily web research was enabled")

class ProfileResponse(BaseModel):
    """AI-generated wallet profile response."""
    profile: str = Field(..., description="Behavioral profile analysis with entity classification")
    real_owner: str = Field(..., description="Unmasked EOA address")

class StatusResponse(BaseModel):
    """Operation status response."""
    status: str = Field(..., description="Operation result status (success/deleted)")

class AddTargetResponse(BaseModel):
    """Response for adding a wallet to the watchlist."""
    status: str = Field(..., description="Operation status")
    resolved_address: str = Field(..., description="Validated Ethereum address stored")

class Target(BaseModel):
    """Wallet address for watchlist addition with validation."""
    address: str = Field(
        ...,
        description="42-character Ethereum proxy address (0x + 40 hex digits)",
        pattern=r'^0x[0-9a-fA-F]{40}$',
        examples=["0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"]
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=MAX_LABEL_LEN,
        description="Human-readable label identifying the entity (1-80 characters)",
        examples=["Suspected Political Whale"]
    )

    @field_validator('address')
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Validate and normalize Ethereum address format."""
        v = v.strip()
        if not ADDRESS_RE.match(v):
            raise ValueError("Must be a 42-character 0x Ethereum address.")
        return v

    @field_validator('label')
    @classmethod
    def validate_label(cls, v: str) -> str:
        """Validate label content and length."""
        v = v.strip()
        if not v:
            raise ValueError("Label cannot be empty.")
        if len(v) > MAX_LABEL_LEN:
            raise ValueError(f"Label too long (max {MAX_LABEL_LEN} chars).")
        return v

# ─── Helper Functions ────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    """Initialize database tables on application startup."""
    init_db()

def _validate_address(address: str) -> str:
    """
    Validate Ethereum address format.
    
    Raises HTTPException 400 if address is malformed.
    """
    if not ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=400,
            detail="Invalid address. Must be a 42-character 0x Ethereum address."
        )
    return address

def _enrich_market(m: dict) -> Optional[dict]:
    """
    Fetch CLOB history for a single market and attach price shift data.
    
    Returns None if market should be excluded (settled or no data).
    """
    clob_token_id = m.get("clob_token_id")
    m['shift'] = 0.0
    m['current_price'] = None

    if clob_token_id:
        history = get_price_history(clob_token_id)
        if history:
            m['current_price'] = float(history[-1]["p"])
            if len(history) >= 2:
                m['shift'] = round((float(history[-1]["p"]) - float(history[0]["p"])) * 100, 1)
    else:
        try:
            db = get_db()
            snap = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
                (m['id'],)
            ).fetchone()
            db.close()
            if snap:
                prices = json.loads(snap['prices'])
                if prices:
                    val = float(prices[0])
                    m['current_price'] = val
        except Exception:
            pass

    # Exclude settled markets (>98% or <2% probability)
    if m['current_price'] is not None:
        if m['current_price'] > 0.98 or m['current_price'] < 0.02:
            return None

    return m

# ─── API Endpoints ───────────────────────────────────────────────────────────
@app.get(
    "/",
    response_class=FileResponse,
    summary="Serve Dashboard Interface",
    tags=["Dashboard"],
    description="Serves the main PolySINT web dashboard for market monitoring and analysis.",
    include_in_schema=False  # Hide from OpenAPI as it serves static HTML
)
def serve_dashboard():
    """Return the static HTML dashboard for the PolySINT user interface."""
    return FileResponse("static/index.html")

@app.get(
    "/markets",
    response_model=List[MarketResponse],
    summary="Search and Filter Prediction Markets",
    tags=["Markets"],
    description=(
        "Retrieve active prediction markets enriched with real-time price data and "
        "24-hour price shift calculations. Markets are pulled from the local database "
        "and enriched via the Polymarket CLOB API."
    ),
    responses={
        200: {
            "description": "List of markets sorted by absolute 24h shift (descending)",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "123456",
                            "question": "Will Bitcoin exceed $100k by end of 2025?",
                            "outcomes": '["Yes", "No"]',
                            "volume": 2450000.50,
                            "created_at": "2024-01-15T10:30:00Z",
                            "clob_token_id": "0xabc123",
                            "shift": 12.5,
                            "current_price": 0.67
                        }
                    ]
                }
            }
        },
        400: {"model": ErrorResponse, "description": "Invalid search query parameters"}
    }
)
def search_markets(
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="Maximum number of markets to return. Higher values increase response time.",
        examples=[25, 50, 100]
    ),
    search: Optional[str] = Query(
        None,
        max_length=MAX_SEARCH_LEN,
        description="Case-insensitive search query for market questions (substring match)",
        examples=["bitcoin", "election", "FDA"]
    ),
    vol_min: Optional[float] = Query(
        None,
        ge=0,
        description="Minimum trading volume filter in USD (inclusive)",
        examples=[10000, 50000]
    ),
    vol_max: Optional[float] = Query(
        None,
        ge=0,
        description="Maximum trading volume filter in USD (inclusive)",
        examples=[100000, 500000]
    ),
):
    """
    Search active prediction markets with optional keyword and volume filters.
    
    **Filtering Behavior:**
    - When no search query is provided, a default volume floor of $5,000 is applied
      to avoid enriching illiquid markets.
    - When a search query is provided, the volume floor is lifted to find specific markets.
    - Settled markets (YES probability >98% or <2%) are automatically excluded.
    
    **Sorting:** Results are sorted by absolute 24h shift (descending), then by volume.
    
    **Performance:** Uses concurrent workers (20 max) for CLOB requests.
    """
    if search is not None and len(search) > MAX_SEARCH_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Search query too long (max {MAX_SEARCH_LEN} chars)."
        )

    db = get_db()
    try:
        query = "SELECT * FROM markets"
        params = []
        if search:
            query += " WHERE question LIKE ?"
            params.append(f"%{search}%")

        all_markets = [dict(r) for r in db.execute(query, params).fetchall()]
    finally:
        db.close()

    volume_floor = MIN_VOLUME_FOR_CLOB if not search else 0

    candidates = []
    for m in all_markets:
        vol = m.get('volume') or 0
        if vol < volume_floor:
            continue
        if vol_min is not None and vol < vol_min:
            continue
        if vol_max is not None and vol > vol_max:
            continue
        candidates.append(m)

    enriched = []
    with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as executor:
        futures = {executor.submit(_enrich_market, m): m for m in candidates}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    enriched.append(result)
            except Exception as e:
                log.error(f"Market enrichment failed: {e}")

    enriched.sort(key=lambda x: (abs(x.get('shift', 0.0)), x.get('volume') or 0.0), reverse=True)
    return enriched[:limit]

@app.get(
    "/watchlist",
    response_model=List[WatchlistItem],
    summary="Get All Watched Wallets",
    tags=["Watchlist"],
    description="Retrieve all wallet addresses currently being monitored for trading activity.",
    responses={
        200: {
            "description": "List of tracked wallets sorted by addition date (newest first)",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "address": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                            "label": "Political Whale",
                            "added_at": "2024-06-15T14:30:00Z"
                        }
                    ]
                }
            }
        }
    }
)
def get_watchlist():
    """
    Return all wallet addresses currently being monitored.
    
    The watchlist is used by the Watcher daemon to track trading activity.
    Alerts are sent via configured webhooks (Discord/Telegram) when watched
    wallets execute new trades.
    """
    db = get_db()
    try:
        res = db.execute("SELECT * FROM watch_list ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in res]
    finally:
        db.close()

@app.get(
    "/wallets/{address}/unmask",
    response_model=UnmaskResponse,
    summary="Unmask Proxy Wallet to EOA",
    tags=["Wallets"],
    description=(
        "Reveal the real Ethereum address (EOA) behind a Polymarket proxy contract. "
        "Calls the `getOwners()` function on the proxy contract via Polygon RPC."
    ),
    responses={
        200: {
            "description": "Proxy resolution result",
            "content": {
                "application/json": {
                    "examples": {
                        "proxy_wallet": {
                            "summary": "Proxy wallet resolved to EOA",
                            "value": {
                                "proxy": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                                "real_owner": "0x1234567890abcdef1234567890abcdef12345678"
                            }
                        },
                        "direct_wallet": {
                            "summary": "Already an EOA (not a proxy)",
                            "value": {
                                "proxy": "0xabcdef1234567890abcdef1234567890abcdef12",
                                "real_owner": "Direct Wallet (Not a Proxy)"
                            }
                        }
                    }
                }
            }
        },
        400: {"model": ErrorResponse, "description": "Invalid Ethereum address format"}
    }
)
def unmask_wallet(
    address: str = Path(
        ...,
        description="42-character Ethereum proxy address (0x + 40 hex digits)",
        pattern=r'^0x[0-9a-fA-F]{40}$',
        examples=["0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"]
    )
):
    """
    Unmask a Polymarket proxy wallet to find the real EOA address.
    
    Many Polymarket users trade through proxy contracts to hide their identity.
    This endpoint calls `getOwners()` (selector `0x7065c0d4`) on the proxy contract
    to reveal the underlying wallet address.
    """
    real_owner = unmask_proxy(address)
    return {"proxy": address, "real_owner": real_owner}

@app.get(
    "/markets/{market_id}/ai-analysis",
    response_model=AnalysisResponse,
    summary="AI Forensic Market Analysis",
    tags=["Markets"],
    description=(
        "Generate an AI-powered forensic analysis of market price movements. "
        "The analysis is grounded in price behavior data and optionally enhanced "
        "with web research via Tavily API."
    ),
    responses={
        200: {
            "description": "AI-generated forensic analysis report",
            "content": {
                "application/json": {
                    "example": {
                        "analysis": (
                            "PRICE ACTION:\n"
                            "Market shifted +15.2% over the last 24h. Single-step spike detected "
                            "with 80% of the move occurring in one candle...\n\n"
                            "EVIDENCE:\n"
                            "No directly relevant news found.\n\n"
                            "TIMING:\n"
                            "Sudden move with no public news suggests pre-public information flow.\n\n"
                            "TYPE: SUSPICIOUS\n\n"
                            "ANALYSIS:\n"
                            "The market exhibited a sudden 15.2% spike with no corresponding news event. "
                            "This pattern is consistent with insider knowledge or large single-trader action.\n\n"
                            "INSIDER SIGNAL: 7 — Single-step spike preceded any available news context."
                        ),
                        "research_used": False
                    }
                }
            }
        },
        400: {"model": ErrorResponse, "description": "Invalid market ID format (must be numeric)"},
        404: {"model": ErrorResponse, "description": "Market not found in database"},
        500: {"model": ErrorResponse, "description": "AI analysis failed (check LLM API configuration)"}
    }
)
def get_ai_analysis(
    market_id: str = Path(
        ...,
        description="Numeric Polymarket market ID",
        pattern=r'^[0-9]+$',
        examples=["123456"]
    ),
    research: bool = Query(
        False,
        description="Enable Tavily web research for news context (requires TAVILY_API_KEY environment variable)"
    )
):
    """
    Run AI analysis on a specific market's price movement.
    
    **Analysis Framework:**
    1. **Price Behavior Analysis** — Always available from CLOB/snapshot data
    2. **News Correlation** — Optional with `?research=true`
    3. **Timing Analysis** — Move character vs news timing
    4. **Classification** — REACTIONARY / SUSPICIOUS / ORGANIC / INSUFFICIENT DATA
    5. **Intelligence Brief** — 2-3 sentence summary
    6. **Insider Signal Score** — 1-10 rating with justification
    """
    if not MARKET_ID_RE.match(market_id):
        raise HTTPException(status_code=400, detail="Invalid market ID format.")

    db = get_db()
    try:
        market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        market = dict(market)
        price_history = None

        if market.get("clob_token_id"):
            price_history = get_history_as_price_list(market["clob_token_id"])

        if not price_history:
            raw = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 5",
                (market_id,)
            ).fetchall()
            price_history = [h['prices'] for h in raw]

        analysis = analyst.analyze_market_shift(
            market['question'],
            price_history,
            market['volume'],
            use_research=research
        )
        return {"analysis": analysis, "research_used": research}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"LLM Analysis failed for {market_id}: {e}")
        raise HTTPException(status_code=500, detail="AI analysis failed.")
    finally:
        db.close()

@app.get(
    "/wallets/{address}/profile",
    response_model=ProfileResponse,
    summary="AI Behavioral Wallet Profile",
    tags=["Wallets"],
    description=(
        "Generate an AI-powered behavioral profile of a wallet's trading activity. "
        "Combines on-chain unmasking with recent trade data for entity classification."
    ),
    responses={
        200: {
            "description": "Entity profile with classification and alpha score",
            "content": {
                "application/json": {
                    "example": {
                        "profile": (
                            "PATTERNS:\n"
                            "- 85% of trades on political markets\n"
                            "- Average position size: $12,500\n"
                            "- 78% win rate over last 30 days\n\n"
                            "ENTITY TYPE: Domain Expert\n\n"
                            "ALPHA LEVEL: 8 — Consistent wins on political markets "
                            "suggest strong information network in political sphere."
                        ),
                        "real_owner": "0x1234567890abcdef1234567890abcdef12345678"
                    }
                }
            }
        },
        400: {"model": ErrorResponse, "description": "Invalid Ethereum address format"},
        500: {"model": ErrorResponse, "description": "AI profiling failed (check LLM API or trade data availability)"}
    }
)
def profile_wallet_api(
    address: str = Path(
        ...,
        description="42-character Ethereum proxy wallet address",
        pattern=r'^0x[0-9a-fA-F]{40}$',
        examples=["0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"]
    )
):
    """
    Generate an AI profile of a wallet's trading behavior.
    
    **Process:**
    1. Unmask proxy wallet to find real EOA
    2. Fetch recent trades from Polymarket Data API
    3. Run AI analysis to classify entity type and assess alpha
    
    **Entity Types:** Political Staffer, Domain Expert, Quantitative Bot,
    Retail Speculator, Market Maker, Whale, Unknown
    
    **Alpha Level:** 1-10 scale rating probability of information edge.
    Scores above 6 require specific pattern justification.
    """
    _validate_address(address)
    try:
        real_owner = unmask_proxy(address)

        from config import Config
        url = f"{Config.DATA_API}/trades?user={address}&limit=15"
        resp = requests.get(url, timeout=10)
        trades_data = resp.json() if resp.status_code == 200 else []

        simplified_trades = [
            f"Bought {t.get('side')} on '{t.get('title')}' for ${t.get('size')}"
            for t in trades_data
        ]
        profile = analyst.profile_wallet(address, real_owner, simplified_trades)

        return {"profile": profile, "real_owner": real_owner}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Profiling failed: {e}")
        raise HTTPException(status_code=500, detail="AI Profiling failed.")

@app.post(
    "/watchlist",
    response_model=AddTargetResponse,
    summary="Add Wallet to Watchlist",
    tags=["Watchlist"],
    description=(
        "Add a wallet address to the monitoring watchlist for continuous OSINT tracking. "
        "The wallet will be monitored by the Watcher daemon for new trading activity."
    ),
    responses={
        200: {
            "description": "Target added successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "resolved_address": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
                    }
                }
            }
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid input, validation error, or duplicate address",
            "content": {
                "application/json": {
                    "examples": {
                        "duplicate": {
                            "summary": "Duplicate address",
                            "value": {"detail": "This 0x address is already in your watchlist."}
                        },
                        "invalid": {
                            "summary": "Invalid address",
                            "value": {"detail": "Must be a 42-character 0x Ethereum address."}
                        }
                    }
                }
            }
        }
    }
)
def add_to_watchlist(target: Target):
    """
    Add a wallet address to the watchlist for continuous monitoring.
    
    **What happens after adding:**
    - The Watcher daemon polls for new trades every 5 minutes
    - Trade alerts are sent via Discord/Telegram webhooks
    - You can profile the entity with AI analysis
    
    **Duplicate Prevention:** Addresses already on the watchlist will return a 400 error.
    """
    db = get_db()
    try:
        db.execute(
            "INSERT INTO watch_list (address, label, added_at) VALUES (?, ?, datetime('now'))",
            (target.address, target.label)
        )
        db.commit()
        return {"status": "success", "resolved_address": target.address}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to add target: {e}")
        raise HTTPException(status_code=400, detail="This 0x address is already in your watchlist.")
    finally:
        db.close()

@app.delete(
    "/watchlist/{address}",
    response_model=StatusResponse,
    summary="Remove Wallet from Watchlist",
    tags=["Watchlist"],
    description="Stop monitoring a wallet address. The Watcher daemon will no longer track this wallet.",
    responses={
        200: {
            "description": "Target removed successfully",
            "content": {
                "application/json": {
                    "example": {"status": "deleted"}
                }
            }
        },
        400: {"model": ErrorResponse, "description": "Invalid Ethereum address format"},
        500: {"model": ErrorResponse, "description": "Database error during deletion"}
    }
)
def remove_from_watchlist(
    address: str = Path(
        ...,
        description="42-character Ethereum proxy address to remove",
        pattern=r'^0x[0-9a-fA-F]{40}$',
        examples=["0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"]
    )
):
    """
    Remove a wallet address from the monitoring watchlist.
    
    This action is immediate. The Watcher daemon will stop polling
    this address on its next cycle (within 5 minutes).
    """
    _validate_address(address)
    db = get_db()
    try:
        db.execute("DELETE FROM watch_list WHERE address = ?", (address,))
        db.commit()
        return {"status": "deleted"}
    except Exception as e:
        log.error(f"Failed to delete target {address}: {e}")
        raise HTTPException(status_code=500, detail="Database error during deletion.")
    finally:
        db.close()
```
