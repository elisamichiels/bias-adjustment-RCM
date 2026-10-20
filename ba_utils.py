"""
ba_utils.py - helper functions shared by notebooks 01 to 06 (EC-Earth3 / RCM bias-adjustment pipeline).

Put this file in the SAME folder as the notebooks (locally and on BDAP).
No data path is defined here: everything comes from config_<profile>.json, written by notebook 00.
Only pathlib / forward-slash paths are used, so the code runs unchanged on Linux (BDAP JupyterLab) and Windows.

Contents
  1. configuration and data reading
  2. conservative regridding (regular lat/lon grids, no ESMF needed)
  3. WDF (FIXED rule) + QDM (xsdba): fit_F / apply_F
  4. saving, small diagnostics, environment helpers
"""
import glob
import json
import os
from pathlib import Path

import numpy as np
import xarray as xr

# --------------------------------------------------------------------------
# Methodological constants (same for every bias-adjustment function)
# --------------------------------------------------------------------------
THRESH_PR = 0.1      # mm/day: below this value = dry day
DTR_MIN = 0.1        # degC: floor of the diurnal temperature range (tasmax - tasmin)
NQUANTILES = 50      # number of QDM quantiles
SEED_WDF = 20250101  # FIXED WDF seed (same rule for every run)


# --------------------------------------------------------------------------
# 1. Configuration and reading
# --------------------------------------------------------------------------
try:                                   # recent xarray: CFDatetimeCoder ; otherwise use_cftime
    _TIME_KW = {"decode_times": xr.coders.CFDatetimeCoder(use_cftime=True)}
except AttributeError:
    _TIME_KW = {"use_cftime": True}


def on_bdap():
    return Path("/eos/jeodpp").exists()


def find_config(path=None):
    """Locate config_<profile>.json written by notebook 00."""
    if path:
        return Path(path)
    if os.environ.get("BA_CONFIG"):
        return Path(os.environ["BA_CONFIG"])
    profile = "bdap" if on_bdap() else "local"
    candidates = [Path.cwd() / "outputs" / f"config_{profile}.json",
                  Path.cwd() / f"config_{profile}.json",
                  Path.cwd().parent / "outputs" / f"config_{profile}.json",
                  Path.cwd().parent / f"config_{profile}.json"]
    if profile == "bdap":
        candidates += [Path(p) for p in glob.glob(
            f"/eos/jeodpp/data/projects/DROUGHTOBS/*/outputs/config_{profile}.json")]
        candidates += [Path(p) for p in glob.glob(
            f"/eos/jeodpp/home/users/*/ba_rcm/outputs/config_{profile}.json")]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "config_<profile>.json not found. Run notebook 00 first (or set CONFIG_PATH).")


def load_config(path=None):
    p = find_config(path)
    cfg = json.loads(p.read_text())
    cfg["_config_file"] = str(p)
    cfg["out"] = Path(cfg["out_root"])
    print(f"Config: {p}  (profile = {cfg['profile']})")
    return cfg


def out_dir(cfg, *parts):
    d = cfg["out"].joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def dataset_available(cfg, name, var):
    spec = cfg["datasets"].get(name)
    if not spec:
        return False
    pat = spec["patterns"].get(var, "")
    if (not pat) or "TO_FILL" in pat:
        return False
    return len(glob.glob(pat)) > 0


def _first(ds, options):
    for o in options:
        if o in ds.coords or o in ds.dims or o in ds.variables:
            return o
    return None


def norm_coords(da):
    """Standard lat/lon/time names; ascending lat; ascending lon in [-180, 180)."""
    ren = {}
    for std, opts in (("lat", ("lat", "latitude", "y")),
                      ("lon", ("lon", "longitude", "x")),
                      ("time", ("time", "valid_time"))):
        found = _first(da, opts)
        if found and found != std:
            ren[found] = std
    if ren:
        da = da.rename(ren)
    lon = ((da["lon"] + 180.0) % 360.0) - 180.0
    da = da.assign_coords(lon=lon).sortby("lon").sortby("lat")
    return da


