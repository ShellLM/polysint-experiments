2026-03-15 15:50:34,613 - llm_consortium.orchestrator - ERROR - Automatic response error for glm-5-chutes: The read operation timed out
# Multi-Chain Microservices Bridge for PolySINT

## Architecture Overview

The solution implements a modular adapter-based architecture that abstracts chain-specific logic while preserving all existing Polygon/Polymarket functionality. New chains are supported by implementing a standard adapter interface and registering in a dynamic registry.

## Core Components

### 1. Abstract Adapter Interface (`adapters/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum

class ChainType(Enum):
    POLYGON = "polygon"
    ETHEREUM = "ethereum"
    ARBITRUM = "arbitrum"
    SOLANA = "solana"
    # Extend as needed

class ProtocolType(Enum):
    POLYMARKET = "polymarket"
    AUGUR = "augur"
    AZURO = "azuro"
    # Extend as needed

@dataclass
class Market:
    id: str
    chain: str
    protocol: str
    question: str
    outcomes: List[str]
    volume: float
    created_at: datetime
    # Chain-specific metadata
    metadata: Dict[str, Any] = None

@dataclass
class PricePoint:
    timestamp: datetime
    price: float
    market_id: str
    chain: str

@dataclass
class WalletProfile:
    address: str
    chain: str
    real_owner: Optional[str] = None
    is_proxy: bool = False
    metadata: Dict[str, Any] = None

class ChainAdapter(ABC):
    """Abstract base class for all chain adapters."""
    
    @abstractmethod
    def health_check(self) -> bool:
        """Check if adapter is operational."""
        pass
    
    @abstractmethod
    def harvest_markets(self, limit: int = 1000) -> List[Market]:
        """Fetch active markets from this chain."""
        pass
    
    @abstractmethod
    def get_price_history(self, market_id: str, interval: str = "1d") -> List[PricePoint]:
        """Get historical price data."""
        pass
    
    @abstractmethod
    def unmask_wallet(self, address: str) -> WalletProfile:
        """Resolve proxy wallets to real owners."""
        pass
    
    @abstractmethod
    def get_wallet_trades(self, address: str, limit: int = 20) -> List[Dict]:
        """Fetch recent trades for a wallet."""
        pass
```

### 2. Dynamic Chain Registry (`adapters/registry.py`)

```python
import importlib
import json
from typing import Dict, Optional, List
from db import get_db
from logger import get_logger

log = get_logger("ChainRegistry")

class ChainRegistry:
    _instance = None
    _adapters: Dict[str, 'ChainAdapter'] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def initialize(self):
        """Load enabled adapters from database."""
        db = get_db()
        try:
            rows = db.execute("""
                SELECT chain_id, chain_name, protocol, adapter_class, config_json 
                FROM chain_adapters WHERE enabled = TRUE
            """).fetchall()
            
            for row in rows:
                self._load_adapter(
                    row['chain_id'],
                    row['adapter_class'],
                    json.loads(row['config_json'] or '{}')
                )
        finally:
            db.close()
    
    def _load_adapter(self, chain_id: str, adapter_class_path: str, config: Dict):
        """Dynamically load and initialize an adapter."""
        try:
            module_path, class_name = adapter_class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            adapter_class = getattr(module, class_name)
            adapter = adapter_class(config)
            self._adapters[chain_id] = adapter
            log.info(f"Loaded adapter for {chain_id}")
        except Exception as e:
            log.error(f"Failed to load adapter {chain_id}: {e}")
    
    def get_adapter(self, chain_id: str) -> Optional['ChainAdapter']:
        return self._adapters.get(chain_id)
    
    def get_all_adapters(self) -> List['ChainAdapter']:
        return list(self._adapters.values())
    
    def enable_chain(self, chain_id: str) -> bool:
        """Enable a chain in database and load adapter."""
        db = get_db()
        try:
            db.execute("UPDATE chain_adapters SET enabled = TRUE WHERE chain_id = ?", (chain_id,))
            db.commit()
            self.initialize()  # Reload all adapters
            return True
        except Exception as e:
            log.error(f"Failed to enable chain {chain_id}: {e}")
            return False
        finally:
            db.close()
    
    def disable_chain(self, chain_id: str) -> bool:
        """Disable a chain and unload adapter."""
        db = get_db()
        try:
            db.execute("UPDATE chain_adapters SET enabled = FALSE WHERE chain_id = ?", (chain_id,))
            db.commit()
            self._adapters.pop(chain_id, None)
            return True
        except Exception as e:
            log.error(f"Failed to disable chain {chain_id}: {e}")
            return False
        finally:
            db.close()

