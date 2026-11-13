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
if [ -f "$CI" ] && ! grep -q "PRIVATE_TMP" "$CI"; then
    sed -i -e 's|/tmp/|${PRIVATE_TMP}/|g' "$CI"
    sed -i -e '0,/^JOBSUFFIX=/s|^JOBSUFFIX=.*|&\nPRIVATE_TMP=$(mktemp -d /tmp/ci_${VARNAME}_XXXXXX); trap '"'"'rm -rf "$PRIVATE_TMP"'"'"' EXIT|' "$CI"
    grep -n "PRIVATE_TMP=" "$CI" || echo "WARNING: private tmp not inserted in $CI"
fi

echo "run folder: $D"
echo "QDM periods:"; sort -u -k1,2 "$Q" | awk '{print $1, $2}' | sort -u
grep -nE '^(REANALYSIS|VARNAME|DOMAIN|MODEL|SCENARIO|CAL_START|CAL_END|GLOBAL_START|GLOBAL_END|PATH_FILES|PATH_CONDA)=' "$D/params.sh"
echo "remaining references to Guido's folder (expected: none, or only in climate_pca / analogue scripts):"
grep -rlI --exclude-dir=data "$G" "$D" || true
ls -la "$D/data/$DOMAIN"
echo SETUP_RUN_DONE
