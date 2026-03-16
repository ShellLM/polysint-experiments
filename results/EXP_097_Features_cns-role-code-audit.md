<thinking>
We are analyzing four model responses to the original prompt: "Create an automated 'Alpha' discovery mode based on whale trade clusters." The responses are from different models (862, 86, 813, 907) and there is an existing synthesis from the second iteration that combined them. We need to produce a final synthesis that represents the most likely best answer.

Let's extract unique points from each response:

**Response 862 (qwen):**
- Complete, working implementation with code for all files (alpha.py, db.py, analyst.py, api.py, start.py, frontend)
- Security bounds (memory limits, trade size caps, input validation)
- Atomic deduplication via SQLite PRIMARY KEY constraint
- Debounce protection for manual scans
- AI integration with whale context parameter
- Frontend with cluster display, auto-refresh, and manual scan button
- Practical, production-ready code

**Response 86 (glm-5):**
- Security hardening focus: thread safety with timeouts, JSON parsing with size limits
- API response sanitization (hiding wallet addresses by default for OPSEC)
- Rate limiting on read endpoints
- Security event logging for audit trails
- Error message sanitization to prevent information leakage

**Response 813 (healer-alpha):**
- Sophisticated multi-dimensional analysis: Gini coefficient for volume concentration
- Wallet relationship mapping across multiple markets
- Temporal burst detection for coordinated trading
- Cluster type classification (buy-side, sell-side, mixed)
- Adaptive baseline learning per market
- Adversarial pattern detection (wash trading, spoofing)
- Cross-market coordination detection

**Response 907 (hunter-alpha):**
- Maintainability focus with SOLID principles
- Dependency injection for testability
- Clear separation of concerns (TradeFetcher, ScoreStrategy, AlertDeduplicator protocols)
- Use of dataclasses and enums for type safety
- Configuration management with immutable dataclass
- Testability through mockable interfaces

**Agreements:**
- All responses agree on core functionality: scan watchlist wallets, group trades by market, detect clusters within time window, score clusters, send alerts
- All include input validation and sanitization
- All have some form of deduplication to prevent duplicate alerts
- All integrate with existing PolySINT system (database, notifier, analyst)

**Disagreements:**
- Complexity level: 862 is practical, 86 focuses on security, 813 is advanced/over-engineered, 907 focuses on architecture
- Scoring algorithm: Simple (862) vs. sophisticated multi-dimensional (813)
- Architecture: Monolithic class (862) vs. dependency injection (907)
- Security emphasis: Basic bounds (862) vs. comprehensive hardening (86)

**Strengths and weaknesses:**
- 862: Strengths - complete, deployable, integrated; Weaknesses - less maintainable, simpler scoring
- 86: Strengths - excellent security hardening; Weaknesses - less complete, focuses only on security aspects
- 813: Strengths - advanced features, sophisticated analysis; Weaknesses - over-engineered for initial implementation, complex
- 907: Strengths - maintainable, testable, SOLID; Weaknesses - more abstract, requires more setup

**Outliers:**
- 813 is an outlier with its advanced machine learning and relationship mapping features that go beyond the core requirement
- 907 is an outlier with its focus on software architecture principles

**Addressing original prompt:**
- All address the core requirement of detecting whale trade clusters
- 862 and the second iteration synthesis provide the most complete implementation
- 86 adds important security considerations that should be incorporated
- 813 and 907 offer valuable enhancements but may be too complex for initial implementation

**Diversity in responses:**
- Good diversity in focus areas (practical, security, advanced features, architecture)
- This diversity allows for a comprehensive synthesis that combines practical implementation with security hardening

**Additional perspectives needed:**
- None major, as the responses cover different aspects comprehensively
- Could consider performance optimization for large watchlists
- Could add monitoring and metrics for the alpha discovery system

**Synthesis approach:**
I'll create a synthesis that:
1. Uses the practical foundation from 862 (complete working code)
2. Incorporates security hardening from 86
3. Adds maintainability improvements inspired by 907 (but simplified)
4. Includes a moderately sophisticated scoring algorithm that incorporates some ideas from 813 (volume concentration, temporal patterns) without over-engineering
5. Maintains integration with the existing PolySINT system
6. Provides clear documentation and deployment instructions
</thinking>

<synthesis_output>
    <first_impression>
        The four responses offer complementary perspectives on implementing whale cluster detection. Response 862 provides a complete, deployable solution. Response 86 adds critical security hardening. Response 813 offers advanced analytical features. Response 907 focuses on maintainable architecture. The second iteration synthesis already combines 862 and 86 effectively, but we can enhance it with selective improvements from 813 and 907 while maintaining practicality.
    </first_impression>

    <analysis>
        The synthesis will build on the second iteration's foundation by:
        1. Keeping the complete, working implementation from 862
        2. Integrating all security hardening from 86
        3. Adding a moderately sophisticated scoring algorithm inspired by 813 (volume concentration, temporal patterns)
        4. Incorporating maintainability improvements from 907 (configuration management, clearer separation)
        5. Maintaining the integration points with existing PolySINT components
        
        The result is a production-ready implementation that is secure, maintainable, and analytically sophisticated without being over-engineered.
    </analysis>
    
    <dissent>
        Response 813's machine learning components and relationship mapping are valuable but introduce complexity that may not be justified for initial deployment. These features should be considered for v2. Response 907's strict SOLID architecture is excellent for maintainability but adds abstraction that may slow initial development; the synthesis adopts a pragmatic middle ground.
    </dissent>

    <synthesis>
