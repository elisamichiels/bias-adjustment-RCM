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

## What the pipeline does (read in Guido's scripts, 12 Nov 2026)

- **Inputs** are prepared before the pipeline (`_create_skeletons_files/create_skeleton*.sh`) and copied into
  `<run>/data/europe/`: the variable of the reference, the GCM (historical + SSP, already cut), the MSLP anomaly of the
  reanalysis and of the GCM. `DOMAIN="europe"` is only the name of that folder.
- **Box**: `cdo sellonlatbox,-25.5,50,23,72.5` for the variables and the MSLP of reanalysis and GCM (the EFAS / CERRA
  domain; the pressure is not taken over a wider Euro-Atlantic sector). `pca.R` fills the missing values at the edges
  of the CERRA domain (Lambert grid remapped to the lat/lon box, `setmisstodis,4`); ERA5 and EC-Earth3 cover the box.
- **MSLP anomaly**: daily mean, 365-day calendar without 29 Feb, `cdo ymonsub` of the monthly climatology of the
  calibration period (1985-2014), computed on each dataset itself (the GCM anomaly averages 0 Pa over 1985-2014,
  -23 Pa over 2070-2099: the future change of the pressure stays in the anomaly). A daily climatology (`ydaymean`) was
  created on 8 Nov 2026 in `CERRA/mslp/`: to ask.
  For us: ERA5 and EC-Earth3 historical against their own 1981-2014 monthly climatology; the GCM runs against the
  EC-Earth3 historical climatology (so that the 2025 / hosing changes of the circulation stay in the anomaly).
- **Regime episodes** (HSMM, 8 regimes, CERRA 1985-2014, `CERRA/mslp/durata_clusters_cerra_1985_2014.csv`): 1351
  episodes, median 6 days, mean 8, 75 % <= 10, 90 % <= 17, max 47. The rerank of the analogues sets the order of the
  days within about a week; the order between episodes comes from the step before (QDM or MBCn).
- **`REMAP` / `GRID_GCM`**: the reference is remapped onto the grid of the model (the model file is the template) in
  the climate imprint, in the DQM at model resolution (`climate_detrended_*`) and in the analogue search
  (`climate_analogs_condor_v1.sh`); the MSLP is remapped before the PCA. In step 2 the model (RCM) is on the 0.25 grid
  of the reference, so these remappings become identities: the climate imprint can be skipped. The analogue search
  would then run at 0.25 deg (much heavier than at the GCM grid).