def _std_units(var, da):
    """Convert to mm/day (pr) or degC (tas*). Returns (da, original units)."""
    u0 = str(da.attrs.get("units", "")).strip()
    u = u0.lower().replace(" ", "")
    if var == "pr":
        if u in ("kgm-2s-1", "kgm**-2s**-1", "kg/m2/s", "mm/s", "kgm^-2s^-1", "kgm-2s-1"):
            da = da * 86400.0
        elif u in ("m", "m/day", "md-1", "mday-1"):
            da = da * 1000.0
        elif u in ("mm/day", "mmday-1", "mmd-1", "mm", "mm/d", "mmd**-1"):
            pass
        else:
            print(f"  [!] unknown pr units '{u0}': assumed mm/day")
        da.attrs["units"] = "mm/d"
    else:
        if u in ("k", "kelvin"):
            da = da - 273.15
        elif u in ("degc", "c", "celsius", "degreec", "degrees_c", "degree_celsius"):
            pass
        else:
            m = float(da.isel(time=slice(0, 5)).mean().compute())
            if m > 150:
                print(f"  [!] unknown {var} units '{u0}' (mean {m:.0f}): assumed Kelvin")
                da = da - 273.15
            else:
                print(f"  [!] unknown {var} units '{u0}': assumed degC")
        da.attrs["units"] = "degC"
    return da, u0


def read_raw(cfg, name, var, chunk_time=31, calendar="noleap"):
    """
    Lazily read a raw dataset (as defined in the config) and put it in standard form:
    dims (time, lat, lon), ascending lat, lon -180..180, units mm/day or degC,
    'noleap' calendar (29 February removed).
    """
    spec = cfg["datasets"][name]
    pattern = spec["patterns"].get(var, "")
    if (not pattern) or "TO_FILL" in pattern:
        raise FileNotFoundError(f"{name}/{var}: path not filled in (notebook 00).")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"{name}/{var}: no file matches {pattern}")
    ds = xr.open_mfdataset(files, combine="by_coords", chunks={"time": chunk_time},
                           parallel=False, **_TIME_KW)
    vname = None
    for a in cfg["aliases"].get(var, [var]):
        if a in ds.data_vars:
            vname = a
            break
    if vname is None:
        raise KeyError(f"{name}: variable {var} not found (variables: {list(ds.data_vars)})")
    da = ds[vname]
    da = da.sortby("time") if "time" in da.dims else da
    _la, _lo = _first(da, ("lat", "latitude", "y")), _first(da, ("lon", "longitude", "x"))
    orig_lat_desc = bool(_la and da[_la].size > 1 and float(da[_la][0]) > float(da[_la][-1]))
    orig_lon_0360 = bool(_lo and float(da[_lo].max()) > 180.0)

    # extra singleton dimensions (expver, height, number...)
    da = norm_coords(da)
    for d in list(da.dims):
        if d not in ("time", "lat", "lon"):
            if da.sizes[d] == 1:
                da = da.isel({d: 0}, drop=True)
            else:
                raise ValueError(f"{name}/{var}: extra dimension '{d}' of size {da.sizes[d]}")
    da = da.transpose("time", "lat", "lon")
    orig_cal = getattr(da.indexes["time"], "calendar", "standard")

    da, u0 = _std_units(var, da)
    if orig_cal != calendar:
        da = da.convert_calendar(calendar, dim="time")
    da = da.chunk({"time": chunk_time, "lat": -1, "lon": -1})
    da.name = var
    da.attrs.update({"orig_units": u0, "orig_calendar": orig_cal, "dataset": name,
                     "orig_lat_desc": int(orig_lat_desc), "orig_lon_0360": int(orig_lon_0360)})
    return da


def read_processed(path, var=None, chunk_time=31):
    path = Path(path)
    ds = xr.open_dataset(path, chunks={"time": chunk_time}, **_TIME_KW)
    var = var or list(ds.data_vars)[0]
    return ds[var]


def subset_time(da, start, end):
    return da.sel(time=slice(str(start), str(end)))


def crop_bbox(da, bbox):
    """bbox = {'lat': (min, max), 'lon': (min, max)}; da already normalised (ascending lat/lon).
    bbox = None -> no cropping (whole domain)."""
    if bbox is None:
        return da
    return da.sel(lat=slice(*bbox["lat"]), lon=slice(*bbox["lon"]))


def domain_of(da, margin=0.0):
    """Lat/lon extent of a (normalised) field, optionally widened by `margin` degrees."""
    return {"lat": (float(da.lat.min()) - margin, float(da.lat.max()) + margin),
            "lon": (float(da.lon.min()) - margin, float(da.lon.max()) + margin)}


