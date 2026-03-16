## Security Assessment: `subprocess.Popen` in `start.py`

### Verdict: SECURE — No Command Injection Risk

The `subprocess.Popen` usage in `start.py` is **not vulnerable to command injection**. This is confirmed by three critical factors:

1. **List-Based Arguments**: All commands use the `[executable, arg1, arg2]` list format rather than string concatenation. This prevents shell metacharacters (`;`, `|`, `&`, `$()`) from being interpreted—they're treated as literal data.

2. **No Shell Execution**: The code uses the default `shell=False`, meaning Python executes the command directly without spawning `/bin/sh` or `cmd.exe`. This eliminates the shell parser entirely from the execution chain.

3. **No External Input**: All arguments are hardcoded—`sys.executable` comes from the runtime, script names are fixed literals, and the port number is a constant string. There is no vector for user-controlled data to reach command construction.

### Hardening Recommendations

While the current code is injection-proof, the following improvements would strengthen it against environment manipulation and improve operational reliability:

#### 1. Use Absolute Paths (Critical)
The current relative path resolution depends on CWD matching the script directory, which is fragile:

```python
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Before (fragile):
subprocess.Popen([sys.executable, "harvest.py"])

# After (deterministic):
subprocess.Popen([sys.executable, os.path.join(SCRIPT_DIR, "harvest.py")], cwd=SCRIPT_DIR)
```

This prevents failures when the script is invoked from a different working directory and mitigates potential binary planting attacks.

#### 2. Pre-flight Script Validation
Validate all required scripts exist before spawning any processes to avoid partial startup states:

```python
def _validate_worker_scripts():
    required = ["harvest.py", "alerts.py", "watcher.py"]
    for script in required:
        path = os.path.join(SCRIPT_DIR, script)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Missing dependency: {script}")
```

#### 3. Timeout-Based Process Cleanup
The current `p.wait()` can hang indefinitely if a worker ignores SIGTERM:

```python
try:
    proc.terminate()
    proc.wait(timeout=10)  # Wait max 10 seconds
except subprocess.TimeoutExpired:
    proc.kill()  # Escalate to SIGKILL
    proc.wait()
```

#### 4. Signal Handling
Add proper signal handlers for graceful shutdown instead of relying solely on KeyboardInterrupt:

```python
import signal

def signal_handler(signum, frame):
    graceful_shutdown()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

### Security Summary

| Risk Category | Status | Notes |
|---------------|--------|-------|
| Command injection | **None** | List args + no shell + no user input |
| Path hijacking | **Low** | Requires prior filesystem access |
| Process management | **Medium** | Custom heartbeat has gaps—consider systemd for production |

The code follows security best practices and is safe to deploy. The primary improvements relate to robustness and defense-in-depth rather than fixing vulnerabilities.
