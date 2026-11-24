#!/bin/bash
# patch_pr_imprint.sh - adapts the pr climate imprint of Guido's scripts (block 1 of a pr run folder made by
# setup_run.sh) to our runs. His pr chain: climatology (4 seasons) -> imprint (one task per calendar day and block of
# years) -> climatology2 (4 extended seasonal files) -> fix_drizzle (4 seasons) -> QDM. Changes (idempotent):
#   1. temporary files: every script used TMP="/tmp" (fixed names, and the imprint runs rm -rf /tmp/z* /tmp/w* ... in
#      the shared /tmp); TMP becomes a private folder, exported so that the R scripts write in it too (they read
#      PRIVATE_TMP, setup_run.sh step 8): on EOS for the climatology / merges, in /tmp for the imprint (many small files)
#   2. no -invertlat after the R outputs (smoothed climatology, filled holes, drizzle threshold): his inputs are stored
#      south -> north, ours north -> south (as in the QDM, setup_run.sh step 9)
#   3. the files he precomputed for CERRA (season, anomaly, smoothed climatology, q90 in .../CERRA/downscaling/) are
#      read where the climatology step writes them for our reference (out/ci/<season>, out/ci/climatology, quantiles)
#   4. wet-day probability of the reference, which no script of his computes (his CERRA files were made by hand: cdo
#      divc,<days> -timsum -gec,0.1 on the extended season, 1985-2014): computed at the end of the climatology step,
#      share of days >= 0.1 mm in the extended season of ERA5 1981-2014, file out/ci/pwet/pwet_<reference>_<season>.nc
#   5. fill_holes.R: Gaussian kernel (0.1, 0.1) degrees is one cell on the 0.25 deg grid (terra focalMat: 1 x 1), so the
#      invalidated values (> 5 x q90) were never refilled; (0.25, 0.3) gives 3 x 3
#   6. imprint tasks: 365 days x blocks of CONSECUTIVE years (the script sets a yearly time axis on each output), within
#      the calibration years and within the run, never across the gap: 2 + 3 blocks; the merges expect days x blocks
# Usage: bash patch_pr_imprint.sh <run folder> <first year of the run> <last year of the run>
set -euo pipefail
D=$1; R1=$2; R2=$3
CI=$D/climate_imprint
grep -q '^VARNAME="pr"' "$D/params.sh" || { echo "$D is not a pr run folder"; exit 1; }
CAL_START=$(sed -n 's/^CAL_START="\([0-9]*\)".*/\1/p' "$D/params.sh"); CAL_END=$(sed -n 's/^CAL_END="\([0-9]*\)".*/\1/p' "$D/params.sh")
for f in "$CI"/*.sh "$D"/R_scripts/fill_holes.R "$D/params.sh"; do [ -f "$f.guido" ] || cp "$f" "$f.guido"; done

# 1. private temporary folder, exported
for f in climateClimatology_condor.sh climateImprint_condor.sh climateClimatology_condor2.sh climateFixGcmDrizzle_condor.sh climateMergetimeImprint_condor.sh; do
    F=$CI/$f
    sed -i 's|^PRIVATE_TMP=$(mktemp -d /tmp/ci_|export PRIVATE_TMP=$(mktemp -d /tmp/ci_|' "$F"
    grep -q 'PRIVATE_TMP=$(mktemp' "$F" || \
        sed -i -e '0,/^source .*fun\.sh/s|^source .*fun\.sh.*|&\nexport PRIVATE_TMP=$(mktemp -d ${SCRATCH}/tmp_${VARNAME}_XXXXXX); trap '"'"'rm -rf "$PRIVATE_TMP"'"'"' EXIT|' "$F"
    sed -i 's|^TMP="/tmp"$|TMP="${PRIVATE_TMP}"|' "$F"

    # his imprint ends with "DEBUG rm -rf ...": DEBUG is not a command, so every task would end with status 127
    sed -i 's|^DEBUG rm -rf "${TMP}"/\*\.nc|rm -rf "${TMP}"/*.nc|' "$F"
done

# 1b. R without --vanilla (fill_holes.R in the imprint) restores ./.RData at start and saves it at the end, in the
#     folder shared by all tasks: two tasks in parallel corrupted it and every later R failed at start (load:
#     "SET_STRING_ELT() must be a 'CHARSXP'"), so no filled.nc (Nov 2026)
sed -i -E '/^\s*#/! s/CMD BATCH "/CMD BATCH --vanilla "/' "$CI"/*.sh

# 2. no latitude flip of the R outputs
sed -i -E '/^\s*#/! s/ -invertlat / /' "$CI"/*.sh

# 3. reference files of the climatology step instead of his CERRA folder
sed -i -E 's#^PATH_OUT_FILES_cq=.*#PATH_OUT_FILES_cq="${PATH_OUT_FILES_ci}/quantiles"#; s#^PATH_OUT_FILES_cli=.*#PATH_OUT_FILES_cli="${PATH_OUT_FILES_ci}/climatology"#; s#^PATH_OUT_FILES_pwet=.*#PATH_OUT_FILES_pwet="${PATH_OUT_FILES_ci}/pwet"#' "$D/params.sh"
sed -i -E '/^\s*#/! s#"/[^"]*/CERRA/downscaling/\$\{SEASON\}/#"${PATH_OUT_FILES_ci}/${SEASON}/#' "$CI/climateImprint_condor.sh"
mkdir -p "$D/data/europe/out/ci/pwet"

