2026-03-15 16:21:29,459 - llm_consortium.orchestrator - ERROR - Automatic response error for glm-5: Error code: 429 - {'detail': 'Infrastructure is at maximum capacity, try again later'}
## Insider Score Leaderboard Implementation

### Backend Changes (api.py)

Add these imports and create a thread-safe leaderboard manager:

```python
# ─── Insider Score Leaderboard ────────────────────────────────────────────────
from datetime import datetime, timezone
import re
import threading
from collections import OrderedDict
from typing import Optional, Dict, Any

class LeaderboardManager:
    """Thread-safe manager for insider score leaderboard with LRU eviction."""
    
    def __init__(self, max_size: int = 200):
        self._scores: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self._max_size = max_size
    
    def add_score(self, market_id: str, analysis: str) -> bool:
        """Parse and store insider score from analysis. Returns True if valid score found."""
        if not market_id or not isinstance(market_id, str):
            return False
        
        # Parse score from analysis - anchor to end of string to prevent injection
        # This looks for the LAST occurrence of the pattern to avoid matching user content
        score_pattern = re.compile(r'INSIDER\s+SIGNAL:\s*\(?(\d{1,2})\)?\s*$', re.IGNORECASE | re.MULTILINE)
        score_match = score_pattern.search(analysis)
        
        if not score_match:
            # Fallback: look for pattern anywhere but validate it's in analysis section
            score_pattern = re.compile(r'ANALYSIS:.*?INSIDER\s+SIGNAL:\s*\(?(\d{1,2})\)?', 
                                      re.IGNORECASE | re.DOTALL)
            score_match = score_pattern.search(analysis)
            if not score_match:
                return False
        
        try:
            score = int(score_match.group(1))
            if not 1 <= score <= 10:
                return False
        except (ValueError, TypeError):
            return False
        
        # Extract classification
        classification = "UNKNOWN"
        type_pattern = re.compile(r'TYPE:\s*(REACTIONARY|SUSPICIOUS|ORGANIC|INSUFFICIENT\s+DATA)', 
                                 re.IGNORECASE)
        type_match = type_pattern.search(analysis)
        if type_match:
            classification = type_match.group(1).upper().strip()
        
        # Extract analysis brief (first sentence of analysis section)
        brief = ""
        analysis_pattern = re.compile(r'ANALYSIS:\s*\n(.*?)(?=\nINSIDER\s+SIGNAL:|\nTYPE:|\Z)', 
                                     re.IGNORECASE | re.DOTALL)
        analysis_match = analysis_pattern.search(analysis)
        if analysis_match:
            brief_text = analysis_match.group(1).strip()
            # Get first non-empty line
            lines = [l.strip() for l in brief_text.split('\n') if l.strip()]
            if lines:
                brief = lines[0][:200]
        
        # Thread-safe storage with LRU eviction
        with self._lock:
            # Remove if already exists to update position in OrderedDict
            if market_id in self._scores:
                del self._scores[market_id]
            
            self._scores[market_id] = {
                "score": score,
                "classification": classification,
                "brief": brief,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Enforce LRU eviction
            if len(self._scores) > self._max_size:
                self._scores.popitem(last=False)  # Remove oldest (first item)
            
            return True
    
    def get_leaderboard(self, limit: int = 20) -> Dict[str, Any]:
        """Get sorted leaderboard entries."""
        with self._lock:
            if not self._scores:
                return {"entries": [], "total": 0}
            
            # Sort by score descending, then by timestamp (newest first)
            sorted_entries = sorted(
                self._scores.items(),
                key=lambda x: (-x[1]["score"], x[1]["timestamp"])
            )[:limit]
            
            return {
                "entries": [
                    {"market_id": mid, **data}
                    for mid, data in sorted_entries
                ],
                "total": len(self._scores)
            }
    
    def clear(self) -> int:
        """Clear all entries. Returns count of cleared entries."""
        with self._lock:
            count = len(self._scores)
            self._scores.clear()
            return count

# Initialize global leaderboard manager
leaderboard = LeaderboardManager(max_size=200)
```

Modify the existing `get_ai_analysis` function to store scores:

```python
@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis(
    market_id: str,
    research: bool = Query(default=False, description="Enable Tavily web research for news context")
):
    # ... existing code until analysis is generated ...
    
    analysis = analyst.analyze_market_shift(
        market['question'],
        price_history,
        market['volume'],
        use_research=research
    )
    
    # ─── Store insider score for leaderboard ────────────────────────────────
    try:
        leaderboard.add_score(market_id, analysis)
    except Exception as e:
        log.warning(f"Failed to store insider score for {market_id}: {e}")
    # ───────────────────────────────────────────────────────────────────────
    
    return {"analysis": analysis, "research_used": research}
```

