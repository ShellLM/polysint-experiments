```python
# config.py
"""
PolySINT Configuration

Environment variables are loaded from .env at import time. Required variables
(LLM_API_KEY, LLM_API_BASE_URL, ANALYSIS_MODEL) must be present before
calling AI features — use Config.llm.require() to fail fast with a clear message.

Two access patterns are supported:

    Structured (new code):     Config.llm.api_key, Config.webhooks.has_discord
    Flat (legacy):             Config.LLM_API_KEY, Config.DISCORD_WEBHOOK_URL
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


# ─── Env Helpers ──────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    """Fetch an environment variable with a fallback default."""
    return os.getenv(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    """Parse a boolean env var (true/false, 1/0, yes/no, on/off)."""
    raw = os.getenv(key, "").strip().lower()
    return raw in ("true", "1", "yes", "on") if raw else default


# ─── Config Sections ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _DatabaseConfig:
    name: str = "polysint_core.db"


@dataclass(frozen=True)
class _PolymarketConfig:
    gamma_api: str = "https://gamma-api.polymarket.com/markets"
    data_api: str = "https://data-api.polymarket.com"
    clob_api: str = "https://clob.polymarket.com"
    rpc_url: str = "https://polygon-rpc.com"


@dataclass(frozen=True)
class _LLMConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    @property
    def is_configured(self) -> bool:
        """True when all three required LLM variables are present."""
        return bool(self.api_key and self.base_url and self.model)

    def require(self) -> None:
        """
        Raise EnvironmentError if LLM is not fully configured.
        Call before using LLM features to get a clear error message.
        """
        if not self.is_configured:
            missing = []
            if not self.api_key:
                missing.append("LLM_API_KEY")
            if not self.base_url:
                missing.append("LLM_API_BASE_URL")
            if not self.model:
                missing.append("ANALYSIS_MODEL")
            raise EnvironmentError(
                f"LLM not configured. Missing: {', '.join(missing)}\n"
                f"Add these to your .env file before using AI analysis."
            )


@dataclass(frozen=True)
class _WebhookConfig:
    discord_url: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @property
    def has_discord(self) -> bool:
        return bool(self.discord_url)

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)

    @property
    def has_any(self) -> bool:
        """True if at least one notification channel is configured."""
        return self.has_discord or self.has_telegram


@dataclass(frozen=True)
class _ResearchConfig:
    tavily_api_key: str = ""
    enabled: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def is_active(self) -> bool:
        """True only when both enabled AND API key is present."""
        return self.enabled and self.is_configured


# ─── Main Config Class ────────────────────────────────────────────────────────

class _Config:
    """
    Central configuration with dual access patterns.

    Structured access (preferred for new code):
        Config.db.name
        Config.llm.api_key
        Config.webhooks.has_discord
        Config.polymarket.clob_api

    Flat interface (backward compatible — no changes needed in existing files):
        Config.DB_NAME
        Config.LLM_API_KEY
        Config.DISCORD_WEBHOOK_URL
    """

    __slots__ = ("_db", "_polymarket", "_llm", "_webhooks", "_research")

    def __init__(self, *, _env_override: dict[str, str] | None = None) -> None:
        """
        Initialize configuration.

        Args:
            _env_override: Optional dict for testing — merged over os.environ.
                           Allows tests to set config without touching real env.
        """
        if _env_override:
            env_get = lambda k, d="": _env_override.get(k, d)
            env_bool = lambda k, d=False: (
                _env_override.get(k, "").lower() in ("true", "1", "yes", "on")
                if k in _env_override else d
            )
        else:
            env_get = _env
            env_bool = _env_bool

        self._db = _DatabaseConfig(name=env_get("DB_NAME", "polysint_core.db"))
        self._polymarket = _PolymarketConfig(
            gamma_api=env_get("GAMMA_API", "https://gamma-api.polymarket.com/markets"),
            data_api=env_get("DATA_API", "https://data-api.polymarket.com"),
            clob_api=env_get("CLOB_API", "https://clob.polymarket.com"),
            rpc_url=env_get("POLYGON_RPC_URL", "https://polygon-rpc.com"),
        )
        self._llm = _LLMConfig(
            api_key=env_get("LLM_API_KEY"),
            base_url=env_get("LLM_API_BASE_URL"),
            model=env_get("ANALYSIS_MODEL"),
        )
        self._webhooks = _WebhookConfig(
            discord_url=env_get("DISCORD_WEBHOOK_URL"),
            telegram_token=env_get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=env_get("TELEGRAM_CHAT_ID"),
        )
        self._research = _ResearchConfig(
            tavily_api_key=env_get("TAVILY_API_KEY"),
            enabled=env_bool("ENABLE_WEB_RESEARCH", False),
        )

    # ── Structured Access ────────────────────────────────────────────────

    @property
    def db(self) -> _DatabaseConfig:
        return self._db

    @property
    def polymarket(self) -> _PolymarketConfig:
        return self._polymarket

    @property
    def llm(self) -> _LLMConfig:
        return self._llm

    @property
    def webhooks(self) -> _WebhookConfig:
        return self._webhooks

    @property
    def research(self) -> _ResearchConfig:
        return self._research

    # ── Flat Interface (backward compatibility) ──────────────────────────

    @property
    def DB_NAME(self) -> str:
        return self._db.name

    @property
    def GAMMA_API(self) -> str:
        return self._polymarket.gamma_api

    @property
    def DATA_API(self) -> str:
        return self._polymarket.data_api

    @property
    def CLOB_API(self) -> str:
        return self._polymarket.clob_api

    @property
    def RPC_URL(self) -> str:
        return self._polymarket.rpc_url

    @property
    def LLM_API_KEY(self) -> str:
        return self._llm.api_key

    @property
    def LLM_API_BASE_URL(self) -> str:
        return self._llm.base_url

    @property
    def LLM_BASE_URL(self) -> str:
        """Backward compat alias for older references in analyst.py."""
        return self._llm.base_url

    @property
    def ANALYSIS_MODEL(self) -> str:
        return self._llm.model

    @property
    def DISCORD_WEBHOOK_URL(self) -> str:
        return self._webhooks.discord_url

    @property
    def TELEGRAM_BOT_TOKEN(self) -> str:
        return self._webhooks.telegram_token

    @property
    def TELEGRAM_CHAT_ID(self) -> str:
        return self._webhooks.telegram_chat_id

    @property
    def TAVILY_API_KEY(self) -> str:
        return self._research.tavily_api_key

    @property
    def ENABLE_WEB_RESEARCH(self) -> bool:
        return self._research.enabled

    # ── Validation & Diagnostics ─────────────────────────────────────────

    def validate(self, *, strict: bool = False) -> list[str]:
        """
        Check configuration for common issues.

        Args:
            strict: If True, raise on first error instead of collecting warnings.

        Returns:
            List of warning messages (empty if everything looks good).
        """
        warnings = []

        # LLM partial configuration (common typo scenario)
        llm_vars = [
            ("LLM_API_KEY", self._llm.api_key),
            ("LLM_API_BASE_URL", self._llm.base_url),
            ("ANALYSIS_MODEL", self._llm.model),
        ]
        present = [name for name, val in llm_vars if val]
        missing = [name for name, val in llm_vars if not val]

        if present and missing:
            msg = (
                f"LLM partially configured — found {', '.join(present)} "
                f"but missing {', '.join(missing)}. "
                f"AI analysis will fail until all three are set."
            )
            if strict:
                raise EnvironmentError(msg)
            warnings.append(msg)

        # No notification channels
        if not self._webhooks.has_any:
            warnings.append(
                "No notification channels configured (Discord or Telegram). "
                "Alerts will only appear in console output."
            )

        # Research enabled but no API key
        if self._research.enabled and not self._research.is_configured:
            warnings.append(
                "ENABLE_WEB_RESEARCH is true but TAVILY_API_KEY is missing. "
                "Web research requests will return empty results."
            )

        return warnings

    def summary(self) -> dict:
        """
        Return configuration state safe for logging.
        No secrets are exposed — API keys are represented as booleans.
        """
        return {
            "database": {
                "name": self._db.name,
            },
            "polymarket": {
                "gamma_api": self._polymarket.gamma_api,
                "data_api": self._polymarket.data_api,
                "clob_api": self._polymarket.clob_api,
            },
            "llm": {
                "configured": self._llm.is_configured,
                "model": self._llm.model or "(not set)",
            },
            "notifications": {
                "discord": self._webhooks.has_discord,
                "telegram": self._webhooks.has_telegram,
            },
            "research": {
                "enabled": self._research.enabled,
                "configured": self._research.is_configured,
                "active": self._research.is_active,
            },
        }

    def __repr__(self) -> str:
        return (
            f"Config("
            f"llm={self._llm.is_configured}, "
            f"discord={self._webhooks.has_discord}, "
            f"telegram={self._webhooks.has_telegram}, "
            f"research={self._research.is_active}"
            f")"
        )


# ─── Module-Level Singleton ───────────────────────────────────────────────────

# Maintains existing import pattern: `from config import Config`
Config = _Config()
```

