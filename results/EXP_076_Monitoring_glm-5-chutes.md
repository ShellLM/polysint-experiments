Here is the implementation of distributed tracing using **OpenTelemetry**. This allows you to track a request from the API entry point, through database queries, to external API calls (Polymarket, OpenAI, Discord), and background worker jobs.

### 1. New File: `tracing.py`
This module configures the tracer provider, exporters, and auto-instrumentation for standard libraries (`requests`, `sqlite3`, `fastapi`).

```python
### FILE: tracing.py ###
import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from logger import get_logger

log = get_logger("Tracing")

def setup_tracing(service_name: str):
    """
    Initializes OpenTelemetry tracing.
    Defaults to OTLP exporter (compatible with Jaeger, Honeycomb, Datadog, etc.)
    Falls back to Console exporter if OTLP_ENDPOINT is not set.
    """
    # Avoid double initialization
    if trace.get_tracer_provider().__class__.__name__ != "TracerProvider":
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        
        if otlp_endpoint:
            log.warning(f"Tracing enabled: Exporting to OTLP at {otlp_endpoint}")
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        else:
            log.warning("Tracing enabled: Exporting to Console (set OTEL_EXPORTER_OTLP_ENDPOINT for production)")
            exporter = ConsoleSpanExporter()

        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Auto-instrument libraries
        RequestsInstrumentor().instrument()
        SQLite3Instrumentor().instrument()
        # FastAPI instrumentation is handled inside api.py to access the app object
        
    return trace.get_tracer(service_name)
```

### 2. Modified File: `config.py`
Add configuration variables for the OpenTelemetry connection.

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
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # Web Research (Tavily)
    ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"

    # ─── Tracing Config ─────────────────────────────────────────────────────
    # Set to true to enable tracing globally
    ENABLE_TRACING = os.getenv("ENABLE_TRACING", "false").lower() == "true"
    # e.g. "http://localhost:4318/v1/traces" for Jaeger or OTLP collector
    OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
```

### 3. Modified File: `api.py`
Initialize tracing at startup and instrument the FastAPI app. Added a manual span around the LLM analysis to track that expensive operation.

```python
### FILE: api.py ###
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
from pydantic import BaseModel, field_validator
import re
import requests
import json

# ─── Tracing Setup ───────────────────────────────────────────────────────────
from config import Config
if Config.ENABLE_TRACING:
    from tracing import setup_tracing
    setup_tracing("polysint-api")

from opentelemetry import trace
tracer = trace.get_tracer(__name__)

if Config.ENABLE_TRACING:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

# ... (Constants and Validators remain the same) ...

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
def startup():
    init_db()
    if Config.ENABLE_TRACING:
        FastAPIInstrumentor.instrument_app(app)

# ... (serve_dashboard, _validate_address, _enrich_market remain the same) ...

@app.get("/markets")
def search_markets(
    limit: int = 50,
    search: str = None,
    vol_min: float = Query(default=None, ge=0, description="Minimum volume (inclusive)"),
    vol_max: float = Query(default=None, ge=0, description="Maximum volume (inclusive)"),
):
    with tracer.start_as_current_span("search_markets") as span:
        span.set_attribute("search.query", search or "")
        span.set_attribute("search.limit", limit)
        
        # ... (Existing logic for search_markets) ...
        # Reject oversized search strings before they reach SQLite
        if search is not None and len(search) > MAX_SEARCH_LEN:
            raise HTTPException(status_code=400, detail=f"Search query too long (max {MAX_SEARCH_LEN} chars).")

        db = get_db()
        try:
            query = "SELECT * FROM markets"
            params = []
            if search:
                query += " WHERE question LIKE ?"
                params.append(f"%{search}%")

            all_markets = [dict(r) for r in db.execute(query, params).fetchall()]
        finally:
            db.close()

        volume_floor = MIN_VOLUME_FOR_CLOB if not search else 0
        candidates = []
        for m in all_markets:
            vol = m.get('volume') or 0
            if vol < volume_floor: continue
            if vol_min is not None and vol < vol_min: continue
            if vol_max is not None and vol > vol_max: continue
            candidates.append(m)

        enriched = []
        with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as executor:
            futures = {executor.submit(_enrich_market, m): m for m in candidates}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result is not None: enriched.append(result)
                except Exception as e:
                    log.error(f"Market enrichment failed: {e}")

        enriched.sort(key=lambda x: (abs(x.get('shift', 0.0)), x.get('volume') or 0.0), reverse=True)
        return enriched[:limit]