def rcm_domain(cfg, run="rcm_2025_nohosing", margin=0.0):
    """
    Domain of the RCM (its own grid extent): there is no hand-made region box in this pipeline.
    Returns None if the RCM path is not filled in yet (callers then use the whole/global domain).
    """
    if not dataset_available(cfg, run, "pr"):
        return None
    return domain_of(read_raw(cfg, run, "pr").isel(time=slice(0, 1)), margin)


def sub_to(ds, like, tol=1e-3):
    """Restrict ds (parameters on a larger grid) to the grid of `like`."""
    if same_grid(ds, like):
        return ds.assign_coords(lat=like.lat, lon=like.lon)
    out = ds.sel(lat=like.lat.values, lon=like.lon.values, method="nearest", tolerance=tol)
    return out.assign_coords(lat=like.lat, lon=like.lon)


def same_grid(a, b, tol=1e-4):
    return (a.sizes["lat"] == b.sizes["lat"] and a.sizes["lon"] == b.sizes["lon"]
            and np.allclose(a.lat, b.lat, atol=tol) and np.allclose(a.lon, b.lon, atol=tol))


# --------------------------------------------------------------------------
# 2. Conservative regridding (separable lat/lon, no ESMF)
# --------------------------------------------------------------------------
def target_grid(res=1.0):
    lat = np.arange(-90 + res / 2, 90, res)
    lon = np.arange(-180 + res / 2, 180, res)
    return lat, lon


def _edges(c):
    c = np.asarray(c, float)
    mid = (c[1:] + c[:-1]) / 2
    return np.concatenate([[c[0] - (c[1] - c[0]) / 2], mid, [c[-1] + (c[-1] - c[-2]) / 2]])


def _lat_weights(src_lat, dst_lat):
    se = np.clip(_edges(src_lat), -90, 90)
    de = np.clip(_edges(dst_lat), -90, 90)
    s, d = np.sin(np.deg2rad(se)), np.sin(np.deg2rad(de))
    lo = np.maximum(d[:-1, None], s[None, :-1])
    hi = np.minimum(d[1:, None], s[None, 1:])
    return np.clip(hi - lo, 0, None)           # (n_dst, n_src) in units of sin(lat)


def _lon_weights(src_lon, dst_lon):
    se, de = _edges(src_lon), _edges(dst_lon)
    w = 0.0
    for k in (-360.0, 0.0, 360.0):             # periodicity in longitude
        lo = np.maximum(de[:-1, None], se[None, :-1] + k)
        hi = np.minimum(de[1:, None], se[None, 1:] + k)
        w = w + np.clip(hi - lo, 0, None)
    return w                                   # (n_dst, n_src) in degrees


def regrid_conservative(da, dst_lat, dst_lon, min_cover=0.5):
    """
    Area-weighted (conservative) regridding.
    Suited to flux/intensity fields (pr in mm/day): the spatial mean is conserved.
    Target cells with less than `min_cover` of their area covered by the source -> NaN.
    Source NaNs are ignored (renormalisation).
    Limitation: cell edges are taken as mid-points between centres (exact for regular grids,
    a very good approximation for the Gaussian grid of EC-Earth3).
    """
    da = norm_coords(da)
    wy = _lat_weights(da.lat.values, dst_lat).astype("float32")
    wx = _lon_weights(da.lon.values, dst_lon).astype("float32")
    dlat_e = np.sin(np.deg2rad(np.clip(_edges(dst_lat), -90, 90)))
    dlon_e = _edges(dst_lon)
    area = (np.diff(dlat_e)[:, None] * np.diff(dlon_e)[None, :]).astype("float32")

    def _f(a):
        m = np.isfinite(a)
        a0 = np.where(m, a, 0).astype("float32")
        num = np.matmul(np.matmul(wy, a0), wx.T)
        den = np.matmul(np.matmul(wy, m.astype("float32")), wx.T)
        ok = (den / area) >= min_cover
        return np.where(ok, num / np.where(den > 0, den, 1), np.nan).astype("float32")

    da = da.chunk({"lat": -1, "lon": -1})
    out = xr.apply_ufunc(
        _f, da, input_core_dims=[["lat", "lon"]], output_core_dims=[["lat", "lon"]],
        exclude_dims={"lat", "lon"}, dask="parallelized", output_dtypes=[np.float32],
        dask_gufunc_kwargs={"output_sizes": {"lat": len(dst_lat), "lon": len(dst_lon)}},
        keep_attrs=True)
    out = out.assign_coords(lat=dst_lat, lon=dst_lon)
    out.attrs["regrid"] = "conservative (area overlap)"
    return out


