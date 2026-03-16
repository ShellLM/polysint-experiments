Here's a complete refactoring of `start.py` to use systemd services with supervisor as an alternative:

## Systemd Service Configuration

### 1. Main Target File (`/etc/systemd/system/polysint.target`)
```ini
[Unit]
Description=PolySINT Intelligence Engine Stack
After=network.target

[Install]
WantedBy=multi-user.target
```

### 2. API Service (`/etc/systemd/system/polysint-api.service`)
```ini
[Unit]
Description=PolySINT API Server
PartOf=polysint.target
After=network.target

[Service]
Type=exec
User=polysint
Group=polysint
WorkingDirectory=/opt/polysint
EnvironmentFile=/opt/polysint/.env
Environment="PYTHONUNBUFFERED=1"

# Run the API server
ExecStart=/opt/polysint/venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port 9000

# Send Boot Notification (replaces start.py logic)
ExecStartPost=/opt/polysint/venv/bin/python -c "
import sys
sys.path.insert(0, '/opt/polysint')
from notifier import Notifier
Notifier().broadcast(
    '**All PolySINT daemon workers have been successfully launched.**\\nAwaiting anomalies and entity movements...', 
    title='🚀 System Boot: Online'
)"

# Send Shutdown Notification
ExecStopPost=/opt/polysint/venv/bin/python -c "
import sys
sys.path.insert(0, '/opt/polysint')
from notifier import Notifier
Notifier().broadcast('System was manually shut down by the administrator.', title='🛑 System Offline')
"

Restart=on-failure
RestartSec=5s
SyslogIdentifier=polysint-api
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=polysint.target
```

### 3. Worker Template Service (`/etc/systemd/system/polysint-worker@.service`)
```ini
[Unit]
Description=PolySINT %i Worker
PartOf=polysint.target
After=network.target

[Service]
Type=exec
User=polysint
Group=polysint
WorkingDirectory=/opt/polysint
EnvironmentFile=/opt/polysint/.env
Environment="PYTHONUNBUFFERED=1"

# Runs the script corresponding to the instance name
# e.g., systemctl start polysint-worker@alerts runs alerts.py
ExecStart=/opt/polysint/venv/bin/python /opt/polysint/%i.py

Restart=on-failure
RestartSec=10s
SyslogIdentifier=polysint-%i
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=polysint.target
```

### 4. Heartbeat Timer (`/etc/systemd/system/polysint-heartbeat.timer`)
```ini
[Unit]
Description=PolySINT Heartbeat Timer

[Timer]
OnCalendar=*:0/6:00  # Every 6 hours
Persistent=true
Unit=polysint-heartbeat.service

[Install]
WantedBy=timers.target
```

### 5. Heartbeat Service (`/etc/systemd/system/polysint-heartbeat.service`)
```ini
[Unit]
Description=PolySINT Heartbeat Service

[Service]
Type=oneshot
User=polysint
Group=polysint
WorkingDirectory=/opt/polysint
EnvironmentFile=/opt/polysint/.env

# Check if the main target is active, then send heartbeat
ExecStart=/bin/bash -c '
if systemctl is-active --quiet polysint.target; then
    /opt/polysint/venv/bin/python -c "
import sys
sys.path.insert(0, \"/opt/polysint\")
from notifier import Notifier
from datetime import datetime
Notifier().broadcast(
    f\"Periodic health check: All systems operational at {datetime.now().strftime(\\\"%%H:%%M:%%S\\\")}\", 
    title=\"💚 System Heartbeat\"
)"
else
    exit 1
fi'
```

