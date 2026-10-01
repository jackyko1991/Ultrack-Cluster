#! /bin/bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/ultrack_lib.sh"
# Job scripts run from SLURM's spool dir, so tell them where this repo is.
export ULTRACK_CLUSTER_DIR="$ULTRACK_LIB_DIR"
################# FILE CONFIGURATIONS #################
# Every setting below can be overridden from the environment, e.g.
#   DATA_DIR=/path/to/labels BATCH_SIZE=40 bash main.sh
DATA_DIR="${DATA_DIR:-/users/kir-fritzsche/oyk357/archive/utse_cyto/2023_10_03_Nyeso1_HCT116_framerate_10sec_flowrate_0p15mlperh/register_denoising_gamma_channel_merged_cropped/cancer_batch5}"
# Label source: a TIFF glob (one 2D frame per file) or a Zarr URI in the
# pyCyto/tanoa convention, e.g. LABEL_SOURCE='/data/exp.zarr#labels/Cellpose/TCell'
# (add '?c=<channel>' for a multi-channel store). See label_io.py.
LABEL_PATH_PATTERN="${LABEL_SOURCE:-$DATA_DIR/*.tif}"
# stdlib-only, so the login node's system python3 is enough
TIME_LENGTH=$(python3 "$ULTRACK_LIB_DIR/label_io.py" frames "$LABEL_PATH_PATTERN")

# uncomment below to manual overide the number of time steps to process, default taking all time slices
BATCH="${BATCH:-3}" # begin from 1
BATCH_SIZE="${BATCH_SIZE:-2880}"
POST_PADDING="${POST_PADDING:-20}"
# BEGIN_TIME/END_TIME (0-based, inclusive) take precedence over BATCH/BATCH_SIZE/POST_PADDING
BEGIN_TIME="${BEGIN_TIME:-$((BATCH_SIZE*(BATCH-1)))}" # begin from 0
END_TIME="${END_TIME:-$((BATCH_SIZE*BATCH-1+POST_PADDING))}"  # end at (max time steps - 1)
if [[ $END_TIME -ge $TIME_LENGTH ]]; then
    END_TIME=$((TIME_LENGTH-1))
fi

TIME_STEPS=$((END_TIME-BEGIN_TIME+1))

export BINNING="${BINNING:-1}"
export JOB_NAME="${JOB_NAME:-20231003_roi-5_$((BEGIN_TIME))-$((END_TIME))_binT-$((BINNING))_tcell}"
MAX_JOBS="${MAX_JOBS:-20}" # DB concurrency limit
CFG_FILE="${CFG_FILE:-config_binning_$BATCH.toml}"
export ULTRACK_DB_PW="${ULTRACK_DB_PW:-ultrack_pw}"
# export ULTRACK_DEBUG=1
SKIP_SEG="${SKIP_SEG:-true}"
SKIP_LINK="${SKIP_LINK:-true}"
# force skip segmentation if choose to skip link
if $SKIP_LINK; then
    log INFO "skipping linking (and segmentation)"
    SKIP_SEG=true
elif $SKIP_SEG; then
    log INFO "skipping segmentation"
fi
# TODO: skip solve for direct export
# SKIP_SOLVE=false

# ULTRACK_DB_EPHEMERAL=true: DB on the server node's local disk with fsync off
# (faster inserts, nothing kept afterwards -- so no resume).
if [[ "${ULTRACK_DB_EPHEMERAL:-false}" == true ]] && $SKIP_SEG; then
    log ERROR "ULTRACK_DB_EPHEMERAL=true cannot resume an existing DB (SKIP_SEG/SKIP_LINK=true)"
    exit 1
fi

################# BMRC CONFIGURATIONS #################
LONG_PARTITION="${LONG_PARTITION:-long}"
SHORT_PARTITION="${SHORT_PARTITION:-short}" # short/long on BMRC