# Singleton accessor
registry = ChainRegistry()
```

### 3. Polygon Adapter (Backward Compatible)

```python
# adapters/polygon_adapter.py
from adapters.base import ChainAdapter, Market, PricePoint, WalletProfile
from clob import get_price_history as polygon_get_history, DEFAULT_INTERVAL
from utils import unmask_proxy
from harvest import extract_first_price
import requests
import json
from typing import List, Dict, Any

class PolygonPolymarketAdapter(ChainAdapter):
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.gamma_api = self.config.get('gamma_api', 'https://gamma-api.polymarket.com/markets')
        self.data_api = self.config.get('data_api', 'https://data-api.polymarket.com')
    
    def health_check(self) -> bool:
        try:
            resp = requests.get(f"{self.gamma_api}?limit=1", timeout=5)
            return resp.status_code == 200
        except:
            return False
    
    def harvest_markets(self, limit: int = 1000) -> List[Market]:
        """Wrap existing harvest.py logic."""
        markets = []
        offset = 0
        batch_size = min(limit, 100)
        
        while offset < limit:
            try:
                resp = requests.get(
                    self.gamma_api,
                    params={"active": "true", "closed": "false", "limit": batch_size, "offset": offset},
                    timeout=15
                )
                if resp.status_code != 200:
                    break
                
                data = resp.json()
                if not data:
                    break
                
                for m in data:
                    clob_token_id = None
                    raw_clob = m.get("clobTokenIds")
                    if raw_clob:
                        try:
                            token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
                            clob_token_id = token_ids[0] if token_ids else None
                        except:
                            pass
                    
                    markets.append(Market(
                        id=m['id'],
                        chain="polygon",
                        protocol="polymarket",
                        question=m.get('question', ''),
                        outcomes=json.loads(m.get('outcomes', '[]')),
                        volume=float(m.get('volume', 0)),
                        created_at=m.get('createdDate', ''),
                        metadata={'clob_token_id': clob_token_id}
                    ))
                
                offset += batch_size
                
            except Exception as e:
                break
        
        return markets
    
    def get_price_history(self, market_id: str, interval: str = DEFAULT_INTERVAL) -> List[PricePoint]:
        """Use existing CLOB functionality."""
        history = polygon_get_history(market_id, interval=interval)
        if not history:
            return []
        
        return [
            PricePoint(
                timestamp=h['t'],
                price=float(h['p']),
                market_id=market_id,
                chain="polygon"
            ) for h in history
        ]
    
    def unmask_wallet(self, address: str) -> WalletProfile:
        real_owner = unmask_proxy(address)
        return WalletProfile(
            address=address,
            chain="polygon",
            real_owner=real_owner,
            is_proxy=(real_owner != "Direct Wallet (Not a Proxy)")
        )
    
    def get_wallet_trades(self, address: str, limit: int = 20) -> List[Dict]:
        try:
            resp = requests.get(
                f"{self.data_api}/trades",
                params={"user": address, "limit": limit},
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
            return []
        except:
            return []
```

### 4. Database Schema Migration

```sql
-- migrations/001_multi_chain_support.sql
ALTER TABLE markets ADD COLUMN chain TEXT DEFAULT 'polygon';
ALTER TABLE markets ADD COLUMN protocol TEXT DEFAULT 'polymarket';
ALTER TABLE markets ADD COLUMN chain_metadata TEXT; -- JSON blob for chain-specific data

CREATE TABLE IF NOT EXISTS chain_adapters (
    chain_id TEXT PRIMARY KEY,
    chain_name TEXT NOT NULL,
    protocol TEXT NOT NULL,
    adapter_class TEXT NOT NULL,
    config_json TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    anomaly_threshold FLOAT DEFAULT 0.10,
    min_volume FLOAT DEFAULT 5000,
    last_harvest TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed default Polygon adapter
INSERT OR IGNORE INTO chain_adapters 
(chain_id, chain_name, protocol, adapter_class, config_json, enabled, anomaly_threshold, min_volume)
VALUES (
    'polygon', 'Polygon', 'polymarket', 
    'adapters.polygon_adapter.PolygonPolymarketAdapter',
    '{"gamma_api": "https://gamma-api.polymarket.com/markets", "data_api": "https://data-api.polymarket.com"}',
    TRUE, 0.10, 5000
);

-- Index for multi-chain queries
CREATE INDEX IF NOT EXISTS idx_markets_chain_protocol ON markets(chain, protocol);
CREATE INDEX IF NOT EXISTS idx_markets_chain_volume ON markets(chain, volume DESC);
```

### 5. Multi-Chain Harvester

```python
# harvest_multi.py
import asyncio
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from db import get_db, init_db
from adapters.registry import registry
from logger import get_logger

log = get_logger("MultiHarvester")

def harvest_chain(adapter, limit_per_chain: int = 1000):
    """Harvest markets from a single chain adapter."""
    try:
        log.info(f"Harvesting {adapter.__class__.__name__}...")
        markets = adapter.harvest_markets(limit=limit_per_chain)
        
        # Save to database with chain metadata
        db = get_db()
        try:
            for market in markets:
                db.execute('''
                    INSERT OR REPLACE INTO markets 
                    (id, question, outcomes, volume, created_at, chain, protocol, chain_metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    market.id,
                    market.question,
                    json.dumps(market.outcomes),
                    market.volume,
                    market.created_at,
                    market.chain,
                    market.protocol,
                    json.dumps(market.metadata) if market.metadata else None
                ))
            db.commit()
            return len(markets)
        finally:
            db.close()
    except Exception as e:
        log.error(f"Harvest failed: {e}")
        return 0

def harvest_all_chains(limit_per_chain: int = 1000):
    """Harvest all enabled chains concurrently."""
    adapters = registry.get_all_adapters()
    if not adapters:
        log.warning("No adapters loaded")
        return {}
    
    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(harvest_chain, adapter, limit_per_chain): adapter
            for adapter in adapters
        }
        for future in futures:
            adapter = futures[future]
            try:
                count = future.result(timeout=300)
                chain_id = adapter.__class__.__name__.replace('Adapter', '').lower()
                results[chain_id] = count
            except Exception as e:
                log.error(f"Harvest failed for {adapter}: {e}")
    
    return results

if __name__ == "__main__":
    init_db()
    registry.initialize()
    
    while True:
        print(f"\n[{datetime.now().isoformat()}] Starting multi-chain harvest...")
        results = harvest_all_chains()
        
        total = sum(results.values())
        print(f"✅ Harvested {total} markets across {len(results)} chains")
        for chain, count in results.items():
            print(f"  - {chain}: {count} markets")
        
        # Wait 15 minutes before next harvest
        import time
        time.sleep(900)
```

### 6. Unified Alert Scanner with Per-Chain Thresholds

```python
# alerts_multi.py
import json
from datetime import datetime
from db import get_db
from adapters.registry import registry
from notifier import Notifier
from logger import get_logger

log = get_logger("MultiAlerts")

# Per-chain configuration
CHAIN_CONFIGS = {
    'polygon': {'threshold': 0.10, 'min_volume': 5000, 'near_resolution': 0.80},
    'ethereum': {'threshold': 0.15, 'min_volume': 10000, 'near_resolution': 0.80},
    'arbitrum': {'threshold': 0.12, 'min_volume': 8000, 'near_resolution': 0.80},
}

def scan_chain_for_anomalies(chain_id: str, adapter):
    """Scan a single chain for anomalies."""
    config = CHAIN_CONFIGS.get(chain_id, CHAIN_CONFIGS['polygon'])
    anomalies = []
    
    db = get_db()
    try:
        markets = db.execute(
            "SELECT * FROM markets WHERE chain = ? AND volume >= ?",
            (chain_id, config['min_volume'])
        ).fetchall()
        
        for market in markets:
            market_dict = dict(market)
            metadata = json.loads(market_dict.get('chain_metadata', '{}') or '{}')
            market_id = metadata.get('clob_token_id') or market_dict['id']
            
            try:
                history = adapter.get_price_history(market_id)
                if not history or len(history) < 2:
                    continue
                
                shift = history[-1].price - history[0].price
                current_price = history[-1].price
                
                if abs(shift) >= config['threshold']:
                    # Near-resolution check
                    if current_price >= config['near_resolution'] or current_price <= (1 - config['near_resolution']):
                        continue
                    
                    anomalies.append({
                        'chain': chain_id,
                        'market_id': market_dict['id'],
                        'question': market_dict['question'],
                        'shift': shift,
                        'current_price': current_price,
                        'volume': market_dict['volume'],
                        'threshold': config['threshold']
                    })
            except Exception as e:
                log.warning(f"Failed to check market {market_dict['id']}: {e}")
    finally:
        db.close()
    
    return anomalies

def scan_all_chains():
    """Scan all chains for anomalies."""
    adapters = registry.get_all_adapters()
    all_anomalies = []
    
    for adapter in adapters:
        chain_id = adapter.__class__.__name__.replace('Adapter', '').lower()
        anomalies = scan_chain_for_anomalies(chain_id, adapter)
        all_anomalies.extend(anomalies)
    
    return all_anomalies

def send_anomaly_alerts(anomalies):
    """Send alerts for detected anomalies."""
    notifier = Notifier()
    
    for anomaly in anomalies:
        direction = "📈" if anomaly['shift'] > 0 else "📉"
        shift_pct = anomaly['shift'] * 100
        price_pct = anomaly['current_price'] * 100
        
        message = (
            f"{direction} **[{anomaly['chain'].upper()}] {anomaly['question']}**\n"
            f"Shifted **{shift_pct:.1f}%** over 24h — now at **{price_pct:.0f}%**\n"
            f"Volume: ${anomaly['volume']:,.0f}\n"
            f"Threshold: {anomaly['threshold']*100:.0f}%\n\n"
            f"_Open the multi-chain dashboard to analyze._"
        )
        
        notifier.broadcast(message, title=f"🚨 {anomaly['chain'].upper()} Anomaly Detected")

if __name__ == "__main__":
    registry.initialize()
    
    while True:
        print(f"\n[{datetime.now().isoformat()}] Scanning all chains for anomalies...")
        anomalies = scan_all_chains()
        
        if anomalies:
            print(f"⚠️ Found {len(anomalies)} anomalies")
            send_anomaly_alerts(anomalies)
        else:
            print("✅ No anomalies detected")
        
        import time
        time.sleep(300)  # 5 minutes
```

### 7. Updated API Endpoints

```python
# api_multi.py — additions to existing FastAPI app
from fastapi import Query, HTTPException
from typing import List, Optional
from adapters.registry import registry
from alerts_multi import scan_all_chains
import json

# Chain Management Endpoints
@app.get("/chains")
def list_chains():
    """List all registered chain adapters."""
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM chain_adapters").fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()

@app.post("/chains/{chain_id}/enable")
def enable_chain(chain_id: str):
    """Enable a chain adapter at runtime."""
    if registry.enable_chain(chain_id):
        return {"status": "enabled", "chain_id": chain_id}
    raise HTTPException(400, "Failed to enable chain")

@app.post("/chains/{chain_id}/disable")
def disable_chain(chain_id: str):
    """Disable a chain adapter at runtime."""
    if chain_id == "polygon":
        raise HTTPException(400, "Cannot disable primary Polygon adapter")
    
    if registry.disable_chain(chain_id):
        return {"status": "disabled", "chain_id": chain_id}
    raise HTTPException(400, "Failed to disable chain")

# Multi-Chain Market Search
@app.get("/markets")
def search_markets(
    chains: Optional[List[str]] = Query(None),
    protocols: Optional[List[str]] = Query(None),
    search: Optional[str] = None,
    vol_min: Optional[float] = None,
    vol_max: Optional[float] = None,
    limit: int = 50
):
    """Search markets across multiple chains."""
    db = get_db()
    try:
        conditions = ["1=1"]
        params = []
        
        if chains:
            placeholders = ",".join(["?"] * len(chains))
            conditions.append(f"chain IN ({placeholders})")
            params.extend(chains)
        
        if protocols:
            placeholders = ",".join(["?"] * len(protocols))
            conditions.append(f"protocol IN ({placeholders})")
            params.extend(protocols)
        
        if search:
            conditions.append("question LIKE ?")
            params.append(f"%{search}%")
        
        if vol_min is not None:
            conditions.append("volume >= ?")
            params.append(vol_min)
        
        if vol_max is not None:
            conditions.append("volume <= ?")
            params.append(vol_max)
        
        where = " AND ".join(conditions)
        query = f"SELECT * FROM markets WHERE {where} ORDER BY volume DESC LIMIT ?"
        params.append(limit)
        
        rows = db.execute(query, params).fetchall()
        markets = []
        
        for row in rows:
            market_dict = dict(row)
            # Parse JSON fields
            if market_dict.get('outcomes'):
                market_dict['outcomes'] = json.loads(market_dict['outcomes'])
            if market_dict.get('chain_metadata'):
                market_dict['chain_metadata'] = json.loads(market_dict['chain_metadata'])
            markets.append(market_dict)
        
        return markets
    finally:
        db.close()

# Chain-Specific AI Analysis
@app.get("/markets/{chain}/{market_id}/ai-analysis")
def get_chain_analysis(
    chain: str,
    market_id: str,
    research: bool = Query(False)
):
    """Run AI analysis on a market from specific chain."""
    adapter = registry.get_adapter(chain)
    if not adapter:
        raise HTTPException(404, f"Chain '{chain}' not found or disabled")
    
    db = get_db()
    try:
        market = db.execute(
            "SELECT * FROM markets WHERE id = ? AND chain = ?",
            (market_id, chain)
        ).fetchone()
        
        if not market:
            raise HTTPException(404, "Market not found")
        
        market_dict = dict(market)
        metadata = json.loads(market_dict.get('chain_metadata', '{}') or '{}')
        clob_token_id = metadata.get('clob_token_id') or market_id
        
        # Get price history from adapter
        price_history = adapter.get_price_history(clob_token_id)
        price_list = [p.price for p in price_history] if price_history else []
        
        # Use existing analyst
        from analyst import PolyAnalyst
        analyst = PolyAnalyst()
        
        analysis = analyst.analyze_market_shift(
            market_question=market_dict['question'],
            price_history=price_list,
            volume=market_dict['volume'],
            use_research=research
        )
        
        return {
            "analysis": analysis,
            "chain": chain,
            "market_id": market_id,
            "research_used": research
        }
    finally:
        db.close()

# Cross-Chain Anomaly Dashboard
@app.get("/alerts/cross-chain")
def get_cross_chain_alerts():
    """Get anomalies across all chains."""
    anomalies = scan_all_chains()
    return {
        "anomalies": anomalies,
        "count": len(anomalies),
        "scanned_at": datetime.utcnow().isoformat()
    }
```

### 8. Frontend Updates

```javascript
// static/app.js — additions for multi-chain support

// Load chain filters
async function loadChainFilters() {
    try {
        const res = await fetch('/chains');
        const chains = await res.json();
        const container = document.getElementById('chainFilters');
        
        container.innerHTML = chains.map(chain => `
            <label class="inline-flex items-center gap-2 px-3 py-1 rounded cursor-pointer
                          ${chain.enabled ? 'bg-gray-800 border border-gray-700' : 'bg-gray-900 border border-gray-800 opacity-50'}">
                <input type="checkbox" 
                       class="chain-checkbox rounded border-gray-600 bg-gray-800 text-polysint"
                       data-chain="${chain.chain_id}"
                       ${chain.enabled ? 'checked' : ''}
                       ${chain.chain_id === 'polygon' ? 'disabled' : ''}
                       onchange="onChainFilterChange()">
                <span class="text-xs font-mono text-gray-300 uppercase">${chain.chain_id}</span>
                <span class="text-[10px] text-gray-500">(${chain.anomaly_threshold * 100}% threshold)</span>
            </label>
        `).join('');
    } catch (e) {
        console.error('Failed to load chains:', e);
    }
}

// Update market loading to include chain filters
async function loadMarkets(searchQuery = '', silent = false) {
    if (!silent) showLoadingState();
    
    // Get selected chains
    const selectedChains = Array.from(document.querySelectorAll('.chain-checkbox:checked'))
        .map(cb => cb.dataset.chain);
    
    const params = new URLSearchParams();
    if (searchQuery) params.set('search', searchQuery);
    if (selectedChains.length > 0) {
        params.set('chains', selectedChains.join(','));
    }
    
    try {
        const res = await fetch(`/markets?${params.toString()}`);
        if (!res.ok) throw new Error(`Backend ${res.status}`);
        
        const markets = await res.json();
        renderMarketsTable(markets);
        
    } catch (e) {
        console.error(e);
        showLoadError(searchQuery);
    }
}

function renderMarketsTable(markets) {
    const table = document.getElementById('marketsTable');
    table.innerHTML = '';
    
    if (markets.length === 0) {
        table.innerHTML = `
            <tr><td colspan="5" class="py-16 text-center text-gray-500">
                No markets found. Try adjusting chain filters.
            </td></tr>`;
        return;
    }
    
    markets.forEach((market, i) => {
        const tr = document.createElement('tr');
        tr.className = `border-b border-gray-800 hover:bg-gray-800/50 transition-colors`;
        tr.style.animationDelay = `${i * 20}ms`;
        
        // Chain badge colors
        const chainColors = {
            'polygon': 'bg-purple-500/15 text-purple-400 border-purple-500/30',
            'ethereum': 'bg-blue-500/15 text-blue-400 border-blue-500/30',
            'arbitrum': 'bg-orange-500/15 text-orange-400 border-orange-500/30'
        };
        const chainColor = chainColors[market.chain] || 'bg-gray-500/15 text-gray-400 border-gray-500/30';
        
        tr.innerHTML = `
            <td class="px-4 py-3">
                <div class="flex items-center gap-2 mb-1">
                    <span class="px-1.5 py-0.5 rounded text-[10px] font-mono border ${chainColor}">
                        ${market.chain.toUpperCase()}
                    </span>
                    <span class="text-[10px] text-gray-500">${market.protocol}</span>
                </div>
                <div class="text-gray-200 text-sm">${market.question}</div>
            </td>
            <td class="px-4 py-3 text-gray-400 text-sm">
                $${Number(market.volume).toLocaleString()}
            </td>
            <td class="px-4 py-3 text-right">
                <button onclick="analyzeMarket('${market.chain}', '${market.id}')"
                    class="bg-polysint/10 text-polysint border border-polysint/30 hover:bg-polysint hover:text-gray-900 px-3 py-1 rounded text-xs transition-all">
                    🤖 Analyze
                </button>
            </td>`;
        table.appendChild(tr);
    });
}

// Chain-specific AI analysis
async function analyzeMarket(chain, marketId) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    
    modal.classList.remove('hidden');
    content.innerHTML = `
        <div class="flex flex-col items-center py-12 space-y-3">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-polysint text-sm animate-pulse">Analyzing ${chain.toUpperCase()} market...</div>
        </div>`;
    
    try {
        const useResearch = document.getElementById('researchToggle')?.checked || false;
        const res = await fetch(`/markets/${chain}/${marketId}/ai-analysis?research=${useResearch}`);
        
        if (!res.ok) throw new Error('Analysis failed');
        
        const data = await res.json();
        const formatted = data.analysis
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            .replace(/\n/g, '<br>');
        
        content.innerHTML = `
            <div class="mb-2 text-xs text-gray-500 font-mono">
                Chain: ${data.chain.toUpperCase()} · Research: ${data.research_used ? 'ON' : 'OFF'}
            </div>
            <div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed">
                ${formatted}
            </div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                ⚠️ Analysis failed for ${chain.toUpperCase()} market.
            </div>`;
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadChainFilters();
    loadWatchlist();
    initResearchToggle();
    // ... rest of existing initialization
});
```

## Implementation Roadmap

1. **Phase 1: Core Infrastructure**
   - Implement base adapter interface and Polygon adapter
   - Add chain/protocol columns to database
   - Create chain_adapters table
   - Update harvester and alert scanner

2. **Phase 2: Multi-Chain API**
   - Add chain management endpoints
   - Update market search to support chain filtering
   - Implement chain-specific AI analysis endpoint

3. **Phase 3: Frontend Updates**
   - Add chain filter UI components
   - Update market table to show chain badges
   - Implement chain-specific analysis modal

4. **Phase 4: Additional Chains**
   - Implement Ethereum/Augur adapter as reference
   - Add adapters for Arbitrum, Solana, etc.
   - Configure per-chain thresholds

5. **Phase 5: Microservices Deployment**
   - Extract adapters to separate services
   - Implement service discovery
   - Add monitoring and health checks

This architecture provides a clean, extensible path to true multi-chain support while maintaining all existing OSINT capabilities. New chains can be added by implementing the adapter interface and registering in the database, without modifying core system code.
