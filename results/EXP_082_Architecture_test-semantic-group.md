```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# System dependencies: curl for healthcheck, ca-certificates for HTTPS, libffi for web3
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash polysint

# Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Create data and logs directories, set ownership
RUN mkdir -p /app/data /app/logs && \
    chown -R polysint:polysint /app

USER polysint

# Health check on dashboard endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:9000/ || exit 1

# Graceful shutdown: SIGTERM is Docker's default, but we handle both SIGTERM and SIGINT
STOPSIGNAL SIGTERM

ENTRYPOINT ["python", "start.py"]
```

```txt
# requirements.txt
fastapi==0.115.6
uvicorn[standard]==0.34.0
requests==2.32.3
web3==6.20.2
openai==1.58.1
python-dotenv==1.0.1
pydantic==2.10.4
```

```yaml
# docker-compose.yml
services:
  polysint:
    build: .
    container_name: polysint-engine
    restart: unless-stopped
    ports:
      - "9000:9000"
    volumes:
      - polysint-data:/app/data
      - polysint-logs:/app/logs
    env_file:
      - .env
    environment:
      - DB_NAME=/app/data/polysint_core.db
      - LOG_DIR=/app/logs
    stop_grace_period: 30s
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:9000/"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  polysint-data:
  polysint-logs:
```

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Docker: DB_NAME=/app/data/polysint_core.db
    # Local: defaults to polysint_core.db in working directory
    DB_NAME = os.getenv("DB_NAME", "polysint_core.db")

    # Polymarket endpoints
    GAMMA_API = "https://gamma-api.polymarket.com/markets"
    DATA_API = "https://data-api.polymarket.com"

    # Blockchain RPC
    RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

    # LLM
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_API_BASE_URL")
    LLM_MODEL = os.getenv("ANALYSIS_MODEL")

    # Notifications
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # Web Research (Tavily)
    ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"
```

```python
# logger.py
import logging
import os
import sys

def get_logger(name):
    log_dir = os.getenv("LOG_DIR", ".")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "analyzer.log")

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.WARNING)

    fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # File handler — persists in mounted volume
    fh = logging.FileHandler(log_path, mode="a")
    fh.setLevel(logging.WARNING)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Stdout handler — visible in `docker compose logs`
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger
```

```python
# start.py
import subprocess
import sys
import signal
import time
from logger import get_logger
from notifier import Notifier

log = get_logger("System")

HEARTBEAT_INTERVAL = 21600  # 6 hours