**Update `clob.py` to use config instead of hardcoded constant:**

```python
# clob.py
import requests
from config import Config
from logger import get_logger

log = get_logger("CLOB")

# Use centralized config instead of hardcoded URL
CLOB_BASE = Config.polymarket.clob_api

DEFAULT_INTERVAL = "1d"
DEFAULT_FIDELITY = 60

_SSL_VERIFY = False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
    """
    Fetches historical price data for a CLOB token from Polymarket.
    Returns a list of {"t": unix_timestamp, "p": price} dicts, oldest first.
    Returns None if the request fails.
    """
    try:
        resp = requests.get(
            f"{CLOB_BASE}/prices-history",
            params={
                "market": clob_token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
            timeout=10,
            verify=_SSL_VERIFY,
        )
        if resp.status_code != 200:
            log.warning(f"CLOB history returned {resp.status_code} for token {clob_token_id}")
            return None

        history = resp.json().get("history", [])
        return sorted(history, key=lambda x: x["t"]) if history else None

    except Exception as e:
        log.error(f"CLOB history fetch failed for token {clob_token_id}: {e}")
        return None


def get_shift(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> float | None:
    history = get_price_history(clob_token_id, interval=interval)
    if not history or len(history) < 2:
        return None
    return float(history[-1]["p"]) - float(history[0]["p"])


def get_history_as_price_list(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> list[float] | None:
    history = get_price_history(clob_token_id, interval=interval)
    if not history:
        return None
    return [float(h["p"]) for h in history]
```

