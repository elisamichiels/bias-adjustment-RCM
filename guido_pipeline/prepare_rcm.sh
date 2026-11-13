#!/bin/bash
# prepare_rcm.sh - RegCM5 0.25 daily runs (DROUGHTOBS/rcm_monthly, one file per month and variable, native rotated
# curvilinear grid) in the format of the inputs of Guido's pipeline, for step 2 (QDM of the RCM against the GCM
# ERA5-like product):
#   - each monthly file remapped onto the ERA5 0.25 grid of the reference box (the grid of the ERA5 reference file of
#     prepare_inputs.sh; weights computed once: remapcon for pr, or remapbil if the RegCM grid has no cell corners;
#     remapbil for tasmax / tasmin), then the 300 remapped months merged. Remapping the merged 25-year file at once
#     made CDO fail when writing (resizeBuf allocation error); month by month it works;
#   - dates: RegCM stamps the value of day D at D+1 00:00 (January file: 2nd January .. 1st February), shifted back by
#     one day (shifttime,-1day), then time 23:00, 365-day calendar without 29 February (as Guido's inputs);
#   - units of the reference: tasmax / tasmin K -> degC, pr kg m-2 s-1 -> mm/d (checked from the file units);
#     dtr = tasmax - tasmin (after the remapping: bilinear interpolation is linear, so the same as remapping the
#     difference); float32 at every step.
#   ERA5 box points outside the RCM domain stay missing (counted in the check).
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

monthly() {   # $1 variable: the 300 monthly files, remapped one by one, merged into $TMP/$1.nc (units of the reference)
    local v=$1 n u conv m w f
    mapfile -t files < <(ls "$SRC/$DIR/${v}_${PFX}_"[0-9][0-9][0-9][0-9][0-9][0-9].nc)
    n=${#files[@]}; [ "$n" -eq 300 ] || { echo "$v: $n monthly files, 300 expected"; exit 1; }
    u=$($C -s showunit "${files[0]}" | xargs)
    case "$v:$u" in
        pr:kg\ m-2\ s-1|pr:kg/m2/s|pr:kg\ m**-2\ s**-1) conv="-setattribute,pr@units=mm/d -mulc,86400" ;;
        pr:mm/d|pr:mm/day) conv="" ;;
        tas*:K)  conv="-setattribute,$v@units=degC -subc,273.15" ;;
        tas*:degC|tas*:C) conv="" ;;
        *) echo "$v: unexpected units '$u'"; exit 1 ;;
    esac
    m=bil; [ "$v" = pr ] && m=con
    w="$TMP/weights_$m.nc"
    if [ ! -f "$w" ]; then
        if ! $C -O gen$m,"$TARGET" -selname,$v "${files[0]}" "$w"; then
            [ "$m" = con ] || exit 1
            log "gencon failed (no cell corners in the RegCM grid?): bilinear weights instead"
            m=bil; w="$TMP/weights_bil.nc"
            [ -f "$w" ] || $C -O genbil,"$TARGET" -selname,$v "${files[0]}" "$w"
        fi
    fi
    log "$v: $n months, units '$u', remap$m"
    mkdir -p "$TMP/$v"
    for f in "${files[@]}"; do
        $C -s -O -b F32 $STD $conv -remap,"$TARGET","$w" -selname,$v "$f" "$TMP/$v/$(basename "$f")"
    done
    $C -s -O -b F32 mergetime "$TMP/$v"/*.nc "$TMP/$v.nc" && rm -rf "$TMP/$v"
}

for v in tasmax dtr pr; do
    o="$OUT/${v}_RegCM5-${TAG}_europe.nc"
    [ -f "$o" ] && { log "present $o"; continue; }
    if [ "$v" = dtr ]; then
        [ -f "$TMP/tasmax.nc" ] || monthly tasmax
        monthly tasmin
        $C -O -f nc4 -b F32 -z zip_1 -setattribute,dtr@units=degC -setname,dtr -sub "$TMP/tasmax.nc" "$TMP/tasmin.nc" "$TMP/x.nc"
    else
        monthly $v
        $C -O -f nc4 -b F32 -z zip_1 copy "$TMP/$v.nc" "$TMP/x.nc"
    fi
    mv "$TMP/x.nc" "$o"; log "written $o"
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
