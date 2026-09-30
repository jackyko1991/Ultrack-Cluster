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
    echo "Skip linking"
    SKIP_SEG=true
fi
if $SKIP_SEG; then
    echo "Skip segmentation"
fi
# TODO: skip solve for direct export
# SKIP_SOLVE=false

################# BMRC CONFIGURATIONS #################
LONG_PARTITION="${LONG_PARTITION:-long}"
SHORT_PARTITION="${SHORT_PARTITION:-short}" # short/long on BMRC

################# ULTRACK VARIABLE AUTO SETTING #################
TIME_STEPS_BINNED=$((TIME_STEPS/BINNING))
if (( TIME_STEPS_BINNED < 2 )); then
    echo "ERROR: need at least 2 time points to track, got $TIME_STEPS_BINNED from $DATA_DIR [$BEGIN_TIME:$END_TIME]" >&2
    exit 1
fi
export DS_LENGTH=$((TIME_STEPS_BINNED-1)) # number of time points - 1
# (not `export X=$(cmd)`: export's own status would hide cmd's failure)
DASEL_BIN=$(resolve_dasel)
export DASEL_BIN
WINDOW_SIZE=$($DASEL_BIN -f $CFG_FILE "tracking.window_size")
# last 0-based window index: ceil(DS_LENGTH / window_size) - 1
NUM_WINDOWS=$(last_batch_index "$DS_LENGTH" "$WINDOW_SIZE")

echo "Slices used from $DATA_DIR: $TIME_STEPS [$BEGIN_TIME:$END_TIME]"
echo "Binning temporally in $BINNING times, resulting in $TIME_STEPS_BINNED steps"
echo "Track window size = $WINDOW_SIZE, windows count = $NUM_WINDOWS"

# conda activate ultrack