# Worker registry: maps display name to script/command
WORKERS = {
    "API Server": {
        "cmd": [sys.executable, "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "9000"],
        "script": None,
    },
    "Harvester": {
        "cmd": [sys.executable, "harvest.py"],
        "script": "harvest.py",
    },
    "Alerts": {
        "cmd": [sys.executable, "alerts.py"],
        "script": "alerts.py",
    },
    "Watcher": {
        "cmd": [sys.executable, "watcher.py"],
        "script": "watcher.py",
    },
}

processes = []
shutdown_requested = False
notifier = Notifier()


def _notify_safely(title, message):
    """Send notification without crashing if webhooks are missing."""
    try:
        notifier.broadcast(message=message, title=title)
    except Exception:
        pass


def shutdown(signum=None, frame=None):
    """Graceful shutdown — handles both SIGTERM and SIGINT."""
    global shutdown_requested
    if shutdown_requested:
        return
    shutdown_requested = True

    print("\nShutting down PolySINT Engine...")
    _notify_safely("System Offline", "Shutting down by orchestrator.")

    for name, proc in processes:
        print(f" -> Stopping {name}...")
        proc.terminate()

    # Wait up to 25s for graceful exit
    deadline = time.time() + 25
    for name, proc in processes:
        remaining = max(0.1, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            print(f" -> Force-killing {name}...")
            proc.kill()
            proc.wait()

    print("Shutdown complete.")
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


def spawn_worker(name):
    """Launch a worker by name."""
    return subprocess.Popen(WORKERS[name]["cmd"])


def start_engine():
    global processes

    print("Starting PolySINT Engine...")

    # Launch all workers
    for name in WORKERS:
        print(f" -> Launching {name}...")
        proc = spawn_worker(name)
        processes.append((name, proc))

    time.sleep(2)  # Let API server bind

    print("\nAll systems nominal. PolySINT is fully operational.\n")
    _notify_safely("System Boot: Online", "All daemon workers launched.")

    last_heartbeat = time.time()

    # Main loop: health monitoring + auto-restart
    while True:
        time.sleep(10)

        if shutdown_requested:
            return

        # Auto-restart crashed workers
        for i, (name, proc) in enumerate(processes):
            if proc.poll() is not None:
                exit_code = proc.returncode
                print(f"WARNING: {name} exited (code {exit_code}). Restarting in 5s...")
                time.sleep(5)
                new_proc = spawn_worker(name)
                processes[i] = (name, new_proc)
                print(f" -> {name} restarted.")

        # Periodic heartbeat notification
        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
            lines = ["**Periodic Health Check:**\n"]
            all_healthy = True

            for name, proc in processes:
                if proc.poll() is None:
                    lines.append(f"🟢 **{name}**: Online")
                else:
                    lines.append(f"🔴 **{name}**: Offline")
                    all_healthy = False

            title = "System Heartbeat" if all_healthy else "System Degraded"
            _notify_safely(title, "\n".join(lines))
            last_heartbeat = time.time()


if __name__ == "__main__":
    start_engine()
```

```
# .dockerignore
__pycache__
*.pyc
*.pyo
*.egg-info
.env
*.log
polysint_core.db*
.git
.gitignore
node_modules
.venv
venv/
.DS_Store
README.md
Makefile
docker-compose*.yml
```

```env
# .env.example
# ─── LLM ───────────────────────────────────────────────────────────────
LLM_API_KEY=sk-your-key-here
LLM_API_BASE_URL=https://api.openai.com/v1
ANALYSIS_MODEL=gpt-4o

# ─── Blockchain ────────────────────────────────────────────────────────
POLYGON_RPC_URL=https://polygon-rpc.com

# ─── Notifications (optional) ─────────────────────────────────────────
DISCORD_WEBHOOK_URL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ─── Web Research (optional) ──────────────────────────────────────────
TAVILY_API_KEY=
ENABLE_WEB_RESEARCH=false
```

```makefile
# Makefile — convenience targets
.PHONY: build up down logs restart reset shell

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

restart:
	docker compose restart

reset:
	docker compose down -v
	docker compose up -d --build

shell:
	docker compose exec polysint /bin/bash
```

### Deployment Instructions

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 2. Build and launch
make build && make up    # or: docker compose up -d --build

# 3. Check status
docker compose ps

# 4. Stream logs (all workers interleaved)
make logs                # or: docker compose logs -f

# 5. Access dashboard
open http://localhost:9000

# 6. Graceful stop (preserves data)
make down                # or: docker compose down

# 7. Full reset (wipes database)
make reset               # or: docker compose down -v && docker compose up -d --build
```

**Key features of this setup:**

1. **Security**: Non-root user execution prevents container escape vulnerabilities
2. **Reliability**: Health checks, signal handling (both SIGTERM and SIGINT), and auto-restart of crashed workers
3. **Observability**: Logs to both file and stdout for Docker log management with rotation (10MB × 3 files)
4. **Persistence**: Named volumes for database and logs survive container restarts
5. **Production-ready**: Graceful shutdown propagates signals to all child processes, 30s grace period for clean exit
6. **Maintainability**: Centralized worker registry in WORKERS dict makes adding/removing workers trivial
7. **Robustness**: Safe notifier wrapper prevents crashes during shutdown if external services are unavailable
