"""Inventory of the inputs of the supervisor's pipeline (step 1): variable name, units, size and time axis of the ERA5
daily files (1981-2014), of the EC-Earth3 historical files and of the GCM runs, and the folders of Input_data.

Usage (JEO-lab terminal):  cd ~/downscaling && git pull && python guido_pipeline/inputs_check.py > ~/inputs_check.txt 2>&1
"""
import glob
import os
import sys

_user_site = os.path.expanduser(f"~/.local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
if os.path.isdir(_user_site) and _user_site not in sys.path:
    sys.path.insert(0, _user_site)
import xarray as xr

I = "/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/Input_data"
G = "/eos/jeodpp/data/projects/DROUGHTOBS/EC-Earth_hosing"

print("===== folders of Input_data")
for root, dirs, _ in os.walk(I):
    if root.count(os.sep) - I.count(os.sep) < 2:
        print(root)

files = (sorted(glob.glob(f"{I}/ERA5_daily_merged/*_1981-2014.nc")) + [f"{I}/ERA5_daily/psl_ERA5_day_1981.nc"]
         + sorted(glob.glob(f"{I}/EC-Earth3_historical_CMIP6/*.nc"))[:3]
         + sorted(glob.glob(f"{G}/stabilization-ssp585-2025_Original/*_day_*.nc")))
print(f"\n===== {len(files)} files")
for f in files:
    try:
        with xr.open_dataset(f, decode_times=False) as d:
            v = [x for x in d.data_vars if d[x].ndim == 3][0]
            t = d["time"]
            lat = [c for c in d[v].dims if c.lower().startswith("lat")]
            lon = [c for c in d[v].dims if c.lower().startswith("lon")]
            box = (f" | lat {float(d[lat[0]].min()):.2f}..{float(d[lat[0]].max()):.2f}"
                   f" lon {float(d[lon[0]].min()):.2f}..{float(d[lon[0]].max()):.2f}") if lat and lon else ""
            print(f"{os.path.basename(f)} | var {v} | units {d[v].attrs.get('units')} | dims {dict(d[v].sizes)}"
                  f" | time {t.attrs.get('units')} | cal {t.attrs.get('calendar')}{box}", flush=True)
    except Exception as e:
        print(f"{os.path.basename(f)} ERROR {e}", flush=True)
print("INPUTS_CHECK_DONE")