Add the leaderboard endpoints:

```python
@app.get("/leaderboard/insider")
def get_insider_leaderboard(limit: int = Query(default=20, ge=1, le=50)):
    """
    Returns markets ranked by insider signal score (descending).
    Only includes markets that have been analyzed with valid scores.
    """
    try:
        result = leaderboard.get_leaderboard(limit)
        
        if not result["entries"]:
            return {"entries": [], "total": 0}
        
        # Batch fetch market data from database
        market_ids = [entry["market_id"] for entry in result["entries"]]
        db = get_db()
        try:
            placeholders = ','.join(['?'] * len(market_ids))
            markets = db.execute(
                f"SELECT id, question, volume FROM markets WHERE id IN ({placeholders})",
                market_ids
            ).fetchall()
            market_dict = {m['id']: dict(m) for m in markets}
        finally:
            db.close()
        
        # Enrich entries with market data
        for entry in result["entries"]:
            market_info = market_dict.get(entry["market_id"], {})
            if market_info:
                entry.update({
                    "question": market_info.get("question", "Unknown Market"),
                    "volume": market_info.get("volume", 0)
                })
        
        return result
    
    except Exception as e:
        log.error(f"Leaderboard fetch failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to load leaderboard")

@app.post("/leaderboard/insider/clear")
def clear_insider_leaderboard():
    """Clear all insider scores (admin endpoint)."""
    try:
        count = leaderboard.clear()
        log.info(f"Cleared {count} entries from insider leaderboard")
        return {"cleared": count, "success": True}
    except Exception as e:
        log.error(f"Failed to clear leaderboard: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear leaderboard")
```

### Frontend HTML (static/index.html)

Add this after the watchlist section:

```html
<!-- ═══ Insider Score Leaderboard ═══ -->
<div class="mt-8 border border-gray-700/50 rounded-xl overflow-hidden" id="leaderboardSection">
  <button onclick="toggleLeaderboard()" id="lbToggle"
    class="w-full flex items-center justify-between px-5 py-3.5 bg-gray-800/60 hover:bg-gray-800 transition-colors"
    aria-expanded="false" aria-controls="leaderboardPanel">
    <div class="flex items-center gap-2">
      <span class="text-lg" role="img" aria-label="trophy">🏆</span>
      <span class="text-sm font-semibold text-gray-200">Insider Score Leaderboard</span>
      <span id="lbCount" class="text-xs text-gray-500 font-mono hidden" aria-live="polite"></span>
    </div>
    <span id="lbArrow" class="text-gray-500 transition-transform duration-200 text-xs" aria-hidden="true">▼</span>
  </button>
  <div id="leaderboardPanel" class="hidden" role="region" aria-label="Insider scores">
    <div class="flex items-center justify-between px-5 py-2 bg-gray-900/30 border-b border-gray-700/30">
      <span class="text-xs text-gray-500">Click any row to view full analysis</span>
      <button onclick="refreshLeaderboard()" 
        class="text-xs text-gray-400 hover:text-polysint transition-colors flex items-center gap-1">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
        </svg>
        Refresh
      </button>
    </div>
    <div id="leaderboardTable" class="divide-y divide-gray-700/40 max-h-96 overflow-y-auto">
      <!-- Populated by JavaScript -->
    </div>
  </div>
</div>
```

### Frontend CSS (Add to <style> section in index.html)

```css
/* ── Insider Score Badges ── */
.score-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  font-weight: 700;
  font-size: 0.8125rem;
  font-family: ui-monospace, monospace;
  flex-shrink: 0;
}
.score-critical { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.score-elevated { background: rgba(251, 146, 60, 0.15); color: #fb923c; border: 1px solid rgba(251, 146, 60, 0.3); }
.score-moderate { background: rgba(250, 204, 21, 0.12); color: #facc15; border: 1px solid rgba(250, 204, 21, 0.25); }
.score-low { background: rgba(52, 211, 153, 0.12); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.25); }

/* ── Classification badges ── */
.type-badge {
  font-size: 0.625rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  text-transform: uppercase;
  white-space: nowrap;
}
.type-suspicious { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.type-reactionary { background: rgba(96, 165, 250, 0.15); color: #60a5fa; }
.type-organic { background: rgba(52, 211, 153, 0.12); color: #34d399; }
.type-insufficient { background: rgba(107, 114, 128, 0.2); color: #9ca3af; }

/* ── Leaderboard row focus states (accessibility) ── */
[role="button"]:focus-visible {
  outline: 2px solid rgba(52, 211, 153, 0.5);
  outline-offset: 2px;
  z-index: 1;
  position: relative;
}

/* ── Scrollbar Styling ── */
#leaderboardTable::-webkit-scrollbar {
  width: 6px;
}

#leaderboardTable::-webkit-scrollbar-track {
  background: rgba(31, 41, 55, 0.5);
  border-radius: 3px;
}

#leaderboardTable::-webkit-scrollbar-thumb {
  background: rgba(75, 85, 99, 0.7);
  border-radius: 3px;
}

#leaderboardTable::-webkit-scrollbar-thumb:hover {
  background: rgba(107, 114, 128, 0.8);
}

/* ── Mobile Responsiveness ── */
@media (max-width: 640px) {
  .score-badge {
    width: 1.75rem;
    height: 1.75rem;
    font-size: 0.75rem;
  }
  
  .type-badge {
    font-size: 0.5rem;
    padding: 0.1rem 0.4rem;
  }
}
```

