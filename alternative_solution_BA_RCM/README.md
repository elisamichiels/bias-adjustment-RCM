# Alternative solution for the bias adjustment of the RCM

Alternative to the supervisor's downscaling pipeline (BCCAQv2, run in its own repository) for the reference of the
RCM bias adjustment. Proposed in November 2026. Notebook 1 runs as soon as F1 is done; notebooks 2-4 need the RCM
runs in the config (notebook 00).

| notebook | what | needs |
|---|---|---|
| `1_reference_quantiles/reference_quantiles` | ERA5 0.25 deg extract (EFAS domain + 1 deg, 1981-2014), reference quantiles (`bu.reference_quantiles`) | ERA5, F1 product of `gcm_2025_nohosing` |
| `2_F2_calculation/F2_calculation` | F2 = QDM of `rcm_2025_nohosing` towards the reference (`bu.fit_F2`), in-sample check | RCM on the ERA5 0.25 deg grid |
| `3_F2_application/F2_application` | F2 applied to the four RCM runs (`bu.apply_F`, the code of F1), European land kept | F2 |
| `4_verification/F2_verification` | calibration against the reference, hosing signal kept, day-to-day structure kept | products |

Outputs in `<gcm_ba_root>/../RCM_BA_alternative/` (`bu.alt_dir`). The reference covers the years of the RCM calibration
run (all the years of the F1 product as long as the RCM is not in the config): rerun notebook 1 once the RCM arrives.
If the RCM grid is not the ERA5 0.25 deg grid, notebook 2 stops: the reference (or the RCM) must then be regridded.

1. **F1** (done, `GCM_BA/`): WDF + QDM of EC-Earth3 towards ERA5 regridded to the EC-Earth3 0.7 deg grid (calibration
   historical 1981-2014), applied to EC-Earth3 2025 no hosing -> GCM_2025_nohosing ERA5-like at 0.7 deg.
2. **Reference at 0.25 deg** (BCSD principle): for each pixel, month m and quantile τ,
   Q_ref = Q_ERA5,0.25(pixel) + I[Q_F1(cell) - Q_ERA5,0.7(cell)], I = interpolation from the 0.7 deg cells to the
   0.25 deg pixels; ratios (interpolated in log) for pr wet days and DTR. The RCM does not enter the reference.
3. **F2**: QDM of RCM 2025 no hosing towards Q_ref, applied unchanged to the four RCM runs, each ranked in its own
   distribution. pr: dry-day frequency first (gap of the dry-day fraction at the pixel), then the wet-day ratios
   (ISIMIP3BASD principle, Lange 2019).

Window: the 3 months centred on m, applied to the days of m, in the three steps (as in F1).

The RCM keeps its own day-to-day sequence and spatial structure (they carry the AMOC effect): the correction acts on
the distributions of each pixel only. Checks planned: the dependence diagnostics (temporal, spatial, inter-variable;
VALUE framework, Maraun et al. 2015) of ERA5 / raw / adjusted, as for F1.
