#! /bin/bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/ultrack_lib.sh"
# Job scripts run from SLURM's spool dir, so tell them where this repo is.
export ULTRACK_CLUSTER_DIR="$ULTRACK_LIB_DIR"
################# FILE CONFIGURATIONS #################
# Every setting below can be overridden from the environment, e.g.
#   DATA_DIR=/path/to/labels BATCH_SIZE=40 bash main.sh
DATA_DIR="${DATA_DIR:-/users/kir-fritzsche/oyk357/archive/utse_cyto/2023_10_03_Nyeso1_HCT116_framerate_10sec_flowrate_0p15mlperh/register_denoising_gamma_channel_merged_cropped/cancer_batch5}"
LABEL_PATH_PATTERN=$DATA_DIR/*.tif
TIME_LENGTH=$(ls $DATA_DIR -1 | wc -l)

# uncomment below to manual overide the number of time steps to process, default taking all time slices
BATCH="${BATCH:-3}" # begin from 1
BATCH_SIZE="${BATCH_SIZE:-2880}"
POST_PADDING="${POST_PADDING:-20}"
BEGIN_TIME=$((BATCH_SIZE*(BATCH-1))) # begin from 0
END_TIME=$((BATCH_SIZE*BATCH-1+POST_PADDING))  # end at (max time steps - 1)
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

################# BMRC CONFIGURATIONS #################
LONG_PARTITION="${LONG_PARTITION:-long}"
SHORT_PARTITION="${SHORT_PARTITION:-short}" # short/long on BMRC

################# ULTRACK VARIABLE AUTO SETTING #################
TIME_STEPS_BINNED=$((TIME_STEPS/BINNING))
if (( TIME_STEPS_BINNED < 2 )); then
    log ERROR "need at least 2 time points to track, got $TIME_STEPS_BINNED from $DATA_DIR [$BEGIN_TIME:$END_TIME]"
    exit 1
fi
export DS_LENGTH=$((TIME_STEPS_BINNED-1)) # number of time points - 1
# (not `export X=$(cmd)`: export's own status would hide cmd's failure)
DASEL_BIN=$(resolve_dasel)
export DASEL_BIN
WINDOW_SIZE=$($DASEL_BIN -f $CFG_FILE "tracking.window_size")
# last 0-based window index: ceil(DS_LENGTH / window_size) - 1
NUM_WINDOWS=$(last_batch_index "$DS_LENGTH" "$WINDOW_SIZE")

export ULTRACK_STAGE=main
LOG_DIR="$PWD/slurm_output/$JOB_NAME"
log INFO "slices from $DATA_DIR: $TIME_STEPS [$BEGIN_TIME:$END_TIME], binning $BINNING -> $TIME_STEPS_BINNED steps"
log INFO "window size $WINDOW_SIZE -> last window index $NUM_WINDOWS"

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
    echo "# data=$DATA_DIR frames=$BEGIN_TIME-$END_TIME binning=$BINNING window_size=$WINDOW_SIZE last_window=$NUM_WINDOWS config=$CFG_FILE"
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
        --output "$LOG_DIR/database-%j.out" resume_server.sh "$CFG_FILE")
    SEGM_JOB_ID=$SERVER_JOB_ID
else
    SERVER_JOB_ID=$(submit db-server --partition "$LONG_PARTITION" --job-name "DATABASE_$JOB_NAME" \
        --output "$LOG_DIR/database-%j.out" create_server.sh "$CFG_FILE")
    SEGM_JOB_ID=$(submit segment --partition "$SHORT_PARTITION" --job-name "SEGMENT_$JOB_NAME" \
        --output "$LOG_DIR/segment/segment-%A_%a.out" --array="0-$DS_LENGTH%$MAX_JOBS" \
        -d "after:$SERVER_JOB_ID" --kill-on-invalid-dep=yes segment.sh "$LABEL_PATH_PATTERN" "$CFG_FILE" "$BEGIN_TIME" "$END_TIME")
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
        --output "$LOG_DIR/link/link-%A_%a.out" --array="0-$((DS_LENGTH - 1))%$MAX_JOBS" \
        -d "$link_dep" --kill-on-invalid-dep=yes link.sh "$CFG_FILE")
fi

# NUM_WINDOWS is the LAST window's 0-based index. Windows are solved in two
# passes, even then odd, because each odd window's boundaries depend on its
# even neighbours. With a single window (NUM_WINDOWS == 0) there is no odd
# pass (--array=1-0:2 would be invalid).
if $SKIP_LINK; then solve_dep="after:$LINK_JOB_ID"; else solve_dep="afterok:$LINK_JOB_ID"; fi
if [[ $NUM_WINDOWS -eq 0 ]]; then
    SOLVE_JOB_ID_1=$(submit solve --partition "$SHORT_PARTITION" --job-name "SOLVE_$JOB_NAME" \
        --output "$LOG_DIR/solve/solve-%A_%a.out" --array=0-0 -d "$solve_dep" --kill-on-invalid-dep=yes solve.sh "$CFG_FILE")
else
    SOLVE_JOB_ID_0=$(submit solve-even --partition "$SHORT_PARTITION" --job-name "SOLVE_$JOB_NAME" \
        --output "$LOG_DIR/solve/solve-%A_%a.out" --array="0-$NUM_WINDOWS:2" -d "$solve_dep" --kill-on-invalid-dep=yes solve.sh "$CFG_FILE")
    SOLVE_JOB_ID_1=$(submit solve-odd --partition "$SHORT_PARTITION" --job-name "SOLVE_$JOB_NAME" \
        --output "$LOG_DIR/solve/solve-%A_%a.out" --array="1-$NUM_WINDOWS:2" -d "afterok:$SOLVE_JOB_ID_0" --kill-on-invalid-dep=yes solve.sh "$CFG_FILE")
fi

EXPORT_JOB_ID=$(submit export --job-name "EXPORT_$JOB_NAME" --output "$LOG_DIR/export-%j.out" \
    -d "afterok:$SOLVE_JOB_ID_1" --kill-on-invalid-dep=yes export.sh "$CFG_FILE")

# Stop the DB server once export ends in any state (upstream failures cancel
# the chain via --kill-on-invalid-dep, so export always ends) and record what
# every job actually used. KEEP_DB=true keeps the server for parameter sweeps.
if ! ${KEEP_DB:-false}; then
    CLEANUP_JOB_ID=$(submit cleanup --partition "$SHORT_PARTITION" --job-name "CLEANUP_$JOB_NAME" \
        --output "$LOG_DIR/cleanup-%j.out" -d "afterany:$EXPORT_JOB_ID" \
        cleanup.sh "$SERVER_JOB_ID" "$MANIFEST")
else
    log WARN "KEEP_DB=true: DB server job $SERVER_JOB_ID keeps running until you scancel it"
fi

log INFO "all jobs submitted; manifest: $MANIFEST"
