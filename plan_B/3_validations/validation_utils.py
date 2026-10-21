"""
validation_utils.py - helpers shared by the plan B validation notebooks (3_validations/...).

Same conventions as the exploration notebook (001_exploration/01_exploration):
  - statistics of a dataset computed once and cached: monthly climatology, yearly means, yearly extremes,
    dry days, wet-day intensity, pooled quantiles on random pixels of the domain;
  - masks of notebook 00c (LISFLOOD domain, with or without the 0.25 deg buffer);
  - maps with coastlines (GISCO), Welch t-test dots, relative differences for pr.
The F1 analogue downscaling is not synchronised day by day with ERA5: only statistics are compared.
"""
import numpy as np
import pandas as pd
import xarray as xr
import dask
import matplotlib.pyplot as plt
from dask.diagnostics import ProgressBar

import ba_utils as bu

QUANTILES = [0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.999]
UNITS = {"pr": "mm/day", "tasmax": "degC", "tasmin": "degC", "dtr": "degC", "rsds": "W m-2"}
CMAP = {"pr": "YlGnBu", "tasmax": "RdYlBu_r", "tasmin": "RdYlBu_r", "dtr": "magma_r", "rsds": "YlOrRd"}
DCMAP = {"pr": "BrBG", "tasmax": "RdBu_r", "tasmin": "RdBu_r", "dtr": "PuOr_r", "rsds": "PuOr_r"}
EXT = {"pr": ("max", "Rx1day"), "tasmax": ("max", "TXx"), "tasmin": ("min", "TNn")}
SEASONS = {"DJF": [12, 1, 2], "MAM": [3, 4, 5], "JJA": [6, 7, 8], "SON": [9, 10, 11]}

STATE = {"cfg": None, "use_mask": True, "mask_files": None, "masks": [], "borders": None, "proj": None}


# --------------------------------------------------------------------------
# setup and masks
# --------------------------------------------------------------------------
def init(cfg, mask_kind="buffer", use_mask=True, borders_res="01M"):
    """Load the masks of notebook 00c and the coastlines. Returns a label of the domain."""
    files = {"domain": ("era5", "ecearth3"), "buffer": ("ecearth3_buffer_on_era5", "ecearth3_buffer")}[mask_kind]
    if use_mask:
        for g in files:
            assert bu.domain_mask_path(cfg, g).exists(), f"Mask '{g}' not found: run notebook 00c_land_mask first."
    try:
        import cartopy.crs as ccrs
        proj = ccrs.PlateCarree()
    except ImportError:
        proj = None
    STATE.update(cfg=cfg, use_mask=use_mask, mask_files=files, proj=proj,
                 masks=[bu.load_domain_mask(cfg, g) for g in files] if use_mask else [],
                 borders=bu.borders(cfg, borders_res))
    if not use_mask:
        return "globe"
    return {"domain": "LISFLOOD domain", "buffer": "LISFLOOD domain + buffer"}[mask_kind]


def mask_for(da):
    """Mask on the grid of `da` (ERA5 or EC-Earth3 grid of 00c; other grids: ERA5-grid mask transferred)."""
    if not STATE["use_mask"]:
        return xr.ones_like(da.isel({d: 0 for d in da.dims if d not in ("lat", "lon")}, drop=True), dtype=bool)
    for m in STATE["masks"]:
        if bu.same_grid(m, da):
            return m.assign_coords(lat=da.lat, lon=da.lon)
    m = bu.load_domain_mask(STATE["cfg"], STATE["mask_files"][0], like=da)
    STATE["masks"].append(m)
    return m


def dmean(da):
    """Area-weighted mean over the domain."""
    return bu.area_mean(da.where(mask_for(da)))


# --------------------------------------------------------------------------
# statistics (computed once, cached)
# --------------------------------------------------------------------------
def sample_points(grid, n, seed=0):
    """Random pixels of the domain, probability proportional to their area (cos lat)."""
    rng = np.random.default_rng(seed)
    w = (np.cos(np.deg2rad(grid.lat.values))[:, None] * np.ones((1, grid.sizes["lon"])) * mask_for(grid).values).ravel()
    idx = rng.choice(w.size, size=min(n, int((w > 0).sum())), replace=False, p=w / w.sum())
    return np.unravel_index(idx, (grid.sizes["lat"], grid.sizes["lon"]))


