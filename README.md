# Ultrack-Cluster
BMRC cluster run test script for [Ultrack](https://github.com/royerlab/ultrack)

## Brief Intro

This version of distributed running is not available on pypi yet. Users may install the nightly code until the next release: 

```bash
# TODO: update to conda env.yml + requirements.txt install
$ mamba create -n ultrack python=3.10
$ mamba activate ultrack
$ pip install -r requirements.txt

# if pip exceed system tmp size
$ TMPDIR=~/work/tmp pip install -r requirements.txt
```

This repository contains essential SLURM scripts that calls ultrack CLI run. The files are equivalent to `segment`, `link` and `solve` function in the ultrack Python API.

Details are modified to fit the BMRC SLURM and infrastructure setup. It provides a reference code for cluster run modification.

### Gurobi License
Ultrack solves linear programming with [Gurobi](https://www.gurobi.com/). For university clusters you may consult the administration team for the [Academic Site License](https://www.gurobi.com/features/academic-site-license/) installation.

ultrack reaches Gurobi through python-mip, which needs `GRB_LICENSE_FILE` and otherwise silently falls back to the much slower CBC solver. `solve.sh` sets it to BMRC's token-server license (`/gpfs3/apps/eb/licenses/gurobi.lic`) automatically; point it elsewhere with `ULTRACK_GUROBI_LICENSE=<file>`. (The old `module load Gurobi/10.0.1-GCCcore-12.2.0` no longer exists on BMRC.)

### Runtime Environment
Each job activates its environment itself, so nothing needs to be active in the shell that runs `main.sh`. Pick one (first match wins):

| Variable | Effect |
|---|---|
| `ULTRACK_SIF=/path/ultrack-cluster.sif` | Run ultrack/python/PostgreSQL inside an Apptainer image built from [`containers/ultrack-cluster.def`](./containers/ultrack-cluster.def) (`apptainer build --fakeroot ultrack-cluster.sif containers/ultrack-cluster.def`). Bind mounts default to `/gpfs3`, `/well`, `/users`; override with `ULTRACK_SIF_ARGS`. |
| `ULTRACK_ENV_ACTIVATE=/path/bin/activate` | Source this file (e.g. a venv). |
| `ULTRACK_PIXI_ENV=<env>` | Activate an environment of this repo's [`pixi.toml`](./pixi.toml) (`pixi shell-hook`; manifest overridable with `ULTRACK_PIXI_MANIFEST`). `default` = CPU, `gpu` = CUDA; see [GPU](#gpu). Install first with `pixi install -e <env>`. |
| `ULTRACK_CONDA_ENV=<prefix or name>` | Activate this conda env (a prefix directory is just put first on `PATH`). |
| *(none)* | Legacy behaviour: `source ~/.bashrc; mamba activate cyto`. |

### Environments and GPU
<a id="gpu"></a>
`pixi.toml` defines separate environments so CPU stages never pull CUDA libraries:

| Env | Contents | Use |
|---|---|---|
| `default` | ultrack 0.8, PostgreSQL, dasel, gurobipy, **CPU** torch | every stage in this repo |
| `gpu` | as `default`, but CUDA torch + cupy + cucim | segment jobs that do GPU work |
| `test` | `default` + pytest | `pixi run -e test test` |

**Does segment need a GPU?** Not in this repo. `segment.py` turns labels into foreground/contours
(`labels_to_edges`) and builds hierarchies (`segment()`, higra, CPU only), so segment tasks request no
GPU by default. ultrack uses the GPU in two places, and only if the environment has it:
- `labels_to_edges`/`labels_to_contours` switch to cupy + cucim when cupy imports and CUDA is available (optional speed-up);
- `ultrack.imgproc` (optical flow, SAM, PlantSeg) needs CUDA torch. A pipeline that makes foreground/contours
  from raw images with these models belongs in a GPU segment job.

To run segment on GPUs: `SEG_GPUS=1 ULTRACK_PIXI_ENV=default bash main.sh`. Segment tasks then go to
`GPU_PARTITION` (default `gpu_short`) with `--gres gpu:$SEG_GPUS` and switch to `SEG_PIXI_ENV` (default `gpu`);
DB, link, solve and export stay on the CPU env. With `ULTRACK_SIF`, `run_ultrack` adds `--nv` on GPU
allocations, but the image must contain cupy/CUDA torch (the current `containers/ultrack-cluster.def`
does not). With conda/venv activation, main.sh only warns: that env must have cupy itself.

Why torch is pinned: ultrack 0.8 requires torch, and pip installs the CUDA build by default (~4 GB of
`nvidia-*` wheels). `default`/`test` take the conda-forge CPU build instead.

**Disk:** install into the workspace, not `~/.pixi/detached-envs` (on /home), and keep caches off /home, e.g.
`RATTLER_CACHE_DIR=/mnt/RAID/.cache/rattler UV_CACHE_DIR=/mnt/RAID/.cache/uv pixi install`, with
`detached-environments = false` in `.pixi/config.toml`.

### Label Input
`LABEL_SOURCE` (main.sh) / `-p` (segment.py) accepts either a TIFF glob, one 2D frame per file
(default `$DATA_DIR/*.tif`), or a Zarr URI in the pyCyto/tanoa convention:
`/data/exp.zarr#labels/Cellpose/TCell`, with `?c=<channel name or index>` for multi-channel stores.
Zarr v2 and v3 are supported, and so are plain arrays (time first) and OME-NGFF 0.4/0.5 multiscale groups (level 0).
A singleton Z axis is dropped. The frame count uses only the standard library (`python3 label_io.py frames <source>`),
so the login node's system Python is enough.

Segment batch 0 creates the DB tables, so main.sh submits it on its own (`segment-init`). The rest of the
array depends on it with `afterok`, and link depends on both.

### PostgreSQL Server Setup
Most cluster environment may not come with all necessary tools for the PostgreSQL server setup in [create_server.sh](./tracking/create_server.sh). For an automated software installation (script dedicated to BMRC folder structure but you may modify to fit your system's installation environment), edit `$INSTALL_DIR` in `install_server_dependency.sh` then run:
```bash
bash install_server_dependency.sh
source ~/.bashrc
```

### Environment Variable
You need a environment variable `$ULTRACK_DB_PW` used in the `create_server.sh`

### Quick Run
#### Data Perquisite
For convenience data IO, the segmentation file input is in zarr format. For quick data conversion from tiff format to zarr, check [tiff_to_zarr.py](./preprocess/tiff_to_zarr.py). Cluster run script is available in [tiff_to_zarr.sbatch](./preprocess/tiff_to_zarr.sbatch)

#### Folder Structures
It assumes the following directory structure, you can modify the file paths as you wish on the `main.sh`

```
root/
    segments.zarr  # boundary and detection maps
    tracking/
        config.toml
        main.sh
        create_server.sh
        ... # other .sh files
```

#### Automated Scripts
1. Change the working directory to `tracking`
2. Activate the global virtual environment
    ```bash
    mamba activate ultrack
    ```
2. In the `main.sh`, you must fill `DS_LENGTH`, `NUM_WINDOWS`, `LABEL_PATH_PATTERN` and `MAX_JOBS` variables. These files are used as a template in my workflow, and a Python script fills this information.

    For example, for a dataset with 225 time points and `window_size` of 50 (from the [`config.toml`](./tracking/config.toml)) we have:

    ``` bash
    DS_LENGTH = 224  # 225 - 1
    NUM_WINDOWS = 4  # ceil(225 / 50) - 1

    LABEL_PATH_PATTERN="/users/kir-fritzsche/oyk357/archive/utse_cyto/2023_10_17_Nyeso1HCT116_1G4CD8_icam_FR10s_0p1mlperh/roi/register_denoise_gamma_channel_merged_masks/tcell/*.tif"
    MAX_JOBS=100
    ```

    `MAX_JOBS` limited the simultaneous tasks for a job task. PostgreSQL only allow limited connection and we set the job count here. Possible to extend with PostgreSQL setting.
    
4. And then you execute `bash main.sh`. You must stop the database job once the tracking is done.
    ```bash
    # check running SLURM job ID
    $ squeue --me 
    # JOBID PARTITION     NAME     USER ST       TIME  NODES NODELIST(REASON)
    # 42037054     short DATABASE   oyk357  R       1:42      1 compe042

    # stop database node
    $ scancel 42037054
    ```

#### Manual Run
Check the file [manual_run.md](./manual_run.md)

## FAQ
1. **Can the label information in the SQL database being reused at different tracking stages?**

    Yes, within the original python script the data is initially transformed from labeled image format to SQL database for potential optimization at a later stage. This process may often take a very long time if the tracking scale is large. For extensive parameter grid search for the tracking parameter settings, users may employ the database server establishment script and subsequently share and reuse the intermediate results to reduce overall computation time.

    Users may only need to run staring from the tracking step that you have changed the parameter from the grid search. E.g. if you change a parameter from `config.linking_config` you can continue from the `ultrack link` step and `ultrack solve` for the `config.tracking_config` parameters. Because building the hierarchies (`ultrack segment`) is the first step, `config.segmentation_config`, it cannot be run from a partially computed database.

    The Ultrack CLI provides the `--overwrite` flag to clean the partial results before re-executing most steps. However, they don't work on distributed computing because not all jobs are executed simultaneously. The database would be cleaned for each job call with `--overwrite` flag. So you must use our helper command `ultrack clear_database -cfg config.toml <STAGE TO CLEAN (e.g. link)>` before executing the respective step.

2. **Is there any available documentation detailing the structure of the database and its associated Python interface for data retrieval?**
    
    [This](https://github.com/royerlab/ultrack/blob/main/ultrack/core/README.md) is the current documentation of the SQL schema implemented [here](https://github.com/royerlab/ultrack/blob/main/ultrack/core/database.py). We use [SQLAlchemy](https://www.sqlalchemy.org/) to interact with it in Python through the code base.

3. **In which circumstances PostgreSQL is recommended over SQLite for ultrack?**
    
    SQLite is used in default for everything in ultrack except for SLURM large dataset run for its simpleness and straightforward that works most of the time.

    However SQLite is not the most performant, and it fails when running several workers. If performance is a concern and don't mind spinning up a server, Postgres is a better option.