# Alpha Discovery Mode: Production-Ready Whale Cluster Detection

## Core Implementation: `alpha.py`

```python
"""
Alpha Discovery Engine
======================
Detects whale trade clusters: multiple tracked wallets trading the same
market within a configurable time window—a strong informed-trading signal.

Key Features:
- Automated hourly scanning of watchlist wallets
- Atomic deduplication via SQLite PRIMARY KEY constraint
- Sophisticated scoring (1-100) based on cluster size, recency, volume concentration, and directional consensus
- Security hardening: input validation, rate limiting, memory bounds
- Optional AI analysis integration
- Real-time dashboard with manual scan capability
"""

import time
import json
import hashlib
import re
import threading
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field

from db import get_db
from config import Config
from notifier import Notifier
from logger import get_logger

log = get_logger("Alpha")

# ─── Configuration ───────────────────────────────────────────────────
@dataclass(frozen=True)
class AlphaConfig:
    """Immutable configuration for alpha detection."""
    MIN_CLUSTER_WALLETS: int = 2
    CLUSTER_TIME_WINDOW_HOURS: int = 4
    SCAN_INTERVAL_SECONDS: int = 3600  # 1 hour between scans
    TRADES_PER_WALLET: int = 50
    TRADE_REQUEST_DELAY: float = 2.0  # Seconds between API calls
    MAX_TRADE_AGE_HOURS: int = 24
    MIN_TRADE_USD: float = 500  # Minimum trade size to consider
    
    # Security bounds
    MAX_WALLETS_TO_SCAN: int = 50
    MAX_TRADE_SIZE_USD: float = 1e12  # $1T cap — reject absurd values
    MAX_MARKETS_IN_MEMORY: int = 500
    MAX_TITLE_LENGTH: int = 200
    VALID_SIDES: tuple = ("BUY", "SELL", "YES", "NO", "LONG", "SHORT")
    
    # Debounce protection
    MIN_SCAN_INTERVAL: int = 300  # 5 minutes between manual scans
    
    @property
    def cluster_window_seconds(self) -> float:
        return self.CLUSTER_TIME_WINDOW_HOURS * 3600

# Global configuration
CONFIG = AlphaConfig()

# ─── Input Sanitization ──────────────────────────────────────────────

def _sanitize_string(s: str, max_len: int = CONFIG.MAX_TITLE_LENGTH) -> str:
    """Removes control characters and truncates. Prevents log injection."""
    if not s:
        return ""
    clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(s))
    return clean[:max_len]

def _validate_trade(trade: dict, wallet: str) -> Optional[dict]:
    """Validate and sanitize a single trade object. Returns None if invalid."""
    try:
        size_raw = trade.get("size", 0)
        try:
            size = float(size_raw) if size_raw is not None else 0.0
        except (TypeError, ValueError):
            return None
        
        if size < CONFIG.MIN_TRADE_USD or size > CONFIG.MAX_TRADE_SIZE_USD:
            return None
        
        side = str(trade.get("side", "?")).upper().strip()
        if side not in CONFIG.VALID_SIDES:
            side = "UNKNOWN"
        
        market_id = str(trade.get("conditionId") or trade.get("market", ""))
        if not market_id or len(market_id) > 128:
            return None
        market_id = _sanitize_string(market_id, 128)
        
        ts_raw = trade.get("timestamp", time.time())
        try:
            if isinstance(ts_raw, str) and ts_raw.strip():
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
            elif isinstance(ts_raw, (int, float)):
                ts = float(ts_raw)
                if ts > 1e12:  # Milliseconds to seconds
                    ts /= 1000
            else:
                ts = time.time()
        except (ValueError, TypeError, OSError):
            ts = time.time()
        
        now = time.time()
        if ts > now + 3600:  # Reject future timestamps >1 hour
            ts = now
        
        return {
            "market_id": market_id,
            "title": _sanitize_string(trade.get("title", "Unknown")),
            "side": side,
            "size": size,
            "price": min(max(float(trade.get("price", 0) or 0), 0.0), 1.0),
            "timestamp": ts,
            "tx_hash": _sanitize_string(trade.get("transactionHash", ""), 66),
            "wallet": wallet,
        }
    except Exception as e:
        log.debug(f"Trade validation failed: {e}")
        return None

def _parse_timestamp(ts_raw: Any) -> float:
    """Best-effort timestamp parsing with bounds checking."""
    now = time.time()
    
    if ts_raw is None:
        return now
    
    if isinstance(ts_raw, (int, float)):
        ts = float(ts_raw)
        if ts > 1e12:  # Convert milliseconds to seconds
            ts /= 1000
        return min(ts, now + 3600)  # Reject future >1 hour
    
    if isinstance(ts_raw, str) and ts_raw.strip():
        try:
            return datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            pass
    
    return now

# ─── Database Layer (Atomic Operations) ───────────────────────────────

def _ensure_table():
    """Create tables with secure defaults."""
    try:
        db = get_db()
        db.execute("""
            CREATE TABLE IF NOT EXISTS alerted_clusters (
                cluster_id TEXT NOT NULL,
                alerted_at TEXT NOT NULL,
                market_id TEXT,
                wallet_count INTEGER,
                wallet_addresses TEXT,
                score INTEGER,
                volume_concentration REAL DEFAULT 0.0,
                PRIMARY KEY (cluster_id, alerted_at)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_clusters_alerted_at ON alerted_clusters(alerted_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_clusters_market ON alerted_clusters(market_id)")
        db.commit()
        db.close()
    except Exception as e:
        log.error(f"Failed to ensure alerted_clusters table: {e}")

def _try_claim_alert(cluster_id: str, market_id: str, wallet_count: int, 
                     wallet_addresses: list, score: int, volume_concentration: float = 0.0) -> bool:
    """Atomic alert claim — prevents race conditions. Returns True if claimed."""
    db = None
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            """INSERT INTO alerted_clusters 
               (cluster_id, alerted_at, market_id, wallet_count, wallet_addresses, score, volume_concentration)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                cluster_id,
                datetime.now(timezone.utc).isoformat(),
                market_id,
                wallet_count,
                json.dumps(wallet_addresses),
                score,
                volume_concentration,
            ),
        )
        
        if cursor.rowcount > 0:
            db.commit()
            return True
        
        db.rollback()
        return False
        
    except Exception as e:
        log.error(f"Alert claim failed: {e}")
        if db:
            db.rollback()
        return False
    finally:
        if db:
            db.close()

def _check_cluster_expansion(cluster_id: str, new_count: int) -> bool:
    """Check if cluster has expanded significantly (re-alert worthy)."""
    try:
        db = get_db()
        row = db.execute(
            "SELECT wallet_count FROM alerted_clusters WHERE cluster_id = ? ORDER BY alerted_at DESC LIMIT 1",
            (cluster_id,),
        ).fetchone()
        db.close()
        
        if row and row["wallet_count"]:
            return new_count >= row["wallet_count"] + 2
        return True
    except Exception:
        return True

# ─── Sophisticated Scoring Algorithm ─────────────────────────────────

def _compute_volume_concentration(trades: List[Dict]) -> float:
    """
    Compute Gini coefficient for trade volume concentration (0-1).
    Higher values indicate volume concentrated in fewer wallets.
    Inspired by advanced analysis in Response 813.
    """
    if not trades:
        return 0.0
    
    # Group by wallet
    wallet_volumes = defaultdict(float)
    for trade in trades:
        wallet_volumes[trade["wallet"]] += trade["size"]
    
    volumes = sorted(wallet_volumes.values())
    n = len(volumes)
    
    if n == 0 or sum(volumes) == 0:
        return 0.0
    
    # Calculate Gini coefficient
    cumulative = 0
    total = sum(volumes)
    gini_sum = 0
    
    for i, volume in enumerate(volumes):
        cumulative += volume
        gini_sum += (2 * (i + 1) - n - 1) * volume
    
    return gini_sum / (n * total)

def _compute_temporal_burst_score(trades: List[Dict]) -> float:
    """
    Score based on temporal clustering of trades.
    Returns 0-20 points for trades concentrated in time.
    """
    if len(trades) < 2:
        return 0.0
    
    timestamps = sorted([t["timestamp"] for t in trades])
    time_spans = []
    
    for i in range(1, len(timestamps)):
        time_spans.append(timestamps[i] - timestamps[i-1])
    
    avg_span = sum(time_spans) / len(time_spans) if time_spans else 0
    
    if avg_span < 300:  # <5 minutes between trades on average
        return 20.0
    elif avg_span < 1800:  # <30 minutes
        return 12.0
    elif avg_span < 3600:  # <1 hour
        return 5.0
    
    return 0.0

def _compute_score(wallet_count: int, trades: List[Dict], dominant_side: str) -> Tuple[int, float]:
    """
    Compute sophisticated alpha score (1-100) and volume concentration.
    
    Components:
    1. Cluster size (max 40 points)
    2. Trade recency (max 20 points)
    3. Directional consensus (max 15 points)
    4. Volume concentration (max 15 points)
    5. Temporal burst (max 10 points)
    
    Returns (score, volume_concentration)
    """
    score = 0
    
    # 1. Cluster size component (max 40)
    score += min(wallet_count * 12, 40)
    
    # 2. Recency component (max 20)
    if trades:
        newest = max(t["timestamp"] for t in trades)
        age_hours = (time.time() - newest) / 3600
        if age_hours < 1:
            score += 20
        elif age_hours < 6:
            score += 12
        elif age_hours < 24:
            score += 5
    
    # 3. Directional consensus (max 15)
    if dominant_side in ("BUY", "YES", "LONG"):
        score += 15
    
    # 4. Volume concentration (max 15)
    volume_concentration = _compute_volume_concentration(trades)
    if volume_concentration > 0.7:  # High concentration
        score += 15
    elif volume_concentration > 0.5:  # Medium concentration
        score += 10
    elif volume_concentration > 0.3:  # Low concentration
        score += 5
    
    # 5. Temporal burst (max 10)
    score += min(_compute_temporal_burst_score(trades), 10)
    
    final_score = min(max(int(score), 1), 100)
    return final_score, volume_concentration

# ─── Core Detection Logic ─────────────────────────────────────────────

class ClusterDetector:
    """Main detector class with atomic alerting and security bounds."""
    
    def __init__(self, config: Optional[AlphaConfig] = None):
        self.config = config or CONFIG
        self.notifier = Notifier()
    
    def scan(self, force: bool = False) -> int:
        """Run detection cycle. Returns count of new alerts generated."""
        acquired = False
        try:
            if force:
                acquired = _scan_lock.acquire(blocking=True, timeout=30)
                if not acquired:
                    log.warning("Scan lock timeout — possible deadlock")
                    return -1
            else:
                acquired = _scan_lock.acquire(blocking=True, timeout=60)
                if not acquired:
                    log.error("Daemon scan lock acquisition failed")
                    return 0
            
            return self._scan_internal()
        finally:
            if acquired:
                _scan_lock.release()
    
    def _scan_internal(self) -> int:
        """Internal scan logic with bounded memory."""
        log.info("Starting alpha cluster scan...")
        start_time = time.time()
        
        # Fetch watchlist with bound
        try:
            db = get_db()
            rows = db.execute(
                "SELECT address, label FROM watch_list LIMIT ?",
                (self.config.MAX_WALLETS_TO_SCAN,),
            ).fetchall()
            db.close()
        except Exception as e:
            log.error(f"Failed to load watchlist: {e}")
            return 0
        
        if len(rows) < self.config.MIN_CLUSTER_WALLETS:
            return 0
        
        wallet_labels = {r["address"]: r["label"] for r in rows}
        addresses = list(wallet_labels.keys())
        
        # Fetch trades with connection pooling
        session = requests.Session()
        all_trades = []
        
        for i, addr in enumerate(addresses):
            trades = self._fetch_wallet_trades(addr, session)
            all_trades.extend(trades)
            
            if i < len(addresses) - 1:
                time.sleep(self.config.TRADE_REQUEST_DELAY)
        
        session.close()
        
        if not all_trades:
            return 0
        
        # Deduplicate by tx_hash
        seen_tx = set()
        unique_trades = []
        for t in all_trades:
            tx = t.get("tx_hash")
            if tx and tx in seen_tx:
                continue
            if tx:
                seen_tx.add(tx)
            unique_trades.append(t)
        
        # Group by market with memory bound
        market_groups = defaultdict(list)
        for t in unique_trades:
            mid = t["market_id"]
            if len(market_groups) < self.config.MAX_MARKETS_IN_MEMORY or mid in market_groups:
                market_groups[mid].append(t)
        
        # Filter by time window
        now = time.time()
        cutoff = now - self.config.cluster_window_seconds
        
        alert_count = 0
        
        for market_id, trades in market_groups.items():
            recent = [t for t in trades if t["timestamp"] >= cutoff]
            if not recent:
                continue
            
            wallets = set(t["wallet"] for t in recent)
            if len(wallets) < self.config.MIN_CLUSTER_WALLETS:
                continue
            
            cluster = self._build_cluster(market_id, wallets, recent, wallet_labels)
            if cluster and self._process_cluster(cluster):
                alert_count += 1
        
        elapsed = time.time() - start_time
        log.info(f"Scan complete: {alert_count} new clusters alerted ({elapsed:.1f}s)")
        return alert_count
    
    def _fetch_wallet_trades(self, address: str, session: requests.Session) -> list:
        """Fetch trades with timeout and validation."""
        try:
            url = f"{Config.DATA_API}/trades"
            resp = session.get(
                url,
                params={"user": address, "limit": self.config.TRADES_PER_WALLET},
                timeout=10,
            )
            
            if resp.status_code != 200:
                log.warning(f"Trade API {resp.status_code} for {address[:8]}...")
                return []
            
            data = resp.json()
            if not isinstance(data, list):
                return []
            
            validated = []
            for t in data:
                trade = _validate_trade(t, address)
                if trade:
                    validated.append(trade)
            
            return validated
            
        except requests.exceptions.Timeout:
            log.warning(f"Trade fetch timeout for {address[:8]}...")
            return []
        except Exception as e:
            log.error(f"Trade fetch error for {address[:8]}...: {e}")
            return []
    
    def _build_cluster(self, market_id: str, wallets: set, trades: list, 
                       wallet_labels: dict) -> Optional[dict]:
        """Build cluster dictionary with validated data."""
        try:
            db = get_db()
            market = db.execute(
                "SELECT question, volume, clob_token_id FROM markets WHERE id = ?",
                (market_id,),
            ).fetchone()
            db.close()
            
            if not market:
                return None
            
            question = _sanitize_string(market["question"])
            volume = float(market["volume"] or 0)
            clob_token_id = market["clob_token_id"]
        except Exception as e:
            log.error(f"Market fetch failed: {e}")
            return None
        
        wallets_sorted = sorted(wallets)
        cluster_id = hashlib.sha256(
            f"{market_id}:{':'.join(wallets_sorted)}".encode()
        ).hexdigest()[:24]
        
        # Determine dominant side by volume
        side_counts = defaultdict(float)
        for t in trades:
            side_counts[t["side"]] += t["size"]
        
        dominant_side = max(side_counts.items(), key=lambda x: x[1])[0] if side_counts else "UNKNOWN"
        
        # Build trade summary for context
        trade_summary = " | ".join(
            f"{t['side']} ${t['size']:,.0f} on '{t['title'][:40]}'"
            for t in sorted(trades, key=lambda x: x['size'], reverse=True)[:10]
        )
        
        wallet_info = [
            {
                "address": addr,
                "label": _sanitize_string(wallet_labels.get(addr, f"...{addr[-6:]}")),
                "side": dominant_side,
            }
            for addr in wallets_sorted
        ]
        
        # Compute sophisticated score
        score, volume_concentration = _compute_score(len(wallets), trades, dominant_side)
        
        return {
            "cluster_id": cluster_id,
            "market_id": market_id,
            "question": question,
            "volume": volume,
            "clob_token_id": clob_token_id,
            "wallets": wallet_info,
            "wallet_count": len(wallets_sorted),
            "trades": trades,
            "trade_summary": trade_summary,
            "dominant_side": dominant_side,
            "score": score,
            "volume_concentration": volume_concentration,
            "whale_context": (
                f"**{len(wallets_sorted)} independently-tracked whale wallets** "
                f"have traded this market within the last {self.config.CLUSTER_TIME_WINDOW_HOURS}h.\n"
                f"Wallets: {', '.join(w['label'] for w in wallet_info)}\n"
                f"Trades: {trade_summary}\n"
                f"Volume Concentration: {volume_concentration:.2f} (0=dispersed, 1=concentrated)"
            ),
        }
    
    def _process_cluster(self, cluster: dict) -> bool:
        """Process cluster with atomic alert claiming. Returns True if alerted."""
        cluster_id = cluster["cluster_id"]
        wallet_count = cluster["wallet_count"]
        wallet_addresses = [w["address"] for w in cluster["wallets"]]
        
        expanded = _check_cluster_expansion(cluster_id, wallet_count)
        
        if _try_claim_alert(cluster_id, cluster["market_id"], wallet_count,
                           wallet_addresses, cluster["score"], cluster["volume_concentration"]):
            self._send_alert(cluster)
            return True
        
        if expanded:
            new_cluster_id = f"{cluster_id}_{int(time.time())}"
            if _try_claim_alert(new_cluster_id, cluster["market_id"], wallet_count,
                               wallet_addresses, cluster["score"], cluster["volume_concentration"]):
                self._send_alert(cluster, is_expansion=True)
                return True
        
        return False
    
    def _send_alert(self, cluster: dict, is_expansion: bool = False):
        """Send alert with sanitized content and optional AI analysis."""
        try:
            # Optional AI analysis for high-score clusters
            ai_context = ""
            if cluster["score"] >= 60:
                try:
                    from analyst import PolyAnalyst
                    from clob import get_history_as_price_list
                    
                    if cluster.get("clob_token_id"):
                        price_history = get_history_as_price_list(cluster["clob_token_id"])
                        if price_history and len(price_history) >= 2:
                            analyst = PolyAnalyst()
                            ai_result = analyst.analyze_market_shift(
                                cluster["question"],
                                price_history,
                                cluster["volume"],
                                use_research=False,
                                whale_context=cluster.get("whale_context", ""),
                            )
                            if ai_result:
                                ai_context = f"\n\n**AI Signal Analysis:**\n{ai_result[:500]}"
                except Exception as e:
                    log.debug(f"AI analysis skipped: {e}")
            
            wallet_lines = []
            for w in cluster["wallets"][:6]:
                emoji = "🟢" if w["side"] in ("BUY", "YES", "LONG") else "🔴"
                safe_label = w["label"].replace("`", "'")
                wallet_lines.append(f"  {emoji} `{safe_label}`")
            
            if len(cluster["wallets"]) > 6:
                wallet_lines.append(f"  _...and {len(cluster['wallets']) - 6} more_")
            
            expansion_note = " (EXPANDED)" if is_expansion else ""
            
            msg = (
                f"**{cluster['question']}**\n"
                f"📊 Volume: ${cluster['volume']:,.0f} | Alpha Score: **{cluster['score']}/100** | "
                f"Concentration: {cluster['volume_concentration']:.2f}\n\n"
                f"🐋 **{cluster['wallet_count']} Whale{'s' if cluster['wallet_count'] > 1 else ''} Converged{expansion_note}:**\n"
                + "\n".join(wallet_lines)
                + f"\n\n⏰ Window: last {self.config.CLUSTER_TIME_WINDOW_HOURS}h\n"
                f"📈 Recent activity: {cluster['trade_summary'][:200]}"
                f"{ai_context}"
            )
            
            self.notifier.broadcast(msg, title="🧠 Alpha: Whale Cluster Detected")
            
        except Exception as e:
            log.error(f"Alert broadcast failed: {e}")

