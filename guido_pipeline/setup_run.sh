#!/bin/bash
# setup_run.sh - one run folder of Guido's downscaling scripts in OUR space (his folders are only read), for a variable
# and an EC-Earth3 stabilised run, with the inputs of prepare_inputs.sh:
#   1. copies once his templates (downscaling*.tar.gz, out*.tar.gz, create_skeleton.sh) into $B
#   2. writes our create_skeleton_<run>_<var>.sh (variable, model, scenario, input files, template of the variable:
#      pr -> downscaling_pr / out_pr, dtr -> downscaling_dtr, others -> downscaling) and runs it in $B
#   3. replaces in the new folder his base path, his conda environment and /scratch/droughtatlas by ours
#   4. sets in params.sh: REANALYSIS=era5, calibration 1981-2014, GLOBAL_START/END = first/last year of the GCM file
# Usage (JEO-lab or JEO-desk):  bash ~/downscaling/guido_pipeline/setup_run.sh stab2050nohos tasmax
set -euo pipefail
RUN=$1; VAR=$2
G=/eos/jeodpp/data/projects/DROUGHTATLAS/guido/downscaling
B=/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/downscaling      # named "downscaling" as his base folder
INP=/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/guido_inputs
ENV=$HOME/envs/guido
DOMAIN=europe; MODEL=EC-Earth3-$RUN; SCENARIO=stab
declare -A LASTYEAR=([stab2025nohos]=2124 [stab2025hos]=2124 [stab2050nohos]=2149 [stab2050hos]=2149)
mkdir -p "$B/scratch"

# 1. Guido's templates, copied once
for f in downscaling.tar.gz downscaling_dtr.tar.gz downscaling_pr.tar.gz out.tar.gz out_pr.tar.gz _create_skeletons_files/create_skeleton.sh; do
    [ -f "$B/$(basename $f)" ] || cp "$G/$f" "$B/"
done
case $VAR in
    pr)  TPL=downscaling_pr.tar.gz;  OUTT=out_pr.tar.gz ;;
    dtr) TPL=downscaling_dtr.tar.gz; OUTT=out.tar.gz ;;
    *)   TPL=downscaling.tar.gz;     OUTT=out.tar.gz ;;
esac
for f in "$INP/era5/${VAR}_era5_1981_2014_europe.nc" "$INP/$RUN/${VAR}_${MODEL}_HISTORICAL_europe.nc" \
         "$INP/era5/mslp_anomaly_era5_1981_2014_europe.nc" "$INP/$RUN/mslp_anomaly_${MODEL}_HISTORICAL_europe.nc"; do
    [ -f "$f" ] || { echo "missing input $f (run prepare_inputs.sh first)"; exit 1; }
done

# 2. our create_skeleton
S="$B/create_skeleton_${RUN}_${VAR}.sh"
sed -e "s|^DOMAIN=.*|DOMAIN=\"$DOMAIN\"|; s|^MODEL=.*|MODEL=\"$MODEL\"|; s|^SCENARIO=.*|SCENARIO=\"$SCENARIO\"|; s|^VARNAME=.*|VARNAME=\"$VAR\"|" \
    -e "s|^REFERENCE_FILE=.*|REFERENCE_FILE=\"$INP/era5/${VAR}_era5_1981_2014_europe.nc\"|" \
    -e "s|^GCM_FILE=.*|GCM_FILE=\"$INP/$RUN/${VAR}_${MODEL}_HISTORICAL_europe.nc\"|" \
    -e "s|^MSLP_FILE_CERRA=.*|MSLP_FILE_CERRA=\"$INP/era5/mslp_anomaly_era5_1981_2014_europe.nc\"|" \
    -e "s|^MSLP_FILE_CMIP6=.*|MSLP_FILE_CMIP6=\"$INP/$RUN/mslp_anomaly_${MODEL}_HISTORICAL_europe.nc\"|" \
    -e "s|tar -xzf  downscaling.tar.gz|tar -xzf  $TPL|; s|tar -xzf  out.tar.gz|tar -xzf  $OUTT|" \
    "$B/create_skeleton.sh" > "$S"
[ "$VAR" = pr ] && sed -i 's|^update_scripts "climate_analogs"|#update_scripts "climate_analogs"|' "$S"
grep -q "$TPL" "$S" || { echo "template line not found in $S"; exit 1; }
cd "$B" && bash "$S"