def area_mean(da, bbox=None):
    """Spatial mean weighted by cos(lat) (over `bbox`, or over the whole field if None)."""
    da = crop_bbox(da, bbox)
    w = np.cos(np.deg2rad(da.lat))
    return da.weighted(w).mean(("lat", "lon"))


# --------------------------------------------------------------------------
# 3. WDF (fixed rule) + QDM
# --------------------------------------------------------------------------
def _rank_value(x, q):
    """Value of x (per pixel) at rank q*n_valid along 'time'; q is a (lat, lon) field."""
    def f(a, qq):
        s = np.sort(a, axis=-1)
        n = np.sum(~np.isnan(a), axis=-1)
        idx = np.floor(np.nan_to_num(qq) * n).astype(int)
        idx = np.clip(idx, 0, np.maximum(n - 1, 0))
        v = np.take_along_axis(s, idx[..., None], axis=-1)[..., 0]
        return np.where(n > 0, v, np.nan)
    if x.chunks is not None:
        x = x.chunk({"time": -1})
    return xr.apply_ufunc(f, x, q, input_core_dims=[["time"], []], dask="parallelized",
                          output_dtypes=[np.float32])


def _rand(like, seed):
    if like.chunks is not None:
        import dask.array as dsa
        arr = dsa.random.RandomState(seed).random_sample(like.shape, chunks=like.chunks).astype("float32")
    else:
        arr = np.random.default_rng(seed).random(like.shape, dtype="float32")
    return xr.DataArray(arr, dims=like.dims, coords=like.coords)


def _wet_only(x, thr=THRESH_PR):
    """Dry days -> NaN: the pr QDM only acts on wet-day intensities."""
    return x.where(x >= thr)


def wdf_fit(pr_ref, pr_hist, thr=THRESH_PR):
    """
    Estimate the WDF rule ONCE (per month and per pixel) on the calibration pair.
      p0_ref, p0_hist : dry-day fraction (pr < thr)
      t  : model threshold. Model days < t -> dry.        (t > thr if the model is too wet)
      q  : probability of activating a model dry day       (q > 0 if the model is too dry)
      hi : upper bound of the intensities drawn for activated days, U(thr, hi)
    The rule (t, q, hi, seed) is then applied unchanged to every run:
    the dry-day frequency of a run (e.g. hosing) is therefore NOT re-imposed.
    """
    rows = []
    months = pr_ref.time.dt.month.values
    monthsh = pr_hist.time.dt.month.values
    for m in range(1, 13):
        r = pr_ref.isel(time=np.where(months == m)[0])
        h = pr_hist.isel(time=np.where(monthsh == m)[0])
        p0r = (r < thr).where(r.notnull()).mean("time")
        p0h = (h < thr).where(h.notnull()).mean("time")
        tq = _rank_value(h, p0r)
        t = xr.where(tq > thr, tq, thr)
        q = xr.where(p0h > 0, ((p0h - p0r) / p0h).clip(0, 1), 0.0)
        hi = _rank_value(r, p0h)
        hi = xr.where(hi > thr, hi, thr)
        ds = xr.Dataset({"t": t, "q": q, "hi": hi, "p0_ref": p0r, "p0_hist": p0h})
        rows.append(ds.expand_dims(month=[m]))
    return xr.concat(rows, dim="month")


def wdf_apply(pr, par, seed=SEED_WDF, thr=THRESH_PR):
    """Apply the fixed WDF rule. Dry days take the value 0."""
    par = sub_to(par, pr)       # clear error if the grid does not match

    def _one(g):
        m = int(g.time.dt.month.values[0])
        t = par["t"].sel(month=m, drop=True)
        q = par["q"].sel(month=m, drop=True).fillna(0.0)
        hi = par["hi"].sel(month=m, drop=True).fillna(thr)
        u1 = _rand(g, seed + 2 * m)
        u2 = _rand(g, seed + 2 * m + 1)
        wet = g >= t
        act = (~wet) & (u1 < q)
        newval = thr + u2 * (hi - thr)
        out = xr.where(wet, g, xr.where(act, newval, 0.0))
        return out.where(g.notnull())

    out = pr.groupby("time.month").map(_one)
    out = out.transpose("time", "lat", "lon")
    out.attrs["units"] = "mm/d"
    return out


