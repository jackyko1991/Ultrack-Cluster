# Running

## Job graph
`tracking/main.sh` submits one SLURM job per stage and returns:

| Stage | Job | Depends on |
|---|---|---|
| Database | `DATABASE_<job>`: PostgreSQL server (`create_server.sh`, or `resume_server.sh` when resuming) | — |
| Segment | `SEGMENT_<job>` array over frames; batch 0 runs alone first and creates the tables | database ready |
| Link | `LINK_<job>` array over the $T-1$ consecutive frame pairs | segment |
| Solve | `SOLVE_<job>` array over time windows: even windows first, then each odd window once its two neighbours finish | link |
| Export | `EXPORT_<job>`: `tracks.csv` and `segments.zarr` | solve |
| Clean-up | `CLEANUP_<job>`: stops the database and writes the resource report, whatever the outcome of export | export ends |

Workers wait for the database through `slurm_output/<job>/db_ready` rather than a fixed delay. A failed stage cancels the stages after it (`--kill-on-invalid-dep`), so export always ends and clean-up always runs.

## Settings
Every setting is an environment variable read by `main.sh`.

**Input and run**

| Variable | Default | Meaning |
|---|---|---|
| `LABEL_SOURCE` | `$DATA_DIR/*.tif` | Label series: TIFF glob or Zarr URI (below) |
| `CFG_FILE` | `config_binning_$BATCH.toml` | Ultrack configuration ([example](../tracking/config.toml)); gets the database address written into it |
| `JOB_NAME` | derived | Names the jobs, `slurm_output/<JOB_NAME>/` and `results/<JOB_NAME>/` |
| `BEGIN_TIME`, `END_TIME` | from `BATCH` | First and last frame, 0-based and inclusive; take precedence over `BATCH`, `BATCH_SIZE`, `POST_PADDING` |
| `BINNING` | 1 | Track every n-th frame |
| `SKIP_SEG`, `SKIP_LINK` | `true` | Reuse candidates and links already in the database; `false` for a new run |
| `ULTRACK_DB_PW` | `ultrack_pw` | Database password for this run; set a random one |

**Cluster and resources**

| Variable | Default | Meaning |
|---|---|---|
| `SHORT_PARTITION`, `LONG_PARTITION` | `short`, `long` | Partitions for workers and the database |
| `MAX_JOBS` | 20 | Concurrent segment/link tasks, bounded by the database's connection limit |
| `SEG_MEM_GB_PER_WORKER`, `LINK_MEM_GB_PER_WORKER` | 4 | Memory per frame of a segment/link task |
| `SEG_TIME`, `LINK_TIME` | 6 h | Time limits |
| `SOLVE_MEM`, `SOLVE_CPUS`, `SOLVE_TIME` | 32 G, 4, 30 h | Per solve window; match `tracking.n_threads` to `SOLVE_CPUS` |
| `MAX_SOLVE_JOBS` | unset | Throttle the even solve pass |
| `EXPORT_MEM`, `EXPORT_CPUS`, `EXPORT_TIME` | 32 G, `data.n_workers`, 24 h | Export |
| `DB_MEM`, `DB_CPUS`, `DB_TIME` | 64 G, 8, 7 days | Database server; `DB_TIME` is an upper bound, clean-up stops it earlier |
| `SEG_GPUS`, `GPU_PARTITION`, `GPU_ACCOUNT`, `SEG_PIXI_ENV` | 0, `gpu_interactive`, —, `gpu` | GPU segmentation ([installation](installation.md#gpu)) |
| `KEEP_DB` | `false` | `true` keeps the database running after export, e.g. for parameter sweeps |
| `ULTRACK_DB_EPHEMERAL` | `false` | `true` puts the database on the server node's local disk with fsync off: faster inserts, but nothing to resume |
| `ULTRACK_WORK_DIR` | `/users/<group>/$USER/work` | Where the database directory `postgresql_ultrack_<JOB_NAME>` is kept |

Frames per segment or link task equal the configuration's `n_workers` for that stage, and so do the CPUs the task requests; `main.sh` sizes the arrays from them.

## Label input
`LABEL_SOURCE` is either a TIFF glob with one 2D frame per file, or a Zarr URI in the pyCyto convention, `/data/exp.zarr#labels/Cellpose/TCell`, with `?c=<channel name or index>` for multi-channel stores. Zarr v2 and v3, plain arrays (time first) and OME-NGFF 0.4/0.5 multiscale groups (level 0) are read; a singleton Z axis is dropped. The frame count needs only the standard library (`python3 label_io.py frames <source>`), so the login node's system Python is enough.

## Outputs and logs
- `results/<JOB_NAME>/tracks.csv`, `segments.zarr`
- `slurm_output/<JOB_NAME>/`: one log per job; `submission.tsv` lists every submitted job with its `sbatch` arguments; `resource_report.tsv` and `resource_report_summary.tsv` give each job's requested and used memory and time, with suggested requests for the next run.

Rerunning a stage replaces that stage's logs.

## Resuming
Candidates and links live in the database, so a failed solve or export does not repeat segmentation and linking. Run `main.sh` again with the same `JOB_NAME` and `CFG_FILE` and with `SKIP_SEG=true SKIP_LINK=true` (the defaults): it restarts the server on the stored database (`resume_server.sh`) and submits solve, export and clean-up. Changing only `[tracking]` parameters, or `SOLVE_MEM`, takes effect this way. `SKIP_SEG=true SKIP_LINK=false` reruns linking as well.

## Database server
- The data directory is `$ULTRACK_WORK_DIR/postgresql_ultrack_<JOB_NAME>`, unless ephemeral.
- On every start the server sets the run's password and rewrites its access rules: only this user, password required over TCP (loopback included), trust only on a private Unix socket. A resumed run can therefore use a new password.
- `max_connections` and memory settings are sized from the job's allocation.
- The address is written into `CFG_FILE` (owner-readable only), because ultrack's address format has no separate credential field.