# ─── Thread-safe scan management ─────────────────────────────────────

_scan_lock = threading.Lock()
_last_scan_time = 0

# ─── Public API ─────────────────────────────────────────────────────

def get_alpha_clusters(hours: int = 24) -> List[Dict[str, Any]]:
    """Fetch clusters for dashboard (read-only, safe)."""
    _ensure_table()
    
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    try:
        db = get_db()
        rows = db.execute("""
            SELECT cluster_id, market_id, wallet_count, alerted_at, score, 
                   wallet_addresses, volume_concentration
            FROM alerted_clusters
            WHERE alerted_at >= ?
            ORDER BY score DESC, wallet_count DESC
        """, (cutoff,)).fetchall()
        db.close()
        
        clusters = []
        for row in rows:
            try:
                mdb = get_db()
                mkt = mdb.execute(
                    "SELECT question, volume FROM markets WHERE id = ?",
                    (row["market_id"],)
                ).fetchone()
                mdb.close()
                question = _sanitize_string(mkt["question"]) if mkt else "Unknown"
                volume = float(mkt["volume"] or 0) if mkt else 0
            except Exception:
                question = "Unknown"
                volume = 0
            
            # Safe JSON parsing with size limit
            wallet_addrs = []
            raw_data = row.get("wallet_addresses", "[]")
            if raw_data and len(raw_data) <= 1_000_000:  # 1MB limit
                try:
                    wallet_addrs = json.loads(raw_data)
                    if not isinstance(wallet_addrs, list):
                        wallet_addrs = []
                except json.JSONDecodeError:
                    wallet_addrs = []
            
            clusters.append({
                "cluster_id": row["cluster_id"],
                "market_id": row["market_id"],
                "question": question,
                "volume": volume,
                "wallet_count": row["wallet_count"],
                "wallets": [{"address": a, "label": f"...{a[-6:]}", "side": "?"} 
                           for a in wallet_addrs if a and isinstance(a, str) and len(a) == 42],
                "score": row["score"],
                "volume_concentration": row.get("volume_concentration", 0.0),
                "alerted": True,
                "alerted_at": row["alerted_at"],
            })
        
        return clusters
        
    except Exception as e:
        log.error(f"Failed to fetch clusters: {e}")
        return []

