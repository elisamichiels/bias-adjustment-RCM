"""
f2_downscaler.py (plan A) - TO BE COMPLETED with the supervisor's downscaling method.

No method is written here. Only the CONTRACT (inputs / outputs) is fixed, so that the notebooks
step3 (training) and step4 (application) work without modification.

Data convention
  - dict {'pr', 'tasmax', 'tasmin'} -> xarray.DataArray (time, lat, lon)
  - pr in mm/day, temperatures in degC, ascending lat, lon in [-180, 180)
"""


def train_f2(coarse, fine, outdir, **kwargs):
    """
    Learn F2 on ERA5 only (synchronised pairs, same day).

    coarse : dict of DataArrays, ERA5 regridded to 1 deg (global)   - downscaling input
    fine   : dict of DataArrays, raw ERA5 0.25 deg (global)         - downscaling target
    outdir : pathlib.Path where to write the learned model (weights, parameters, ...)

    To do: train and save into `outdir`. Returns nothing.
    """
    raise NotImplementedError("train_f2: downscaling method to be provided (supervisor).")


def apply_f2(coarse_sim, outdir, target_lat, target_lon, **kwargs):
    """
    Apply F2 to a 1 deg dataset (here: each GCM run 'ERA5-like' 1 deg, global).

    coarse_sim : dict {'pr','tasmax','tasmin'} of 1 deg DataArrays
    outdir     : folder of the model learned by train_f2
    target_lat, target_lon : coordinates of the global ERA5 0.25 deg grid to produce

    Returns: dict {'pr','tasmax','tasmin'} of DataArrays (time, lat, lon) on the target grid.
    """
    raise NotImplementedError("apply_f2: downscaling method to be provided (supervisor).")