def compute_stats(d, path=None, overwrite=False, n_sample=3000, label=""):
    """
    d: dict var -> daily DataArray (time, lat, lon), already restricted to the wanted period.
    Returns the compact statistics (and writes them to `path`); read from `path` if it exists.
    """
    if path is not None and path.exists() and not overwrite:
        return xr.open_dataset(path).load()
    print(f"-> computing the statistics of {label or path}")
    d = dict(d)
    if "tasmax" in d and "tasmin" in d:
        d["dtr"] = d["tasmax"] - d["tasmin"]
    grid = next(iter(d.values())).isel(time=0)
    iy, ix = sample_points(grid, n_sample)
    pick = dict(lat=xr.DataArray(iy, dims="point"), lon=xr.DataArray(ix, dims="point"))
    out, pts, scal, attrs = {}, {}, {}, {}
    for v, da in d.items():
        yrs = np.unique(da.time.dt.year.values)
        attrs.update({f"period_{v}": f"{yrs[0]}-{yrs[-1]}", f"ndays_{v}": int(da.sizes["time"]),
                      f"expected_days_{v}": int(len(yrs) * 365)})
        out[f"{v}_clim_month"] = da.groupby("time.month").mean()
        out[f"{v}_year_mean"] = da.groupby("time.year").mean()
        pts[v] = da.isel(**pick)
        scal[f"nan_frac_{v}"] = da.isnull().mean()
        scal[f"min_{v}"] = da.min()
        scal[f"max_{v}"] = da.max()
    for v, (how, _) in EXT.items():
        if v in d:
            out[f"{v}_year_ext"] = getattr(d[v].groupby("time.year"), how)()
    if "pr" in d:
        dry = (d["pr"] < bu.THRESH_PR).where(d["pr"].notnull())
        out["pr_year_dry"] = dry.groupby("time.year").mean()
        out["pr_month_dry"] = dry.groupby("time.month").mean()
        out["pr_year_sdii"] = d["pr"].where(d["pr"] >= bu.THRESH_PR).groupby("time.year").mean()
        scal["frac_pr_negative"] = (d["pr"] < 0).mean()
        scal["frac_pr_below_m0.01"] = (d["pr"] < -0.01).mean()
    if "dtr" in d:
        scal["frac_tasmin_gt_tasmax"] = (d["dtr"] < 0).mean()
    with ProgressBar():
        out, pts, scal = dask.compute(out, pts, scal)
    ds = xr.Dataset({k: v.astype("float32") for k, v in out.items()}).assign_coords(q=QUANTILES)
    for v, p in pts.items():
        a = p.values.ravel()
        a = a[np.isfinite(a)]
        ds[f"{v}_q"] = ("q", np.quantile(a, QUANTILES).astype("float32"))
        if v == "pr":
            ds["pr_q_wet"] = ("q", np.quantile(a[a >= bu.THRESH_PR], QUANTILES).astype("float32"))
            attrs["pooled_dry_frac"] = float((a < bu.THRESH_PR).mean())
    ds.attrs = {**attrs, **{k: float(val) for k, val in scal.items()}}
    if path is not None:
        ds.to_netcdf(path)
    return ds


def regrid_stats(ds, grid, path=None, overwrite=False):
    """Conservative regridding of the gridded statistics onto `grid` (pooled quantiles copied unchanged)."""
    if path is not None and path.exists() and not overwrite:
        return xr.open_dataset(path).load()
    out = xr.Dataset({k: bu.regrid_conservative(v, grid.lat.values, grid.lon.values).compute()
                      for k, v in ds.data_vars.items() if {"lat", "lon"} <= set(v.dims)})
    out = out.assign_coords(q=ds.q) if "q" in ds.coords else out
    for k, v in ds.data_vars.items():
        if "q" in v.dims:
            out[k] = v
    out.attrs = ds.attrs
    if path is not None:
        out.to_netcdf(path)
    return out


# --------------------------------------------------------------------------
# climatologies, differences, scores
# --------------------------------------------------------------------------
def has(ds, v, kind="year_mean"):
    return ds is not None and f"{v}_{kind}" in ds


def seas(ds, v, season, kind="mean"):
    """Climatology: 'ANN' from the yearly means, seasons from the monthly climatology. kind: 'mean', 'ext', 'dry', 'sdii'."""
    if kind == "ext":
        return ds[f"{v}_year_ext"].mean("year")
    if kind == "dry":
        return ds["pr_year_dry"].mean("year") if season == "ANN" else ds["pr_month_dry"].sel(month=SEASONS[season]).mean("month")
    if kind == "sdii":
        return ds["pr_year_sdii"].mean("year")
    if season == "ANN":
        return ds[f"{v}_year_mean"].mean("year")
    return ds[f"{v}_clim_month"].sel(month=SEASONS[season]).mean("month")


def yearly(ds, v, kind="mean"):
    return {"mean": ds[f"{v}_year_mean"] if f"{v}_year_mean" in ds else None,
            "ext": ds.get(f"{v}_year_ext"), "dry": ds.get("pr_year_dry"), "sdii": ds.get("pr_year_sdii")}[kind]