################# RESOURCES #################
# Per-stage requests, passed explicitly to sbatch. Defaults are well below the
# old ones (15G per segment/link task, 300G/20 CPUs for 10 days for the DB)
# yet keep headroom over what the 2026-09-30 smoke test measured on an
# 800x800 patch (0.65 GB per segment/link frame, 3.6 GB for a solve window);
# full-FOV frames are ~9x larger. After a run, slurm_output/<job>/
# resource_report_summary.tsv suggests values from the actual peaks.
SEG_MEM_GB_PER_WORKER="${SEG_MEM_GB_PER_WORKER:-4}"
LINK_MEM_GB_PER_WORKER="${LINK_MEM_GB_PER_WORKER:-4}"
SEG_TIME="${SEG_TIME:-06:00:00}"
# GPUs per segment task. 0 (default): labels -> contours -> blur -> hierarchies
# all on CPU. With >0, contours and blur run on the GPU (cupy/cucim); the
# hierarchy stays on CPU. Set >0 only for GPU work
# (cupy/cucim contours, ultrack.imgproc models); with the pixi runtime those
# tasks then switch to the CUDA environment SEG_PIXI_ENV (see README "GPU").
SEG_GPUS="${SEG_GPUS:-0}"
SEG_PIXI_ENV="${SEG_PIXI_ENV:-gpu}"
LINK_TIME="${LINK_TIME:-06:00:00}"
SOLVE_MEM="${SOLVE_MEM:-32G}"
SOLVE_CPUS="${SOLVE_CPUS:-4}"
SOLVE_TIME="${SOLVE_TIME:-1-06:00:00}"
DB_MEM="${DB_MEM:-64G}"
DB_CPUS="${DB_CPUS:-8}"
DB_TIME="${DB_TIME:-7-00:00:00}"   # upper bound only: cleanup.sh stops it when export ends
EXPORT_MEM="${EXPORT_MEM:-32G}"
EXPORT_TIME="${EXPORT_TIME:-1-00:00:00}"

################# ULTRACK VARIABLE AUTO SETTING #################
# frames begin..end taking every BINNING-th: ceil, as segment.py slices [begin:end+1:BINNING]
TIME_STEPS_BINNED=$(ceil_div "$TIME_STEPS" "$BINNING")
if (( TIME_STEPS_BINNED < 2 )); then
    log ERROR "need at least 2 time points to track, got $TIME_STEPS_BINNED from $LABEL_PATH_PATTERN [$BEGIN_TIME:$END_TIME]"
    exit 1
fi
export DS_LENGTH=$((TIME_STEPS_BINNED-1)) # number of time points - 1
# (not `export X=$(cmd)`: export's own status would hide cmd's failure)
DASEL_BIN=$(resolve_dasel)
export DASEL_BIN
WINDOW_SIZE=$($DASEL_BIN -f $CFG_FILE "tracking.window_size")
# last 0-based window index: ceil(DS_LENGTH / window_size) - 1
NUM_WINDOWS=$(last_batch_index "$DS_LENGTH" "$WINDOW_SIZE")

# Frames per array task = the config's n_workers: ultrack's batch_index_range
# gives batch i the items [i*n, (i+1)*n) and processes them with an n-process
# pool, so the array size, n_workers and --cpus-per-task must agree (an array
# sized for n=1 with n>1 in the config indexes past the end and fails).
# segment() splits the T frames; link() splits range(max_t) = the T-1 pairs.
SEG_WORKERS=$($DASEL_BIN -f "$CFG_FILE" "segmentation.n_workers")
LINK_WORKERS=$($DASEL_BIN -f "$CFG_FILE" "linking.n_workers")
SEG_LAST=$(last_batch_index "$TIME_STEPS_BINNED" "$SEG_WORKERS")
LINK_LAST=$(last_batch_index "$DS_LENGTH" "$LINK_WORKERS")
if [[ "$($DASEL_BIN -f "$CFG_FILE" "tracking.n_threads")" == 0 ]]; then
    log WARN "tracking.n_threads = 0 lets the solver use every core on the node; set it to SOLVE_CPUS=$SOLVE_CPUS"
