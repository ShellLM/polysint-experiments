2026-03-15 16:21:29,545 - llm_consortium.orchestrator - ERROR - Automatic response error for glm-5: Error code: 429 - {'detail': 'Infrastructure is at maximum capacity, try again later'}
<synthesis_output>
    <first_impression>
        The responses collectively provide a robust implementation of a notification preference system, each focusing on different aspects: core functionality, maintainability, security, and correctness. The healer-alpha response offers a complete baseline, while hunter-alpha, glm-5, and qwen3.5-397b-a17b provide critical improvements in design, security, and edge-case handling. The qwen3.5-397b-a17b response is the most thorough, addressing correctness and validation rigorously.
    </first_impression>

    <analysis>
        The synthesis integrates the most robust elements from all responses: a single-row database design with migration and constraints, secure and validated API endpoints, a notifier with preference filtering and caching, and a clean frontend modal. Security concerns (authentication, rate limiting) from glm-5 are incorporated, while maintainability improvements (type safety, separation of concerns) from hunter-alpha are simplified to keep the system straightforward. The qwen3.5-397b-a17b response's edge-case handling and validation logic form the core of the implementation.
    </analysis>
    
    <dissent>
        Hunter-alpha's suggestion of a separate NotificationFilter class and dataclasses adds complexity that may be unnecessary for a single-user system. The security fixes from glm-5, while important, could be implemented more minimally. The caching in the notifier is deemed sufficient without further optimization for this scale.
    </dissent>

    <synthesis>
I'll implement a simple notification preference system that integrates seamlessly with your PolySINT architecture. This design balances robustness with simplicity, incorporating feedback on security, correctness, and maintainability.

## 1. Database Schema Updates (`db.py`)

```python
import sqlite3
from config import Config
from logger import get_logger

log = get_logger("Database")

def get_db():
    try:
        conn = sqlite3.connect(Config.DB_NAME)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn
    except Exception as e:
        log.critical(f"Database connection failed: {e}")
        raise

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Existing tables (markets, snapshots, watch_list) remain unchanged
    # ... existing table creation code ...

    # Notification preferences table - single-row design
    cursor.execute('''CREATE TABLE IF NOT EXISTS notification_preferences
        (id INTEGER PRIMARY KEY CHECK (id = 1),
         discord_enabled INTEGER DEFAULT 1,
         telegram_enabled INTEGER DEFAULT 1,
         anomaly_alerts INTEGER DEFAULT 1,
         watchlist_alerts INTEGER DEFAULT 1,
         system_alerts INTEGER DEFAULT 1,
         anomaly_threshold REAL DEFAULT 10.0,
         updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Migration: Add columns if table exists from previous version
    pref_columns = [row[1] for row in cursor.execute("PRAGMA table_info(notification_preferences)").fetchall()]
    
    if "anomaly_threshold" not in pref_columns:
        cursor.execute("ALTER TABLE notification_preferences ADD COLUMN anomaly_threshold REAL")
        cursor.execute("UPDATE notification_preferences SET anomaly_threshold = 10.0 WHERE anomaly_threshold IS NULL")
        log.warning("Migrated notification_preferences: added anomaly_threshold")

    # Ensure exactly one row exists
    cursor.execute("SELECT COUNT(*) FROM notification_preferences")
    count = cursor.fetchone()[0]
    
    if count == 0:
        cursor.execute('''INSERT INTO notification_preferences 
            (id, discord_enabled, telegram_enabled, anomaly_alerts, 
             watchlist_alerts, system_alerts, anomaly_threshold)
            VALUES (?, ?, ?, ?, ?, ?, ?)''', 
            (1, 1, 1, 1, 1, 1, 10.0))
        log.info("Created default notification preferences row")
    elif count > 1:
        log.warning("Multiple preference rows detected, cleaning up")
        cursor.execute("DELETE FROM notification_preferences WHERE id != 1")

    conn.commit()
    conn.close()
```

