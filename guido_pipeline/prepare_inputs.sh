#!/bin/bash
# prepare_inputs.sh - input files of the supervisor's pipeline (step 1: climate imprint + QDM) with ERA5 as reference
# and the EC-Earth3 stabilised runs, in the format of Guido's run folders (one folder data/europe with 4 netCDF files):
#   <var>_era5_1981_2014_europe.nc                        reference (ERA5 0.25 deg)
#   <var>_EC-Earth3-<run>_HISTORICAL_europe.nc            GCM: historical 1981-2014 + stabilised run, one file
#   mslp_anomaly_era5_1981_2014_europe.nc                 ERA5 psl minus its 1981-2014 monthly climatology
#   mslp_anomaly_EC-Earth3-<run>_HISTORICAL_europe.nc     GCM psl minus the monthly climatology of the HISTORICAL
#                                                         1981-2014 (the change of the run stays in the anomaly)
# Format as Guido's inputs: box sellonlatbox,-25.5,50,23,72.5 (the GCM variables with a margin of ~2 cells for the
# bilinear interpolation of the climate imprint), 365-day calendar without 29 February, time 23:00, MSLP variable
# named msl. Units of the reference: tasmax and dtr in degC, pr in mm/d; the GCM is converted to them (K -> degC,
# kg m-2 s-1 x 86400). Outputs already written are skipped.
#
# Usage (JEO-desk terminal, CDO of ~/envs/cdo):
#   nohup bash ~/downscaling/guido_pipeline/prepare_inputs.sh > ~/prepare_inputs.log 2>&1 < /dev/null &
#   tail -5 ~/prepare_inputs.log        (ends with PREPARE_DONE)
#   ONLY=stab2025nohos bash ...          only that run (ERA5 files are always prepared)
set -euo pipefail

C=~/envs/cdo/bin/cdo; [ -x "$C" ] || C=cdo
IN=/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/Input_data
GCMDIR=/eos/jeodpp/data/projects/DROUGHTOBS/EC-Earth_hosing
OUT=/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/guido_inputs
TMP=${TMPDIR:-/tmp}/prep_guido_$$
BOX="-25.5,50,23,72.5"             # Guido's europe box (variables of the reference, MSLP of reference and GCM)
BOX_GCM="-28,52.5,21,74.5"         # GCM variables: the box + ~2 EC-Earth3 cells
VARS="tasmax dtr pr"
declare -A RUNS=([stab2025nohos]=stabilization-ssp585-2025_Original [stab2025hos]=stabilization-ssp585-2025_Hosing
                 [stab2050nohos]=stabilization-ssp585-2050_Original [stab2050hos]=stabilization-ssp585-2050_Hosing)
FMT="-f nc4 -z zip_1"
STD="-settime,23:00:00 -setcalendar,365_day -del29feb"
mkdir -p "$OUT/era5" "$TMP"
trap 'rm -rf "$TMP"' EXIT
log() { echo "$(date +%T) $*"; }

# unit conversion of a GCM variable to the units of the reference
convert() {   # $1 variable
    case $1 in
        tasmax) echo "-setattribute,tasmax@units=degC -subc,273.15" ;;
        pr)     echo "-setattribute,pr@units=mm/d -mulc,86400" ;;
        dtr)    echo "-setattribute,dtr@units=degC" ;;
    esac
}

# ---- 1. reference: ERA5 variables and MSLP anomaly
for v in $VARS; do
    o="$OUT/era5/${v}_era5_1981_2014_europe.nc"
    [ -f "$o" ] && { log "present $o"; continue; }
    log "ERA5 $v"
    $C -O $FMT $STD -sellonlatbox,$BOX "$IN/ERA5_daily_merged/${v}_ERA5_day_1981-2014.nc" "$TMP/x.nc" && mv "$TMP/x.nc" "$o"