@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis(
    market_id: str,
    research: bool = Query(default=False, description="Enable Tavily web research for news context")
):
    with tracer.start_as_current_span("ai_analysis_endpoint") as span:
        span.set_attribute("market.id", market_id)
        span.set_attribute("analysis.research_enabled", research)
        
        if not MARKET_ID_RE.match(market_id):
            raise HTTPException(status_code=400, detail="Invalid market ID format.")

        db = get_db()
        try:
            market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
            if not market:
                raise HTTPException(status_code=404, detail="Market not found")

            market = dict(market)
            price_history = None

            if market.get("clob_token_id"):
                price_history = get_history_as_price_list(market["clob_token_id"])

            if not price_history:
                raw = db.execute(
                    "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 5",
                    (market_id,)
                ).fetchall()
                price_history = [h['prices'] for h in raw]

            # Manual span for the LLM call logic inside analyst
            with tracer.start_as_current_span("run_llm_analysis"):
                analysis = analyst.analyze_market_shift(
                    market['question'],
                    price_history,
                    market['volume'],
                    use_research=research
                )
            return {"analysis": analysis, "research_used": research}
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"LLM Analysis failed for {market_id}: {e}")
            raise HTTPException(status_code=500, detail="AI analysis failed.")
        finally:
            db.close()

# ... (Rest of the file remains the same) ...
```

### 4. Modified File: `analyst.py`
Add manual spans around the LLM request and the web research call, as these are high-latency operations you'll want to see in your traces.

```python
### FILE: analyst.py ###
import os
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
from researcher import PolyResearcher
from config import Config

# ─── Tracing Setup ───────────────────────────────────────────────────────────
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

load_dotenv()

# ... (_derive_price_behaviour remains the same) ...

class PolyAnalyst:
    def __init__(self):
        self.client = OpenAI(
            base_url=os.getenv("LLM_API_BASE_URL"),
            api_key=os.getenv("LLM_API_KEY")
        )
        self.model = os.getenv("ANALYSIS_MODEL")
        self.researcher = PolyResearcher()

    def analyze_market_shift(self, market_question, price_history, volume, use_research: bool = None):
        with tracer.start_as_current_span("analyst.analyze_market_shift") as span:
            span.set_attribute("market.question", market_question)
            span.set_attribute("analysis.use_research", use_research)
            
            if use_research is None:
                use_research = Config.ENABLE_WEB_RESEARCH

            behaviour = _derive_price_behaviour(price_history)

            if use_research:
                # This internal call is also traced via researcher.py instrumentation
                news_context = self.researcher.get_market_context(market_question)
            else:
                news_context = "Web research disabled. No external news context available."

            current_time = datetime.now(timezone.utc).strftime("%B %d, %Y - %H:%M:%S UTC")
            
            # ... (System prompt construction) ...
            system_prompt = ( # ... shortened for brevity, logic unchanged
                "You are a Senior OSINT & Forensic Financial Analyst specialising in prediction markets. "
                f"CRITICAL: The current real-world date and time is {current_time}. "
                # ... (rest of prompt string)
            )
            
            prompt = f"""
MARKET QUESTION: "{market_question}"
TOTAL VOLUME: ${volume:,.0f}
# ... (rest of prompt string)
"""

            with tracer.start_as_current_span("openai.chat.completions") as llm_span:
                llm_span.set_attribute("llm.model", self.model)
                llm_span.set_attribute("llm.vendor", "openai_compatible")
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0
                )
            
            return response.choices[0].message.content

    # ... (profile_wallet remains the same) ...
```

### 5. Modified File: `researcher.py`
Add spans to track the Tavily API call latency.

```python
### FILE: researcher.py ###
import os
import requests
from dotenv import load_dotenv
from logger import get_logger

# ─── Tracing Setup ───────────────────────────────────────────────────────────
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

load_dotenv()
log = get_logger("Researcher")

MAX_QUERY_LENGTH = 100 

class PolyResearcher:
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")

    def get_market_context(self, market_question):
        with tracer.start_as_current_span("researcher.get_market_context") as span:
            span.set_attribute("research.query_original", market_question)
            
            if not self.api_key:
                print("⚠️ [RESEARCHER] No TAVILY_API_KEY found in .env! Skipping web search.")
                return "No search API key configured. Context unavailable."

            query_text = market_question
            if len(query_text) > MAX_QUERY_LENGTH:
                query_text = query_text[:MAX_QUERY_LENGTH].rsplit(' ', 1)[0]

            span.set_attribute("research.query_used", query_text)
            print(f"🔎[RESEARCHER] Scouring the web for: '{query_text}'...")

            url = "https://api.tavily.com/search"
            payload = {
                "api_key": self.api_key,
                "query": f"latest news: {query_text}",
                "search_depth": "basic",
                "include_domains": ["reuters.com", "apnews.com", "bloomberg.com", "twitter.com"],
                "max_results": 5
            }

            # Note: The requests call inside this is auto-instrumented by tracing.py
            # But we keep this manual span to catch the parsing logic and error handling
            try:
                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    span.set_attribute("research.results_count", len(results))
                    # ... (rest of logic unchanged)
                    print(f"✅ [RESEARCHER] Found {len(results)} relevant news articles.")
                    if not results: return "No relevant news found."
                    
                    context_parts = []
                    for r in results:
                        title = r.get('title', 'Untitled')
                        snippet = r.get('content', '')[:300]
                        source_url = r.get('url', 'URL unavailable')
                        published = r.get('published_date', 'Date unknown')
                        context_parts.append(
                            f"- TITLE: {title}\n"
                            f"  DATE: {published}\n"
                            f"  SOURCE: {source_url}\n"
                            f"  SNIPPET: {snippet}..."
                        )
                    return "\n\n".join(context_parts)

                log.error(f"Tavily API error {resp.status_code} for query '{query_text}': {resp.text[:200]}")
                span.set_attribute("error", True)
                span.set_attribute("error.type", "APIError")
                return "Search failed (API Error)."
            except Exception as e:
                span.record_exception(e)
                log.error(f"Search failed: {e}")
                return "Search failed (Network Error)."
