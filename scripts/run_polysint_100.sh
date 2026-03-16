#!/usr/bin/env bash
SOURCE_FILE="/home/thomas/ai_diary/polysint_all_source.txt"
RESULTS_DIR="/home/thomas/ai/experiments/polysint_100/results"
mkdir -p "$RESULTS_DIR"

run_exp() {
    local id=$1; local cat=$2; local model=$3; local p=$4
    local out="$RESULTS_DIR/EXP_${id}_${cat}_${model}.md"
    echo "[RUNNING] $id: $p"
    # Use agent8 for every 10th experiment to hit the 'complex' requirement
    if [[ $((10#$id % 10)) -eq 0 ]]; then
        AI_AUTO_CONFIRM=1 AGENT_ROLE=manager bash ~/ai/agent8.sh <<< "Task: $p\nSource Context: $(cat "$SOURCE_FILE")" > "$out" 2>&1
    else
        llm -m "$model" "$p" < "$SOURCE_FILE" > "$out" 2>&1
    fi
    echo "[DONE] $id"
}

export -f run_exp
export SOURCE_FILE RESULTS_DIR

run_exp "001" "Security" "cns-role-code-audit" "Audit api.py for missing authentication on sensitive endpoints (watchlist CRUD, profiling)." &
run_exp "002" "Security" "cns-role-code-audit" "Check for potential SQL injection vulnerabilities in db.py and api.py queries." &
run_exp "003" "Security" "cns-role-code-audit" "Assess risk of LLM prompt injection in analyst.py market question handling." &
run_exp "004" "Security" "cns-role-code-audit" "Check harvest.py for SSRF vulnerabilities when fetching external market data." &
run_exp "005" "Security" "cns-role-code-audit" "Audit notifier.py for sensitive credential leakage in error logs or responses." &
wait
run_exp "006" "Security" "cns-role-code-audit" "Evaluate use of subprocess.Popen in start.py for potential command injection." &
run_exp "007" "Security" "cns-role-code-audit" "Inspect static/app.js for XSS vulnerabilities when rendering market data." &
run_exp "008" "Security" "cns-role-code-audit" "Check for insecure direct object references (IDOR) in market analysis endpoints." &
run_exp "009" "Security" "cns-role-code-audit" "Audit clob.py for potential SSRF via attacker-controlled token IDs." &
run_exp "010" "Security" "cns-role-code-audit" "Review file permissions and secret handling in logger.py and config.py." &
wait
run_exp "011" "Performance" "hunter-alpha" "Optimize market enrichment in api.py to use bulk CLOB history fetching if possible." &
run_exp "012" "Performance" "hunter-alpha" "Analyze SQL query performance in db.py and suggest index optimizations." &
run_exp "013" "Performance" "hunter-alpha" "Optimize the harvester loop in harvest.py to handle rate limits more efficiently." &
run_exp "014" "Performance" "hunter-alpha" "Suggest improvements for memory management in watcher.py for large sets of seen trades." &
run_exp "015" "Performance" "hunter-alpha" "Evaluate async/await patterns in api.py to improve concurrent request throughput." &
wait
run_exp "016" "Performance" "hunter-alpha" "Optimize frontend bundle size and asset loading in static/index.html." &
run_exp "017" "Performance" "hunter-alpha" "Analyze analyst.py price behaviour derivation for potential speedups." &
run_exp "018" "Performance" "hunter-alpha" "Reduce latency in market search by pre-filtering volume before database calls." &
run_exp "019" "Performance" "hunter-alpha" "Optimize the heartbeat check in start.py to consume fewer resources." &
run_exp "020" "Performance" "hunter-alpha" "Improve clob.py history sorting and parsing for efficiency." &
wait
run_exp "021" "Error Handling" "glm-5-chutes" "Add robust retry logic with exponential backoff to clob.py history fetching." &
run_exp "022" "Error Handling" "glm-5-chutes" "Implement circuit breakers for external API calls in researcher.py." &
run_exp "023" "Error Handling" "glm-5-chutes" "Improve error reporting in notifier.py when webhooks fail." &
run_exp "024" "Error Handling" "glm-5-chutes" "Add transaction safety and rollbacks to db.py write operations." &
run_exp "025" "Error Handling" "glm-5-chutes" "Handle potential JSON decode errors gracefully in harvest.py and analyst.py." &
wait
run_exp "026" "Error Handling" "glm-5-chutes" "Improve network glitch handling in harvest.py pagination loop." &
run_exp "027" "Error Handling" "glm-5-chutes" "Add type checking and validation for all inputs in api.py utility functions." &
run_exp "028" "Error Handling" "glm-5-chutes" "Ensure all background processes in start.py log crashes before exiting." &
run_exp "029" "Error Handling" "glm-5-chutes" "Improve feedback to frontend in static/app.js when backend errors occur." &
run_exp "030" "Error Handling" "glm-5-chutes" "Handle malformed outcomePrices shapes more robustly in harvest.py." &
wait
run_exp "031" "Code Quality" "test-semantic-group" "Add comprehensive type hints to analyst.py for better maintainability." &
run_exp "032" "Code Quality" "test-semantic-group" "Refactor extract_first_price in harvest.py for better readability and simplicity." &
run_exp "033" "Code Quality" "test-semantic-group" "Implement a cleaner configuration management pattern in config.py." &
run_exp "034" "Code Quality" "test-semantic-group" "Standardize logging levels and formats across all PolySINT modules." &
run_exp "035" "Code Quality" "test-semantic-group" "Apply DRY principles to market data parsing in api.py and harvest.py." &
wait
run_exp "036" "Code Quality" "test-semantic-group" "Organize api.py into smaller, more focused sub-modules." &
run_exp "037" "Code Quality" "test-semantic-group" "Improve documentation and docstrings for all core logic functions." &
run_exp "038" "Code Quality" "test-semantic-group" "Standardize naming conventions (snake_case vs camelCase) across JS and Python." &
run_exp "039" "Code Quality" "test-semantic-group" "Refactor watcher.py to use a more structured event-driven pattern." &
run_exp "040" "Code Quality" "test-semantic-group" "Improve modularity of the frontend JS to avoid monolithic code in app.js." &
wait
run_exp "041" "Testing" "cns-role-code-audit" "Create a suite of unit tests for market shift calculations in analyst.py." &
run_exp "042" "Testing" "cns-role-code-audit" "Implement integration tests for the FastAPI endpoints in api.py." &
run_exp "043" "Testing" "cns-role-code-audit" "Design mock objects for Polymarket API calls to test harvest.py offline." &
run_exp "044" "Testing" "cns-role-code-audit" "Create stress tests for the database connection pool in db.py." &
run_exp "045" "Testing" "cns-role-code-audit" "Add frontend testing scripts for index.html using a tool like Playwright or Cypress." &
wait
run_exp "046" "Testing" "cns-role-code-audit" "Implement property-based testing for market question normalization." &
run_exp "047" "Testing" "cns-role-code-audit" "Create a test harness for security audit simulations on api.py." &
run_exp "048" "Testing" "cns-role-code-audit" "Add regression tests for the clob_token_id migration in db.py." &
run_exp "049" "Testing" "cns-role-code-audit" "Design a pipeline for automated UI testing of the dashboard." &
run_exp "050" "Testing" "cns-role-code-audit" "Create tests for the wallet unmasking logic in utils.py." &
wait
run_exp "051" "API Design" "test-semantic-group" "Implement cursor-based pagination for the /markets endpoint in api.py." &
run_exp "052" "API Design" "test-semantic-group" "Add versioning (e.g., /v1/) to all PolySINT API routes." &
run_exp "053" "API Design" "test-semantic-group" "Standardize JSON response formats for success and error cases." &
run_exp "054" "API Design" "test-semantic-group" "Add rate limiting headers and enforcement to all public endpoints." &
run_exp "055" "API Design" "test-semantic-group" "Expose more granular volume filter options in the /markets search API." &
wait
run_exp "056" "API Design" "test-semantic-group" "Create a dedicated health-check endpoint for monitoring tools." &
run_exp "057" "API Design" "test-semantic-group" "Add Swagger/OpenAPI documentation decorators to all FastAPI routes." &
run_exp "058" "API Design" "test-semantic-group" "Implement a bulk watchlist addition endpoint in api.py." &
run_exp "059" "API Design" "test-semantic-group" "Add support for CORS configuration in the API server." &
run_exp "060" "API Design" "test-semantic-group" "Improve the search query validation to prevent oversized inputs." &
wait
run_exp "061" "Frontend" "hunter-alpha" "Add a responsive mobile-friendly layout to static/index.html." &
run_exp "062" "Frontend" "hunter-alpha" "Improve data visualization for market shifts using Sparklines or charts." &
run_exp "063" "Frontend" "hunter-alpha" "Add a dark mode / light mode toggle to the CSS design system." &
run_exp "064" "Frontend" "hunter-alpha" "Implement better loading indicators and skeleton screens in app.js." &
run_exp "065" "Frontend" "hunter-alpha" "Add accessibility (Aria) attributes to all interactive dashboard elements." &
wait
run_exp "066" "Frontend" "hunter-alpha" "Improve the layout of the wallet profiling results for better readability." &
run_exp "067" "Frontend" "hunter-alpha" "Add a real-time status indicator for the harvester and anomaly scanner." &
run_exp "068" "Frontend" "hunter-alpha" "Enhance the search bar with auto-suggestions or recent searches." &
run_exp "069" "Frontend" "hunter-alpha" "Improve error messaging UI with toast notifications." &
run_exp "070" "Frontend" "hunter-alpha" "Add a 'Copy to Clipboard' feature for wallet addresses and market IDs." &
wait
run_exp "071" "Monitoring" "glm-5-chutes" "Implement Prometheus-style metrics for API latency and request counts." &
run_exp "072" "Monitoring" "glm-5-chutes" "Add structured JSON logging across the entire PolySINT stack." &
run_exp "073" "Monitoring" "glm-5-chutes" "Create a script for automated daily intelligence summaries based on logs." &
run_exp "074" "Monitoring" "glm-5-chutes" "Enhance start.py heartbeat to include disk space and memory usage metrics." &
run_exp "075" "Monitoring" "glm-5-chutes" "Implement Slack/Discord notifications for critical system crashes." &
wait
run_exp "076" "Monitoring" "glm-5-chutes" "Add tracing (e.g., OpenTelemetry) to track requests across the stack." &
run_exp "077" "Monitoring" "glm-5-chutes" "Create a dashboard for monitoring harvester lag and sync status." &
run_exp "078" "Monitoring" "glm-5-chutes" "Implement log rotation and archiving to prevent disk space issues." &
run_exp "079" "Monitoring" "glm-5-chutes" "Add alerts for unusually high API latency or error rates." &
run_exp "080" "Monitoring" "glm-5-chutes" "Improve the system heartbeat to report on database health/connectivity." &
wait
run_exp "081" "Architecture" "test-semantic-group" "Migrate the harvester to a task queue (e.g., RQ or Celery) for better scaling." &
run_exp "082" "Architecture" "test-semantic-group" "Containerize the PolySINT engine using Docker and Docker Compose." &
run_exp "083" "Architecture" "test-semantic-group" "Implement a caching layer (e.g., Redis) for frequently accessed market data." &
run_exp "084" "Architecture" "test-semantic-group" "Refactor for dependency injection to make components more testable." &
run_exp "085" "Architecture" "test-semantic-group" "Decouple the frontend from the backend using a proper build step (Vite/Next)." &
wait
run_exp "086" "Architecture" "test-semantic-group" "Move long-running AI analysis to a background worker process." &
run_exp "087" "Architecture" "test-semantic-group" "Implement a more robust database migration strategy (e.g. Alembic)." &
run_exp "088" "Architecture" "test-semantic-group" "Refactor start.py to use a systemd service file or supervisor." &
run_exp "089" "Architecture" "test-semantic-group" "Design a microservices bridge for multi-chain support beyond Polygon." &
run_exp "090" "Architecture" "test-semantic-group" "Implement a plugin architecture for adding new data sources." &
wait
run_exp "091" "Features" "cns-role-code-audit" "Add support for tracking multiple outcomes per market in alerts.py." &
run_exp "092" "Features" "cns-role-code-audit" "Implement a basic 'Insider Score' leaderboard in the frontend." &
run_exp "093" "Features" "cns-role-code-audit" "Add a feature to export watchlist data to CSV or PDF." &
run_exp "094" "Features" "cns-role-code-audit" "Integrate additional news sources (e.g. RSS feeds) into researcher.py." &
run_exp "095" "Features" "cns-role-code-audit" "Implement a simple notification preference system for users." &
wait
run_exp "096" "Features" "cns-role-code-audit" "Add historical trend line charts to the market analysis profile." &
run_exp "097" "Features" "cns-role-code-audit" "Create an automated 'Alpha' discovery mode based on whale trade clusters." &
run_exp "098" "Features" "cns-role-code-audit" "Implement support for multi-currency volume tracking (USD/USDC)." &
run_exp "099" "Features" "cns-role-code-audit" "Add a social sharing feature for interesting market anomalies." &
run_exp "100" "Features" "cns-role-code-audit" "Integrate a basic feedback loop where users can rate AI analysis accuracy." &
wait
wait
echo '---'
echo '100 Experiments Completed.'
