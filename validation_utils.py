"""
validation_utils.py - helpers shared by the validation / verification notebooks (plan_B/3_validations, GCM_BA/4_verification).

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
        try:                                  # da on a part of the mask's grid (region of the GCM bias adjustment)
            return bu.sub_to(m, da)
        except KeyError:
            pass
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


def _cached(path, overwrite, label, build):
    """Read `path` if it exists (and not overwrite), otherwise compute build() (a lazy Dataset) and write it."""
    if path is not None and path.exists() and not overwrite:
        return xr.open_dataset(path).load()
    print(f"-> computing {label}")
    with ProgressBar():
        ds = build().compute()
    if path is not None:
        ds.to_netcdf(path)
    return ds


def monthly_quantiles(d, path=None, overwrite=False, qs=(0.5, 0.9, 0.99), chunks_space=None, label=""):
    """Per-pixel quantiles of each calendar month (pr: wet days >= THRESH_PR only), dims (month, quantile, lat, lon).
    QDM is trained per month and per pixel: in calibration the adjusted run should reproduce these quantiles of ERA5."""
    cs = chunks_space or {"lat": 32, "lon": 64}

    def build():
        out = {}
        for v, x in d.items():
            x = x.where(x >= bu.THRESH_PR) if v == "pr" else x
            out[v] = x.chunk({"time": -1, **cs}).groupby("time.month").quantile(list(qs), dim="time")
        return xr.Dataset(out)
    return _cached(path, overwrite, f"the monthly quantiles of {label or path}", build)


def daily_climatology(d, path=None, overwrite=False, label=""):
    """Per-pixel mean annual cycle, one value per day of the year ('noleap': 365 days)."""
    return _cached(path, overwrite, f"the daily climatology of {label or path}",
                   lambda: xr.Dataset({v: x.groupby("time.dayofyear").mean() for v, x in d.items()}))


MONTH_START = np.cumsum([0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30])   # index of the 1st day of each month ('noleap')


def month_steps(corr, n=5):
    """
    corr: daily climatology of a correction (dayofyear, lat, lon). Step at each change of month (12 boundaries, Dec -> Jan
    included): mean of the n first days of the new month minus mean of the n last days of the old one. Reference: the
    same between two consecutive n-day blocks inside the months (days 6-10 -> 11-15 and 16-20 -> 21-25).
    Returns (steps at the boundaries (boundary, lat, lon), steps inside the months (block, lat, lon)).
    """
    c = corr.transpose("dayofyear", "lat", "lon").values
    ends = np.r_[MONTH_START[1:], 365]
    at = [c[MONTH_START[(m + 1) % 12]:MONTH_START[(m + 1) % 12] + n].mean(0) - c[ends[m] - n:ends[m]].mean(0)
          for m in range(12)]
    inside = [c[s + a + n:s + a + 2 * n].mean(0) - c[s + a:s + a + n].mean(0) for s in MONTH_START for a in (5, 15)]
    mk = lambda arr, dim: xr.DataArray(np.array(arr), dims=(dim, "lat", "lon"),
                                       coords={dim: np.arange(len(arr)), "lat": corr.lat, "lon": corr.lon})
    return mk(at, "boundary"), mk(inside, "block")


def pr_amplification(adj, raw, path=None, overwrite=False, wet=1.0, big=5.0, label=""):
    """Per pixel, over the wet days of the raw run (>= `wet` mm/day): number of wet days, share multiplied by more
    than `big` by the adjustment (%), largest factor, largest raw and adjusted values."""
    def build():
        isw = raw >= wet
        ratio = (adj / raw).where(isw)
        n = isw.sum("time")
        return xr.Dataset({"n_wet": n, "frac_big": 100 * (ratio > big).sum("time") / n.where(n > 0),
                           "max_factor": ratio.max("time"), "raw_max": raw.max("time"), "adj_max": adj.max("time")})
    return _cached(path, overwrite, f"the pr amplification of {label or path}", build)


ORDER_STATS = ["inv_below", "inv_across", "inv_above", "max_drop_across", "max_drop", "n_above", "n_pairs"]


def _order_stats(raw, adj, hq, wet, tol):
    """raw, adj (..., time); hq (...). Days sorted by raw value (wet days only); an inversion is a drop of the adjusted
    value larger than tol between two consecutive days (raw strictly increasing)."""
    raw = np.where(raw >= wet, raw, np.nan)
    idx = np.argsort(raw, axis=-1)                                          # NaN (dry days) at the end
    r = np.take_along_axis(raw, idx, axis=-1)
    a = np.take_along_axis(adj, idx, axis=-1)
    r0, r1, a0, a1 = r[..., :-1], r[..., 1:], a[..., :-1], a[..., 1:]
    pair = np.isfinite(r0) & np.isfinite(r1) & np.isfinite(a0) & np.isfinite(a1) & (r1 > r0)
    drop = np.where(pair, a0 - a1, 0.0)
    inv = pair & (drop > tol)
    h = hq[..., None]
    across = inv & (r0 <= h) & (r1 > h)
    out = [(inv & (r1 <= h)).sum(-1), across.sum(-1), (inv & (r0 > h)).sum(-1),
           np.where(across, drop, 0.0).max(-1), np.where(inv, drop, 0.0).max(-1), (r > h).sum(-1), pair.sum(-1)]
    return np.stack([np.asarray(o, dtype="float32") for o in out], axis=-1)


def pr_order(adj, raw, hq, path=None, overwrite=False, wet=None, tol=0.01, chunks_space=None, label=""):
    """
    Is the order of the wet days kept by the adjustment? Per pixel and calendar month, the wet days of the raw run
    (>= wet, default THRESH_PR) are sorted by raw value; a drop of the adjusted value (> tol mm/day) between two
    consecutive days is an inversion. Counted below the model's last historical quantile hq (hq = hist_q of the last
    quantile, dims (month, lat, lon): QDM itself), across hq (switch to the additive correction) and above hq; largest
    drop across hq and overall (mm/day); number of days above hq; number of pairs compared.
    """
    wet = bu.THRESH_PR if wet is None else wet
    cs = chunks_space or {"lat": 32, "lon": 64}

    def build():
        parts = []
        for m in range(1, 13):
            sel = lambda x: x.isel(time=np.flatnonzero(x.time.dt.month.values == m)).chunk({"time": -1, **cs})
            r, a = sel(raw), sel(adj).assign_coords(time=sel(raw).time)
            h = hq.sel(month=m, drop=True).assign_coords(lat=r.lat, lon=r.lon).chunk(cs)
            st = xr.apply_ufunc(_order_stats, r, a, h, kwargs={"wet": wet, "tol": tol},
                                input_core_dims=[["time"], ["time"], []], output_core_dims=[["stat"]],
                                dask="parallelized", output_dtypes=["float32"],
                                dask_gufunc_kwargs={"output_sizes": {"stat": len(ORDER_STATS)}})
            parts.append(st.assign_coords(stat=ORDER_STATS))
        st = xr.concat(parts, dim="month").assign_coords(month=np.arange(1, 13))
        return st.to_dataset(dim="stat")
    return _cached(path, overwrite, f"the order of the wet days of {label or path}", build)


def land_stats(da, q=95):
    """Area-weighted mean and (unweighted) q-th percentile of da over the domain."""
    m = mask_for(da)
    vals = da.where(m).values
    return float(dmean(da)), float(np.nanpercentile(vals[np.isfinite(vals)], q))


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
            "sd ratio": np.sqrt(vx / vr) if vr > 0 else np.nan, "sd diff": np.sqrt(vx) - np.sqrt(vr)}


def scores_no_pairing(x, ref):
    """
    Components of the RMSE that do not need any correspondence between x and ref (RMSE^2 = bias^2 + (sd_x - sd_ref)^2
    + 2 sd_x sd_ref (1 - r)): mean bias and spatial variability (sd ratio, sd difference). Used against ERA5, as the
    analogue downscaling is not paired with ERA5; RMSE and r are kept for downscaled vs raw.
    """
    sc = scores(x, ref)
    return {"bias": sc["bias"], "sd ratio": sc["sd ratio"], "sd diff": sc["sd diff"]}


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
