import subprocess
import sys
import time
from datetime import datetime
from logger import get_logger
from notifier import Notifier
import sqlite3
from config import Config

log = get_logger("System")

# Set how often you want the Heartbeat check-in (in seconds)
# 21600 = 6 hours. (Change to 3600 for 1 hour, or 60 for testing)
HEARTBEAT_INTERVAL = 21600 


def check_database_health():
    """
    Tests database connectivity and returns health status with basic stats.
    Returns a dict with:
      - status: 'healthy', 'degraded', or 'offline'
      - markets: count of markets
      - snapshots: count of snapshots
      - watchlist: count of tracked wallets
      - error: error message if any
    """
    result = {
        "status": "offline",
        "markets": 0,
        "snapshots": 0,
        "watchlist": 0,
        "error": None
    }
    
    conn = None
    try:
        conn = sqlite3.connect(Config.DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Test basic connectivity with a simple query
        cursor.execute("SELECT 1")
        
        # Get market count
        cursor.execute("SELECT COUNT(*) FROM markets")
        result["markets"] = cursor.fetchone()[0]
        
        # Get snapshot count
        cursor.execute("SELECT COUNT(*) FROM snapshots")
        result["snapshots"] = cursor.fetchone()[0]
        
        # Get watchlist count
        cursor.execute("SELECT COUNT(*) FROM watch_list")
        result["watchlist"] = cursor.fetchone()[0]
        
        # Check WAL mode is active (optional health indicator)
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]
        
        # If we got here, DB is responsive
        result["status"] = "healthy" if journal_mode.lower() == "wal" else "degraded"
        
    except sqlite3.OperationalError as e:
        result["status"] = "offline"
        result["error"] = f"DB operational error: {str(e)[:50]}"
        log.error(f"Database health check failed (operational): {e}")
        
    except sqlite3.DatabaseError as e:
        result["status"] = "offline"
        result["error"] = f"DB error: {str(e)[:50]}"
        log.error(f"Database health check failed (database): {e}")
        
    except Exception as e:
        result["status"] = "offline"
        result["error"] = f"Unexpected: {str(e)[:50]}"
        log.error(f"Database health check failed (unexpected): {e}")
        
    finally:
        if conn:
            conn.close()
    
    return result


def start_engine():
    print("🚀 Starting PolySINT Engine...")
    processes = []
    notifier = Notifier()

    try:
        # 1. Start the FastAPI Server
        print(" -> Launching API Server (Port 9000)...")
        api_proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--port", "9000"])
        processes.append(("API Server", api_proc))
        time.sleep(2)

        # 2. Start the Harvester
        print(" -> Launching Data Harvester...")
        harvest_proc = subprocess.Popen([sys.executable, "harvest.py"])
        processes.append(("Harvester Worker", harvest_proc))

        # 3. Start the Alerts
        print(" -> Launching Anomaly Detector...")
        alerts_proc = subprocess.Popen([sys.executable, "alerts.py"])
        processes.append(("Alerts Worker", alerts_proc))

        # 4. Start the Watcher
        print(" -> Launching Whale Watcher...")
        watcher_proc = subprocess.Popen([sys.executable, "watcher.py"])
        processes.append(("Watcher Worker", watcher_proc))

        print("\n✅ All systems nominal! PolySINT is fully operational.")
        print("🛑 Press [Ctrl + C] to safely shut down all systems.\n")

        # Send Boot Alert
        notifier.broadcast(
            message="**All PolySINT daemon workers have been successfully launched.**\nAwaiting anomalies and entity movements...",
            title="🚀 System Boot: Online"
        )

        last_heartbeat = time.time()

        # The Heartbeat Loop
        while True:
            time.sleep(10)  # Quick loop so Ctrl+C stays responsive
            current_time = time.time()
            
            # If the interval has passed, run the health check
            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                # ─── Process Status Check ──────────────────────────────────────
                status_msg = "**Periodic Health Check:**\n\n"
                status_msg += "**Processes:**\n"
                all_healthy = True
                
                for name, p in processes:
                    # p.poll() is None means the process is still running perfectly
                    if p.poll() is None:
                        status_msg += f"🟢 **{name}**: Online\n"
                    else:
                        status_msg += f"🔴 **{name}**: Offline (Crashed)\n"
                        all_healthy = False
                
                # ─── Database Health Check ─────────────────────────────────────
                db_health = check_database_health()
                status_msg += "\n**Database:**\n"
                
                if db_health["status"] == "healthy":
                    status_msg += f"🟢 **SQLite**: Connected (WAL mode)\n"
                elif db_health["status"] == "degraded":
                    status_msg += f"🟡 **SQLite**: Connected (rollback journal)\n"
                    all_healthy = False
                else:
                    status_msg += f"🔴 **SQLite**: Offline\n"
                    if db_health["error"]:
                        status_msg += f"   └ Error: {db_health['error']}\n"
                    all_healthy = False
                
                # ─── Database Stats ────────────────────────────────────────────
                status_msg += "\n**Stats:**\n"
                status_msg += f"📊 Markets: {db_health['markets']:,}\n"
                status_msg += f"📸 Snapshots: {db_health['snapshots']:,}\n"
                status_msg += f"👁️ Watchlist: {db_health['watchlist']} targets\n"
                
                # Change title/color based on overall health
                title = "💚 System Heartbeat" if all_healthy else "⚠️ System Degraded"
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending Heartbeat to Discord...")
                notifier.broadcast(message=status_msg, title=title)
                
                last_heartbeat = current_time

    except KeyboardInterrupt:
        print("\n\n⚠️ Shutting down PolySINT Engine...")
        
        # Send Shutdown Alert
        notifier.broadcast(message="System was manually shut down by the administrator.", title="🛑 System Offline")
        
        for name, p in processes:
            print(f" -> Stopping {name}...")
            p.terminate() 
            p.wait()      
        print("🛑 Shutdown complete. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    start_engine()