def _as_keys(d):
    """{'pr','tasmax','tasmin'} -> {'pr','tasmax','dtr'}."""
    dtr = (d["tasmax"] - d["tasmin"]).clip(min=DTR_MIN)
    dtr.attrs["units"] = "K"
    tx = d["tasmax"].copy()
    tx.attrs["units"] = "degC"
    pr = d["pr"].copy()
    pr.attrs["units"] = "mm/d"
    return {"pr": pr, "tasmax": tx, "dtr": dtr}


def _prep(x, chunks_space):
    return x.chunk({"time": -1, **chunks_space})


def fit_F(ref, hist, outdir, chunks_space=None, nquantiles=NQUANTILES, progress=True):
    """
    Train a correction function F = WDF (pr) + QDM, per month and per pixel:
        pr     : fixed WDF, then multiplicative QDM (wet days only)
        tasmax : additive QDM
        dtr    : multiplicative QDM (tasmin = adjusted tasmax - adjusted dtr)
    ref, hist : dict {'pr','tasmax','tasmin'} of DataArrays (time, lat, lon), same grids.
    Writes the parameters to outdir (wdf_params.nc, qdm_pr.nc, qdm_tasmax.nc, qdm_dtr.nc).
    """
    from dask.diagnostics import ProgressBar
    from xsdba.adjustment import QuantileDeltaMapping
    chunks_space = chunks_space or {"lat": 30, "lon": 60}
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    R, H = _as_keys(ref), _as_keys(hist)
    for k in R:
        if not same_grid(R[k], H[k]):
            raise ValueError(f"{k}: ref and hist are not on the same grid.")
    pb = ProgressBar() if progress else None

    def _compute_save(ds, path):
        if pb:
            with pb:
                ds = ds.compute()
        else:
            ds = ds.compute()
        ds.to_netcdf(path)
        return ds

    # --- WDF
    print("WDF: estimating the rule (once)")
    pr_r = _prep(R["pr"], chunks_space)
    pr_h = _prep(H["pr"], chunks_space)
    par = _compute_save(wdf_fit(pr_r, pr_h), outdir / "wdf_params.nc")
    pr_h_w = _prep(_wet_only(wdf_apply(pr_h, par)), chunks_space)
    pr_r_w = _prep(_wet_only(pr_r), chunks_space)
    pr_h_w.attrs["units"] = pr_r_w.attrs["units"] = "mm/d"

    # --- QDM
    jobs = {"pr": ("*", pr_r_w, pr_h_w),
            "tasmax": ("+", _prep(R["tasmax"], chunks_space), _prep(H["tasmax"], chunks_space)),
            "dtr": ("*", _prep(R["dtr"], chunks_space), _prep(H["dtr"], chunks_space))}
    for k, (kind, r, h) in jobs.items():
        print(f"QDM {k} (kind '{kind}', {nquantiles} quantiles, per month)")
        q = QuantileDeltaMapping.train(r, h, nquantiles=nquantiles, group="time.month", kind=kind)
        _compute_save(q.ds, outdir / f"qdm_{k}.nc")
    print("Parameters written to", outdir)


def apply_F(sim, Fdir, chunks_space=None, seed=SEED_WDF):
    """
    Apply F (trained by fit_F) to a run `sim` = dict {'pr','tasmax','tasmin'}.
    Returns a dict of adjusted DataArrays (lazy).
    """
    from xsdba.adjustment import QuantileDeltaMapping
    chunks_space = chunks_space or {"lat": 30, "lon": 60}
    Fdir = Path(Fdir)
    S = _as_keys(sim)
    par = xr.open_dataset(Fdir / "wdf_params.nc").load()
    out = {}

    pr_d = wdf_apply(_prep(S["pr"], chunks_space), par, seed=seed)      # dry days = 0
    pr_w = _prep(_wet_only(pr_d), chunks_space)                         # dry days = NaN
    pr_w.attrs["units"] = "mm/d"
    def _load_q(k):
        qd = sub_to(xr.open_dataset(Fdir / f"qdm_{k}.nc").load(), S["pr"])
        return QuantileDeltaMapping.from_dataset(qd)

    q = _load_q("pr")
    pr_a = q.adjust(pr_w, extrapolation="constant", interp="linear")
    # wet days: QDM (>= threshold); dry days: 0; if the QDM could not correct a value (no wet days
    # in the training data at this pixel/month) the WDF value is kept.
    pr_a = pr_a.transpose(*pr_d.dims)
    out["pr"] = xr.where(pr_d.isnull(), np.nan,
                         xr.where(pr_d < THRESH_PR, 0.0,
                                  xr.where(pr_a.isnull(), pr_d, pr_a.clip(min=THRESH_PR))))

    q = _load_q("tasmax")
    tx_a = q.adjust(_prep(S["tasmax"], chunks_space), extrapolation="constant", interp="linear")
    q = _load_q("dtr")
    dtr_a = q.adjust(_prep(S["dtr"], chunks_space), extrapolation="constant", interp="linear")
    out["tasmax"] = tx_a.transpose("time", "lat", "lon")
    out["tasmin"] = (tx_a - dtr_a).transpose("time", "lat", "lon")
    for k, unit in (("pr", "mm/d"), ("tasmax", "degC"), ("tasmin", "degC")):
        out[k].name = k
        out[k].attrs = {"units": unit}
        out[k] = out[k].drop_vars([c for c in out[k].coords if c not in ("time", "lat", "lon")])
    return out