done
o="$OUT/era5/mslp_anomaly_era5_1981_2014_europe.nc"
if [ ! -f "$o" ]; then
    log "ERA5 MSLP anomaly"
    n=$(ls "$IN"/ERA5_daily/psl_ERA5_day_{1981..2014}.nc | wc -l); [ "$n" -eq 34 ] || { echo "ERA5 psl: $n yearly files, 34 expected"; exit 1; }
    $C -O $FMT $STD -sellonlatbox,$BOX -chname,psl,msl -mergetime "$IN"/ERA5_daily/psl_ERA5_day_{1981..2014}.nc "$TMP/msl.nc"
    $C -O ymonmean "$TMP/msl.nc" "$OUT/era5/mslp_climatology_era5_1981_2014_europe.nc"
    $C -O $FMT ymonsub "$TMP/msl.nc" "$OUT/era5/mslp_climatology_era5_1981_2014_europe.nc" "$TMP/x.nc" && mv "$TMP/x.nc" "$o"
fi

# ---- 2. GCM: historical 1981-2014 + each stabilised run
HIST=$IN/EC-Earth3_historical_CMIP6_merged
PSL_HIST=$IN/EC-Earth3_historical_CMIP6/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19810101-20141231.nc
for run in "${!RUNS[@]}"; do
    [ -n "${ONLY:-}" ] && [ "$run" != "$ONLY" ] && continue
    dir=${RUNS[$run]}; od="$OUT/$run"; mkdir -p "$od"
    for v in $VARS; do
        o="$od/${v}_EC-Earth3-${run}_HISTORICAL_europe.nc"
        [ -f "$o" ] && { log "present $o"; continue; }
        log "GCM $run $v"
        $C -O $STD -sellonlatbox,$BOX_GCM $(convert $v) "$HIST/${v}_day_EC-Earth3_historical_r1i1p1f1_gr_19810101-20141231.nc" "$TMP/h.nc"
        if [ "$v" = dtr ]; then
            $C -O $STD -sellonlatbox,$BOX_GCM $(convert dtr) -setname,dtr -sub \
                "$GCMDIR/$dir/tasmax_day_EC-Earth3_${dir}_r1i1p1f1_NH_"*.nc "$GCMDIR/$dir/tasmin_day_EC-Earth3_${dir}_r1i1p1f1_NH_"*.nc "$TMP/r.nc"
        else
            $C -O $STD -sellonlatbox,$BOX_GCM $(convert $v) "$GCMDIR/$dir/${v}_day_EC-Earth3_${dir}_r1i1p1f1_NH_"*.nc "$TMP/r.nc"
        fi
        $C -O $FMT mergetime "$TMP/h.nc" "$TMP/r.nc" "$TMP/x.nc" && mv "$TMP/x.nc" "$o"
    done
    o="$od/mslp_anomaly_EC-Earth3-${run}_HISTORICAL_europe.nc"
    if [ ! -f "$o" ]; then
        log "GCM $run MSLP anomaly"
        $C -O $STD -sellonlatbox,$BOX -chname,psl,msl "$PSL_HIST" "$TMP/h.nc"
        $C -O $STD -sellonlatbox,$BOX -chname,psl,msl "$GCMDIR/$dir/psl_day_EC-Earth3_${dir}_r1i1p1f1_NH_"*.nc "$TMP/r.nc"
        $C -O ymonmean "$TMP/h.nc" "$od/mslp_climatology_EC-Earth3_historical_1981_2014_europe.nc"
        $C -O mergetime "$TMP/h.nc" "$TMP/r.nc" "$TMP/m.nc"
        $C -O $FMT ymonsub "$TMP/m.nc" "$od/mslp_climatology_EC-Earth3_historical_1981_2014_europe.nc" "$TMP/x.nc" && mv "$TMP/x.nc" "$o"
    fi
done

# ---- 3. check: steps, first and last date, units, box of every file
log "check"
for f in "$OUT"/era5/*_europe.nc "$OUT"/stab*/*_europe.nc; do
    d=$($C -s showdate "$f" | tr -s ' ' '\n' | grep -v '^$')
    echo "$(basename "$f"): $($C -s ntime "$f") steps, $(echo "$d" | head -1) .. $(echo "$d" | tail -1), $($C -s showname "$f")," \
         "units $($C -s showunit "$f" | xargs), $($C -s griddes "$f" | grep -E '^(xsize|ysize|xfirst|yfirst)' | tr -s ' ' | tr '\n' ' ')"
done
echo PREPARE_DONE