# clean log dir
rm ./slurm_output/$JOB_NAME/*.out -f
if ! $SKIP_SEG; then
    rm ./slurm_output/$JOB_NAME/segment/*.out -f
fi
if ! $SKIP_LINK; then
    rm ./slurm_output/$JOB_NAME/link/*.out -f
fi
rm ./slurm_output/$JOB_NAME/solve/*.out -f

mkdir -p slurm_output/$JOB_NAME

# The DB job writes "host:port" here once PostgreSQL accepts connections;
# every worker waits for it (wait_for_db) instead of a fixed start delay.
export ULTRACK_DB_READY_FILE="$PWD/slurm_output/$JOB_NAME/db_ready"
rm -f "$ULTRACK_DB_READY_FILE"
if ! $SKIP_SEG; then
    mkdir -p slurm_output/$JOB_NAME/segment
fi
if ! $SKIP_LINK; then
    mkdir -p slurm_output/$JOB_NAME/link
fi
mkdir -p slurm_output/$JOB_NAME/solve

if $SKIP_SEG; then
    SERVER_JOB_ID=$(sbatch --partition $LONG_PARTITION --job-name "DATABASE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/database-%j.out" --parsable resume_server.sh "$CFG_FILE")
else
    SERVER_JOB_ID=$(sbatch --partition $LONG_PARTITION --job-name "DATABASE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/database-%j.out" --parsable create_server.sh "$CFG_FILE")
fi
echo "Server creation job submited (ID: $SERVER_JOB_ID)"

# limit node workers for the segmentation
if $SKIP_SEG; then
    SEGM_JOB_ID=$SERVER_JOB_ID
else
    # SEGM_JOB_ID=$(sbatch --partition $PARTITION --parsable --array=0-$DS_LENGTH%200 -d after:$SERVER_JOB_ID+1 segment.sh ../segmentation.zarr)
    SEGM_JOB_ID=$(sbatch --partition $SHORT_PARTITION --job-name "SEGMENT_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/segment/segment-%A_%a.out" --parsable --array=0-$DS_LENGTH%$MAX_JOBS -d after:$SERVER_JOB_ID segment.sh "$LABEL_PATH_PATTERN" "$CFG_FILE" "$BEGIN_TIME" "$END_TIME")
fi

if [[ -d "../flow.zarr" ]]; then
    if $SKIP_SEG; then
        FLOW_JOB_ID=$(sbatch --partition $SHORT_PARTITION --parsable --mem 120GB --cpus-per-task=2 --job-name FLOW \
            --output=./slurm_output/flow-%j.out -d after:$SEGM_JOB_ID \
            ultrack add_flow ../flow.zarr -cfg $CFG_FILE -r napari -cha=1)
    else
        FLOW_JOB_ID=$(sbatch --partition $SHORT_PARTITION --parsable --mem 120GB --cpus-per-task=2 --job-name FLOW \
            --output=./slurm_output/flow-%j.out -d afterok:$SEGM_JOB_ID \
            ultrack add_flow ../flow.zarr -cfg $CFG_FILE -r napari -cha=1)
    fi
else
    FLOW_JOB_ID=$SEGM_JOB_ID
fi

# link multi channel
# LINK_JOB_ID=$(sbatch --partition $PARTITION --parsable --array=0-$((DS_LENGTH - 1))%200 -d afterok:$FLOW_JOB_ID link.sh -r napari-ome-zarr ../fused.zarr)

# link single channel
if $SKIP_SEG; then
    if $SKIP_LINK; then
        LINK_JOB_ID=$FLOW_JOB_ID
    else
        LINK_JOB_ID=$(sbatch --partition $SHORT_PARTITION --job-name "LINK_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/link/link-%A_%a.out" --parsable --array=0-$((DS_LENGTH - 1))%$MAX_JOBS -d after:$FLOW_JOB_ID link.sh "$CFG_FILE")
    fi
else
    LINK_JOB_ID=$(sbatch --partition $SHORT_PARTITION --job-name "LINK_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/link/link-%A_%a.out" --parsable --array=0-$((DS_LENGTH - 1))%$MAX_JOBS -d afterok:$FLOW_JOB_ID link.sh "$CFG_FILE")
fi

if [[ $NUM_WINDOWS -eq 0 ]]; then
    # Bug fix: this used to check "-eq 1", which is wrong. NUM_WINDOWS is
    # the LAST window's 0-based index (ceil(DS_LENGTH/window_size) - 1),
    # so NUM_WINDOWS==1 means TWO windows exist (indices 0 and 1) -- the
    # general (else) branch below already handles that correctly via its
    # own 0-$NUM_WINDOWS:2 / 1-$NUM_WINDOWS:2 array slicing. The special
    # case actually needed is NUM_WINDOWS==0 (only ONE window, index 0,
    # total), where the general branch's odd-window array (--array=1-0:2,
    # start > end) would be an invalid SLURM array range. The old
    # "-eq 1" special case instead submitted only --array=0-0 whenever
    # NUM_WINDOWS was 1, silently never solving window 1 at all, and the
    # export step then ran on an incomplete solve.
    if $SKIP_LINK; then
        SOLVE_JOB_ID_1=$(sbatch --partition $SHORT_PARTITION --job-name "SOLVE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/solve/solve-%A_%a.out" --parsable --array=0-0 -d after:$LINK_JOB_ID solve.sh "$CFG_FILE")
    else
        SOLVE_JOB_ID_1=$(sbatch --partition $SHORT_PARTITION --job-name "SOLVE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/solve/solve-%A_%a.out" --parsable --array=0-0 -d afterok:$LINK_JOB_ID solve.sh "$CFG_FILE")
    fi
else
    if $SKIP_LINK; then
        SOLVE_JOB_ID_0=$(sbatch --partition $SHORT_PARTITION --job-name "SOLVE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/solve/solve-%A_%a.out" --parsable --array=0-$NUM_WINDOWS:2 -d after:$LINK_JOB_ID solve.sh "$CFG_FILE")
    else
        SOLVE_JOB_ID_0=$(sbatch --partition $SHORT_PARTITION --job-name "SOLVE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/solve/solve-%A_%a.out" --parsable --array=0-$NUM_WINDOWS:2 -d afterok:$LINK_JOB_ID solve.sh "$CFG_FILE")
    fi
    SOLVE_JOB_ID_1=$(sbatch --partition $SHORT_PARTITION --job-name "SOLVE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/solve/solve-%A_%a.out" --parsable --array=1-$NUM_WINDOWS:2 -d afterok:$SOLVE_JOB_ID_0 solve.sh "$CFG_FILE")
fi

# sbatch --mem 500GB --partition $PARTITION --cpus-per-task=50 --job-name EXPORT \
#     --output=./slurm_output/export-%j.out -d afterok:$SOLVE_JOB_ID_1 \
#     ultrack export zarr-napari -cfg $CFG_FILE -o results \
#     --measure -r napari-ome-zarr -i ../fused.zarr
# EXPORT_JOB_ID=$(sbatch --job-name "EXPORT_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/export-%j.out" export.sh)
EXPORT_JOB_ID=$(sbatch --job-name "EXPORT_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/export-%j.out" -d afterok:$SOLVE_JOB_ID_1 export.sh "$CFG_FILE")

# # stop DB server after job completion
# while true; do
#     if [[ $(squeue -j $SEGM_JOB_ID | wc -l) -eq 1 ]]; then
#         scancel $SERVER_JOB_ID
#         echo "DB server job stopped"
#         break
#     fi
#     sleep 60  # Check every minute
# done