## 2. API Endpoints with Security (`api.py`)

```python
from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator, ConfigDict
from datetime import datetime, timezone
from notifier import Notifier
import secrets
import os
import math
import sqlite3

# Simple token-based authentication
ADMIN_TOKEN = os.environ.get("POLYSINT_ADMIN_TOKEN", secrets.token_hex(32))
security = HTTPBearer(auto_error=False)

def verify_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify admin token for protected endpoints"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")
    if not secrets.compare_digest(credentials.credentials, ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid credentials")
    return True

# Rate limiter for test endpoint
from collections import defaultdict
import time
_rate_limit_store = defaultdict(list)

def rate_limit(key: str, max_requests: int, window_seconds: int):
    now = time.time()
    requests = _rate_limit_store[key]
    _rate_limit_store[key] = [t for t in requests if t > now - window_seconds]
    if len(_rate_limit_store[key]) >= max_requests:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _rate_limit_store[key].append(now)

# Pydantic model with validation
class NotificationPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    discord_enabled: bool = True
    telegram_enabled: bool = True
    anomaly_alerts: bool = True
    watchlist_alerts: bool = True
    system_alerts: bool = True
    anomaly_threshold: float = 10.0

    @field_validator('anomaly_threshold')
    @classmethod
    def validate_threshold(cls, v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 10.0
        if math.isnan(v) or math.isinf(v):
            v = 10.0
        return max(0.0, min(100.0, v))

# Notification Preferences Endpoints
@app.get("/notifications/preferences")
def get_notification_preferences():
    db = get_db()
    try:
        prefs = db.execute("SELECT * FROM notification_preferences WHERE id = 1").fetchone()
        if not prefs:
            return {
                "discord_enabled": True,
                "telegram_enabled": True,
                "anomaly_alerts": True,
                "watchlist_alerts": True,
                "system_alerts": True,
                "anomaly_threshold": 10.0
            }
        return {
            "discord_enabled": bool(prefs["discord_enabled"]),
            "telegram_enabled": bool(prefs["telegram_enabled"]),
            "anomaly_alerts": bool(prefs["anomaly_alerts"]),
            "watchlist_alerts": bool(prefs["watchlist_alerts"]),
            "system_alerts": bool(prefs["system_alerts"]),
            "anomaly_threshold": float(prefs["anomaly_threshold"]) if prefs["anomaly_threshold"] is not None else 10.0
        }
    except sqlite3.Error as e:
        log.error(f"Database error fetching preferences: {e}")
        return {
            "discord_enabled": True,
            "telegram_enabled": True,
            "anomaly_alerts": True,
            "watchlist_alerts": True,
            "system_alerts": True,
            "anomaly_threshold": 10.0
        }
    finally:
        db.close()

@app.put("/notifications/preferences")
def update_notification_preferences(
    prefs: NotificationPreferences,
    _: bool = Depends(verify_admin)
):
    db = get_db()
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        db.execute('''
            INSERT INTO notification_preferences 
                (id, discord_enabled, telegram_enabled, anomaly_alerts, 
                 watchlist_alerts, system_alerts, anomaly_threshold, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                discord_enabled = excluded.discord_enabled,
                telegram_enabled = excluded.telegram_enabled,
                anomaly_alerts = excluded.anomaly_alerts,
                watchlist_alerts = excluded.watchlist_alerts,
                system_alerts = excluded.system_alerts,
                anomaly_threshold = excluded.anomaly_threshold,
                updated_at = excluded.updated_at
        ''', (
            1 if prefs.discord_enabled else 0,
            1 if prefs.telegram_enabled else 0,
            1 if prefs.anomaly_alerts else 0,
            1 if prefs.watchlist_alerts else 0,
            1 if prefs.system_alerts else 0,
            prefs.anomaly_threshold,
            timestamp
        ))
        
        db.commit()
        
        # Clear notifier cache
        notifier = Notifier()
        notifier.clear_cache()
        
        log.info(f"Notification preferences updated: threshold={prefs.anomaly_threshold}")
        return {"status": "success", "message": "Notification preferences updated"}
    except sqlite3.Error as e:
        log.error(f"Database error updating preferences: {e}")
        raise HTTPException(status_code=500, detail="Database error during update")
    except Exception as e:
        log.error(f"Failed to update notification preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to update preferences")
    finally:
        db.close()

@app.post("/notifications/test")
def test_notification(
    request: Request,
    _: bool = Depends(verify_admin)
):
    # Rate limit: 3 requests per hour per IP
    client_ip = request.client.host if request.client else "unknown"
    rate_limit(f"test_notif_{client_ip}", max_requests=3, window_seconds=3600)
    
    db = get_db()
    try:
        prefs = db.execute("SELECT * FROM notification_preferences WHERE id = 1").fetchone()
        
        notifier = Notifier()
        test_msg = f"🔔 **Test Notification**\n\nThis is a test message from PolySINT.\nSent at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        
        channels_used = []
        channels_failed = []
        
        if prefs:
            if prefs['discord_enabled'] and notifier.discord_url:
                try:
                    notifier.send_discord(test_msg, title="🧪 Test Notification")
                    channels_used.append("Discord")
                except Exception as e:
                    channels_failed.append(f"Discord: {str(e)}")
                    
            if prefs['telegram_enabled'] and notifier.tg_token:
                try:
                    notifier.send_telegram(test_msg, title="🧪 Test Notification")
                    channels_used.append("Telegram")
                except Exception as e:
                    channels_failed.append(f"Telegram: {str(e)}")
        
        response = {
            "status": "success",
            "message": f"Test notification sent to {len(channels_used)} channel(s)",
            "channels": channels_used
        }
        
        if channels_failed:
            response["warnings"] = channels_failed
        
        return response
    except Exception as e:
        log.error(f"Failed to send test notification: {e}")
        raise HTTPException(status_code=500, detail="Failed to send test notification")
    finally:
        db.close()
```