def welch_sig(a, b, t_crit=2.0):
    """|Welch t| > t_crit on yearly values (dim 'year'). Serial correlation ignored: indicative only."""
    a, b = a.dropna("year", how="all"), b.dropna("year", how="all")
    se = np.sqrt(a.var("year", ddof=1) / a.sizes["year"] + b.var("year", ddof=1) / b.sizes["year"])
    return np.abs(a.mean("year") - b.mean("year")) / se > t_crit


def diff(a, b, v):
    """a - b; relative (%) for pr (masked where b < 0.1 mm/day)."""
    return (100 * (a - b) / b).where(b > 0.1) if v == "pr" else a - b


def dlabel(v):
    return "%" if v == "pr" else UNITS[v]


def scores(x, ref):
    """Area-weighted scores of the field x against ref over the domain (same grid): bias, RMSE, correlation, sd ratio."""
    m = mask_for(ref) & x.notnull() & ref.notnull()
    w = (np.cos(np.deg2rad(ref.lat)) * xr.ones_like(ref)).where(m)
    ws = float(w.sum())
    xs, rs = x.where(m), ref.where(m)
    mx, mr = float((w * xs).sum()) / ws, float((w * rs).sum()) / ws
    vx = float((w * (xs - mx) ** 2).sum()) / ws
    vr = float((w * (rs - mr) ** 2).sum()) / ws
    cov = float((w * (xs - mx) * (rs - mr)).sum()) / ws
    return {"bias": mx - mr, "RMSE": float(np.sqrt(float((w * (xs - rs) ** 2).sum()) / ws)),
            "corr": cov / np.sqrt(vx * vr) if vx > 0 and vr > 0 else np.nan,
            "sd ratio": np.sqrt(vx / vr) if vr > 0 else np.nan}


def regression(x, y):
    """Area-weighted regression y = a + slope * x over the domain (same grid): slope, correlation, mean ratio."""
    m = mask_for(x) & x.notnull() & y.notnull()
    w = (np.cos(np.deg2rad(x.lat)) * xr.ones_like(x)).where(m)
    ws = float(w.sum())
    xs, ys = x.where(m), y.where(m)
    mx, my = float((w * xs).sum()) / ws, float((w * ys).sum()) / ws
    vx = float((w * (xs - mx) ** 2).sum()) / ws
    vy = float((w * (ys - my) ** 2).sum()) / ws
    cov = float((w * (xs - mx) * (ys - my)).sum()) / ws
    return {"slope": cov / vx if vx > 0 else np.nan, "corr": cov / np.sqrt(vx * vy) if vx > 0 and vy > 0 else np.nan,
            "mean raw": mx, "mean downscaled": my, "mean ratio": my / mx if mx != 0 else np.nan}


# --------------------------------------------------------------------------
# maps
# --------------------------------------------------------------------------
def map_axes(nr, nc, w=5.0, h=2.7):
    kw = {"subplot_kw": {"projection": STATE["proj"]}} if STATE["proj"] is not None else {}
    fig, axes = plt.subplots(nr, nc, figsize=(w * nc, h * nr), squeeze=False, **kw)
    return fig, axes


def clim_lim(da, v):
    return (0, float(np.nanpercentile(da.where(mask_for(da)), 98))) if v in ("pr", "rsds") else None


def draw(ax, da, title, cmap="viridis", lim=None, sym=False, sig=None, label="", extent=None):
    """Map of `da` over the domain (grey outside), optional significance dots, coastlines; extent = (lon0, lon1, lat0, lat1)."""
    m = mask_for(da)
    da = da.where(m)
    if sig is not None:
        sig = sig & m
    if extent is not None:
        da = da.sel(lon=slice(extent[0], extent[1]), lat=slice(extent[2], extent[3]))
        sig = None if sig is None else sig.sel(lon=slice(extent[0], extent[1]), lat=slice(extent[2], extent[3]))
    ax.set_facecolor("0.85")
    if sym:
        lim = lim or float(np.nanpercentile(np.abs(da.values), 98)) or 1.0
        vmin, vmax = -lim, lim
    else:
        vmin, vmax = (None, None) if lim is None else lim
    kw = {"transform": STATE["proj"]} if STATE["proj"] is not None else {}
    im = ax.pcolormesh(da.lon, da.lat, da, shading="auto", cmap=cmap, vmin=vmin, vmax=vmax, **kw)
    if sig is not None:
        ax.contourf(sig.lon, sig.lat, sig.astype(float), levels=[0.5, 1.5], hatches=["...."], colors="none", **kw)
    if STATE["borders"]:
        bu.draw_borders(ax, STATE["borders"], transform=STATE["proj"])
    if extent is not None:
        ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
    ax.set_title(title, fontsize=9)
    plt.colorbar(im, ax=ax, shrink=0.8, label=label)
    return lim