fi
SEG_GPU_ARGS=()
SEG_PARTITION="$SHORT_PARTITION"
if (( SEG_GPUS > 0 )); then
    # BMRC: gpu_interactive (x86, 12 h, short queue) with GPU_ACCOUNT=gpu_kir.prj;
    # segment needs x86 (higra, ultrack's hierarchy, has no aarch64 build)
    SEG_PARTITION="${GPU_PARTITION:-gpu_interactive}"
    SEG_GPU_ARGS=(--gres "gpu:$SEG_GPUS")
    if [[ -n "${GPU_ACCOUNT:-}" ]]; then
        SEG_GPU_ARGS+=(--account "$GPU_ACCOUNT")
    fi
    if [[ -n "${ULTRACK_SIF:-}" ]]; then
        log WARN "SEG_GPUS=$SEG_GPUS with ULTRACK_SIF: the image must contain cupy/CUDA torch, or segment ignores the GPU"
    elif [[ -n "${ULTRACK_PIXI_ENV:-}" ]]; then
        SEG_GPU_ARGS+=(--export "ALL,ULTRACK_PIXI_ENV=$SEG_PIXI_ENV")
    else
        log WARN "SEG_GPUS=$SEG_GPUS: segment uses the GPU only if its environment has cupy/cucim (or CUDA torch)"
    fi
fi
for workers in "$SEG_WORKERS" "$LINK_WORKERS"; do
    if (( MAX_JOBS * workers > ${ULTRACK_PG_MAX_CONNECTIONS:-500} * 9 / 10 )); then
        log WARN "MAX_JOBS=$MAX_JOBS x n_workers=$workers DB connections may exceed max_connections=${ULTRACK_PG_MAX_CONNECTIONS:-500}"
    fi
done

export ULTRACK_STAGE=main
# results/<job>/tracks.csv under the directory main.sh is run from (a stable
# location callers such as pyCyto read)
RESULTS_DIR="$PWD/results/$JOB_NAME"
LOG_DIR="$PWD/slurm_output/$JOB_NAME"
log INFO "slices from $LABEL_PATH_PATTERN: $TIME_STEPS [$BEGIN_TIME:$END_TIME], binning $BINNING -> $TIME_STEPS_BINNED steps"
log INFO "window size $WINDOW_SIZE -> last window index $NUM_WINDOWS"
log INFO "segment: partition $SEG_PARTITION, $SEG_GPUS GPU(s)/task"
log INFO "segment: $SEG_WORKERS frames/task -> $((SEG_LAST + 1)) tasks; link: $LINK_WORKERS frames/task -> $((LINK_LAST + 1)) tasks"

