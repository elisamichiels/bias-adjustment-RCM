#!/bin/bash
# patch_smooth_per_period.sh - climate_smooth/climateSmoothDelta.sh of one run folder: the running mean of the delta
# factors (runmean,11, Guido's extra step to ClimDown) is computed separately for each QDM period of
# climate_qdm/task_arguments_qdm_delta.txt. Guido's periods follow each other, ours do not (1981-2014, then the run,
# e.g. 2100-2149): one running mean over the merged delta series would average 31 Dec 2014 with 1-5 Jan 2100 (deltas
# near 0 in the calibration period, several K in the run) over the 5 days on each side of the junction. The 5 days at
# each end of a period, which runmean,11 drops, keep their unsmoothed delta (no day lost, also 1-5 Jan of the first
# year and 27-31 Dec of the last). The running mean is stamped at the middle day (CDO_TIMESTAT_DATE=middle, passed to
# CDO; Guido sets it without exporting it). Guido's version is kept as climateSmoothDelta.sh.guido. Idempotent.
# Usage (JEO-lab or JEO-desk):  bash ~/downscaling/guido_pipeline/patch_smooth_per_period.sh <run folder>
#                               (also called by setup_run.sh)
set -euo pipefail
D=$1
F="$D/climate_smooth/climateSmoothDelta.sh"
T="$D/climate_qdm/task_arguments_qdm_delta.txt"
[ -f "$F" ] && [ -f "$T" ] || { echo "missing $F or $T"; exit 1; }
if grep -q "smoothing per QDM period" "$F"; then
    echo "already patched: $F"
else
    grep -q '^${CDO} selmon,${MONTH} -runmean,11 "${SMOOTH_model_with_path}"' "$F" \
        || { echo "smoothing line not found in $F: not patched"; exit 1; }
    [ -f "$F.guido" ] || cp "$F" "$F.guido"
    cat > "$F.block" <<EOF
# smoothing per QDM period (guido_pipeline/patch_smooth_per_period.sh): the periods of the merged delta series do not
# follow each other (e.g. 2014 then 2100), so the running mean is computed within each period; the 5 days at each end
# of a period, dropped by runmean,11, keep their unsmoothed delta
PIECES=()
while read -r Y1 Y2; do
    CDO_TIMESTAT_DATE=middle \${CDO} -runmean,11 -selyear,\${Y1}/\${Y2} "\${SMOOTH_model_with_path}" "\${PRIVATE_TMP}/run_\${Y1}.nc"
    \${CDO} -seldate,\${Y1}-01-01T00:00:00,\${Y1}-01-05T23:59:59 "\${SMOOTH_model_with_path}" "\${PRIVATE_TMP}/head_\${Y1}.nc"
    \${CDO} -seldate,\${Y2}-12-27T00:00:00,\${Y2}-12-31T23:59:59 "\${SMOOTH_model_with_path}" "\${PRIVATE_TMP}/tail_\${Y1}.nc"
    PIECES+=("\${PRIVATE_TMP}/head_\${Y1}.nc" "\${PRIVATE_TMP}/run_\${Y1}.nc" "\${PRIVATE_TMP}/tail_\${Y1}.nc")
done < <(awk '{print \$1, \$2}' "$T" | sort -u)
\${CDO} selmon,\${MONTH} -mergetime "\${PIECES[@]}" "\${PRIVATE_TMP}/unique_delta_\${MONTH}_\${VARNAME}_\${DOMAIN}_\${MODEL}_\${SCENARIO}.nc"
echo "unique_delta \${MONTH}: \$(\${CDO} -s ntime "\${PRIVATE_TMP}/unique_delta_\${MONTH}_\${VARNAME}_\${DOMAIN}_\${MODEL}_\${SCENARIO}.nc") days (smoothed per period)"
EOF
    awk -v blk="$F.block" '/^\$\{CDO\} selmon,\$\{MONTH\} -runmean,11/ && !done {while ((getline l < blk) > 0) print l; done=1; next} {print}' \
        "$F" > "$F.new"
    mv "$F.new" "$F"; rm -f "$F.block"
fi
grep -n -A13 "smoothing per QDM period" "$F" | head -n 14