## Deployment Script (`deploy.sh`)
```bash
#!/bin/bash
set -e

PROJECT_DIR="/opt/polysint"
SERVICE_DIR="/etc/systemd/system"

echo "🚀 Deploying PolySINT Engine..."

# Create system user and directories
if ! id "polysint" &>/dev/null; then
    echo " -> Creating user 'polysint'..."
    sudo useradd -r -s /bin/false polysint
fi

sudo mkdir -p $PROJECT_DIR
sudo mkdir -p /var/log/polysint

# Copy application files
echo " -> Copying source files..."
sudo cp -r ./* $PROJECT_DIR/

# Setup Python environment
echo " -> Setting up Python environment..."
sudo -u polysint python3 -m venv $PROJECT_DIR/venv
sudo -u polysint $PROJECT_DIR/venv/bin/pip install -r $PROJECT_DIR/requirements.txt

# Install systemd services
echo " -> Installing systemd units..."
sudo cp $PROJECT_DIR/systemd/*.service $SERVICE_DIR/
sudo cp $PROJECT_DIR/systemd/*.timer $SERVICE_DIR/
sudo cp $PROJECT_DIR/systemd/*.target $SERVICE_DIR/
sudo systemctl daemon-reload

echo "✅ Deployment complete!"
echo "Start the system with: sudo systemctl start polysint.target"
echo "Enable on boot with: sudo systemctl enable polysint.target"
```

## Management Script (`manage.sh`)
```bash
#!/bin/bash
case "$1" in
    start)
        sudo systemctl start polysint.target
        echo "PolySINT started."
        ;;
    stop)
        sudo systemctl stop polysint.target
        echo "PolySINT stopped."
        ;;
    restart)
        sudo systemctl restart polysint.target
        echo "PolySINT restarted."
        ;;
    status)
        sudo systemctl status polysint.target
        ;;
    logs)
        # Usage: ./manage.sh logs api OR ./manage.sh logs alerts
        UNIT="polysint-${2:-api}"
        echo "Tailing logs for $UNIT..."
        sudo journalctl -u $UNIT -f
        ;;
    enable)
        sudo systemctl enable polysint.target
        echo "PolySINT will start on boot."
        ;;
    disable)
        sudo systemctl disable polysint.target
        echo "PolySINT disabled from starting on boot."
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs [service]|enable|disable}"
        echo "Services: api, harvester, alerts, watcher"
        exit 1
        ;;
esac
```

## Supervisor Alternative (`supervisor/polysint.conf`)
```ini
[group:polysint]
programs=polysint-api,polysint-harvester,polysint-alerts,polysint-watcher

[program:polysint-api]
command=/opt/polysint/venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port 9000
directory=/opt/polysint
user=polysint
autostart=true
autorestart=true
stdout_logfile=/var/log/polysint/api.log
stderr_logfile=/var/log/polysint/api.error.log

[program:polysint-harvester]
command=/opt/polysint/venv/bin/python harvest.py
directory=/opt/polysint
user=polysint
autostart=true
autorestart=true
stdout_logfile=/var/log/polysint/harvester.log
stderr_logfile=/var/log/polysint/harvester.error.log

[program:polysint-alerts]
command=/opt/polysint/venv/bin/python alerts.py
directory=/opt/polysint
user=polysint
autostart=true
autorestart=true
stdout_logfile=/var/log/polysint/alerts.log
stderr_logfile=/var/log/polysint/alerts.error.log

[program:polysint-watcher]
command=/opt/polysint/venv/bin/python watcher.py
directory=/opt/polysint
user=polysint
autostart=true
autorestart=true
stdout_logfile=/var/log/polysint/watcher.log
stderr_logfile=/var/log/polysint/watcher.error.log
```

## Directory Structure
```
polysint/
├── systemd/
│   ├── polysint.target
│   ├── polysint-api.service
│   ├── polysint-worker@.service
│   ├── polysint-heartbeat.timer
│   └── polysint-heartbeat.service
├── supervisor/
│   └── polysint.conf
├── *.py (application files)
├── deploy.sh
├── manage.sh
└── requirements.txt
```

## Migration Steps
1. Delete the old `start.py`
2. Create the directory structure as shown above
3. Run `chmod +x deploy.sh manage.sh`
4. Run `sudo ./deploy.sh`
5. Configure environment: `sudo nano /opt/polysint/.env`
6. Start services: `sudo systemctl start polysint.target`
7. Check status: `sudo ./manage.sh status`

This refactoring provides production-grade reliability with automatic restarts, proper logging via journalctl, and maintains all original functionality including the notification system from start.py.
