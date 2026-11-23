#!/bin/bash
# run_submit.sh - runs the jobs of one of Guido's Condor submit files WITHOUT Condor: for each line of the task file
# named in "queue task from <file>", calls the script of the "arguments=" line as Condor would
# (<script_run.sh> <cluster> <process> <task fields>), one job after the other (his core scripts use fixed file names
# in /tmp, so two jobs on the same machine must not run at the same time). One log per job in <submit dir>/logs_local/.
# Usage (inside a climate_* folder of a run created by setup_run.sh):
#   bash ~/downscaling/guido_pipeline/run_submit.sh submit.condor.imprint
#   nohup bash ~/downscaling/guido_pipeline/run_submit.sh submit.condor.imprint > ~/imprint.log 2>&1 < /dev/null &
# PARALLEL=6 bash run_submit.sh ... runs 6 jobs at a time (see below when it is safe).
# Prints one line per job (ok / FAILED, seconds) and a summary; failed jobs can be rerun with the same command
# restricted to their lines (ONLY_LINES="3 17" bash run_submit.sh ...), or, for the climate imprint, only the days whose
# output is missing or incomplete (ONLY_MISSING_CI=1 bash run_submit.sh submit.condor.imprint).
# A job is FAILED when the script returns an error or its logs report one (Guido's script_run.sh always returns 0).
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

# ONLY_MISSING_CI=1 (submit.condor.imprint only): rerun only the days whose output out/ci/MM/ci_MM_*_DD.nc is missing
# or has another number of steps than the other days (e.g. jobs that failed silently when /tmp was full)
if [ "${ONLY_MISSING_CI:-0}" = 1 ]; then
    ROOT=$(dirname "$(dirname "$(readlink -f "$SUB")")")
    C=$ENV/bin/cdo
    declare -A NT=()
    for i in "${!lines[@]}"; do
        read -r m d <<< "${lines[$i]}"
        f=$(ls "$ROOT"/data/*/out/ci/"$m"/ci_"${m}"_*_"${d}".nc 2>/dev/null | head -1)
        NT[$i]=$([ -n "$f" ] && $C -s ntime "$f" 2>/dev/null || echo 0)
    done
    mode=$(printf '%s\n' "${NT[@]}" | grep -v '^0$' | sort | uniq -c | sort -rn | awk 'NR==1 {print $2}')
    ONLY_LINES=""
    for i in "${!lines[@]}"; do [ "${NT[$i]}" = "${mode:-x}" ] || ONLY_LINES="$ONLY_LINES $((i + 1))"; done
    echo "$(date +%T) ONLY_MISSING_CI: $(echo $ONLY_LINES | wc -w) days missing or incomplete (complete files have ${mode:-?} steps)"
    [ -z "$ONLY_LINES" ] && { echo RUN_SUBMIT_DONE; exit 0; }
fi

# a job fails if the script returns an error OR its logs report one: Guido's script_run.sh files end with an echo, so
# they return 0 even when the core script failed (e.g. "Disk quota exceeded"); the HDF5-DIAG messages CDO prints when
# it checks whether an output file already exists are ignored
job_failed() {   # $1 .err file, $2 .out file
    grep -v -E 'HDF5-DIAG|^ +#[0-9]+:|^ +major:|^ +minor:' "$1" | \
        grep -q -i -E 'disk quota|abort|file error|cdi +error|error \(|cannot allocate|open failed|segmentation|killed|permission denied' \
    || grep -q -i -E 'abort|file error' "$2"
}
# PARALLEL=N runs N jobs at a time: only for core scripts whose temporary files are in a private folder (setup_run.sh
# steps 6 and 8, patch_pr_imprint.sh); the status of each job goes to a file, so the summary is the same either way
STAT=$(mktemp -d); trap 'rm -rf "$STAT"' EXIT
run_job() {   # $1 index of the task line
    local i=$1 t0 rc st
    t0=$(date +%s)
    # shellcheck disable=SC2086
    bash "$script" 0 "$i" ${lines[$i]} > "$LOG/${name}_$((i + 1)).out" 2> "$LOG/${name}_$((i + 1)).err"
    rc=$?
    if [ $rc -eq 0 ] && ! job_failed "$LOG/${name}_$((i + 1)).err" "$LOG/${name}_$((i + 1)).out"; then st=ok; else st=FAILED; fi
    echo "$st" > "$STAT/$((i + 1))"
    echo "$(date +%T) job $((i + 1))/${#lines[@]} [${lines[$i]}] $st ($(( $(date +%s) - t0 )) s)"
}
NPAR=${PARALLEL:-1}
for i in "${!lines[@]}"; do
    if [ -n "${ONLY_LINES:-}" ] && ! [[ " $ONLY_LINES " == *" $((i + 1)) "* ]]; then continue; fi
    if [ "$NPAR" -gt 1 ]; then
        while [ "$(jobs -rp | wc -l)" -ge "$NPAR" ]; do wait -n; done
        run_job "$i" &
    else
        run_job "$i"
    fi
done
wait
nok=$(grep -l '^ok$' "$STAT"/* 2>/dev/null | wc -l)
failed=($(grep -l '^FAILED$' "$STAT"/* 2>/dev/null | xargs -r -n1 basename | sort -n))
nfail=${#failed[@]}
echo "$(date +%T) $name: $nok ok, $nfail failed${failed:+ (lines: ${failed[*]})}; logs in $LOG"
echo RUN_SUBMIT_DONE
