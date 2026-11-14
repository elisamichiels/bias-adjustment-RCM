#!/bin/bash
# run_submit.sh - runs the jobs of one of Guido's Condor submit files WITHOUT Condor: for each line of the task file
# named in "queue task from <file>", calls the script of the "arguments=" line as Condor would
# (<script_run.sh> <cluster> <process> <task fields>), one job after the other (his core scripts use fixed file names
# in /tmp, so two jobs on the same machine must not run at the same time). One log per job in <submit dir>/logs_local/.
# Usage (inside a climate_* folder of a run created by setup_run.sh):
#   bash ~/downscaling/guido_pipeline/run_submit.sh submit.condor.imprint
#   nohup bash ~/downscaling/guido_pipeline/run_submit.sh submit.condor.imprint > ~/imprint.log 2>&1 < /dev/null &
# Prints one line per job (ok / FAILED, seconds) and a summary; failed jobs can be rerun with the same command
# restricted to their lines (ONLY_LINES="3 17" bash run_submit.sh ...).
set -uo pipefail
SUB=$1
[ -f "$SUB" ] || { echo "no submit file $SUB"; exit 1; }
ENV=$HOME/envs/guido
export PATH="$ENV/bin:$PATH"
export HDF5_USE_FILE_LOCKING=FALSE                                 # EOS refuses HDF5 file locks
export PROJ_LIB="$ENV/share/proj" PROJ_DATA="$ENV/share/proj"   # PROJ database of the environment (terra fails without it)
args=$(grep -E '^\s*arguments\s*=' "$SUB" | sed -E 's/^\s*arguments\s*=\s*//')
script=$(echo "$args" | awk '{print $1}')
tfile=$(grep -E '^\s*queue\s+task\s+from' "$SUB" | sed -E 's/.*from\s+//' | tr -d '\r')
[ -n "$script" ] && [ -f "$script" ] || { echo "script of 'arguments=' not found: $script"; exit 1; }
LOG=$(dirname "$(readlink -f "$SUB")")/logs_local; mkdir -p "$LOG"
name=$(basename "$SUB")
if [ -z "$tfile" ]; then           # submit without a task file: one job
    lines=("")
else
    [ -f "$tfile" ] || { echo "task file not found: $tfile"; exit 1; }
    mapfile -t lines < <(sed -e '$a\' "$tfile" | tr -d '\r' | grep -v '^\s*$')
fi
echo "$(date +%T) $name: ${#lines[@]} jobs, script $script"
nok=0; nfail=0; failed=()
for i in "${!lines[@]}"; do
    if [ -n "${ONLY_LINES:-}" ] && ! [[ " $ONLY_LINES " == *" $((i + 1)) "* ]]; then continue; fi
    t0=$(date +%s)
    # shellcheck disable=SC2086
    bash "$script" 0 "$i" ${lines[$i]} > "$LOG/${name}_$((i + 1)).out" 2> "$LOG/${name}_$((i + 1)).err"
    rc=$?
    if [ $rc -eq 0 ]; then nok=$((nok + 1)); st=ok; else nfail=$((nfail + 1)); failed+=($((i + 1))); st=FAILED; fi
    echo "$(date +%T) job $((i + 1))/${#lines[@]} [${lines[$i]}] $st ($(( $(date +%s) - t0 )) s)"
done
echo "$(date +%T) $name: $nok ok, $nfail failed${failed:+ (lines: ${failed[*]})}; logs in $LOG"
echo RUN_SUBMIT_DONE