## 3. Notifier with Preference Filtering (`notifier.py`)

```python
import requests
from config import Config
from logger import get_logger
from db import get_db
import math
from urllib.parse import urlparse

log = get_logger("Notifier")

class Notifier:
    def __init__(self):
        self.discord_url = Config.DISCORD_WEBHOOK_URL
        self.tg_token = Config.TELEGRAM_BOT_TOKEN
        self.tg_chat_id = Config.TELEGRAM_CHAT_ID
        self._prefs_cache = None
    
    def _get_preferences(self):
        """Load notification preferences with caching"""
        if self._prefs_cache is not None:
            return self._prefs_cache
        
        db = None
        try:
            db = get_db()
            prefs = db.execute("SELECT * FROM notification_preferences WHERE id = 1").fetchone()
            
            if prefs:
                self._prefs_cache = {
                    "discord_enabled": bool(prefs["discord_enabled"]),
                    "telegram_enabled": bool(prefs["telegram_enabled"]),
                    "anomaly_alerts": bool(prefs["anomaly_alerts"]),
                    "watchlist_alerts": bool(prefs["watchlist_alerts"]),
                    "system_alerts": bool(prefs["system_alerts"]),
                    "anomaly_threshold": float(prefs["anomaly_threshold"]) if prefs["anomaly_threshold"] is not None else 10.0
                }
                return self._prefs_cache
        except Exception as e:
            log.warning(f"Failed to load notification preferences: {e}")
        finally:
            if db:
                db.close()
        
        # Defaults
        self._prefs_cache = {
            "discord_enabled": True,
            "telegram_enabled": True,
            "anomaly_alerts": True,
            "watchlist_alerts": True,
            "system_alerts": True,
            "anomaly_threshold": 10.0
        }
        return self._prefs_cache
    
    def _validate_url(self, url: str, allowed_domains: set) -> bool:
        """Validate webhook URL to prevent SSRF"""
        if not url:
            return False
        try:
            parsed = urlparse(url)
            return parsed.scheme in {"https"} and parsed.netloc in allowed_domains
        except Exception:
            return False
    
    def _should_send_notification(self, notification_type: str, alert_data: dict = None) -> bool:
        """Check if notification should be sent based on preferences"""
        prefs = self._get_preferences()
        
        valid_types = {"anomaly", "watchlist", "system", "general"}
        if notification_type not in valid_types:
            notification_type = "general"
        
        # Check alert type preferences
        if notification_type == "anomaly" and not prefs.get("anomaly_alerts", True):
            return False
        elif notification_type == "watchlist" and not prefs.get("watchlist_alerts", True):
            return False
        elif notification_type == "system" and not prefs.get("system_alerts", True):
            return False
        
        # Check anomaly threshold
        if notification_type == "anomaly" and alert_data and "shift" in alert_data:
            try:
                shift = float(alert_data["shift"])
                if math.isnan(shift) or math.isinf(shift):
                    return True  # Send on invalid data
                threshold = prefs.get("anomaly_threshold", 10.0)
                if abs(shift) < threshold:
                    return False
            except (TypeError, ValueError):
                return True  # Send on parse error
        
        return True
    
    def _escape_markdown(self, text: str, mode: str = "telegram") -> str:
        """Escape markdown special characters"""
        if mode == "telegram":
            escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        else:  # discord
            escape_chars = ['*', '_', '~', '`', '|', '>', '#']
        
        for char in escape_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    def send_discord(self, message: str, title: str = "PolySINT Alert",
                     notification_type: str = "general", alert_data: dict = None):
        if not self.discord_url:
            return
        
        if not self._validate_url(self.discord_url, {"discord.com", "discordapp.com"}):
            log.error("Invalid Discord webhook URL")
            return
        
        if not self._should_send_notification(notification_type, alert_data):
            log.info(f"Discord notification suppressed: {title}")
            return
        
        prefs = self._get_preferences()
        if not prefs.get("discord_enabled", True):
            return
        
        safe_title = self._escape_markdown(title, "discord")
        safe_message = self._escape_markdown(message, "discord")
        
        payload = {
            "embeds": [{
                "title": safe_title,
                "description": safe_message,
                "color": 16711680
            }]
        }
        
        try:
            resp = requests.post(self.discord_url, json=payload, timeout=10)
            resp.raise_for_status()
            log.info(f"Discord notification sent: {title}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                log.error(f"Discord rate limited: {e}")
            else:
                log.error(f"Discord HTTP error {e.response.status_code}: {e}")
        except Exception as e:
            log.error(f"Discord broadcast failed: {e}")
    
    def send_telegram(self, message: str, title: str = "PolySINT Alert",
                      notification_type: str = "general", alert_data: dict = None):
        if not self.tg_token or not self.tg_chat_id:
            return
        
        if not self._should_send_notification(notification_type, alert_data):
            log.info(f"Telegram notification suppressed: {title}")
            return
        
        prefs = self._get_preferences()
        if not prefs.get("telegram_enabled", True):
            return
        
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        safe_title = self._escape_markdown(title, "telegram")
        safe_message = self._escape_markdown(message, "telegram")
        formatted_message = f"*{safe_title}*\n\n{safe_message}"
        
        payload = {
            "chat_id": self.tg_chat_id,
            "text": formatted_message,
            "parse_mode": "Markdown"
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            log.info(f"Telegram notification sent: {title}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                log.error(f"Telegram rate limited: {e}")
            else:
                log.error(f"Telegram HTTP error {e.response.status_code}: {e}")
        except Exception as e:
            log.error(f"Telegram broadcast failed: {e}")
    
    def broadcast(self, message: str, title: str = "PolySINT Alert",
                  notification_type: str = "general", alert_data: dict = None):
        if not self._should_send_notification(notification_type, alert_data):
            log.info(f"Notification suppressed by preferences: {title}")
            print(f"\n[{title}] (SUPPRESSED by preferences)\n{message}\n")
            return
        
        self.send_discord(message, title, notification_type, alert_data)
        self.send_telegram(message, title, notification_type, alert_data)
        print(f"\n[{title}]\n{message}\n")
    
    def clear_cache(self):
        """Clear preferences cache"""
        self._prefs_cache = None
```

## 4. Frontend Integration (`static/index.html` and `static/app.js`)

Add a notification preferences button to the toolbar:
```html
<button onclick="openNotificationModal()" 
        class="bg-gray-700 hover:bg-gray-600 text-gray-200 px-3 py-1 rounded text-xs transition-colors border border-gray-600">
    🔔 Notifications
</button>
```

Add the notification modal (place after the AI modal):
```html
<div id="notificationModal" class="hidden fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50">
    <div class="bg-gray-800 rounded-lg shadow-xl w-full max-w-md mx-4">
        <div class="flex justify-between items-center border-b border-gray-700 px-6 py-4">
            <h3 class="text-lg font-semibold text-white">🔔 Notification Preferences</h3>
            <button onclick="closeNotificationModal()" class="text-gray-400 hover:text-white">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
            </button>
        </div>
        <div class="p-6 space-y-4">
            <div class="space-y-3">
                <h4 class="text-sm font-medium text-gray-300">Channels</h4>
                <div class="flex items-center justify-between">
                    <span class="text-blue-400">Discord</span>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" id="discordEnabled" class="sr-only peer">
                        <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                    </label>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-cyan-400">Telegram</span>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" id="telegramEnabled" class="sr-only peer">
                        <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-cyan-600"></div>
                    </label>
                </div>
            </div>
            
            <div class="space-y-3 pt-4 border-t border-gray-700">
                <h4 class="text-sm font-medium text-gray-300">Alert Types</h4>
                <div class="flex items-center justify-between">
                    <span class="text-sm text-gray-400">Market Anomalies</span>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" id="anomalyAlerts" class="sr-only peer">
                        <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-red-600"></div>
                    </label>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-sm text-gray-400">Watchlist Activity</span>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" id="watchlistAlerts" class="sr-only peer">
                        <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600"></div>
                    </label>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-sm text-gray-400">System Alerts</span>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" id="systemAlerts" class="sr-only peer">
                        <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-yellow-600"></div>
                    </label>
                </div>
            </div>
            
            <div class="space-y-3 pt-4 border-t border-gray-700">
                <h4 class="text-sm font-medium text-gray-300">Anomaly Threshold</h4>
                <div class="flex items-center space-x-4">
                    <input type="range" id="anomalyThreshold" min="1" max="50" value="10" 
                           class="w-full h-2 bg-gray-600 rounded-lg appearance-none cursor-pointer">
                    <span id="thresholdValue" class="text-sm text-polysint font-mono min-w-[40px]">10%</span>
                </div>
                <p class="text-xs text-gray-500">Minimum price shift to trigger anomaly alerts</p>
            </div>
            
            <div class="pt-4 border-t border-gray-700">
                <button onclick="testNotifications()" 
                        class="w-full bg-gray-700 hover:bg-gray-600 text-gray-200 font-medium py-2 px-4 rounded transition-colors">
                    🧪 Send Test Notification
                </button>
            </div>
            
            <div id="notificationError" class="text-xs text-red-400 hidden"></div>
            <div id="notificationSuccess" class="text-xs text-emerald-400 hidden"></div>
        </div>
        <div class="border-t border-gray-700 px-6 py-4 flex justify-end space-x-3">
            <button onclick="closeNotificationModal()" class="px-4 py-2 text-gray-400 hover:text-white transition-colors">
                Cancel
            </button>
            <button onclick="saveNotificationPreferences()" 
                    class="px-4 py-2 bg-polysint hover:bg-emerald-400 text-gray-900 font-medium rounded transition-colors">
                Save Preferences
            </button>
        </div>
    </div>
</div>
```

Add to `static/app.js`:
```javascript
// Notification Preferences Modal Functions
async function openNotificationModal() {
    const modal = document.getElementById('notificationModal');
    if (!modal) return;
    
    modal.classList.remove('hidden');
    
    try {
        const res = await fetch('/notifications/preferences');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        
        const prefs = await res.json();
        
        // Set checkbox states with null checks
        const discordEl = document.getElementById('discordEnabled');
        const telegramEl = document.getElementById('telegramEnabled');
        const anomalyEl = document.getElementById('anomalyAlerts');
        const watchlistEl = document.getElementById('watchlistAlerts');
        const systemEl = document.getElementById('systemAlerts');
        const thresholdEl = document.getElementById('anomalyThreshold');
        const thresholdValueEl = document.getElementById('thresholdValue');
        
        if (discordEl) discordEl.checked = prefs.discord_enabled !== false;
        if (telegramEl) telegramEl.checked = prefs.telegram_enabled !== false;
        if (anomalyEl) anomalyEl.checked = prefs.anomaly_alerts !== false;
        if (watchlistEl) watchlistEl.checked = prefs.watchlist_alerts !== false;
        if (systemEl) systemEl.checked = prefs.system_alerts !== false;
        
        // Set threshold with validation
        const threshold = prefs.anomaly_threshold || 10.0;
        const clampedThreshold = Math.max(1, Math.min(50, parseFloat(threshold) || 10.0));
        
        if (thresholdEl) {
            thresholdEl.value = clampedThreshold;
        }
        if (thresholdValueEl) {
            thresholdValueEl.textContent = `${clampedThreshold}%`;
        }
        
    } catch (e) {
        console.error('Failed to load preferences:', e);
        showInlineError('notificationError', 'Failed to load preferences');
    }
}

function closeNotificationModal() {
    const modal = document.getElementById('notificationModal');
    if (modal) modal.classList.add('hidden');
    clearInlineError('notificationError');
    clearInlineSuccess('notificationSuccess');
}

// Attach event listener after DOM load
document.addEventListener('DOMContentLoaded', function() {
    const thresholdSlider = document.getElementById('anomalyThreshold');
    const thresholdValue = document.getElementById('thresholdValue');
    
    if (thresholdSlider && thresholdValue) {
        thresholdSlider.addEventListener('input', function(e) {
            const val = parseFloat(e.target.value);
            const clamped = Math.max(1, Math.min(50, val));
            thresholdValue.textContent = `${clamped}%`;
        });
    }
});

async function saveNotificationPreferences() {
    const discordEl = document.getElementById('discordEnabled');
    const telegramEl = document.getElementById('telegramEnabled');
    const anomalyEl = document.getElementById('anomalyAlerts');
    const watchlistEl = document.getElementById('watchlistAlerts');
    const systemEl = document.getElementById('systemAlerts');
    const thresholdEl = document.getElementById('anomalyThreshold');
    
    if (!discordEl || !telegramEl || !thresholdEl) {
        showInlineError('notificationError', 'Form elements not found');
        return;
    }
    
    const prefs = {
        discord_enabled: discordEl.checked,
        telegram_enabled: telegramEl.checked,
        anomaly_alerts: anomalyEl ? anomalyEl.checked : true,
        watchlist_alerts: watchlistEl ? watchlistEl.checked : true,
        system_alerts: systemEl ? systemEl.checked : true,
        anomaly_threshold: parseFloat(thresholdEl.value) || 10.0
    };
    
    // Validate threshold range
    if (prefs.anomaly_threshold < 1 || prefs.anomaly_threshold > 50) {
        showInlineError('notificationError', 'Threshold must be between 1 and 50');
        return;
    }
    
    try {
        const res = await fetch('/notifications/preferences', {
            method: 'PUT',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}`
            },
            body: JSON.stringify(prefs)
        });
        
        if (res.ok) {
            showInlineSuccess('notificationSuccess', '✓ Preferences saved');
            setTimeout(() => {
                closeNotificationModal();
                clearInlineSuccess('notificationSuccess');
            }, 1500);
        } else {
            const data = await res.json();
            throw new Error(data.detail || 'Failed to save');
        }
    } catch (e) {
        showInlineError('notificationError', e.message || 'Failed to save preferences');
    }
}

async function testNotifications() {
    try {
        const res = await fetch('/notifications/test', { 
            method: 'POST',
            headers: { 'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}` }
        });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || `HTTP ${res.status}`);
        }
        
        const data = await res.json();
        showInlineSuccess('notificationSuccess', `✓ ${data.message}`);
        setTimeout(() => clearInlineSuccess('notificationSuccess'), 3000);
    } catch (e) {
        showInlineError('notificationError', e.message || 'Failed to send test');
    }
}