# fresh log dirs for the stages that will run
rm -f "$LOG_DIR"/*.out "$LOG_DIR"/segment/*.out "$LOG_DIR"/link/*.out "$LOG_DIR"/solve/*.out
mkdir -p "$LOG_DIR/segment" "$LOG_DIR/link" "$LOG_DIR/solve"

# The DB job writes "host:port" here once PostgreSQL accepts connections;
# every worker waits for it (wait_for_db) instead of a fixed start delay.
export ULTRACK_DB_READY_FILE="$LOG_DIR/db_ready"
rm -f "$ULTRACK_DB_READY_FILE"

# Every submission goes through here and is recorded in the manifest, so a run
# can be reconstructed (and inspected with sacct) from its log directory.
MANIFEST="$LOG_DIR/submission.tsv"
{
    echo "# submitted $(date '+%F %T') by $USER on $(hostname -s) repo=$(ultrack_cluster_version)"
    echo "# data=$LABEL_PATH_PATTERN frames=$BEGIN_TIME-$END_TIME binning=$BINNING window_size=$WINDOW_SIZE last_window=$NUM_WINDOWS config=$CFG_FILE"
    printf 'stage\tjob_id\tsbatch_args\n'
} > "$MANIFEST"

# submit <stage> <sbatch args...>: prints the job id (and only that on stdout)
submit() {
    local stage="$1"; shift
    local id
    # explicit: errexit does not apply inside $(...), where submit runs
    id=$(sbatch --parsable "$@") || { log ERROR "sbatch failed for $stage"; return 1; }
    id="${id%%;*}"   # --parsable may append ";cluster"
    if [[ ! "$id" =~ ^[0-9]+$ ]]; then
        log ERROR "sbatch returned no job id for $stage: '$id'"
        return 1
    fi
    printf '%s\t%s\t%s\n' "$stage" "$id" "$*" >> "$MANIFEST"
    log INFO "submitted $stage as job $id" >&2
    echo "$id"
}


if $SKIP_SEG; then
    SERVER_JOB_ID=$(submit db-server --partition "$LONG_PARTITION" --job-name "DATABASE_$JOB_NAME" \
        --mem "$DB_MEM" --cpus-per-task "$DB_CPUS" --time "$DB_TIME" \
        --output "$LOG_DIR/database-%j.out" "$ULTRACK_CLUSTER_DIR/resume_server.sh" "$CFG_FILE")
    SEGM_JOB_ID=$SERVER_JOB_ID
else
    SERVER_JOB_ID=$(submit db-server --partition "$LONG_PARTITION" --job-name "DATABASE_$JOB_NAME" \
        --mem "$DB_MEM" --cpus-per-task "$DB_CPUS" --time "$DB_TIME" \
        --output "$LOG_DIR/database-%j.out" "$ULTRACK_CLUSTER_DIR/create_server.sh" "$CFG_FILE")
    seg_args=(--partition "$SEG_PARTITION" --job-name "SEGMENT_$JOB_NAME" \
        --output "$LOG_DIR/segment/segment-%A_%a.out" --cpus-per-task="$SEG_WORKERS" \
        ${SEG_GPU_ARGS[@]+"${SEG_GPU_ARGS[@]}"} \
        --mem "$(( SEG_MEM_GB_PER_WORKER * SEG_WORKERS ))G" --time "$SEG_TIME" --kill-on-invalid-dep=yes)
    seg_cmd=("$ULTRACK_CLUSTER_DIR/segment.sh" "$LABEL_PATH_PATTERN" "$CFG_FILE" "$BEGIN_TIME" "$END_TIME")
    # Batch 0 creates the tables (and clears any old data), so it runs alone
    # first: the other batches start only once it has succeeded, and a late or
    # requeued batch 0 can no longer wipe segments they already inserted.
    SEGM_JOB_ID=$(submit segment-init "${seg_args[@]}" --array=0-0 -d "after:$SERVER_JOB_ID" "${seg_cmd[@]}")
    if (( SEG_LAST >= 1 )); then
        seg_rest=$(submit segment "${seg_args[@]}" --array="1-$SEG_LAST%$MAX_JOBS" \
            -d "afterok:$SEGM_JOB_ID" "${seg_cmd[@]}")
        SEGM_JOB_ID="$SEGM_JOB_ID:$seg_rest"   # afterok:<init>:<rest> downstream
    fi
fi

if [[ -d "../flow.zarr" ]]; then
    # sbatch needs a script: the old `sbatch ... ultrack add_flow ...` form
    # handed it the ultrack executable as the batch script.
    flow_cmd="source '$ULTRACK_CLUSTER_DIR/ultrack_lib.sh' && activate_ultrack_env && wait_for_db && run_ultrack ultrack add_flow ../flow.zarr -cfg '$CFG_FILE' -r napari -cha=1"
    if $SKIP_SEG; then flow_dep="after:$SEGM_JOB_ID"; else flow_dep="afterok:$SEGM_JOB_ID"; fi
    FLOW_JOB_ID=$(submit flow --partition "$SHORT_PARTITION" --mem 120GB --cpus-per-task=2 --job-name "FLOW_$JOB_NAME" \
        --output "$LOG_DIR/flow-%j.out" -d "$flow_dep" --kill-on-invalid-dep=yes --wrap "bash -c \"$flow_cmd\"")
else
    FLOW_JOB_ID=$SEGM_JOB_ID
fi

if $SKIP_LINK; then
    LINK_JOB_ID=$FLOW_JOB_ID
else
    if $SKIP_SEG; then link_dep="after:$FLOW_JOB_ID"; else link_dep="afterok:$FLOW_JOB_ID"; fi
    LINK_JOB_ID=$(submit link --partition "$SHORT_PARTITION" --job-name "LINK_$JOB_NAME" \
        --output "$LOG_DIR/link/link-%A_%a.out" --array="0-$LINK_LAST%$MAX_JOBS" --cpus-per-task="$LINK_WORKERS" \
        --mem "$(( LINK_MEM_GB_PER_WORKER * LINK_WORKERS ))G" --time "$LINK_TIME" \
        -d "$link_dep" --kill-on-invalid-dep=yes "$ULTRACK_CLUSTER_DIR/link.sh" "$CFG_FILE")
fi

# NUM_WINDOWS is the LAST window's 0-based index. Windows are solved in two
# passes, even then odd, because each odd window's boundaries depend on its
# even neighbours. With a single window (NUM_WINDOWS == 0) there is no odd
# pass (--array=1-0:2 would be invalid).
if $SKIP_LINK; then solve_dep="after:$LINK_JOB_ID"; else solve_dep="afterok:$LINK_JOB_ID"; fi
solve_res=(--partition "$SHORT_PARTITION" --job-name "SOLVE_$JOB_NAME" \
    --mem "$SOLVE_MEM" --cpus-per-task "$SOLVE_CPUS" --time "$SOLVE_TIME" \
    --output "$LOG_DIR/solve/solve-%A_%a.out")
MAX_SOLVE_JOBS="${MAX_SOLVE_JOBS:-}"   # optional throttle on the even pass
throttle="${MAX_SOLVE_JOBS:+%$MAX_SOLVE_JOBS}"
if [[ $NUM_WINDOWS -eq 0 ]]; then
    SOLVE_JOB_ID_0=$(submit solve "${solve_res[@]}" --array=0-0 \
        -d "$solve_dep" --kill-on-invalid-dep=yes "$ULTRACK_CLUSTER_DIR/solve.sh" "$CFG_FILE")
    export_dep="afterok:$SOLVE_JOB_ID_0"
else
    SOLVE_JOB_ID_0=$(submit solve-even "${solve_res[@]}" --array="0-$NUM_WINDOWS:2$throttle" \
        -d "$solve_dep" --kill-on-invalid-dep=yes "$ULTRACK_CLUSTER_DIR/solve.sh" "$CFG_FILE")
    if ${SOLVE_PER_WINDOW_DEPS:-true}; then
        # Each odd window waits only for its two even neighbours, so it can
        # start while other even windows are still queued or running.
        export_dep="afterok:$SOLVE_JOB_ID_0"
        for (( w = 1; w <= NUM_WINDOWS; w += 2 )); do
            window_dep="afterok:${SOLVE_JOB_ID_0}_$((w - 1))"
            if (( w + 1 <= NUM_WINDOWS )); then
                window_dep+=":${SOLVE_JOB_ID_0}_$((w + 1))"
            fi
            odd_id=$(submit "solve-odd-$w" "${solve_res[@]}" --array="$w-$w" \
                -d "$window_dep" --kill-on-invalid-dep=yes "$ULTRACK_CLUSTER_DIR/solve.sh" "$CFG_FILE")
            export_dep+=":$odd_id"
        done
    else
        SOLVE_JOB_ID_1=$(submit solve-odd "${solve_res[@]}" --array="1-$NUM_WINDOWS:2" \
            -d "afterok:$SOLVE_JOB_ID_0" --kill-on-invalid-dep=yes "$ULTRACK_CLUSTER_DIR/solve.sh" "$CFG_FILE")
        export_dep="afterok:$SOLVE_JOB_ID_0:$SOLVE_JOB_ID_1"
    fi
fi

EXPORT_JOB_ID=$(submit export --partition "$SHORT_PARTITION" --job-name "EXPORT_$JOB_NAME" --output "$LOG_DIR/export-%j.out" \
    --mem "$EXPORT_MEM" --time "$EXPORT_TIME" \
    -d "$export_dep" --kill-on-invalid-dep=yes "$ULTRACK_CLUSTER_DIR/export.sh" "$CFG_FILE" "$RESULTS_DIR")

# Stop the DB server once export ends in any state (upstream failures cancel
# the chain via --kill-on-invalid-dep, so export always ends) and record what
# every job actually used. KEEP_DB=true keeps the server for parameter sweeps.
if ! ${KEEP_DB:-false}; then
    CLEANUP_JOB_ID=$(submit cleanup --partition "$SHORT_PARTITION" --job-name "CLEANUP_$JOB_NAME" \
        --output "$LOG_DIR/cleanup-%j.out" -d "afterany:$EXPORT_JOB_ID" \
        "$ULTRACK_CLUSTER_DIR/cleanup.sh" "$SERVER_JOB_ID" "$MANIFEST")
else
    log WARN "KEEP_DB=true: DB server job $SERVER_JOB_ID keeps running until you scancel it"
fi

log INFO "all jobs submitted; manifest: $MANIFEST"