# 3. paths of Guido's installation -> ours
D="$B/climdown_cdo_${VAR}_${DOMAIN}_${MODEL}_${SCENARIO}"
{ grep -rlI --exclude-dir=data -e "$G" -e /mnt/jeoproc/envs -e /scratch/droughtatlas "$D" || true; } | while read -r f; do
    sed -i -e "s|$G|$B|g" -e "s|/mnt/jeoproc/envs/DROUGHTATLASPROC/anaconda3/envs/droughta|$ENV|g" \
           -e "s|/scratch/droughtatlas|$B/scratch|g" "$f"
done

# 4. parameters of our runs
sed -i -e 's|^REANALYSIS=.*|REANALYSIS="era5"|' -e 's|^CAL_START=.*|CAL_START="1981"|' -e 's|^CAL_END=.*|CAL_END="2014"|' \
       -e 's|^GLOBAL_START=.*|GLOBAL_START="1981"|' -e "s|^GLOBAL_END=.*|GLOBAL_END=\"${LASTYEAR[$RUN]}\"|" "$D/params.sh"

# 5. QDM periods of a stabilised run (no trend: one period for the historical, one for the whole run, instead of
#    Guido's 9 periods of 30 years), and the number of delta files expected by the merge (periods x 12 months)
first_run_year=$((LASTYEAR[$RUN] - 49))
Q="$D/climate_qdm/task_arguments_qdm_delta.txt"
[ -f "$Q.guido" ] || cp "$Q" "$Q.guido"
if [ "$VAR" != pr ]; then
    for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
        printf "1981 2014 %s\n%s %s %s\n" "$m" "$first_run_year" "${LASTYEAR[$RUN]}" "$m"
    done > "$Q"
    sed -i 's/!= "108"/!= "24"/; s/expected 108 files/expected 24 files/' "$D/climate_qdm/climateQDMMergeDelta_condor.sh"
    grep -n '"24"' "$D/climate_qdm/climateQDMMergeDelta_condor.sh" || echo "WARNING: merge_delta count not changed"
else
    echo "pr: QDM task file left as in Guido's template (seasonal), to adapt after reading it"
fi

# 6. private temporary folder for the climate imprint jobs: the core script writes fixed names in /tmp
#    (/tmp/anomaly.nc, /tmp/remapped_anom.nc ...), harmless under Condor (one /tmp per job) but two variables running at
#    the same time on one machine would overwrite each other. Pure CDO script: every /tmp/ becomes a mktemp folder.
CI="$D/climate_imprint/climateImprint_condor.sh"
if [ -f "$CI" ]; then
    grep -q 'PRIVATE_TMP}/' "$CI" || sed -i -e 's|/tmp/|${PRIVATE_TMP}/|g' "$CI"
    # the folder is created right after fun.sh is sourced (params.sh, which defines VARNAME, is sourced before it)
    grep -q 'PRIVATE_TMP=$(mktemp' "$CI" || \
        sed -i -e '0,/^source .*fun\.sh/s|^source .*fun\.sh.*|&\nPRIVATE_TMP=$(mktemp -d /tmp/ci_${VARNAME}_XXXXXX); trap '"'"'rm -rf "$PRIVATE_TMP"'"'"' EXIT|' "$CI"
    grep -n 'PRIVATE_TMP=$(mktemp' "$CI" || echo "WARNING: private tmp not inserted in $CI"
fi

# 7. dtr MULTIPLICATIVE (our change to Guido's pipeline, as in F1): an additive climate imprint gave negative daily
#    ranges (e.g. -4.7 degC on 1 January, ERA5 climatology + a large negative GCM anomaly); a ratio anomaly keeps dtr
#    positive. Climate imprint: anomaly = GCM / GCM climatology (div), times the ERA5 climatology (mul); QDM: RATIO=TRUE,
#    KIND=mult (the ratio branch of his R QDM only censors values below trace = 0.05, harmless for dtr).
if [ "$VAR" = dtr ]; then
    if [ -f "$CI" ] && ! grep -q "dtr multiplicative" "$CI"; then
        sed -i -e 's|^\(\s*\${CDO}\) sub "\${PRIVATE_TMP}/\${1}" "\${PRIVATE_TMP}/\${2}" "\${PRIVATE_TMP}/anomaly.nc"|# dtr multiplicative (setup_run.sh): ratio anomaly instead of difference\n\1 div "${PRIVATE_TMP}/${1}" "${PRIVATE_TMP}/${2}" "${PRIVATE_TMP}/anomaly.nc"|' \
               -e 's|^-add "\${PRIVATE_TMP}/remapped_anom.nc" \\|-mul "${PRIVATE_TMP}/remapped_anom.nc" \\|' "$CI"
    fi
    grep -n -E 'CDO\} (div|sub) "\$\{PRIVATE_TMP\}/\$\{1\}"|^-(mul|add) "\$\{PRIVATE_TMP\}/remapped_anom' "$CI"
    if ! grep -q "dtr multiplicative" "$D/params.sh"; then
        printf '\n# dtr multiplicative (setup_run.sh): ratio QDM, as the climate imprint\nif [[ "$VARNAME" == "dtr" ]]; then\n    KIND="mult"\n    RATIO=TRUE\nfi\n' >> "$D/params.sh.tmp_add"
        # insert the block right after the KIND / RATIO / NQUANT / REMAP if-block (before GRID_GCM)
        awk -v add="$(cat "$D/params.sh.tmp_add")" '/^GRID_GCM=/ && !done {print add; done=1} {print}' "$D/params.sh" > "$D/params.sh.new" \
            && mv "$D/params.sh.new" "$D/params.sh"; rm -f "$D/params.sh.tmp_add"
    fi
    grep -n -A4 "dtr multiplicative" "$D/params.sh" || echo "WARNING: dtr ratio block not found in params.sh"