**Add explicit guard in `analyst.py` before first LLM call:**

```python
# analyst.py — at the top of __init__
from config import Config

class PolyAnalyst:
    def __init__(self):
        Config.llm.require()  # Fail fast with clear message if LLM vars missing
        self.client = OpenAI(
            base_url=Config.llm.base_url,
            api_key=Config.llm.api_key,
        )
        self.model = Config.llm.model
        self.researcher = PolyResearcher()
```

**Add validation to `start.py`:**

```python
# start.py — after imports, before launching workers
from config import Config

for warning in Config.validate():
    print(f"⚠️  {warning}")

print(f"Configuration: {Config.__repr__()}")
```

**What changed from the original `config.py`:**

| Before | After |
|---|---|
| Hardcoded `CLOB_BASE` in `clob.py` | `Config.CLOB_API` / `Config.polymarket.clob_api` |
| Scattered `os.getenv()` in each module | Centralized env reading at init |
| No validation | `Config.validate(strict=True)` with clear errors |
| No safe logging | `Config.summary()` exposes health without secrets |
| LLM vars required at import time | Optional at import; `Config.llm.require()` guards at call site |
| No testing support | `Config(_env_override={"KEY": "val"})` for unit tests |
| Loose attributes | `__slots__` prevents accidental typos from creating phantom attributes |

**Migration is zero-effort** — all existing code using `Config.DB_NAME`, `Config.DATA_API`, etc. continues to work unchanged. New code can opt into `Config.db.name`, `Config.polymarket.clob_api` for better organization.
