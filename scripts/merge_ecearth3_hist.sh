#!/bin/bash
# Merge the yearly EC-Earth3 historical files into one file per variable (CDO mergetime).
# Usage (JEO-desk or JEO-lab terminal):  bash merge_ecearth3_hist.sh
# Output: Input_data/EC-Earth3_historical_CMIP6_merged/<var>_day_EC-Earth3_historical_r1i1p1f1_gr_<start>-<end>.nc
# (separate folder: the config reads the yearly folder, a merged file next to it would be read twice)

# the projects folder is seen differently on JEO-lab and JEO-desk
for root in /eos/jeodpp/data/projects /mnt/eos_rw/projects; do
  if [ -d "$root/DROUGHTOBS/elisa/GCM_downscaling/Input_data" ]; then BASE="$root/DROUGHTOBS/elisa/GCM_downscaling/Input_data"; break; fi
done
if [ -z "$BASE" ]; then echo "Input_data folder not found under /eos/jeodpp/data/projects or /mnt/eos_rw/projects"; exit 1; fi
command -v cdo >/dev/null || { echo "cdo not found on this machine"; exit 1; }

IN="$BASE/EC-Earth3_historical_CMIP6"
OUT="$BASE/EC-Earth3_historical_CMIP6_merged"
mkdir -p "$OUT"
echo "input : $IN"
echo "output: $OUT"
for v in pr tasmax tasmin rsds; do
  files=$(ls "$IN"/${v}_day_EC-Earth3_historical_r1i1p1f1_gr_*.nc 2>/dev/null | sort)
  if [ -z "$files" ]; then echo "$v: no file, skipped"; continue; fi
  start=$(echo "$files" | head -1 | sed -E 's/.*_([0-9]{8})-[0-9]{8}\.nc/\1/')
  end=$(echo "$files" | tail -1 | sed -E 's/.*_[0-9]{8}-([0-9]{8})\.nc/\1/')
  out="$OUT/${v}_day_EC-Earth3_historical_r1i1p1f1_gr_${start}-${end}.nc"
  if [ -f "$out" ]; then echo "$v: $(basename "$out") already exists, skipped"; continue; fi
  echo "$v: $(echo "$files" | wc -l) files -> $(basename "$out")"
  cdo -f nc4 -z zip_1 mergetime $files "$out.tmp" && mv "$out.tmp" "$out"
  echo "$v: $(cdo -s ntime "$out") days"
done
echo "done"
