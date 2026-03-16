I'll create a comprehensive health-check system for monitoring PolySINT services. This implementation uses a modular router approach with multiple endpoints for different monitoring needs, including Prometheus metrics support.

        ## 1. Create the Health Router Module

```python
### FILE: health.py ###
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from datetime import datetime, timezone
from config import Config
from db import get_db
from clob import CLOB_BASE
from logger import get_logger
import requests
import time
import psutil
import os

log = get_logger("HealthCheck")
router = APIRouter(prefix="/health", tags=["health"])

# Thresholds for alerts
CPU_WARNING = 70
CPU_CRITICAL = 90
MEMORY_WARNING = 80
MEMORY_CRITICAL = 95
DISK_WARNING = 80
DISK_CRITICAL = 95


def check_database():
    """Check database connectivity and record counts"""
    start = time.time()
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT 1")
        cursor.execute("SELECT COUNT(*) FROM markets")
        market_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM watch_list")
        watchlist_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM snapshots")
        snapshot_count = cursor.fetchone()[0]
        db.close()

        return {
            "status": "healthy",
            "details": {
                "connected": True,
                "market_count": market_count,
                "watchlist_count": watchlist_count,
                "snapshot_count": snapshot_count,
                "response_time_ms": round((time.time() - start) * 1000, 2)
            }
        }
    except Exception as e:
        log.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "response_time_ms": round((time.time() - start) * 1000, 2)
        }


def check_clob_api():
    """Check Polymarket CLOB API connectivity"""
    start = time.time()
    try:
        resp = requests.get(
            f"{CLOB_BASE}/time",
            timeout=5,
            verify=False
        )
        response_time = round((time.time() - start) * 1000, 2)

        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": "healthy",
                "details": {
                    "base_url": CLOB_BASE,
                    "status_code": resp.status_code,
                    "server_time": data.get("serverTime"),
                    "response_time_ms": response_time
                }
            }
        else:
            return {
                "status": "degraded",
                "details": {
                    "base_url": CLOB_BASE,
                    "status_code": resp.status_code,
                    "response_time_ms": response_time
                }
            }
    except requests.exceptions.Timeout:
        return {"status": "unhealthy", "error": "Connection timeout", "response_time_ms": round((time.time() - start) * 1000, 2)}
    except requests.exceptions.ConnectionError:
        return {"status": "unhealthy", "error": "Connection failed", "response_time_ms": round((time.time() - start) * 1000, 2)}
    except Exception as e:
        log.error(f"CLOB API health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "response_time_ms": round((time.time() - start) * 1000, 2)}


def check_gamma_api():
    """Check Polymarket Gamma API connectivity"""
    start = time.time()
    try:
        resp = requests.get(
            f"{Config.GAMMA_API}?limit=1",
            timeout=5
        )
        response_time = round((time.time() - start) * 1000, 2)

        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": "healthy",
                "details": {
                    "base_url": Config.GAMMA_API,
                    "status_code": resp.status_code,
                    "markets_available": len(data) if isinstance(data, list) else None,
                    "response_time_ms": response_time
                }
            }
        else:
            return {
                "status": "degraded",
                "details": {
                    "base_url": Config.GAMMA_API,
                    "status_code": resp.status_code,
                    "response_time_ms": response_time
                }
            }
    except Exception as e:
        log.error(f"Gamma API health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "response_time_ms": round((time.time() - start) * 1000, 2)}


def check_llm_api():
    """Check LLM API connectivity if configured"""
    start = time.time()
    try:
        if Config.LLM_API_KEY and Config.LLM_BASE_URL:
            resp = requests.get(
                Config.LLM_BASE_URL.rstrip('/') + "/models",
                headers={"Authorization": f"Bearer {Config.LLM_API_KEY}"},
                timeout=5
            )
            status = "healthy" if resp.status_code < 500 else "degraded"
            return {
                "status": status,
                "details": {
                    "configured": True,
                    "status_code": resp.status_code,
                    "response_time_ms": round((time.time() - start) * 1000, 2)
                }
            }
        else:
            return {"status": "not_configured", "details": {"configured": False}}
    except Exception as e:
        log.error(f"LLM API health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "response_time_ms": round((time.time() - start) * 1000, 2)}


def check_background_services():
    """Check if daemon processes are running"""
    try:
        services = {
            "harvester": any("harvest.py" in (p.info.get('cmdline') or []) for p in psutil.process_iter(['cmdline'])),
            "alerts": any("alerts.py" in (p.info.get('cmdline') or []) for p in psutil.process_iter(['cmdline'])),
            "watcher": any("watcher.py" in (p.info.get('cmdline') or []) for p in psutil.process_iter(['cmdline']))
        }

        all_running = all(services.values())
        return {
            "status": "healthy" if all_running else "degraded",
            "details": services
        }
    except Exception as e:
        log.error(f"Background services check failed: {e}")
        return {"status": "error", "error": str(e)}


def check_system_metrics():
    """Collect system resource metrics"""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        process = psutil.Process()
        process_memory = process.memory_info()

        # Determine status based on thresholds
        status = "healthy"
        warnings = []

        if cpu_percent > CPU_WARNING:
            status = "degraded" if cpu_percent < CPU_CRITICAL else "unhealthy"
            warnings.append(f"CPU usage: {cpu_percent}%")

        if memory.percent > MEMORY_WARNING:
            status = "degraded" if memory.percent < MEMORY_CRITICAL else "unhealthy"
            warnings.append(f"Memory usage: {memory.percent}%")

        if disk.percent > DISK_WARNING:
            status = "degraded" if disk.percent < DISK_CRITICAL else "unhealthy"
            warnings.append(f"Disk usage: {disk.percent}%")

        return {
            "status": status,
            "warnings": warnings,
            "metrics": {
                "cpu_percent": cpu_percent,
                "memory": {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "available_gb": round(memory.available / (1024**3), 2),
                    "percent_used": memory.percent
                },
                "disk": {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "percent_used": disk.percent
                },
                "process": {
                    "pid": process.pid,
                    "memory_rss_mb": round(process_memory.rss / (1024**2), 2),
                    "uptime_seconds": round(time.time() - process.create_time(), 2),
                    "threads": process.num_threads()
                }
            }
        }
    except Exception as e:
        log.error(f"System metrics collection failed: {e}")
        return {"status": "error", "error": str(e)}


@router.get("")
@router.get("/")
async def health_check():
    """
    Comprehensive health check endpoint for monitoring tools.
    Returns detailed status of all system components.
    """
    start_time = time.time()

    checks = {
        "database": check_database(),
        "clob_api": check_clob_api(),
        "gamma_api": check_gamma_api(),
        "llm_api": check_llm_api(),
        "background_services": check_background_services()
    }

    system = check_system_metrics()

    # Determine overall status
    all_statuses = [check.get("status") for check in checks.values()]
    all_statuses.append(system.get("status"))

    if all(status == "healthy" for status in all_statuses):
        overall_status = "healthy"
        status_code = 200
    elif any(status == "unhealthy" for status in all_statuses):
        overall_status = "unhealthy"
        status_code = 503
    else:
        overall_status = "degraded"
        status_code = 200

    response = {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "PolySINT Core Engine",
        "check_duration_ms": round((time.time() - start_time) * 1000, 2),
        "checks": checks,
        "system": system
    }

    return JSONResponse(
        content=response,
        status_code=status_code,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Health-Status": overall_status
        }
    )


@router.get("/simple")
async def simple_health_check():
    """
    Lightweight health check for load balancers.
    Only checks database connectivity.
    """
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        db.close()
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "error": str(e)}
        )


@router.get("/ready")
async def readiness_probe():
    """
    Kubernetes readiness probe.
    Checks critical dependencies before accepting traffic.
    """
    db_check = check_database()
    clob_check = check_clob_api()

    if db_check["status"] == "healthy" and clob_check["status"] in ["healthy", "degraded"]:
        return {"status": "ready"}
    else:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "database": db_check["status"],
                "clob_api": clob_check["status"]
            }
        )


@router.get("/live")
async def liveness_probe():
    """
    Kubernetes liveness probe.
    Verifies the process is alive and responsive.
    """
    process = psutil.Process()
    memory_mb = process.memory_info().rss / (1024 * 1024)

    # If process is using over 2GB, something is wrong
    if memory_mb > 2048:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "unhealthy",
                "reason": f"Memory limit exceeded: {round(memory_mb, 2)}MB"
            }
        )

    return {
        "status": "alive",
        "memory_mb": round(memory_mb, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/metrics")
async def prometheus_metrics():
    """
    Prometheus-compatible metrics endpoint.
    Returns system metrics in plain text format for scraping.
    """
    try:
        process = psutil.Process()
        process_memory = process.memory_info()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        metrics = []

        # CPU
        metrics.append('# HELP polysint_cpu_percent CPU usage percentage')
        metrics.append('# TYPE polysint_cpu_percent gauge')
        metrics.append(f'polysint_cpu_percent {psutil.cpu_percent(interval=0.1)}')

        # Process Memory
        metrics.append('# HELP polysint_process_memory_bytes Process memory usage')
        metrics.append('# TYPE polysint_process_memory_bytes gauge')
        metrics.append(f'polysint_process_memory_bytes{{type="rss"}} {process_memory.rss}')
        metrics.append(f'polysint_process_memory_bytes{{type="vms"}} {process_memory.vms}')

        # System Memory
        metrics.append('# HELP polysint_system_memory_bytes System memory')
        metrics.append('# TYPE polysint_system_memory_bytes gauge')
        metrics.append(f'polysint_system_memory_bytes{{type="total"}} {memory.total}')
        metrics.append(f'polysint_system_memory_bytes{{type="available"}} {memory.available}')

        # Disk
        metrics.append('# HELP polysint_disk_bytes Disk usage')
        metrics.append('# TYPE polysint_disk_bytes gauge')
        metrics.append(f'polysint_disk_bytes{{type="total"}} {disk.total}')
        metrics.append(f'polysint_disk_bytes{{type="free"}} {disk.free}')

        # Database counts
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute("SELECT COUNT(*) FROM markets")
            market_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM watch_list")
            watchlist_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM snapshots")
            snapshot_count = cursor.fetchone()[0]
            db.close()

            metrics.append('# HELP polysint_database_records Database record counts')
            metrics.append('# TYPE polysint_database_records gauge')
            metrics.append(f'polysint_database_records{{table="markets"}} {market_count}')
            metrics.append(f'polysint_database_records{{table="watch_list"}} {watchlist_count}')
            metrics.append(f'polysint_database_records{{table="snapshots"}} {snapshot_count}')
        except:
            pass

        # Uptime
        metrics.append('# HELP polysint_uptime_seconds Process uptime')
        metrics.append('# TYPE polysint_uptime_seconds gauge')
        metrics.append(f'polysint_uptime_seconds {round(time.time() - process.create_time(), 2)}')

        return Response(
            content="\n".join(metrics) + "\n",
            media_type="text/plain",
            headers={"Cache-Control": "no-cache"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Export router for inclusion in main app
health_router = router
```

