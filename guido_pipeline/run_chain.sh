#!/bin/bash
# run_chain.sh - runs several of Guido's submit files one after the other with run_submit.sh, each inside its own
# folder, and stops at the first step with a failed job (a later step never runs on incomplete inputs).
# One log per step in <submit dir>/logs_local/chain_<submit name>.log, all of them also printed on screen.
# Usage (JEO-desk):
#   nohup bash ~/downscaling/guido_pipeline/run_chain.sh <dir>/submit.condor.a <dir>/submit.condor.b ... \
#         > ~/chain.log 2>&1 < /dev/null &
#   WAIT_PID=<pid> WAIT_LOG=<log> ...   first waits for that process (e.g. a run_submit.sh already running) to end,
#                                       and goes on only if its log reports "0 failed"
# Ends with CHAIN_DONE, or CHAIN_STOPPED and the name of the step that failed.
set -uo pipefail
HERE=$(dirname "$(readlink -f "$0")")
ok_log() { grep -q -E ': [0-9]+ ok, 0 failed' "$1"; }   # summary line of run_submit.sh without failures

if [ -n "${WAIT_PID:-}" ]; then
    echo "$(date +%T) waiting for process $WAIT_PID"
    while kill -0 "$WAIT_PID" 2>/dev/null; do sleep 60; done
    if [ -n "${WAIT_LOG:-}" ] && ! ok_log "$WAIT_LOG"; then
        echo "$(date +%T) CHAIN_STOPPED: $WAIT_LOG does not report 0 failed"; exit 1
    fi
fi
for sub in "$@"; do
    [ -f "$sub" ] || { echo "$(date +%T) CHAIN_STOPPED: no submit file $sub"; exit 1; }
    d=$(dirname "$(readlink -f "$sub")"); s=$(basename "$sub")
    mkdir -p "$d/logs_local"; log="$d/logs_local/chain_${s}.log"
    (cd "$d" && bash "$HERE/run_submit.sh" "$s") 2>&1 | tee "$log"
    ok_log "$log" || { echo "$(date +%T) CHAIN_STOPPED at $s (see $log)"; exit 1; }
done
echo "$(date +%T) CHAIN_DONE"