# 4. wet-day probability of the reference (end of the climatology step) and its name in fix_drizzle
if ! grep -q "pwet (patch_pr_imprint.sh)" "$CI/climateClimatology_condor.sh"; then
    cat >> "$CI/climateClimatology_condor.sh" <<'EOF'

##################################################################
# pwet (patch_pr_imprint.sh): share of days with at least 0.1 mm in the extended season of the reference, as Guido's
# CERRA files (cdo divc,<number of days> -timsum -gec,0.1); read by climateFixGcmDrizzle_condor.sh
##################################################################
${CDO} -O timmean -gec,0.1 "${SEASON_CERRA}" "${TMP}/pwet.nc"
cp "${TMP}/pwet.nc" "${PATH_OUT_FILES_pwet}/pwet_${OBS_model%.nc}_${SEASON}.nc"
echo "pwet written: ${PATH_OUT_FILES_pwet}/pwet_${OBS_model%.nc}_${SEASON}.nc"
EOF
fi
sed -i 's|pwet_pr_cerra_1985_2014_daysum_remapped_no29feb_europe_${SEASON}\.nc|pwet_${OBS_model%.nc}_${SEASON}.nc|' "$CI/climateFixGcmDrizzle_condor.sh"

# 5. hole filling on the 0.25 deg grid
sed -i -E 's/^param1<-0\.1$/param1<-0.25/; s/^param2<-0\.1$/param2<-0.3/' "$D/R_scripts/fill_holes.R"

# 5b. ERA5 climatology not smoothed: his kernel for the reference, (1, 0.1) deg, is one cell at 0.25 deg (no smoothing)
#     and the R smoothing fails on it ("File not found, abort!"); a 3 x 3 kernel would blur the reference over 75 km
#     (his 0.1 deg was about 15 km on CERRA). The climatology is copied under the "smooth" name read by the imprint.
sed -i 's@^smooth_climatology "${CERRA_CLIMATOLOGY}" "${PARAM1_CERRA}" "${PARAM2_CERRA}".*@cp "${CERRA_CLIMATOLOGY}" "${PATH_OUT_FILES_ci}/climatology/$(basename "${CERRA_CLIMATOLOGY}" | sed "s/climatology/smooth_climatology/g")"   # patch_pr_imprint.sh: ERA5 not smoothed@' "$CI/climateClimatology_condor.sh"

# 6. imprint tasks: blocks of consecutive years, 2 in the calibration period and 3 in the run
blocks() {   # first last n: n blocks of consecutive years
    local a=$1 b=$2 n=$3 len k
    len=$((b - a + 1))
    for ((k = 0; k < n; k++)); do echo "$((a + k * len / n))/$((a + (k + 1) * len / n - 1))"; done
}
BL=$( { blocks "$CAL_START" "$CAL_END" 2; blocks "$R1" "$R2" 3; } )
NBLK=$(echo "$BL" | wc -l)
T=$CI/task_arguments_imprint.txt
ndays=(31 28 31 30 31 30 31 31 30 31 30 31)
for y in $BL; do
    for m in $(seq 1 12); do
        for d in $(seq 1 "${ndays[$((m - 1))]}"); do printf "%02d %02d/%02d %s\n" "$m" "$d" "$d" "$y"; done
    done
done > "$T"
sed -i -E 's/"\$\{expected_days\}" \* [0-9]+\)\)/"${expected_days}" * '"$NBLK"'))/' "$CI/climateClimatology_condor2.sh" "$CI/climateMergetimeImprint_condor.sh"

# checks
echo "imprint: $(wc -l < "$T") tasks, blocks: $(echo $BL)"
echo "files expected per day by the merges:"; grep -h -o '"${expected_days}" \* [0-9]*' "$CI/climateClimatology_condor2.sh" "$CI/climateMergetimeImprint_condor.sh"
echo "TMP lines:"; grep -n '^TMP=' "$CI"/*.sh
echo "exported private folders:"; grep -c 'export PRIVATE_TMP=$(mktemp' "$CI"/climate*.sh
echo "R calls without --vanilla:"; grep -n -E '^[^#]*CMD BATCH' "$CI"/*.sh | grep -v -- '--vanilla' || echo "  none"
echo "DEBUG lines left:"; grep -n '^DEBUG' "$CI"/*.sh || echo "  none"
echo "invertlat left (code lines):"; grep -n -E '^[^#]*invertlat' "$CI"/*.sh || echo "  none"
echo "CERRA folder left (code lines):"; grep -n -E '^[^#]*CERRA/downscaling' "$CI"/*.sh "$D/params.sh" || echo "  none"
grep -n -E '^PATH_OUT_FILES_(cq|cli|pwet)=' "$D/params.sh"
grep -n -E '^param[12]<-' "$D/R_scripts/fill_holes.R"
echo "smoothing of the climatologies:"; grep -n -E '^(smooth_climatology|cp "\$\{CERRA_CLIMATOLOGY\}")' "$CI/climateClimatology_condor.sh"
grep -n 'pwet_\${OBS_model' "$CI/climateFixGcmDrizzle_condor.sh" "$CI/climateClimatology_condor.sh"
echo PATCH_PR_IMPRINT_DONE