## 2. Update api.py to Include the Health Router

Add this import near the top of `api.py`:

```python
from health import health_router
```

Add this line after creating the FastAPI app instance:

```python
app.include_router(health_router)
```

## 3. Add psutil to Dependencies

```bash
# Add to requirements.txt
psutil>=5.9.0
```

## 4. Create Monitoring Client Script

```python
### FILE: monitor.py ###
#!/usr/bin/env python3
"""
PolySINT Health Check Client
Usage:
    python monitor.py                  # Full health check
    python monitor.py --simple         # Quick check
    python monitor.py --metrics        # Show Prometheus metrics
    python monitor.py --watch          # Continuous monitoring
"""
import requests
import json
import sys
import time
import argparse
from datetime import datetime


class PolySINTMonitor:
    def __init__(self, base_url="http://localhost:9000"):
        self.base_url = base_url.rstrip('/')

    def check_health(self):
        """Full health check"""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=10)
            return resp.status_code, resp.json()
        except requests.exceptions.ConnectionError:
            return 0, {"status": "unreachable", "error": "Connection refused"}
        except Exception as e:
            return 0, {"status": "error", "error": str(e)}

    def check_simple(self):
        """Simple readiness check"""
        try:
            resp = requests.get(f"{self.base_url}/health/simple", timeout=5)
            return resp.status_code == 200
        except:
            return False

    def get_metrics(self):
        """Fetch Prometheus metrics"""
        try:
            resp = requests.get(f"{self.base_url}/health/metrics", timeout=5)
            return resp.text if resp.status_code == 200 else None
        except:
            return None

    def watch(self, interval=30):
        """Continuous monitoring"""
        print(f"Monitoring {self.base_url} every {interval}s (Ctrl+C to stop)\n")
        try:
            while True:
                status_code, data = self.check_health()
                status = data.get("status", "unknown")
                icon = {"healthy": "[OK]", "degraded": "[WARN]", "unhealthy": "[ERR]"}.get(status, "[?]")
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"{timestamp} {icon} {status.upper()}")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped.")


def main():
    parser = argparse.ArgumentParser(description="PolySINT Monitor")
    parser.add_argument("--url", default="http://localhost:9000", help="Base URL")
    parser.add_argument("--simple", action="store_true", help="Simple check")
    parser.add_argument("--metrics", action="store_true", help="Show metrics")
    parser.add_argument("--watch", action="store_true", help="Continuous mode")
    parser.add_argument("--interval", type=int, default=30, help="Watch interval (seconds)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    monitor = PolySINTMonitor(args.url)

    if args.watch:
        monitor.watch(args.interval)
    elif args.metrics:
        metrics = monitor.get_metrics()
        print(metrics if metrics else "Failed to fetch metrics")
    elif args.simple:
        ok = monitor.check_simple()
        print("[OK] Ready" if ok else "[FAIL] Not ready")
        sys.exit(0 if ok else 1)
    else:
        status_code, data = monitor.check_health()
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            status = data.get("status", "unknown")
            print(f"\nPolySINT Health: {status.upper()}")
            print(f"Timestamp: {data.get('timestamp', 'N/A')}")
            print(f"Response: {data.get('check_duration_ms', 'N/A')}ms")
            if "checks" in data:
                print("\nComponents:")
                for name, check in data["checks"].items():
                    print(f"  {name}: {check.get('status', 'unknown')}")
        sys.exit(0 if status_code == 200 else 1)


if __name__ == "__main__":
    main()
```

## Available Endpoints

| Endpoint | Purpose | Use Case |
|----------|---------|----------|
| `/health` | Full system check | Detailed diagnostics |
| `/health/simple` | Database check | Load balancers |
| `/health/ready` | Readiness probe | Kubernetes |
| `/health/live` | Liveness probe | Kubernetes |
| `/health/metrics` | Prometheus format | Monitoring systems |

## Example Usage

```bash
# Quick check
curl http://localhost:9000/health/simple

# Full diagnostics
curl http://localhost:9000/health

# Prometheus metrics
curl http://localhost:9000/health/metrics

# Using the monitor client
python monitor.py --watch --interval 60
```