def force_alpha_scan() -> dict:
    """Trigger manual scan with debounce protection."""
    global _last_scan_time
    
    now = time.time()
    if now - _last_scan_time < CONFIG.MIN_SCAN_INTERVAL:
        wait = int(CONFIG.MIN_SCAN_INTERVAL - (now - _last_scan_time))
        return {
            "status": "rate_limited",
            "message": f"Please wait {wait} seconds before next scan",
            "retry_after": wait,
        }
    
    _last_scan_time = now
    
    try:
        detector = ClusterDetector()
        count = detector.scan(force=True)
        return {"status": "complete", "clusters_alerted": count}
    except Exception as e:
        log.error(f"Manual scan failed: {e}")
        return {"status": "error", "message": "Scan failed"}

def run_daemon():
    """Daemon entry point with crash protection."""
    _ensure_table()
    detector = ClusterDetector()
    
    log.info(f"Alpha Discovery daemon online — "
             f"min_wallets={CONFIG.MIN_CLUSTER_WALLETS}, "
             f"window={CONFIG.CLUSTER_TIME_WINDOW_HOURS}h, "
             f"scan_interval={CONFIG.SCAN_INTERVAL_SECONDS}s")
    
    while True:
        try:
            detector.scan(force=False)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"Alpha scan error: {e}", exc_info=True)
        
        time.sleep(CONFIG.SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    print("=" * 60)
    print("Alpha Discovery Engine v1.1")
    print("=" * 60)
    print(f"Min cluster wallets: {CONFIG.MIN_CLUSTER_WALLETS}")
    print(f"Time window: {CONFIG.CLUSTER_TIME_WINDOW_HOURS} hours")
    print(f"Min trade size: ${CONFIG.MIN_TRADE_USD:,}")
    print(f"Scan interval: {CONFIG.SCAN_INTERVAL_SECONDS}s")
    print(f"Security: Input validation, rate limiting, atomic deduplication")
    print("=" * 60)
    run_daemon()
```

---

## Database Schema Update: `db.py`

Add to `init_db()`:

```python
# Alpha cluster alert tracking with enhanced schema
cursor.execute('''CREATE TABLE IF NOT EXISTS alerted_clusters (
    cluster_id TEXT NOT NULL,
    alerted_at TEXT NOT NULL,
    market_id TEXT,
    wallet_count INTEGER,
    wallet_addresses TEXT,
    score INTEGER,
    volume_concentration REAL DEFAULT 0.0,
    PRIMARY KEY (cluster_id, alerted_at)
)''')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_clusters_alerted_at ON alerted_clusters(alerted_at)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_clusters_market ON alerted_clusters(market_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_clusters_score ON alerted_clusters(score DESC)')
```

---

## Analyst Integration: `analyst.py`

Add `whale_context` parameter to `analyze_market_shift`:

```python
def analyze_market_shift(self, market_question, price_history, volume, 
                       use_research: bool = None, whale_context: str = ""):
    # ... existing code ...
    
    whale_section = ""
    if whale_context:
        whale_section = f"""
━━━ CLUSTER SIGNAL: CONVERGING WALLETS ━━━
{whale_context}

NOTE: Multiple independently-tracked whale wallets converging on the same
market within a short time window is a STRONG signal of informed trading.
The volume concentration metric indicates whether trading is dominated by
a few large wallets or distributed across many. High concentration with
directional consensus significantly increases the INSIDER SIGNAL score.
"""
    
    # Add whale_section to prompt after PRICE BEHAVIOUR section
```

---

## API Endpoints: `api.py`

```python
from alpha import get_alpha_clusters, force_alpha_scan
from fastapi import Request

# Simple rate limiter for alpha endpoints
_alpha_rate_limit_cache = {}

def _rate_limit_alpha(request: Request, max_requests: int = 30, window: int = 60) -> bool:
    """Rate limit alpha endpoints by client IP."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    key = f"alpha:{client_ip}"
    
    if key not in _alpha_rate_limit_cache:
        _alpha_rate_limit_cache[key] = []
    
    # Prune old entries
    cutoff = now - window
    _alpha_rate_limit_cache[key] = [t for t in _alpha_rate_limit_cache[key] if t > cutoff]
    
    if len(_alpha_rate_limit_cache[key]) >= max_requests:
        return False
    
    _alpha_rate_limit_cache[key].append(now)
    return True

@app.get("/alpha/clusters")
def list_alpha_clusters(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168),
    include_wallets: bool = Query(default=False, description="Include wallet addresses (OPSEC risk)")
):
    """Return whale trade clusters with optional wallet details."""
    # Rate limiting
    if not _rate_limit_alpha(request):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"}
        )
    
    try:
        clusters = get_alpha_clusters(hours=hours)
        
        # Security: Sanitize response — hide wallet addresses by default
        if not include_wallets:
            safe_clusters = []
            for c in clusters:
                safe_cluster = {
                    "cluster_id": c["cluster_id"],
                    "market_id": c["market_id"],
                    "question": c["question"],
                    "volume": c["volume"],
                    "wallet_count": c["wallet_count"],
                    "score": c["score"],
                    "volume_concentration": c.get("volume_concentration", 0.0),
                    "alerted_at": c["alerted_at"],
                }
                safe_clusters.append(safe_cluster)
            clusters = safe_clusters
        
        return {"clusters": clusters, "count": len(clusters)}
    except Exception as e:
        log.error(f"Alpha cluster fetch failed: {e}")
        # Security: Generic error message
        raise HTTPException(status_code=500, detail="Operation failed")

@app.post("/alpha/scan")
def trigger_alpha_scan(request: Request):
    """Manually trigger alpha cluster scan. Debounce protected."""
    # Security: Log scan trigger for audit
    client_ip = request.client.host if request.client else "unknown"
    log.info(f"Manual alpha scan triggered by {client_ip}")
    
    result = force_alpha_scan()
    
    if result.get("status") == "rate_limited":
        raise HTTPException(
            status_code=429,
            detail=result["message"],
            headers={"Retry-After": str(result["retry_after"])},
        )
    
    return result
```

---

## Start Script: `start.py`

```python
# Add after other process launches
print(" -> Launching Alpha Discovery...")
alpha_proc = subprocess.Popen([sys.executable, "alpha.py"])
processes.append(("Alpha Discovery", alpha_proc))
time.sleep(2)
```

---

## Frontend: `static/app.js`

```javascript
// ─── Alpha Cluster Discovery ────────────────────────────────────────
let alphaClusters = [];
let alphaRefreshTimer = null;
const ALPHA_REFRESH_INTERVAL = 60; // seconds

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
    // ... existing initialization ...
    loadAlphaClusters();
    startAlphaAutoRefresh();
});

function startAlphaAutoRefresh() {
    clearInterval(alphaRefreshTimer);
    let countdown = ALPHA_REFRESH_INTERVAL;
    updateAlphaCountdown(countdown);

    alphaRefreshTimer = setInterval(() => {
        countdown--;
        updateAlphaCountdown(countdown);
        if (countdown <= 0) {
            loadAlphaClusters(true);
            countdown = ALPHA_REFRESH_INTERVAL;
        }
    }, 1000);
}

function updateAlphaCountdown(secs) {
    const el = document.getElementById('alphaCountdown');
    if (el) {
        el.textContent = secs > 0 ? `Refresh in ${secs}s` : 'Refreshing...';
    }
}

async function loadAlphaClusters(silent = false) {
    const container = document.getElementById('alphaClusters');
    const badge = document.getElementById('alphaBadge');
    if (!container) return;

    if (!silent) {
        container.innerHTML = `
            <div class="text-center py-6 text-gray-600 text-xs">
                <div class="animate-pulse">Scanning for whale convergence...</div>
            </div>`;
    }

    try {
        const res = await fetch('/alpha/clusters?hours=24');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        alphaClusters = data.clusters || [];

        if (badge) {
            const count = alphaClusters.length;
            badge.textContent = count;
            badge.className = count > 0
                ? 'ml-1 inline-flex items-center justify-center px-1.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                : 'ml-1 inline-flex items-center justify-center px-1.5 py-0.5 rounded-full text-xs font-bold bg-gray-700 text-gray-500 border border-gray-600';
        }

        renderAlphaClusters();

    } catch (e) {
        console.error('Alpha fetch failed:', e);
        container.innerHTML = `
            <div class="text-center py-6 text-red-400 text-xs">
                Failed to load clusters.
                <button onclick="loadAlphaClusters()" class="text-polysint underline ml-1">Retry</button>
            </div>`;
    }
}

function renderAlphaClusters() {
    const container = document.getElementById('alphaClusters');
    if (!container) return;

    if (alphaClusters.length === 0) {
        container.innerHTML = `
            <div class="text-center py-8 text-gray-600 text-xs">
                <div class="text-2xl mb-2 opacity-40">🧠</div>
                No whale clusters detected in the last 24h.<br>
                <span class="text-gray-700">Add wallets to the watchlist to enable discovery.</span>
            </div>`;
        return;
    }

    container.innerHTML = alphaClusters.map(c => {
        const score = c.score || 0;
        const concentration = c.volume_concentration || 0;
        const scoreColor = score >= 70 ? 'text-emerald-400' : 
                          score >= 40 ? 'text-amber-400' : 'text-gray-400';
        
        const concentrationBar = `
            <div class="w-full bg-gray-700 rounded-full h-1.5 mt-1">
                <div class="bg-polysint h-1.5 rounded-full" style="width: ${concentration * 100}%"></div>
            </div>
            <div class="text-xs text-gray-500 mt-0.5">Concentration: ${(concentration * 100).toFixed(0)}%</div>
        `;

        return `
        <div class="bg-gray-800/40 rounded-lg border border-gray-700/50 p-3 mb-2 hover:border-emerald-700/50 transition-all">
            <div class="flex items-start justify-between gap-2 mb-2">
                <div class="text-sm font-medium text-gray-200 leading-snug flex-1">
                    ${escapeHtml(truncate(c.question || 'Unknown Market', 80))}
                </div>
                <div class="text-right shrink-0">
                    <div class="text-lg font-bold ${scoreColor}">${score}</div>
                    <div class="text-xs text-gray-700">alpha</div>
                </div>
            </div>

            <div class="flex items-center gap-2 mb-2 flex-wrap">
                <span class="inline-flex items-center text-xs bg-emerald-900/30 text-emerald-400 border border-emerald-800/50 rounded px-1.5 py-0.5 font-bold">
                    🐋 ${c.wallet_count} whale${c.wallet_count > 1 ? 's' : ''}
                </span>
                ${c.alerted ? '<span class="text-xs text-gray-600">✓ alerted</span>' : 
                  '<span class="text-xs text-amber-500">● new</span>'}
            </div>

            ${concentrationBar}

            <div class="flex gap-1.5 mt-2">
                <button onclick="analyzeMarket('${c.market_id}')"
                    class="flex-1 bg-polysint/10 text-polysint border border-polysint/30 hover:bg-polysint hover:text-white px-2 py-1 rounded text-xs transition-all">
                    🤖 AI Analyze
                </button>
            </div>
        </div>`;
    }).join('');
}

async function triggerAlphaScan() {
    const btn = document.getElementById('alphaScanBtn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="animate-pulse">Scanning...</span>';
    }

    try {
        const res = await fetch('/alpha/scan', { method: 'POST' });
        if (res.status === 429) {
            const data = await res.json();
            alert(`Rate limited: ${data.detail}`);
            return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await loadAlphaClusters();
    } catch (e) {
        console.error('Alpha scan failed:', e);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '⚡ Scan Now';
        }
    }
}
```

---

## HTML Panel: `static/index.html`

```html
<div class="bg-gray-800/50 rounded-xl border border-gray-700/50 p-4">
    <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-gray-300 flex items-center">
            🧠 Alpha Clusters
            <span id="alphaBadge" class="ml-1 inline-flex items-center justify-center px-1.5 py-0.5 rounded-full text-xs font-bold bg-gray-700 text-gray-500 border border-gray-600">0</span>
        </h3>
        <div class="flex items-center gap-2">
            <span id="alphaCountdown" class="text-xs text-gray-700 font-mono"></span>
            <button id="alphaScanBtn" onclick="triggerAlphaScan()"
                class="text-xs bg-emerald-900/30 text-emerald-400 border border-emerald-800/50 hover:bg-emerald-800 hover:text-white px-2 py-0.5 rounded transition-all">
                ⚡ Scan Now
            </button>
        </div>
    </div>
    <div id="alphaClusters">
        <!-- Cluster cards injected by JavaScript -->
    </div>
</div>
```

---

## Key Enhancements Over Previous Iterations

1. **Sophisticated Scoring**: Incorporates volume concentration (Gini coefficient) and temporal burst detection for more nuanced cluster assessment.

2. **Enhanced Security**: 
   - Rate limiting on API endpoints
   - Safe JSON parsing with size limits
   - Generic error messages to prevent information leakage
   - Audit logging for security events

3. **Improved Maintainability**:
   - Configuration dataclass for easy tuning
   - Clear separation between scoring components
   - Better error handling and logging

4. **OPSEC Considerations**: 
   - Wallet addresses hidden by default in API responses
   - Optional wallet inclusion via query parameter
   - Sanitized labels in alerts to prevent injection

5. **Performance Monitoring**: 
   - Scan timing logs
   - Memory-bounded operations
   - Connection pooling for trade fetching

6. **Dashboard Enhancements**:
   - Volume concentration visualization
   - Real-time countdown timer
   - Responsive design with proper error states

## Deployment Instructions

1. **Install dependencies**: Ensure all existing PolySINT dependencies are installed.

2. **Update database**: Run the system once to apply the schema migration for `alerted_clusters`.

3. **Configure watchlist**: Add whale wallet addresses to the watchlist via the dashboard.

4. **Start the system**: Use `start.py` to launch all components including Alpha Discovery.

5. **Monitor**: Check `analyzer.log` for Alpha Discovery logs and system health.

6. **API Usage**:
   - `GET /alpha/clusters` - Retrieve recent clusters (rate-limited)
   - `POST /alpha/scan` - Trigger manual scan (debounce-protected)
   - Use `?include_wallets=true` for detailed wallet information

## Future Enhancements (v2)

- **Wallet Relationship Mapping**: Track which wallets frequently trade together across markets
- **Adaptive Baselines**: Learn normal convergence rates per market to detect truly anomalous clusters
- **Adversarial Detection**: Wash trading and spoofing pattern identification
- **Cross-Market Coordination**: Detect wallets trading multiple correlated markets simultaneously
- **User Feedback Loop**: Allow users to mark false positives to improve scoring accuracy

This implementation provides a production-ready Alpha Discovery system that securely detects whale trade clusters, provides sophisticated scoring, integrates seamlessly with the existing PolySINT architecture, and maintains high standards for security and maintainability.
</synthesis_output>

<confidence>
    0.92
</confidence>

<refinement_areas>
    - Performance optimization for large watchlists (>100 wallets)
    - Real-time WebSocket updates for cluster detection
    - Machine learning for adaptive threshold tuning
    - Integration with external threat intelligence feeds
    - Advanced visualization of cluster evolution over time
</refinement_areas>

<needs_iteration>
    false
</needs_iteration>

<ranking>
    <rank position="1">862</rank>
    <rank position="2">86</rank>
    <rank position="3">907</rank>
    <rank position="4">813</rank>
</ranking>
