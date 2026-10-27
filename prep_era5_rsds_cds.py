"""
prep_era5_rsds_cds.py - DAILY ERA5 solar radiation (rsds) downloaded from the Copernicus Climate Data Store, for the
years missing in the BDAP hourly copy (ssrd from 2005 only, see prep_era5_daily.py).

Source: CDS dataset "ERA5 post-processed daily statistics on single levels" (derived-era5-single-levels-daily-statistics),
variable surface_solar_radiation_downwards, daily_mean of the 1-hourly values, UTC days, global 0.25 deg.
One request per month, kept in <raw>/ssrd_daily_mean_<year>_<month>.nc (not downloaded again if present).

Daily value: mean of the hourly ssrd accumulations (J m-2 over one hour) / 3600 -> W m-2, clipped at 0
(= daily mean surface downwelling shortwave radiation, CMIP6 'rsds' units, as prep_era5_daily.py).

Output: <dst>/rsds_ERA5_day_<year>.nc, same layout as prep_era5_daily.py (variable rsds, dims time/lat/lon,
lat 90..-90, lon 0..359.75, float32, days at 00:00).

Needs: a CDS account, the licence of the dataset accepted on its web page, the API key in ~/.cdsapirc, and cdsapi
(pip install --user cdsapi).

Usage (JEO-lab terminal, from the repository folder):
  # test: 2006 in a separate folder, compared with the file built from the BDAP hourly copy
  python prep_era5_rsds_cds.py --start 2006 --end 2006 --dst <check folder> --compare <ERA5_daily folder>
  # the missing years
  nohup python prep_era5_rsds_cds.py --start 1981 --end 2004 > era5_rsds_cds.log 2>&1 &
Years already written are skipped, so the script can be stopped and restarted.
"""
import argparse
import calendar
import os
os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")   # BDAP/EOS refuses HDF5 file locks ("NetCDF: HDF error")
import sys
import time
import zipfile
from pathlib import Path