// Helper functions (reusing existing ones if available)
function showInlineError(id, msg) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = msg;
        el.classList.remove('hidden');
        el.classList.add('text-red-400');
    }
}

function clearInlineError(id) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = '';
        el.classList.add('hidden');
    }
}

function showInlineSuccess(id, msg) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = msg;
        el.classList.remove('hidden');
        el.classList.add('text-emerald-400');
    }
}

function clearInlineSuccess(id) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = '';
        el.classList.add('hidden');
    }
}
```

## 5. Integration with Existing Components

Update `alerts.py` to pass notification data:
```python
# In both primary and fallback paths, update the broadcast call:
notifier.broadcast(
    msg, 
    title="🚨 Market Anomaly Detected",
    notification_type="anomaly",
    alert_data={
        "shift": float(shift) if clob_token_id else float(diff),
        "market_id": str(m['id']),
        "volume": float(market_volume)
    }
)
```

Update `watcher.py`:
```python
notifier.broadcast(
    msg,
    title="🐳 OSINT Target Activity",
    notification_type="watchlist",
    alert_data={
        "address": str(address),
        "trade_id": str(trade_id)
    }
)
```

Update `start.py`:
```python
# Boot notification
notifier.broadcast(
    message="**All PolySINT daemon workers have been successfully launched.**\nAwaiting anomalies and entity movements...",
    title="🚀 System Boot: Online",
    notification_type="system"
)

