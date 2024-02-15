#! /bin/bash
################# FILE CONFIGURATIONS ################# 
DATA_DIR="/users/kir-fritzsche/oyk357/archive/utse_cyto/2023_10_17_Nyeso1HCT116_1G4CD8_icam_FR10s_0p1mlperh/roi/register_denoise_gamma_channel_merged_masks/tcell"
LABEL_PATH_PATTERN=$DATA_DIR/*.tif
TIME_STEPS=$(ls $DATA_DIR -1 | wc -l)

# uncomment below to manual overide the number of time steps to process, default taking all time slices
export BEGIN_TIME=2160 # begin from 0
export END_TIME=4319  # end at (max time steps - 1)
TIME_STEPS=$((END_TIME-BEGIN_TIME+1))

export BINNING=1
export JOB_NAME="20231017_roi-0_$((BEGIN_TIME))-$((END_TIME))_binT-$((BINNING))_tcell"
MAX_JOBS=100 # DB concurrency limit
export CFG_FILE="config_binning_2.toml"
export ULTRACK_DB_PW="ultrack_pw"
# export ULTRACK_DEBUG=1
SKIP_SEG=false

################# BMRC CONFIGURATIONS ################# 
LONG_PARTITION=short
SHORT_PARTITION=short # short/long on BMRC
DELAY_AFTER_DB_SERVER=1 # ultrack start time delay after database server creation, in minutes

################# ULTRACK VARIABLE AUTO SETTING ################# 
# Helper function to calculate the ceiling of a number
ceil() {
    if [[ $1 =~ ^[0-9]*(\.[0-9]+)?$ ]]; then
        integerPart=${1%.*}
        fractionalPart=${1#*.}
        
        if [[ -z $fractionalPart ]]; then
            echo $integerPart
        else
            if [[ $integerPart -ge 0 ]]; then
                echo "$((integerPart + 1))"
            else
                echo "$integerPart"
            fi
        fi
    else
        echo "Error: Not a valid number"
        return 1
    fi
}

TIME_STEPS_BINNED=$((TIME_STEPS/BINNING))
export DS_LENGTH=$((TIME_STEPS_BINNED-1)) # number of time points - 1
WINDOW_SIZE=$(dasel -f $CFG_FILE "tracking.window_size")
# NUM_WINDOWS=ceil($DS_LENGTH/window_size) - 1 , window_size should be exactly the one in config.toml
NUM_WINDOWS=$(echo "scale=2;$DS_LENGTH / $WINDOW_SIZE" | bc)
NUM_WINDOWS=$(ceil $NUM_WINDOWS)
NUM_WINDOWS=$((NUM_WINDOWS-1))

echo "Slices used from $DATA_DIR: $TIME_STEPS [$BEGIN_TIME:$END_TIME]"
echo "Binning temporally in $BINNING times, resulting in $TIME_STEPS_BINNED steps"
echo "Track window size = $WINDOW_SIZE, windows count = $NUM_WINDOWS"

# conda activate ultrack

# clean log dir
rm ./slurm_output/$JOB_NAME/*.out -f
if ! $SKIP_SEG; then
    rm ./slurm_output/$JOB_NAME/segment/*.out -f
fi
rm ./slurm_output/$JOB_NAME/link/*.out -f
rm ./slurm_output/$JOB_NAME/solve/*.out -f

mkdir -p slurm_output/$JOB_NAME
if ! $SKIP_SEG; then
    mkdir -p slurm_output/$JOB_NAME/segment
fi
mkdir -p slurm_output/$JOB_NAME/link
mkdir -p slurm_output/$JOB_NAME/solve

if $SKIP_SEG; then
    SERVER_JOB_ID=$(sbatch --partition $LONG_PARTITION --job-name "DATABASE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/database-%j.out" --parsable resume_server.sh)
else
    SERVER_JOB_ID=$(sbatch --partition $LONG_PARTITION --job-name "DATABASE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/database-%j.out" --parsable create_server.sh)
fi
echo "Server creation job submited (ID: $SERVER_JOB_ID)"

# limit node workers for the segmentation
if $SKIP_SEG; then
    SEGM_JOB_ID=$SERVER_JOB_ID
else
    # SEGM_JOB_ID=$(sbatch --partition $PARTITION --parsable --array=0-$DS_LENGTH%200 -d after:$SERVER_JOB_ID+1 segment.sh ../segmentation.zarr)
    SEGM_JOB_ID=$(sbatch --partition $SHORT_PARTITION --job-name "SEGMENT_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/segment/segment-%A_%a.out" --parsable --array=0-$DS_LENGTH%$MAX_JOBS -d after:$SERVER_JOB_ID+$DELAY_AFTER_DB_SERVER segment.sh "$LABEL_PATH_PATTERN")
fi

if [[ -d "../flow.zarr" ]]; then
    if $SKIP_SEG; then
        FLOW_JOB_ID=$(sbatch --partition $SHORT_PARTITION --parsable --mem 120GB --cpus-per-task=2 --job-name FLOW \
            --output=./slurm_output/flow-%j.out -d after:$SEGM_JOB_ID+$DELAY_AFTER_DB_SERVER \
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
    LINK_JOB_ID=$(sbatch --partition $SHORT_PARTITION --job-name "LINK_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/link/link-%A_%a.out" --parsable --array=0-$((DS_LENGTH - 1))%$MAX_JOBS -d after:$FLOW_JOB_ID+$DELAY_AFTER_DB_SERVER link.sh)
else
    LINK_JOB_ID=$(sbatch --partition $SHORT_PARTITION --job-name "LINK_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/link/link-%A_%a.out" --parsable --array=0-$((DS_LENGTH - 1))%$MAX_JOBS -d afterok:$FLOW_JOB_ID link.sh)
fi

if [[ $NUM_WINDOWS -eq 1 ]]; then
    SOLVE_JOB_ID_1=$(sbatch --partition $SHORT_PARTITION --job-name "SOLVE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/solve/solve-%A_%a.out" --parsable --array=0-0 -d afterok:$LINK_JOB_ID solve.sh)
else
    SOLVE_JOB_ID_0=$(sbatch --partition $SHORT_PARTITION --job-name "SOLVE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/solve/solve-%A_%a.out" --parsable --array=0-$NUM_WINDOWS:2 -d afterok:$LINK_JOB_ID solve.sh)
    SOLVE_JOB_ID_1=$(sbatch --partition $SHORT_PARTITION --job-name "SOLVE_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/solve/solve-%A_%a.out" --parsable --array=1-$NUM_WINDOWS:2 -d afterok:$SOLVE_JOB_ID_0 solve.sh)
fi

# sbatch --mem 500GB --partition $PARTITION --cpus-per-task=50 --job-name EXPORT \
#     --output=./slurm_output/export-%j.out -d afterok:$SOLVE_JOB_ID_1 \
#     ultrack export zarr-napari -cfg $CFG_FILE -o results \
#     --measure -r napari-ome-zarr -i ../fused.zarr
# EXPORT_JOB_ID=$(sbatch --job-name "EXPORT_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/export-%j.out" export.sh)
EXPORT_JOB_ID=$(sbatch --job-name "EXPORT_$JOB_NAME" --output "$PWD/slurm_output/$JOB_NAME/export-%j.out" -d afterok:$SOLVE_JOB_ID_1 export.sh)

# # stop DB server after job completion
# while true; do
#     if [[ $(squeue -j $SEGM_JOB_ID | wc -l) -eq 1 ]]; then
#         scancel $SERVER_JOB_ID
#         echo "DB server job stopped"
#         break
#     fi
#     sleep 60  # Check every minute
# done