# packages installed with "pip install --user" (JEO-lab does not add them to sys.path by itself)
_user_site = os.path.expanduser(f"~/.local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
if os.path.isdir(_user_site) and _user_site not in sys.path:
    sys.path.insert(0, _user_site)

import numpy as np
import pandas as pd
import xarray as xr

DST = "/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/Input_data/ERA5_daily"
RAW = "/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/Input_data/ERA5_cds_raw/ssrd_daily_mean"
DATASET = "derived-era5-single-levels-daily-statistics"
STD = {"valid_time": "time", "latitude": "lat", "longitude": "lon"}


def download_month(client, year, month, path):
    """One CDS request (one month, all days); a zip answer is unpacked into `path`."""
    if path.exists():
        return
    tmp = path.with_suffix(".part")
    request = {
        "product_type": "reanalysis",
        "variable": ["surface_solar_radiation_downwards"],
        "year": str(year),
        "month": [f"{month:02d}"],
        "day": [f"{d:02d}" for d in range(1, calendar.monthrange(year, month)[1] + 1)],
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
    }
    client.retrieve(DATASET, request, str(tmp))
    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            names = [n for n in z.namelist() if n.endswith(".nc")]
            if len(names) != 1:
                raise ValueError(f"{tmp}: expected one .nc file in the zip, found {z.namelist()}")
            path.write_bytes(z.read(names[0]))
        tmp.unlink()
    else:
        tmp.replace(path)


def open_month(path):
    ds = xr.open_dataset(path)
    ds = ds.rename({k: v for k, v in STD.items() if k in ds.dims or k in ds.coords})
    da = ds["ssrd"].drop_vars(["number", "expver"], errors="ignore").load()
    ds.close()
    return da


def build_year(year, raw, dst, client):
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    paths = [raw / f"ssrd_daily_mean_{year}_{m:02d}.nc" for m in range(1, 13)]
    for m, p in enumerate(paths, start=1):
        t0 = time.time()
        if not p.exists():
            download_month(client, year, m, p)
            print(f"  {p.name} downloaded in {(time.time() - t0) / 60:.1f} min", flush=True)
    da = xr.concat([open_month(p) for p in paths], dim="time")
    if da.sizes["time"] != days.size:
        raise ValueError(f"{year}: {da.sizes['time']} days found, {days.size} expected")
    if not np.array_equal(pd.DatetimeIndex(da.time.values).normalize(), days):
        raise ValueError(f"{year}: the days of the CDS files are not 1 Jan .. 31 Dec")
    da = da.assign_coords(time=days)
    if da.lat[0] < da.lat[-1]:
        da = da.isel(lat=slice(None, None, -1))                 # lat 90..-90, as prep_era5_daily.py
    da = da.assign_coords(lon=da.lon % 360).sortby("lon")       # lon 0..359.75
    rsds = (da / 3600.0).clip(min=0.0).astype("float32").rename("rsds")
    rsds.attrs = {"units": "W m-2", "long_name": "surface downwelling shortwave radiation (daily mean)",
                  "source": f"ERA5 post-processed daily statistics (CDS {DATASET})",
                  "daily_method": "daily_mean of hourly ssrd (J m-2 per hour), UTC days, / 3600, clipped at 0"}
    out = dst / f"rsds_ERA5_day_{year}.nc"
    tmp = out.with_suffix(".tmp.nc")
    enc = {"rsds": {"zlib": True, "complevel": 1, "dtype": "float32", "_FillValue": np.float32(1e20)}}
    rsds.to_dataset().to_netcdf(tmp, encoding=enc)
    tmp.replace(out)
    return out


def compare(new_path, ref_path):
    """Day-by-day comparison of the CDS file with the file built from the BDAP hourly copy (same year)."""
    a = xr.open_dataset(new_path)["rsds"].load()
    b = xr.open_dataset(ref_path)["rsds"].load()
    if a.shape != b.shape:
        print(f"different shapes: CDS {a.shape} vs BDAP {b.shape}")
        return
    b = b.assign_coords(time=a.time, lat=a.lat, lon=a.lon)
    w = np.cos(np.deg2rad(a.lat))
    d = a - b
    gm = lambda x: float(x.weighted(w).mean(("lat", "lon")).mean("time"))
    print(f"\n=== {Path(new_path).name}: CDS vs BDAP-built ({Path(ref_path).parent})")
    print(f"  global mean rsds       : CDS {gm(a):.3f}   BDAP {gm(b):.3f}   W m-2")
    print(f"  mean difference        : {gm(d):+.4f} W m-2")
    print(f"  mean |difference|      : {gm(abs(d)):.4f} W m-2")
    print(f"  max |difference|       : {float(abs(d).max()):.3f} W m-2")
    print(f"  99.9th pct |difference|: {float(np.nanpercentile(abs(d).values, 99.9)):.3f} W m-2")
    print(f"  correlation (all values): {float(xr.corr(a, b)):.6f}")
    for shift in (-1, 1):   # a one-day shift would show up as a much better match here
        ds = a.isel(time=slice(1, -1)) - b.shift(time=shift).isel(time=slice(1, -1))
        print(f"  mean |difference| if BDAP shifted by {shift:+d} day: {gm(abs(ds)):.4f} W m-2")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--dst", default=DST)
    ap.add_argument("--raw", default=RAW, help="folder of the monthly CDS downloads")
    ap.add_argument("--compare", default=None, help="folder of the existing rsds_ERA5_day_<year>.nc to compare with")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    dst, raw = Path(a.dst), Path(a.raw)
    dst.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    import cdsapi
    client = cdsapi.Client()
    for year in range(a.start, a.end + 1):
        out = dst / f"rsds_ERA5_day_{year}.nc"
        if out.exists() and not a.overwrite:
            print(f"{year}: already done")
        else:
            t0 = time.time()
            print(f"{year}: downloading / building", flush=True)
            build_year(year, raw, dst, client)
            print(f"{year}: done in {(time.time() - t0) / 60:.1f} min -> {out}", flush=True)
        if a.compare:
            ref = Path(a.compare) / f"rsds_ERA5_day_{year}.nc"
            if ref.exists() and ref.resolve() != out.resolve():
                compare(out, ref)
            else:
                print(f"  no other file to compare with: {ref}")


if __name__ == "__main__":
    main()