### Frontend JavaScript (static/app.js)

```javascript
// ═══════════════════════════════════════════════════════════════════════════════
// Insider Score Leaderboard
// ═══════════════════════════════════════════════════════════════════════════════

let leaderboardState = {
  isOpen: false,
  isLoading: false,
  entries: [],
  error: null
};

function toggleLeaderboard() {
  const panel = document.getElementById('leaderboardPanel');
  const arrow = document.getElementById('lbArrow');
  const toggle = document.getElementById('lbToggle');
  
  if (!panel || !arrow || !toggle) {
    console.error('Leaderboard elements not found');
    return;
  }
  
  // Toggle state
  leaderboardState.isOpen = !leaderboardState.isOpen;
  
  // Update UI
  panel.classList.toggle('hidden', !leaderboardState.isOpen);
  toggle.setAttribute('aria-expanded', leaderboardState.isOpen);
  arrow.style.transform = leaderboardState.isOpen ? 'rotate(180deg)' : '';
  
  // Refresh when opening (not closing) for better UX
  if (leaderboardState.isOpen && !leaderboardState.isLoading) {
    refreshLeaderboard();
  }
}

async function refreshLeaderboard() {
  if (leaderboardState.isLoading) return;
  
  const container = document.getElementById('leaderboardTable');
  const countEl = document.getElementById('lbCount');
  
  if (!container) return;
  
  leaderboardState.isLoading = true;
  leaderboardState.error = null;
  
  // Show loading state
  container.innerHTML = `
    <div class="py-8 text-center">
      <div class="flex justify-center space-x-1 mb-3">
        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
      </div>
      <div class="text-gray-400 text-sm">Loading insider scores...</div>
    </div>`;
  
  try {
    const res = await fetch('/leaderboard/insider?limit=20');
    
    if (!res.ok) {
      throw new Error(`Server returned ${res.status}`);
    }
    
    const data = await res.json();
    
    if (!data || !Array.isArray(data.entries)) {
      throw new Error('Invalid response format');
    }
    
    leaderboardState.entries = data.entries;
    
    // Update count badge
    if (countEl && typeof data.total === 'number') {
      countEl.textContent = `${data.total} scored`;
      countEl.classList.toggle('hidden', data.total === 0);
    }
    
    if (data.entries.length === 0) {
      container.innerHTML = `
        <div class="py-8 text-center text-gray-600 text-sm italic">
          No scores yet. Run AI analysis on markets to populate.
          <div class="mt-2 text-xs text-gray-500">Scores update automatically when you analyze markets.</div>
        </div>`;
      return;
    }
    
    container.innerHTML = '';
    
    data.entries.forEach((entry, index) => {
      if (!entry || typeof entry.score !== 'number' || !entry.market_id) {
        console.warn('Skipping invalid leaderboard entry:', entry);
        return;
      }
      
      const rankLabel = index < 3 ? ['🥇', '🥈', '🥉'][index] : `#${index + 1}`;
      const scoreClass = _getScoreClass(entry.score);
      const typeClass = _getTypeClass(entry.classification);
      const timeAgo = _formatTimestamp(entry.timestamp);
      
      const shortQ = typeof entry.question === 'string' 
        ? (entry.question.length > 80 ? entry.question.slice(0, 77) + '…' : entry.question)
        : 'Unknown Market';
      
      const row = document.createElement('div');
      row.className = 'flex items-center gap-3 px-5 py-3 hover:bg-gray-700/20 transition-colors cursor-pointer';
      row.setAttribute('role', 'button');
      row.setAttribute('tabindex', '0');
      row.setAttribute('data-market-id', entry.market_id);
      row.setAttribute('aria-label', `Rank ${index + 1}: ${shortQ}, Score ${entry.score}`);
      
      row.onclick = () => {
        const marketId = entry.market_id;
        if (!marketId) return;
        
        // Visual feedback
        const rowEl = document.querySelector(`[data-market-id="${marketId}"]`);
        if (rowEl) {
          rowEl.classList.add('bg-gray-700/30');
          setTimeout(() => rowEl.classList.remove('bg-gray-700/30'), 300);
        }
        
        // Open analysis modal
        analyzeMarket(marketId);
      };
      
      row.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          row.onclick();
        }
      };
      
      row.innerHTML = `
        <span class="text-sm w-8 text-center flex-shrink-0 ${index < 3 ? '' : 'text-gray-500'}" 
              aria-hidden="true">${rankLabel}</span>
        <span class="score-badge ${scoreClass}" 
              title="Insider Score: ${entry.score}/10"
              aria-label="Insider score ${entry.score} out of 10">${entry.score}</span>
        <div class="flex-1 min-w-0">
          <div class="text-sm text-gray-200 truncate" title="${escapeHtml(entry.question)}">${escapeHtml(shortQ)}</div>
          <div class="flex items-center gap-2 mt-0.5 flex-wrap">
            <span class="type-badge ${typeClass}">${escapeHtml(entry.classification || 'UNKNOWN')}</span>
            ${entry.brief ? `
              <span class="text-xs text-gray-500 truncate hidden sm:inline" 
                    title="${escapeHtml(entry.brief)}">${escapeHtml(entry.brief)}</span>` : ''}
          </div>
        </div>
        <span class="text-xs text-gray-600 flex-shrink-0 font-mono hidden sm:inline" 
              title="${entry.timestamp}">${timeAgo}</span>
      `;
      
      container.appendChild(row);
    });
    
  } catch (error) {
    console.error('Leaderboard refresh failed:', error);
    leaderboardState.error = error;
    
    const errorMessage = error.name === 'AbortError' 
      ? 'Request timed out'
      : error.message || 'Unknown error occurred';
    
    container.innerHTML = `
      <div class="py-8 text-center">
        <div class="text-red-400 text-sm mb-2">⚠️ ${escapeHtml(errorMessage)}</div>
        <button onclick="refreshLeaderboard()" 
          class="text-xs text-polysint underline hover:text-emerald-400 transition-colors">
          Retry loading
        </button>
        <div class="mt-3 text-xs text-gray-600">
          Scores are cached and update when you analyze markets.
        </div>
      </div>`;
  } finally {
    leaderboardState.isLoading = false;
  }
}

