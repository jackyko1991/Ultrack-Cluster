# Ultrack-Cluster

Distributed [Ultrack](https://github.com/royerlab/ultrack) tracking on a SLURM cluster: candidate segmentation and linking run as job arrays, the integer linear program is solved in overlapping time windows, and a PostgreSQL server started as a cluster job coordinates them. Written for BMRC (University of Oxford); partitions, accounts and licence paths are environment variables, so it adapts to other SLURM sites.

It is used as the Ultrack node of [pyCyto](https://github.com/bpi-oxford/Cytotoxicity-Pipeline), which vendors it as a subtree.

## Requirements
- SLURM, and [pixi](https://pixi.sh) on the login node.
- A [Gurobi](https://www.gurobi.com/) licence (academic site licence). Without one ultrack silently falls back to the much slower CBC solver, so the solve stage stops instead unless `ULTRACK_ALLOW_CBC=1`.

## Install
```bash
git clone https://github.com/jackyko1991/Ultrack-Cluster.git
cd Ultrack-Cluster
pixi install                 # default: ultrack 0.8, PostgreSQL 16, dasel, Gurobi, CPU torch
pixi install -e gpu          # only for GPU segmentation
pixi run -e test test        # optional: test suite
```

## Quick start
```bash
cd tracking
export ULTRACK_PIXI_ENV=default            # each job activates this environment itself
export ULTRACK_DB_PW="$(openssl rand -base64 18)"
LABEL_SOURCE='/data/exp.zarr#labels/Cellpose/Nuclei' \
CFG_FILE=$PWD/config.toml JOB_NAME=exp01 \
BEGIN_TIME=0 END_TIME=99 \
SKIP_SEG=false SKIP_LINK=false \
SHORT_PARTITION=short LONG_PARTITION=long \
bash main.sh
```
`main.sh` submits the whole job graph (database, segment, link, solve, export, clean-up) and returns. Tracks are written to `results/<JOB_NAME>/tracks.csv` and `segments.zarr`; logs, a per-job resource report and the list of submitted jobs to `slurm_output/<JOB_NAME>/`.

`SKIP_SEG` and `SKIP_LINK` default to `true`, which resumes from an existing database; set both to `false` for a new run.

## Documentation
| Page | Contents |
|---|---|
| [Installation and environments](docs/installation.md) | pixi environments, GPU, Apptainer image, other activation options, disk and caches |
| [Running](docs/running.md) | job graph, every `main.sh` setting, label input, resources, resuming, the database server |
| [Solver settings](docs/solver.md) | ILP size, Gurobi LP method for large windows |
| [Manual run](docs/manual-run.md) | submitting stages one by one, useful SLURM commands |
| [FAQ](docs/faq.md) | reusing the database, schema, PostgreSQL vs SQLite |
