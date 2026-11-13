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

## Blocks 1 (climate imprint) and 2 (QDM), read in Guido's scripts (13 Nov 2026)

- **Block 1, `climate_imprint/climateImprint_condor.sh`**, one task per calendar day (MONTH DAY): daily climatology of
  the reference and of the GCM over CAL_START..CAL_END (`runmean,11` then `ydaymean`; the GCM uses CAL_START-1 and
  CAL_END+1 as buffer years if present), anomaly = GCM - its climatology, remapped (`REMAP`) onto the reference grid,
  added to the reference climatology (`sub` / `add` in the tasmax version: check the pr version, ratio expected).
  Then `climateMergetimeImprint` (all days in one file) and `climateQDMImprint` (one file per month extended by 15 days
  of the previous and next month).
- **Block 2, `climate_qdm/`**: `climateQDMDelta_condor.sh`, one task per (QDM_START QDM_END MONTH) from the task
  arguments: mp = CI output of QDM_START..QDM_END (the years corrected), mc = CI output of CAL_START..CAL_END, oc =
  reference of CAL_START..CAL_END (month +- 15 days, aligned with mc); delta factors in R
  (`quantile_delta_mapping_calculatefactors.R`); `climateQDMMergeDelta` merges them (expects exactly **108** files = 9
  periods x 12 months: to change), then the smoothing (`climate_smooth/`, not read yet), then
  `climateQDMApplyDelta_condor.sh` per (period, month) (`quantile_delta_mapping_applyfactors.R`), merge and postprocess.
- **Years**: only `selyear` on CAL_START/CAL_END (params.sh) and QDM_START/QDM_END (task arguments). No loop over
  continuous years: a GCM file historical 1981-2014 + run 2075-2124 works, no renumbering. For a stabilised run, one QDM
  window = the whole run (e.g. `2075 2124 MM`), which is QDM without the 30-year moving windows.
- **Inputs**: `${PATH_FILES}` must contain exactly **4** netCDF files (check in block 1): the reference variable
  (`${VARNAME}*${REANALYSIS}*.nc`), the GCM variable (`${VARNAME}*${MODEL}*.nc`, historical + run in one file) and the
  two MSLP anomaly files (not used by blocks 1-2: real or placeholder files, or edit the check). 365-day calendar
  (DEL29FEB TRUE), time 23:00.
- **GCM runs available** (`DROUGHTOBS/EC-Earth_hosing/stabilization-ssp585-{2025,2050}_{Original,Hosing}`): pr, psl,
  tasmax, tasmin (+ ta, ua, va, zg) daily, NH, 2075-2124 (2025) and 2100-2149 (2050).

## Running it ourselves: what we learnt (13 Nov 2026)

- **Run folders** are created by `_create_skeletons_files/create_skeleton.sh` from `downscaling.tar.gz` (template scripts
  with placeholders XXPARAMSXX / XXSCRIPTXX); the generated scripts carry absolute paths under
  `/eos/jeodpp/data/projects/DROUGHTATLAS/guido/downscaling/`, so a copy in our space needs a path rewrite.
- **Execution**: HTCondor jobs (docker, `sudo -u droughtatlasproc condor_submit`) with the conda environment
  `/mnt/jeoproc/envs/DROUGHTATLASPROC/anaconda3/envs/droughta` (CDO, R, Rscript, NCO). The user has no Condor access
  (groups: users, JEODPP_notebook); outside Condor each task is `script_run.sh <cluster> <process> <args>` and could be
  looped on JEO-lab, with our own CDO and an R with the packages of the R scripts.
- **QDM smoothing** (`climate_smooth/climateSmoothDelta.sh`): `runmean,11` along the merged delta series, then per month.
- **pr climate imprint is a different algorithm** (`climdown_cdo_pr_*/climate_imprint/climateImprint_condor.sh`):
  ratio anomaly (`cdo div`) to the climatology; for each GCM day the best-correlated low-resolution CERRA anomaly day
  within a 30-day block (whole field and NSPLIT x NSPLIT subgrids, Fisher z weighted by the anomaly); RSTAR = GCM anomaly
  / CERRA low-res anomaly, remapped (`remapcon`) to high resolution; pr = RSTAR x CERRA high-res anomaly x CERRA
  climatology; outlier mask > 5 x CERRA seasonal q90; hole filling in R. It uses precomputed CERRA seasonal climatology,
  q90 and wet-day probability (`CERRA/downscaling/{climatology,quantiles,pwet}`): ERA5 versions are needed. So the pr
  climate imprint already borrows the daily spatial pattern of a reanalysis day (an analogue-like step).

## Guido's documentation (book "CMIP6 Dowscaling", 16 Dec 2025, `DROUGHTATLAS/guido/downscaling/documentation/dowscaling/`)

- Two independent blocks: (1) `climate_imprint` -> `climate_qdm` (delta) -> `climate_smooth` -> `climate_qdm` (apply,
  postprocess, merge); (2) `climate_detrended_past/future` (DQM). Then `climate_pca` (PCA, HSMM, analogues, reranking)
  needs both. Blocks 1 alone give the climate imprint + QDM product (`qdm/merged/qdm_01_12_*.nc`).
- Block 1 submit order: imprint (365 jobs) -> [check_imprint: skip] -> mergetime_imprint (12) -> mergetime_monthly_imprint
  (1) -> qdm_imprint (12, extended months) -> qdm_delta (108 = periods x months) -> merge_delta (1) -> smooth_delta (12)
  -> qdm_applydelta (108) -> postprocess_qdm (12) -> mergetime_monthly_qdm (1). Integrity checks after each step
  (`check_missing_layers`, `check_delta_no_missing_layers.sh`, `check_applydelta_no_missing_layers.sh`); the R steps
  often produce files with empty layers, to regenerate.
- Memory: 8 GB per job, except qdm_delta / qdm_applydelta (R, pixel-wise) 100-460 GB at CERRA 5 km; at ERA5 0.25 deg
  (~25 times fewer pixels) roughly 4-20 GB.
- Environment: CDO (not the BDAP one), R with terra, tidyverse, sf, ggspatial, scico, rnaturalearth (the delta factors
  are computed with the R package ClimDown), ncdump, ncview, python. Condor: `sudo -u droughtatlasproc condor_submit`.
- The book covers tasmax, tasmin, tas (7 models x 3 SSPs); pr (its own climate imprint) is not documented.