# Heartbeat notification
notifier.broadcast(
    message=status_msg,
    title=title,
    notification_type="system"
)
```

## Summary

This implementation provides a secure, robust notification preference system with:

1. **Single-row database design** with proper migrations and constraints
2. **Secure API endpoints** with token authentication and rate limiting
3. **Preference filtering** in the Notifier with caching and threshold control
4. **User-friendly frontend** with real-time feedback and validation
5. **Test functionality** to verify notification channels
6. **Backward compatibility** with existing behavior as defaults

The system is designed for single-admin use while providing comprehensive control over notification behavior and security. Set the `POLYSINT_ADMIN_TOKEN` environment variable to secure the preference endpoints, and store the token in the frontend session storage after authentication.
</synthesis_output>

    <confidence>
        0.85
    </confidence>

    <refinement_areas>
        The authentication mechanism could be extended to support multiple users if needed. The frontend authentication flow (login page) is not implemented. Additional error handling could be added for network failures during preference saves. The rate limiting is in-memory and may not persist across restarts.
    </refinement_areas>

    <needs_iteration>
        false
    </needs_iteration>

    <ranking>
        <rank position="1">822</rank>
        <rank position="2">812</rank>
        <rank position="3">807</rank>
        <rank position="4">684</rank>
    </ranking>
</synthesis_output>
