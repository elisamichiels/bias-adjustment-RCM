"""
prep_era5_daily.py - build DAILY ERA5 (pr, tasmax, tasmin) from the HOURLY ERA5 copy on BDAP.

Source (one file per year and per variable, global 0.25 deg, hourly):
  <src>/total_precipitation/consolidated/<year>/<year>_cds_era5_total_precipitation.nc   (tp, m)
  <src>/2m_temperature/consolidated/<year>/<year>_cds_era5_2m_temperature.nc             (t2m, K)
Only the 'consolidated' files are used (the 'nrt' near-real-time files are ignored).

Daily values (UTC days, same definition as the CDS "ERA5 post-processed daily statistics", 1-hourly):
  pr     = sum of the 24 hourly accumulations valid from D 01:00 to D+1 00:00 (ERA5 hourly tp at time t
           is the accumulation over the previous hour), x 1000 -> mm/day, small negative values clipped to 0
  tasmax = max of the 24 hourly t2m values from D 00:00 to D 23:00, - 273.15 -> degC
  tasmin = min of the same 24 values
Note: tasmax/tasmin from hourly t2m slightly underestimate the extremes compared with ERA5 mx2t/mn2t.

Output (one file per year and per variable; names match the 'era5' pattern of notebook 00):
  <dst>/pr_ERA5_day_<year>.nc, <dst>/tasmax_ERA5_day_<year>.nc, <dst>/tasmin_ERA5_day_<year>.nc
  original grid (lat 90..-90, lon 0..359.75): ba_utils.read_raw normalises it when reading.

Usage (JEO-lab terminal, from the repository folder):
  python prep_era5_daily.py --start 1981 --end 1981                  # test on one year first
  nohup python prep_era5_daily.py --start 1981 --end 2025 > era5_daily.log 2>&1 &
Years already written are skipped, so the script can be stopped and restarted.
"""
import argparse
import os
import sys
import time
from pathlib import Path

