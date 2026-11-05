# Alternative solution for the bias adjustment of the RCM

Alternative to the supervisor's downscaling pipeline (BCCAQv2, run in its own repository) for the reference of the
RCM bias adjustment. Proposed in November 2026, not implemented yet: waiting for the decision and for the RCM runs.

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
