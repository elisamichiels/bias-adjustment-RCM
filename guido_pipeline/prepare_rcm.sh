#!/bin/bash
# prepare_rcm.sh - RegCM5 0.25 daily runs (DROUGHTOBS/rcm_monthly, one file per month and variable, native rotated
# curvilinear grid) in the format of the inputs of Guido's pipeline, for step 2 (QDM of the RCM against the GCM
# ERA5-like product):
#   - the 300 monthly files of each variable merged (25 years);
#   - dates: RegCM stamps the value of day D at D+1 00:00 (January file: 2nd January .. 1st February), shifted back by
#     one day (shifttime,-1day), then time 23:00, 365-day calendar without 29 February (as Guido's inputs);
#   - units of the reference: tasmax / tasmin K -> degC, pr kg m-2 s-1 -> mm/d; dtr = tasmax - tasmin;
#   - remapped from the RegCM grid onto the ERA5 0.25 grid of the reference box (grid of the ERA5 reference file of
#     prepare_inputs.sh): remapcon for pr (remapbil if the RegCM file has no cell corners), remapbil for the others.
#     ERA5 box points outside the RCM domain stay missing (counted in the check).
# Output: guido_inputs/rcm_<tag>/<var>_RegCM5-<tag>_europe.nc ; outputs already written are skipped.
# Expected check: 9125 steps (25 x 365), 2125-01-01 .. 2149-12-31, 303 x 199 points.
# Usage (JEO-desk):  nohup bash ~/downscaling/guido_pipeline/prepare_rcm.sh stab2050nohos > ~/prepare_rcm.log 2>&1 < /dev/null &
#                    tags: stab2050nohos (stabilization-ssp585-2050_Base), stab2050hos (stabilization-ssp585-2050_Hose)
set -euo pipefail
TAG=${1:-stab2050nohos}
C=~/envs/guido/bin/cdo; [ -x "$C" ] || C=~/envs/cdo/bin/cdo
SRC=/eos/jeodpp/data/projects/DROUGHTOBS/rcm_monthly
INP=/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/guido_inputs
declare -A DIRS=([stab2050nohos]="stabilization-ssp585-2050_Base 2050_Base" [stab2050hos]="stabilization-ssp585-2050_Hose 2050_Hose")
read -r DIR PFX <<< "${DIRS[$TAG]}"
TARGET="$INP/era5/tasmax_era5_1981_2014_europe.nc"      # ERA5 0.25 grid of the reference box
OUT="$INP/rcm_$TAG"; TMP=${TMPDIR:-/tmp}/prep_rcm_$$
mkdir -p "$OUT" "$TMP"; trap 'rm -rf "$TMP"' EXIT
STD="-settime,23:00:00 -setcalendar,365_day -del29feb -shifttime,-1day"
log() { echo "$(date +%T) $*"; }
[ -f "$TARGET" ] || { echo "missing $TARGET (run prepare_inputs.sh first)"; exit 1; }
$C -s griddes "$TARGET" > "$TMP/target_grid.txt"

merged() {   # $1 variable: the monthly files merged, dates shifted, 365-day calendar, in the units of the reference
    local v=$1 n u conv
    n=$(ls "$SRC/$DIR/${v}_${PFX}_"[0-9][0-9][0-9][0-9][0-9][0-9].nc | wc -l)
    [ "$n" -eq 300 ] || { echo "$v: $n monthly files, 300 expected"; exit 1; }
    u=$($C -s showunit "$SRC/$DIR/${v}_${PFX}_212501.nc" | xargs)
    case "$v:$u" in
        pr:kg\ m-2\ s-1|pr:kg/m2/s|pr:kg\ m**-2\ s**-1) conv="-setattribute,pr@units=mm/d -mulc,86400" ;;
        pr:mm/d|pr:mm/day) conv="" ;;
        tas*:K)  conv="-setattribute,$v@units=degC -subc,273.15" ;;
        tas*:degC|tas*:C) conv="" ;;
        *) echo "$v: unexpected units '$u'"; exit 1 ;;
    esac
    log "merge $v ($n files, units '$u')"
    $C -O $STD $conv -selname,$v -mergetime "$SRC/$DIR/${v}_${PFX}_"[0-9][0-9][0-9][0-9][0-9][0-9].nc "$TMP/$v.nc"
}

for v in tasmax dtr pr; do
    o="$OUT/${v}_RegCM5-${TAG}_europe.nc"
    [ -f "$o" ] && { log "present $o"; continue; }
    if [ "$v" = dtr ]; then
        [ -f "$TMP/tasmax.nc" ] || merged tasmax
        merged tasmin
        $C -O -setattribute,dtr@units=degC -setname,dtr -sub "$TMP/tasmax.nc" "$TMP/tasmin.nc" "$TMP/dtr.nc"
        m=remapbil
    else
        merged $v
        m=remapbil; [ "$v" = pr ] && m=remapcon
    fi
    log "remap $v ($m) onto the ERA5 0.25 grid"
    if ! $C -O -f nc4 -z zip_1 $m,"$TMP/target_grid.txt" "$TMP/$v.nc" "$TMP/x.nc"; then
        [ "$m" = remapcon ] || exit 1
        log "remapcon failed (no cell corners in the RegCM file?): remapbil instead"
        $C -O -f nc4 -z zip_1 remapbil,"$TMP/target_grid.txt" "$TMP/$v.nc" "$TMP/x.nc"
    fi
    mv "$TMP/x.nc" "$o"
done

log "check"
for f in "$OUT"/*_europe.nc; do
    d=$($C -s showdate "$f" | tr -s ' ' '\n' | grep -v '^$')
    echo "$(basename "$f"): $($C -s ntime "$f") steps, $(echo "$d" | head -1) .. $(echo "$d" | tail -1), $($C -s showname "$f"), units $($C -s showunit "$f" | xargs)," \
         "grid $($C -s griddes "$f" | grep -E '^(xsize|ysize)' | tr -s ' ' | tr '\n' ' ')," \
         "missing cells (first day) $($C -s outputf,%.0f,1 -fldsum -setmisstoc,1 -setrtoc,-1e30,1e30,0 -seltimestep,1 "$f")," \
         "mean $($C -s outputf,%.2f,1 -timmean -fldmean "$f")"
done
echo PREPARE_RCM_DONE