```

### 6. Modified File: `alerts.py`
Initialize tracing for the background anomaly scanner process.

```python
### FILE: alerts.py ###
import json
import time
from db import get_db
from notifier import Notifier
from logger import get_logger
from clob import get_shift, get_price_history, DEFAULT_INTERVAL
from config import Config

# ─── Tracing Setup ───────────────────────────────────────────────────────────
if Config.ENABLE_TRACING:
    from tracing import setup_tracing
    setup_tracing("polysint-alerts")

from opentelemetry import trace
tracer = trace.get_tracer(__name__)

log = get_logger("Alerts")

# ... (Constants remain the same) ...

def scan_for_anomalies():
    with tracer.start_as_current_span("scan_cycle") as span:
        db = get_db()
        markets = db.execute("SELECT id, question, volume, clob_token_id FROM markets").fetchall()
        db.close()
        
        span.set_attribute("scan.market_count", len(markets))
        notifier = Notifier()

        for m in markets:
            # ... (Existing logic) ...
            market_volume = m['volume'] or 0
            if market_volume < MIN_ALERT_VOLUME:
                continue
            
            # Create a span for processing a single market candidate
            with tracer.start_as_current_span("process_market") as market_span:
                market_span.set_attribute("market.id", m['id'])
                clob_token_id = m['clob_token_id']
                try:
                    if clob_token_id:
                        shift = get_shift(clob_token_id)
                        if shift is None: continue
                        
                        market_span.set_attribute("market.shift", shift)
                        
                        if abs(shift) >= ANOMALY_THRESHOLD:
                            # ... (Logic for alert generation)
                            history = get_price_history(clob_token_id)
                            if not history: continue
                            
                            current_price = float(history[-1]['p'])
                            
                            if current_price >= NEAR_RESOLUTION_THRESHOLD or current_price <= (1 - NEAR_RESOLUTION_THRESHOLD):
                                log.warning(f"Suppressed alert for '{m['question']}': price {current_price:.2f} is near resolution.")
                                continue
                            
                            # ... (Broadcast logic)
                            direction = "📈" if shift > 0 else "📉"
                            msg = ( # ... formatted message
                            )
                            notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

                    else:
                        # ... (Snapshot fallback logic unchanged)
                        pass
                except Exception as e:
                    log.error(f"Error scanning anomaly for {m['id']}: {e}")
                    market_span.record_exception(e)

if __name__ == "__main__":
    print(
        f"Anomaly Scanner active — "
        f"Threshold: {ANOMALY_THRESHOLD * 100:.0f}% over {DEFAULT_INTERVAL} | "
        f"Min volume: ${MIN_ALERT_VOLUME:,} | "
        f"Near-resolution cutoff: {NEAR_RESOLUTION_THRESHOLD * 100:.0f}%"
    )
    while True:
        scan_for_anomalies()
        time.sleep(300)
```

### 7. Modified File: `start.py`
Initialize tracing for the main process (which spawns children). Note that because `start.py` uses `subprocess.Popen`, the children need their own initialization (handled in their respective `if __name__ == "__main__"` blocks above). `start.py` itself acts as a monitor.

```python
### FILE: start.py ###
import subprocess
import sys
import time
from datetime import datetime
from logger import get_logger
from notifier import Notifier
from config import Config

# ─── Tracing Setup ───────────────────────────────────────────────────────────
if Config.ENABLE_TRACING:
    from tracing import setup_tracing
    setup_tracing("polysint-main")

log = get_logger("System")

HEARTBEAT_INTERVAL = 21600 

def start_engine():
    print("🚀 Starting PolySINT Engine...")
    # ... (Existing startup logic)
    processes =[]
    notifier = Notifier()
    
    # ... (try/except block for starting processes remains the same)
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
        
        # ... (Rest of the file remains the same)
```

### 8. Dependencies
You will need to add the OpenTelemetry packages to your `requirements.txt`.

```text
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp
opentelemetry-instrumentation-fastapi
opentelemetry-instrumentation-requests
opentelemetry-instrumentation-sqlite3
```

### How to Run
1.  **Install dependencies:**
    `pip install -r requirements.txt`
2.  **Enable Tracing:**
    Add `ENABLE_TRACING=true` to your `.env` file.
3.  **Configure Exporter (Optional but recommended):**
    Add `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces` to `.env`.
    *If you don't set this, traces will print to the console (stdout).*
4.  **Start the Engine:**
    `python start.py`

You will now see trace spans generated for every API request, database query, and external HTTP call. If you run a collector (like **Jaeger** in Docker), you can visualize the entire flow of a request through the system.
