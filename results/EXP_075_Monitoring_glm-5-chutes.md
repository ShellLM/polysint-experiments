Here is the implementation for critical crash notifications and automatic restarts, along with Slack support.

### 1. Update `config.py`
Add the Slack webhook URL configuration.

```python
### FILE: config.py ###
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_NAME = "polysint_core.db"

    # Polymarket specific endpoints
    GAMMA_API = "https://gamma-api.polymarket.com/markets"
    DATA_API = "https://data-api.polymarket.com"

    # Blockchain RPC
    RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

    # LLM
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_API_BASE_URL")
    LLM_MODEL = os.getenv("ANALYSIS_MODEL")

    # Webhook Configurations
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL") # NEW
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # Web Research (Tavily)
    ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"
```

### 2. Update `notifier.py`
Add the Slack sending logic and integrate it into the broadcast method.

```python
### FILE: notifier.py ###
import requests
from config import Config
from logger import get_logger

log = get_logger("Notifier")

class Notifier:
    def __init__(self):
        self.discord_url = Config.DISCORD_WEBHOOK_URL
        self.slack_url = Config.SLACK_WEBHOOK_URL # NEW
        self.tg_token = Config.TELEGRAM_BOT_TOKEN
        self.tg_chat_id = Config.TELEGRAM_CHAT_ID

    def send_discord(self, message: str, title: str = "PolySINT Alert"):
        if not self.discord_url:
            return
        
        payload = {
            "embeds":[
                {
                    "title": title,
                    "description": message,
                    "color": 16711680  # Alert Red
                }
            ]
        }
        try:
            resp = requests.post(self.discord_url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            log.error(f"Discord broadcast failed: {e}")

    # NEW METHOD
    def send_slack(self, message: str, title: str = "PolySINT Alert"):
        if not self.slack_url:
            return
        
        # Slack attachments format for better visibility
        payload = {
            "attachments": [
                {
                    "color": "#FF0000", # Red
                    "title": title,
                    "text": message,
                    "mrkdwn_in": ["text"]
                }
            ]
        }
        try:
            resp = requests.post(self.slack_url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            log.error(f"Slack broadcast failed: {e}")

    def send_telegram(self, message: str, title: str = "PolySINT Alert"):
        if not self.tg_token or not self.tg_chat_id:
            return
        
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        formatted_message = f"*{title}*\n\n{message}"
        
        payload = {
            "chat_id": self.tg_chat_id,
            "text": formatted_message,
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            log.error(f"Telegram broadcast failed: {e}")

    def broadcast(self, message: str, title: str = "PolySINT Alert"):
        """Pushes actionable OSINT to all configured external endpoints."""
        self.send_discord(message, title)
        self.send_slack(message, title) # NEW
        self.send_telegram(message, title)
        # Fallback console print
        print(f"\n[{title}]\n{message}\n")
```

### 3. Update `start.py`
Refactor the process management to include crash detection, automatic restarts, and immediate failure notifications.

```python
### FILE: start.py ###
import subprocess
import sys
import time
from datetime import datetime
from logger import get_logger
from notifier import Notifier

log = get_logger("System")

# Set how often you want the Heartbeat check-in (in seconds)
HEARTBEAT_INTERVAL = 21600 

def start_engine():
    print("🚀 Starting PolySINT Engine...")
    processes = []
    notifier = Notifier()

    # Define process configurations: (Name, Command Args List)
    process_configs = [
        ("API Server", [sys.executable, "-m", "uvicorn", "api:app", "--port", "9000"]),
        ("Harvester Worker", [sys.executable, "harvest.py"]),
        ("Alerts Worker", [sys.executable, "alerts.py"]),
        ("Watcher Worker", [sys.executable, "watcher.py"]),
    ]

    try:
        # Launch initial processes
        for name, cmd in process_configs:
            print(f" -> Launching {name}...")
            proc = subprocess.Popen(cmd)
            processes.append({"name": name, "cmd": cmd, "proc": proc})
            time.sleep(2)

        print("\n✅ All systems nominal! PolySINT is fully operational.")
        print("🛑 Press [Ctrl + C] to safely shut down all systems.\n")

        # Send Boot Alert
        notifier.broadcast(
            message="**All PolySINT daemon workers have been successfully launched.**\nAwaiting anomalies and entity movements...",
            title="🚀 System Boot: Online"
        )

        last_heartbeat = time.time()

        # The Supervisor Loop
        while True:
            time.sleep(10) # Check every 10 seconds for crashes
            
            # ─── CRASH DETECTION & AUTO-RESTART ───────────────────────────────
            for p in processes:
                poll = p["proc"].poll()
                
                # If poll() is not None, the process has exited
                if poll is not None:
                    error_msg = (
                        f"**CRITICAL FAILURE:** `{p['name']}` crashed with exit code {poll}.\n"
                        f"Attempting immediate restart..."
                    )
                    log.critical(error_msg)
                    
                    # Send Alert immediately
                    notifier.broadcast(error_msg, title="🚨 Process Crash Detected")
                    
                    # Restart the process
                    try:
                        new_proc = subprocess.Popen(p["cmd"])
                        p["proc"] = new_proc # Update the stored process object
                        
                        recover_msg = f"Successfully restarted `{p['name']}`."
                        print(f" -> {recover_msg}")
                        log.info(recover_msg)
                        notifier.broadcast(f"**Recovery:** {recover_msg}", title="🛠️ System Recovery")
                    except Exception as e:
                        fatal_msg = f"FATAL: Failed to restart `{p['name']}`: {e}"
                        print(f" -> {fatal_msg}")
                        log.error(fatal_msg)
                        notifier.broadcast(fatal_msg, title="🆘 Recovery Failed")

            # ─── PERIODIC HEARTBEAT ───────────────────────────────────────────
            current_time = time.time()
            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                status_msg = "**Periodic Health Check:**\n"
                all_healthy = True
                
                for p in processes:
                    # Check if process is running
                    if p["proc"].poll() is None:
                        status_msg += f"🟢 **{p['name']}**: Online\n"
                    else:
                        status_msg += f"🔴 **{p['name']}**: Offline\n"
                        all_healthy = False
                
                # Change title/color based on health
                title = "💚 System Heartbeat" if all_healthy else "⚠️ System Degraded"
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending Heartbeat to configured channels...")
                notifier.broadcast(message=status_msg, title=title)
                
                last_heartbeat = current_time

    except KeyboardInterrupt:
        print("\n\n⚠️ Shutting down PolySINT Engine...")
        
        # Send Shutdown Alert
        notifier.broadcast(message="System was manually shut down by the administrator.", title="🛑 System Offline")
        
        for p in processes:
            print(f" -> Stopping {p['name']}...")
            p["proc"].terminate() 
            p["proc"].wait()      
        print("🛑 Shutdown complete. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    start_engine()
```
