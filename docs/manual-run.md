# Manual run

`main.sh` is the supported way to run; this page is for running or rerunning single stages.

## Recipe from a previous run
Every job `main.sh` submits is recorded in `slurm_output/<JOB_NAME>/submission.tsv` with its full `sbatch` arguments. To rerun a stage by hand, copy its line and drop the dependency (`-d …`). The job scripts read the same environment as `main.sh` (`ULTRACK_PIXI_ENV`, `ULTRACK_DB_PW`, `JOB_NAME`, `ULTRACK_CLUSTER_DIR`, `ULTRACK_DB_READY_FILE`), so export those first.

## Stage by stage
Run from `tracking/` with the environment exported:
```bash
export ULTRACK_PIXI_ENV=default ULTRACK_DB_PW=... JOB_NAME=exp01 CFG_FILE=$PWD/config.toml
export ULTRACK_CLUSTER_DIR=$PWD ULTRACK_DB_READY_FILE=$PWD/slurm_output/$JOB_NAME/db_ready
```

1. Database server: `sbatch create_server.sh $CFG_FILE` for a new database, `sbatch resume_server.sh $CFG_FILE` for an existing one. Once it accepts connections it writes its address into `$CFG_FILE` and `host:port` into `$ULTRACK_DB_READY_FILE`.
2. Segment, one array task per `segmentation.n_workers` frames; task 0 first, as it creates the tables:
   ```bash
   sbatch --array=0-0 segment.sh "$LABEL_SOURCE" $CFG_FILE <begin> <end>
   sbatch --array=1-<last>%<MAX_JOBS> -d afterok:<task-0 job> segment.sh "$LABEL_SOURCE" $CFG_FILE <begin> <end>
   ```
3. Link, one task per `linking.n_workers` frame pairs: `sbatch --array=0-<last>%<MAX_JOBS> -d afterok:<segment jobs> link.sh $CFG_FILE`
4. Solve: even windows, then odd windows. The last window index is $\lceil (T-1)/\text{window\_size} \rceil - 1$ for $T$ tracked frames.
   ```bash
   sbatch --array=0-<last>:2 -d afterok:<link job> solve.sh $CFG_FILE
   sbatch --array=1-<last>:2 -d afterok:<even job> solve.sh $CFG_FILE
   ```
5. Export: `sbatch -d afterok:<solve jobs> export.sh $CFG_FILE results/$JOB_NAME`
6. Stop the server: `scancel <database job>`, or `sbatch -d afterany:<export job> cleanup.sh <database job> slurm_output/$JOB_NAME/submission.tsv`, which also writes the resource report.

Clear a stage before recomputing it (ultrack's `--overwrite` would clear the database once per array task): `pixi run ultrack clear_database -cfg $CFG_FILE {all|links|solutions}`.

## Database access from a workstation
Forward the server's port through the login node, then connect to `localhost`:
```bash
ssh -L 5432:<server node>:<port> <user>@<login node>
pg_dump -h localhost -p 5432 -U $USER -f ultrack.sql ultrack    # optional backup
```

## Useful SLURM commands
```bash
squeue --me                                              # progress
sacct -j <job> -o JobID%20,JobName,State,Elapsed,ReqMem,MaxRSS
sacct -j <job> -o ReqCPUS,ElapsedRaw,TRESUsageInMax%80   # CPU use
scontrol update JobId=<job> Dependency=afterany:<other>  # change a dependency
```