# packages installed with "pip install --user" (JEO-lab does not add them to sys.path by itself)
_user_site = os.path.expanduser(f"~/.local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
if os.path.isdir(_user_site) and _user_site not in sys.path:
    sys.path.insert(0, _user_site)

import dask
import numpy as np
import pandas as pd
import xarray as xr
from dask.diagnostics import ProgressBar

SRC = "/eos/jeodpp/data/base/Meteo/GLOBAL/ECMWF/Reanalysis/ERA5/LATEST/Data/NetCDF"
DST = "/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/Input_data/ERA5_daily"
SOURCES = {"pr": ("total_precipitation", "tp"), "tas": ("2m_temperature", "t2m")}


def src_file(src, folder, year):
    return Path(src) / folder / "consolidated" / str(year) / f"{year}_cds_era5_{folder}.nc"


STD_DIMS = {"time": "valid_time", "lat": "latitude", "lon": "longitude"}   # the BDAP files differ by year


def open_one(path, name):
    """
    Open one hourly file lazily with standard dim names (valid_time, latitude, longitude).
    Chunked (compressed) files, e.g. tp: dask blocks = stored blocks, so each one is read once.
    Contiguous files, e.g. t2m: one day of the whole globe at a time.
    """
    with xr.open_dataset(str(path)) as ds0:
        dims, stored = ds0[name].dims, ds0[name].encoding.get("chunksizes")
    if stored:
        chunks = dict(zip(dims, stored))
    else:
        chunks = {d: (24 if STD_DIMS.get(d, d) == "valid_time" else -1) for d in dims}
    ds = xr.open_dataset(str(path), chunks=chunks)
    ds = ds.rename({d: s for d, s in STD_DIMS.items() if d in ds.dims or d in ds.coords})
    da = ds[name]
    if "expver" in da.dims:                     # ERA5 / ERA5T mix: keep the first non-missing value
        merged = da.isel(expver=0)
        for i in range(1, da.sizes["expver"]):
            merged = merged.fillna(da.isel(expver=i))
        da = merged
    da = da.drop_vars(["expver", "number"], errors="ignore")
    std = {STD_DIMS.get(d, d): c for d, c in chunks.items()}
    blocks = ({"valid_time": 24 * 28, "latitude": std["latitude"], "longitude": std["longitude"]}
              if stored else {"valid_time": 24})
    return da, blocks


def hourly_block(paths, name, start, n_days):
    """Exactly n_days * 24 hourly steps from `start` (checked: no missing hour), in day-aligned dask blocks."""
    parts = [open_one(p, name) for p in paths]
    blocks = parts[0][1]
    da = xr.concat([d for d, _ in parts], dim="valid_time") if len(parts) > 1 else parts[0][0]
    expected = pd.date_range(start, periods=n_days * 24, freq="h")
    da = da.sel(valid_time=slice(expected[0], expected[-1]))
    if da.sizes["valid_time"] != expected.size or not np.array_equal(da.valid_time.values, expected.values):
        raise ValueError(f"{name}: missing hours between {expected[0]} and {expected[-1]} "
                         f"({da.sizes['valid_time']} found, {expected.size} expected)")
    return da.chunk(blocks)


def to_daily(da, how, days):
    out = getattr(da.coarsen(valid_time=24), how)()
    out = out.rename({"valid_time": "time", "latitude": "lat", "longitude": "lon"})
    return out.assign_coords(time=days).chunk({"time": 28, "lat": -1, "lon": -1})   # whole-globe blocks to write


def write_job(da, name, units, long_name, method, path):
    da = da.astype("float32").rename(name)
    da.attrs = {"units": units, "long_name": long_name, "source": "ERA5 hourly (BDAP copy), consolidated",
                "daily_method": method}
    enc = {name: {"zlib": True, "complevel": 1, "dtype": "float32", "_FillValue": np.float32(1e20)}}
    tmp = path.with_suffix(".tmp.nc")
    return tmp, da.to_dataset().to_netcdf(tmp, encoding=enc, compute=False)


def do_year(year, src, dst, which):
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    jobs = []
    if "pr" in which:
        folder, name = SOURCES["pr"]
        cur, nxt = src_file(src, folder, year), src_file(src, folder, year + 1)
        if not (cur.exists() and nxt.exists()):
            print(f"  [skip pr {year}] needs {cur.name} and {nxt.name} (31 Dec ends at {year + 1}-01-01 00:00)")
        else:
            tp = hourly_block([cur, nxt], name, f"{year}-01-01 01:00", days.size)
            pr = (to_daily(tp, "sum", days) * 1000.0).clip(min=0.0)
            jobs.append(write_job(pr, "pr", "mm/d", "daily precipitation",
                                  "sum of hourly tp valid D 01:00 .. D+1 00:00 (UTC), x1000, clipped at 0",
                                  dst / f"pr_ERA5_day_{year}.nc"))
    if "tas" in which:
        folder, name = SOURCES["tas"]
        cur = src_file(src, folder, year)
        if not cur.exists():
            print(f"  [skip tasmax/tasmin {year}] {cur} not found")
        else:
            t2m = hourly_block([cur], name, f"{year}-01-01 00:00", days.size)
            jobs.append(write_job(to_daily(t2m, "max", days) - 273.15, "tasmax", "degC",
                                  "daily maximum near-surface air temperature",
                                  "max of hourly t2m D 00:00 .. D 23:00 (UTC), -273.15",
                                  dst / f"tasmax_ERA5_day_{year}.nc"))
            jobs.append(write_job(to_daily(t2m, "min", days) - 273.15, "tasmin", "degC",
                                  "daily minimum near-surface air temperature",
                                  "min of hourly t2m D 00:00 .. D 23:00 (UTC), -273.15",
                                  dst / f"tasmin_ERA5_day_{year}.nc"))
    if not jobs:
        return
    with ProgressBar():
        dask.compute(*[j for _, j in jobs])       # one pass: t2m is read once for tasmax and tasmin
    for tmp, _ in jobs:
        tmp.replace(tmp.with_suffix("").with_suffix(".nc"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--vars", nargs="+", default=["pr", "tas"], choices=["pr", "tas"],
                    help="pr = precipitation, tas = tasmax + tasmin")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DST)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    dst = Path(a.dst)
    dst.mkdir(parents=True, exist_ok=True)
    for year in range(a.start, a.end + 1):
        outs = {"pr": [dst / f"pr_ERA5_day_{year}.nc"],
                "tas": [dst / f"tasmax_ERA5_day_{year}.nc", dst / f"tasmin_ERA5_day_{year}.nc"]}
        which = [v for v in a.vars if a.overwrite or not all(p.exists() for p in outs[v])]
        if not which:
            print(f"{year}: already done")
            continue
        t0 = time.time()
        print(f"{year}: {', '.join(which)}", flush=True)
        do_year(year, a.src, dst, which)
        print(f"{year}: done in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
