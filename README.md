# PolySINT — 100 AI Improvement Experiments

Automated code improvement experiments for the **PolySINT** (Polymarket OSINT) prediction market intelligence engine.

## What is PolySINT?

PolySINT is a Python/FastAPI application that monitors Polymarket prediction markets for anomalous price movements, profiles whale wallets, and provides AI-powered market analysis. It includes:

- **API Server** — FastAPI dashboard with market search, AI analysis, and wallet profiling
- **Data Harvester** — Continuous ingestion from Polymarket's Gamma API
- **Anomaly Detector** — Automated price shift alerting via Discord/Telegram
- **Whale Watcher** — Tracked entity trade monitoring
- **AI Analyst** — LLM-powered market shift classification (REACTIONARY / SUSPICIOUS / ORGANIC)

## Experiment Framework

100 targeted experiments were run against the full PolySINT codebase using:

### Models
| Model | Provider | Role |
|-------|----------|------|
| `hunter-alpha` | OpenRouter | Deep reasoning, complex analysis |
| `glm-5-chutes` | Chutes (GLM-5-TEE) | Alternative perspective, error handling |
| `healer-alpha` | OpenRouter | Coordination, synthesis |

### Consortiums (Multi-Model Reasoning)
| Consortium | Strategy | Models | Use Case |
|-----------|----------|--------|----------|
| `test-semantic-group` | Default | hunter-alpha:2, healer-alpha:2, glm-5-chutes:2 | Code quality, API design, architecture |
| `cns-role-code-audit` | Role | glm-5, healer-alpha, qwen3.5-397b, hunter-alpha | Security audit with 4 specialist roles |

**Role assignments for `cns-role-code-audit`:**
1. 🔒 **Security Auditor** — injection, auth bypass, data leaks, SSRF, race conditions
2. ⚡ **Performance Engineer** — complexity, memory, I/O patterns, scalability
3. ✅ **Correctness Prover** — logic, edge cases, off-by-one, null handling, type safety
4. 🛠️ **Maintainability Reviewer** — readability, naming, abstraction, test coverage, SOLID

### Agent Framework
Every 10th experiment used `agent8.sh` (autonomous bash agent with manager/subagent pattern) for complex multi-step analysis tasks.

## Results Summary

| Category | Experiments | Total Output | Tool |
|----------|------------|-------------|------|
| Security | 10 | 63 KB | `cns-role-code-audit` |
| Performance | 10 | 411 KB | `hunter-alpha` |
| Error Handling | 10 | 125 KB | `glm-5-chutes` |
| Code Quality | 10 | 207 KB | `test-semantic-group` |
| Testing | 10 | 298 KB | `cns-role-code-audit` |
| API Design | 10 | 249 KB | `test-semantic-group` |
| Frontend | 10 | 280 KB | `hunter-alpha` |
| Monitoring | 10 | 158 KB | `glm-5-chutes` |
| Architecture | 10 | 195 KB | `test-semantic-group` |
| Features | 10 | 304 KB | `cns-role-code-audit` |
| **Total** | **100** | **~2.3 MB** | |

## Directory Structure

```
polysint/
├── README.md                  # This file
├── source/
│   └── polysint_all_source.txt   # Complete PolySINT source code (16 files)
├── audit/
│   └── initial_security_audit.md # Previous agent8 security audit output
├── results/
│   ├── EXP_001_Security_cns-role-code-audit.md
│   ├── EXP_002_Security_cns-role-code-audit.md
│   ├── ...
│   └── EXP_100_Features_cns-role-code-audit.md
└── scripts/
    └── run_polysint_100.sh       # Experiment runner script
```

## How It Was Run

```bash
# The experiment runner uses parallel batches of 5
AI_AUTO_CONFIRM=1 bash run_polysint_100.sh

# Each experiment pipes the full source code as context:
llm -m "cns-role-code-audit" "Audit api.py for missing authentication" < polysint_all_source.txt

# Every 10th experiment uses the agent8 autonomous framework:
AI_AUTO_CONFIRM=1 AGENT_ROLE=manager bash ~/ai/agent8.sh <<< "Task: ..."
```

## Key Files (Source)

| File | Purpose |
|------|---------|
| `alerts.py` | Anomaly detection daemon |
| `analyst.py` | LLM-powered market analysis |
| `api.py` | FastAPI endpoints and dashboard |
| `clob.py` | Polymarket CLOB price history |
| `config.py` | Environment configuration |
| `db.py` | SQLite database layer |
| `harvest.py` | Market data ingestion |
| `logger.py` | Logging configuration |
| `notifier.py` | Discord/Telegram webhooks |
| `researcher.py` | Tavily web research |
| `start.py` | Process orchestrator |
| `utils.py` | Blockchain wallet unmasking |
| `watcher.py` | Whale trade monitoring |
| `static/app.js` | Dashboard frontend logic |

## Date

Experiments executed: **2026-03-15** (11:00 UTC — 17:20 UTC)

## License

MIT
