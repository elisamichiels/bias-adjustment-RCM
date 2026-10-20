"""
f1_downscaler.py - TO BE COMPLETED with the supervisor's analogue-based downscaling method.

No method is written here. Only the CONTRACT (inputs / outputs) is fixed, so that the notebooks
step1 (training) and step2 (application) work without modification.

No WDF, no QDM, no regridding: the analogue method does not require day-by-day consistency
between EC-Earth3 and ERA5.

Data convention
  - dict {'pr', 'tasmax', 'tasmin'} -> xarray.DataArray (time, lat, lon)
  - pr in mm/day, temperatures in degC, ascending lat, lon in [-180, 180)
"""


def train_f1(gcm_hist, era5, outdir, **kwargs):
    """
    Learn F1: EC-Earth3 historical (native resolution) -> ERA5 0.25 deg.

    gcm_hist : dict of DataArrays, EC-Earth3 historical at native resolution (~0.7 deg), Europe + small margin
    era5     : dict of DataArrays, ERA5 0.25 deg (Europe)
               (both cover the same training period but are NOT paired day by day)
    outdir   : pathlib.Path where to write what was learned (analogue library, parameters, ...)

    To do: train and save into `outdir`. Returns nothing.
    """
    raise NotImplementedError("train_f1: analogue-based downscaling method to be provided (supervisor).")


def apply_f1(gcm_sim, outdir, target_lat, target_lon, **kwargs):
    """
    Apply F1 to a GCM run (native resolution) to obtain an 'ERA5-like' 0.25 deg field.

    gcm_sim : dict {'pr','tasmax','tasmin'} of DataArrays, native GCM (Europe + margin)
    outdir  : folder of what was learned by train_f1
    target_lat, target_lon : coordinates of the ERA5 0.25 deg grid (Europe) to produce

    Returns: dict {'pr','tasmax','tasmin'} of DataArrays (time, lat, lon) on the target grid.
    """
    raise NotImplementedError("apply_f1: analogue-based downscaling method to be provided (supervisor).")