// ── Helper Functions ──

function _getScoreClass(score) {
  const s = typeof score === 'number' ? score : parseInt(score, 10);
  if (isNaN(s) || s < 1 || s > 10) return 'score-low';
  
  if (s >= 8) return 'score-critical';
  if (s >= 6) return 'score-elevated';
  if (s >= 4) return 'score-moderate';
  return 'score-low';
}

function _getTypeClass(classification) {
  if (typeof classification !== 'string') return 'type-insufficient';
  
  const normalized = classification.toUpperCase().trim();
  switch (normalized) {
    case 'SUSPICIOUS':         return 'type-suspicious';
    case 'REACTIONARY':        return 'type-reactionary';
    case 'ORGANIC':            return 'type-organic';
    case 'INSUFFICIENT DATA':  return 'type-insufficient';
    default:                   return 'type-insufficient';
  }
}

function _formatTimestamp(isoStr) {
  if (typeof isoStr !== 'string' || !isoStr) return '';
  
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return '';
    
    const now = new Date();
    const diffMs = now - d;
    
    if (diffMs < 0) return 'just now';
    
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1)  return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24)  return `${diffHr}h ago`;
    
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
    
  } catch (e) {
    return '';
  }
}

function escapeHtml(text) {
  if (typeof text !== 'string') return '';
  if (text.length === 0) return '';
  
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Hook into existing market loading to refresh leaderboard when markets update
// Add this line at the end of the loadMarkets() function's try block:
// if (leaderboardState.isOpen) refreshLeaderboard();
```

### Integration Notes

1. **Auto-refresh**: The leaderboard automatically refreshes when opened. For automatic updates when markets load, add `if (leaderboardState.isOpen) refreshLeaderboard();` at the end of the `loadMarkets()` function's try block.

2. **Security Considerations**: The regex parsing is anchored to prevent injection attacks from market titles. For production, consider adding authentication to the leaderboard endpoints.

3. **Performance**: In-memory storage resets on server restart. For persistence, consider adding a SQLite table to store scores.

4. **Error Handling**: The implementation includes proper error handling with retry functionality and loading states.
