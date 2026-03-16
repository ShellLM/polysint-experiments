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
run_exp "001" "Security" "cns-role-code-audit" "Audit api.py for missing authentication"