fi

# 8. temporary files of the other block-1 scripts (merges, QDM, smoothing) on EOS instead of /tmp: on JEO-desk the
#    per-user quota of /tmp is about 5 GB (Disk quota exceeded) and these steps write files of several GB with fixed
#    names. Each core script gets a private folder ${SCRATCH}/tmp_<var>_XXXXXX (SCRATCH = $B/scratch on EOS, from
#    params.sh), exported so that the R scripts it calls use it too; the R scripts read "/tmp/x" as
#    file.path(Sys.getenv("PRIVATE_TMP", "/tmp"), "x") (unchanged behaviour when the variable is not set).
for f in "$D"/climate_imprint/*.sh "$D"/climate_qdm/*.sh "$D"/climate_smooth/*.sh; do
    case "$(basename "$f")" in script_run*|climateImprint_condor.sh) continue ;; esac
    grep -q "/tmp/" "$f" || continue
    grep -q 'PRIVATE_TMP}/' "$f" || sed -i -e 's|/tmp/|${PRIVATE_TMP}/|g' "$f"
    if ! grep -q 'PRIVATE_TMP=$(mktemp' "$f"; then
        if grep -q '^source .*fun\.sh' "$f"; then
            sed -i -e '0,/^source .*fun\.sh/s|^source .*fun\.sh.*|&\nexport PRIVATE_TMP=$(mktemp -d ${SCRATCH}/tmp_${VARNAME}_XXXXXX); trap '"'"'rm -rf "$PRIVATE_TMP"'"'"' EXIT|' "$f"
        else
            echo "WARNING: $f uses /tmp but does not source fun.sh: not patched, check it"
            sed -i -e 's|${PRIVATE_TMP}/|/tmp/|g' "$f"
        fi
    fi
done
for f in "$D"/R_scripts/*.R; do
    grep -q -E "[\"']/tmp/" "$f" || continue
    sed -i -E -e "s#\"/tmp/([^\"]*)\"#file.path(Sys.getenv(\"PRIVATE_TMP\", \"/tmp\"), \"\1\")#g" \
              -e "s#'/tmp/([^']*)'#file.path(Sys.getenv(\"PRIVATE_TMP\", \"/tmp\"), \"\1\")#g" "$f"
done
echo "block-1 scripts with a private temporary folder on EOS:"
grep -l 'PRIVATE_TMP=$(mktemp -d ${SCRATCH}' "$D"/climate_imprint/*.sh "$D"/climate_qdm/*.sh "$D"/climate_smooth/*.sh 2>/dev/null | xargs -r -n1 basename || true
echo "R scripts reading PRIVATE_TMP:"; grep -l 'Sys.getenv("PRIVATE_TMP"' "$D"/R_scripts/*.R 2>/dev/null | xargs -r -n1 basename || true
echo "remaining /tmp/ in block-1 core scripts (expected: only climateImprint_condor.sh mktemp):"
grep -n "/tmp/" "$D"/climate_imprint/*.sh "$D"/climate_qdm/*.sh "$D"/climate_smooth/*.sh | grep -v "script_run" || true

echo "run folder: $D"
echo "QDM periods:"; sort -u -k1,2 "$Q" | awk '{print $1, $2}' | sort -u
grep -nE '^(REANALYSIS|VARNAME|DOMAIN|MODEL|SCENARIO|CAL_START|CAL_END|GLOBAL_START|GLOBAL_END|PATH_FILES|PATH_CONDA)=' "$D/params.sh"
echo "remaining references to Guido's folder (expected: none, or only in climate_pca / analogue scripts):"
grep -rlI --exclude-dir=data "$G" "$D" || true
ls -la "$D/data/$DOMAIN"
echo SETUP_RUN_DONE