# --------------------------------------------------------------------------
# 4. Saving, simple diagnostics, environment helpers
# --------------------------------------------------------------------------
def save_da(da, path, name=None, progress=True):
    """Write a DataArray to compressed NetCDF (float32) through a temporary file."""
    from dask.diagnostics import ProgressBar
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = name or da.name
    da = da.astype("float32").rename(name)
    tmp = path.with_suffix(".tmp.nc")
    enc = {name: {"zlib": True, "complevel": 3, "dtype": "float32", "_FillValue": np.float32(1e20)}}
    if progress:
        with ProgressBar():
            da.to_dataset().to_netcdf(tmp, encoding=enc)
    else:
        da.to_dataset().to_netcdf(tmp, encoding=enc)
    tmp.replace(path)
    return path


def save_ds(ds, path, progress=True):
    """Write a Dataset (several variables) to compressed float32 NetCDF."""
    from dask.diagnostics import ProgressBar
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = ds.astype("float32")
    tmp = path.with_suffix(".tmp.nc")
    enc = {v: {"zlib": True, "complevel": 3, "dtype": "float32", "_FillValue": np.float32(1e20)}
           for v in ds.data_vars}
    if progress:
        with ProgressBar():
            ds.to_netcdf(tmp, encoding=enc)
    else:
        ds.to_netcdf(tmp, encoding=enc)
    tmp.replace(path)
    return path


def summarize(da, thr=THRESH_PR):
    """Small computed summary: mean, quantiles, dry-day fraction for pr."""
    v = da.values.ravel()
    v = v[np.isfinite(v)]
    out = {"n": int(v.size), "mean": float(v.mean()),
           "p05": float(np.percentile(v, 5)), "p50": float(np.percentile(v, 50)),
           "p95": float(np.percentile(v, 95)), "p99": float(np.percentile(v, 99))}
    if da.attrs.get("units") == "mm/d":
        out["dry_frac"] = float((v < thr).mean())
    return out


def check_environment():
    """Print which required Python packages are available (call at the top of a notebook)."""
    import importlib
    missing = []
    for mod in ["numpy", "pandas", "xarray", "dask", "netCDF4", "cftime", "matplotlib", "scipy", "xsdba"]:
        try:
            m = importlib.import_module(mod)
            print(f"  ok       {mod:11s} {getattr(m, '__version__', '')}")
        except Exception:
            print(f"  MISSING  {mod}")
            missing.append(mod)
    if missing:
        print("\nInstall in your conda environment, e.g.:")
        print("  conda install -c conda-forge " + " ".join(m for m in missing if m != "xsdba"))
        if "xsdba" in missing:
            print("  pip install xsdba")
    return missing


def start_dask(n_workers=None, threads_per_worker=1, memory_limit="auto"):
    """
    Optional: start a local dask cluster to use several CPU cores (JEO-lab / JEO-desk node).
    Returns the Client, or None if dask.distributed is not installed.
    The per-pixel QDM is CPU-heavy, so this is useful on large grids.
    """
    try:
        from dask.distributed import Client, LocalCluster
    except Exception:
        print("dask.distributed not available: running with the default threaded scheduler.")
        return None
    n_workers = n_workers or max(1, (os.cpu_count() or 2) - 1)
    cluster = LocalCluster(n_workers=n_workers, threads_per_worker=threads_per_worker,
                           memory_limit=memory_limit)
    client = Client(cluster)
    print(f"Dask cluster: {n_workers} workers. Dashboard: {client.dashboard_link}")
    return client
