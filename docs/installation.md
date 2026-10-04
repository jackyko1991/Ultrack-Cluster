# Installation and environments

## pixi environments
[`pixi.toml`](../pixi.toml) defines separate environments, so CPU stages never pull CUDA libraries:

| Env | Contents | Use |
|---|---|---|
| `default` | ultrack 0.8, PostgreSQL 16, dasel 2.8, gurobipy 11, **CPU** torch | every stage |
| `gpu` | as `default`, with CUDA torch, cupy and cucim | segment tasks that do GPU work |
| `test` | `default` + pytest | `pixi run -e test test` |

ultrack 0.8 requires torch, and pip installs the CUDA build by default (about 4 GB of `nvidia-*` wheels); `default` and `test` take the conda-forge CPU build instead.

PostgreSQL comes with the environment, so no system installation is needed. ([`tracking/install_server_dependency.sh`](../tracking/install_server_dependency.sh) builds it from source for setups without pixi.)

## How jobs activate their environment
Each job activates its runtime itself, so nothing needs to be active in the shell that runs `main.sh`. The first setting found wins:

| Variable | Effect |
|---|---|
| `ULTRACK_SIF=/path/ultrack-cluster.sif` | Run ultrack, python and PostgreSQL inside an Apptainer image built from [`containers/ultrack-cluster.def`](../containers/ultrack-cluster.def) (`apptainer build --fakeroot ultrack-cluster.sif containers/ultrack-cluster.def`). Bind mounts default to `/gpfs3`, `/well`, `/users`; override with `ULTRACK_SIF_ARGS`. |
| `ULTRACK_ENV_ACTIVATE=/path/bin/activate` | Source this file (e.g. a venv). |
| `ULTRACK_PIXI_ENV=<env>` | Activate an environment of this repository's `pixi.toml` (manifest overridable with `ULTRACK_PIXI_MANIFEST`). **Recommended.** |
| `ULTRACK_CONDA_ENV=<prefix or name>` | Activate this conda environment. |
| *(none)* | Legacy: `source ~/.bashrc; mamba activate cyto`. |

## GPU
Segmentation does not need a GPU: turning labels into foreground and contours and building the hierarchies runs on CPUs. ultrack uses a GPU only if the environment has it:
- contour preparation switches to cupy and cucim when they import and CUDA is available (a speed-up);
- `ultrack.imgproc` (optical flow, SAM, PlantSeg) needs CUDA torch; a pipeline that computes foreground and contours from raw images with these models belongs in a GPU segment job.

`SEG_GPUS=1` sends segment tasks to `GPU_PARTITION` (default `gpu_interactive`; on BMRC with `GPU_ACCOUNT=gpu_kir.prj`) with `--gres gpu:1`, switching them to `SEG_PIXI_ENV` (default `gpu`). The database, link, solve and export stay on the CPU environment. The Apptainer image does not contain cupy or CUDA torch.

## Gurobi licence
ultrack reaches Gurobi through python-mip, which needs `GRB_LICENSE_FILE`. `solve.sh` sets it to BMRC's token-server licence (`/gpfs3/apps/eb/licenses/gurobi.lic`); point it elsewhere with `ULTRACK_GUROBI_LICENSE=<file>`.

## Disk and caches
Install into the repository (`detached-environments = false` in `.pixi/config.toml`), not into `~/.pixi/detached-envs` on a small home volume, and keep caches on a large disk:
```bash
RATTLER_CACHE_DIR=/large/disk/.cache/rattler UV_CACHE_DIR=/large/disk/.cache/uv pixi install
```
[`requirements.txt`](../requirements.txt) is kept for a plain pip installation; it does not pin the versions the tests use.
