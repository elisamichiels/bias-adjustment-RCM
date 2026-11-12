# Supervisor's downscaling pipeline (Guido) for the RCM bias adjustment

Decided at the meeting with the supervisor (11 Nov 2026): the reference of the RCM bias adjustment is built with Guido's
pipeline (ClimDown / BCCAQv2, R scripts on EOS `DROUGHTATLAS/guido/downscaling`), run with ERA5 instead of CERRA.

- **Step 1**: EC-Earth3 historical (calibration 1981-2014) + `gcm_2025_nohosing` -> `GCM_2025_nohosing_ERA5like_0.25`:
  climate imprint + QDM + analogues, each variable separately (tasmax, DTR, pr); MBCn in place of the QDM only if the
  dependence test on the step-1 product fails.
- **Step 2**: each RCM run against `GCM_2025_nohosing_ERA5like_0.25`, without the climate imprint: QDM + analogues,
  with `rcm_2025_nohosing` as "historical" and each other run as "scenario".

Inputs prepared so far (EOS `DROUGHTOBS/elisa/GCM_downscaling/Input_data/`):
- `ERA5_daily_merged/*_ERA5_day_1981-2014.nc` (pr, tasmax, tasmin, dtr, rsds; cut from 1981-2020);
- `ERA5_daily/psl_ERA5_day_<year>.nc` (daily mean of the hourly msl, `prep_era5_daily.py` / CDO daymean, 1981-2014);
- `EC-Earth3_historical_CMIP6/psl_day_EC-Earth3_historical_r1i1p1f1_gr_*.nc` (`prep_ecearth3_psl_esgf.py`).

Trace of the pr jitter: 0.005 mm/day kept with ERA5 (test `GCM_BA/8_test_trace`, note `jitter.docx`).
