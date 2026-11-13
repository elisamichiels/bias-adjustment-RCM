#!/bin/bash
# setup_env.sh - conda (micromamba) environment ~/envs/guido for running a copy of Guido's downscaling scripts outside
# Condor: the tools of his "droughta" environment (CDO, NCO, ncdump, python, R with the packages his R scripts load)
# plus the small utilities his params.sh expects in the same bin folder (awk, column, tail, bc).
# R packages: those called by his R scripts (library / :: in R_scripts, checked 13 Nov 2026): terra, tidyverse (dplyr,
# purrr, stringr, lubridate), glue, ncdf4, irlba, sf, ggspatial, scico, rnaturalearth, patchwork, ragg, factoextra,
# PCICt; from CRAN: mhsmm (HSMM of the analogue block) and climdex.pcic (ETCCDI), optional for blocks 1-2.
# ClimDown is NOT needed (none of his scripts loads it; not available for R 4.5 anyway).
# Re-running it on an existing environment only adds what is missing.
# Usage (JEO-desk terminal):  nohup bash ~/downscaling/guido_pipeline/setup_env.sh > ~/setup_env.log 2>&1 < /dev/null &
set -euo pipefail
ENV=$HOME/envs/guido
MM=$HOME/bin/micromamba; [ -x "$MM" ] || MM=micromamba
PKGS="cdo nco libnetcdf python bc gawk r-base r-terra r-tidyverse r-ncdf4 r-irlba r-glue r-sf r-ggspatial r-scico
      r-rnaturalearth r-patchwork r-ragg r-factoextra r-pcict"
if [ -d "$ENV/conda-meta" ]; then
    "$MM" install -y -p "$ENV" -c conda-forge $PKGS
else
    "$MM" create -y -p "$ENV" -c conda-forge $PKGS
fi
# CRAN packages without a conda-forge build (blocks 3 and ETCCDI; a failure does not stop blocks 1-2)
"$ENV/bin/Rscript" -e 'for (p in c("mhsmm", "climdex.pcic")) if (!requireNamespace(p, quietly = TRUE))
    tryCatch(install.packages(p, repos = "https://cloud.r-project.org"), error = function(e) message(p, ": ", conditionMessage(e)))' || true
# utilities called through PATH_CONDA in params.sh: link the system ones when the environment has none
for t in awk column tail bc; do
    [ -x "$ENV/bin/$t" ] || ln -sf "$(command -v $t)" "$ENV/bin/$t"
done
"$ENV/bin/cdo" --version 2>&1 | head -1
"$ENV/bin/Rscript" -e 'for (p in c("terra", "tidyverse", "lubridate", "glue", "ncdf4", "irlba", "patchwork", "ragg", "mhsmm", "climdex.pcic"))
    cat(p, if (requireNamespace(p, quietly = TRUE)) as.character(packageVersion(p)) else "MISSING", "\n")'
echo ENV_DONE
