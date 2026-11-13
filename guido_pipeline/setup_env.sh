#!/bin/bash
# setup_env.sh - conda (micromamba) environment ~/envs/guido for running a copy of Guido's downscaling scripts outside
# Condor: the tools of his "droughta" environment (CDO, NCO, ncdump, R with the packages of his R scripts, python) plus
# the small utilities his params.sh expects in the same bin folder (awk, column, tail, bc).
# Usage (JEO-lab or JEO-desk terminal):  bash ~/downscaling/guido_pipeline/setup_env.sh > ~/setup_env.log 2>&1
set -euo pipefail
ENV=$HOME/envs/guido
MM=$HOME/bin/micromamba; [ -x "$MM" ] || MM=micromamba
"$MM" create -y -p "$ENV" -c conda-forge cdo nco libnetcdf python bc gawk \
    r-base r-terra r-tidyverse r-ncdf4 r-irlba r-glue r-sf r-ggspatial r-scico r-rnaturalearth r-remotes
# ClimDown (delta factors of the QDM, according to Guido's documentation): CRAN, installed inside the environment
"$ENV/bin/Rscript" -e 'if (!requireNamespace("ClimDown", quietly = TRUE)) install.packages("ClimDown", repos = "https://cloud.r-project.org")'
# utilities called through PATH_CONDA in params.sh: link the system ones when the environment has none
for t in awk column tail bc; do
    [ -x "$ENV/bin/$t" ] || ln -sf "$(command -v $t)" "$ENV/bin/$t"
done
"$ENV/bin/cdo" --version 2>&1 | head -1
"$ENV/bin/Rscript" -e 'for (p in c("terra", "tidyverse", "ncdf4", "ClimDown")) cat(p, as.character(packageVersion(p)), "\n")'
echo ENV_DONE
