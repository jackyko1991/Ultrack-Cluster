#! /bin/bash

DS_LENGTH=500
NUM_WINDOWS=5
PARTITION=short # short/long on BMRC

# IMAGE_PATH_PATTERN="/users/kir-fritzsche/oyk357/archive/utse_cyto/2023_10_17_Nyeso1HCT116_1G4CD8_icam_FR10s_0p1mlperh/roi/register_denoise_gamma_channel_merged/t/tcells/*.tif"
LABEL_PATH_PATTERN="/users/kir-fritzsche/oyk357/archive/utse_cyto/2023_10_17_Nyeso1HCT116_1G4CD8_icam_FR10s_0p1mlperh/roi/register_denoise_gamma_channel_merged_masks/tcells/*.tif"

export CFG_FILE="config.toml"
export ULTRACK_DB_PW="ultrack_pw"
# export ULTRACK_DEBUG=1

conda activate ultrack

rm ./slurm_output/*.out -f
mkdir -p slurm_output

SERVER_JOB_ID=$(sbatch --partition $PARTITION --parsable create_server.sh)
echo "Server creation job submited (ID: $SERVER_JOB_ID)"

# SEGM_JOB_ID=$(sbatch --partition $PARTITION --parsable --array=0-$DS_LENGTH%200 -d after:$SERVER_JOB_ID+1 segment.sh ../segmentation.zarr)
SEGM_JOB_ID=$(sbatch --partition $PARTITION --parsable --array=0-$DS_LENGTH%200 -d after:$SERVER_JOB_ID+1 segment.sh $LABEL_PATH_PATTERN)

exit

if [[ -d "../flow.zarr" ]]; then
    FLOW_JOB_ID=$(sbatch --partition $PARTITION --parsable --mem 120GB --cpus-per-task=2 --job-name FLOW \
        --output=./slurm_output/flow-%j.out -d afterok:$SEGM_JOB_ID \
        ultrack add_flow ../flow.zarr -cfg $CFG_FILE -r napari -cha=1)
else
    FLOW_JOB_ID=$SEGM_JOB_ID
fi

# link multi channel
# LINK_JOB_ID=$(sbatch --partition $PARTITION --parsable --array=0-$((DS_LENGTH - 1))%200 -d afterok:$FLOW_JOB_ID link.sh -r napari-ome-zarr ../fused.zarr)

# link single channel
LINK_JOB_ID=$(sbatch --partition $PARTITION --parsable --array=0-$((DS_LENGTH - 1))%200 -d afterok:$FLOW_JOB_ID link.sh)

if (($NUM_WINDOWS == 0)); then
    SOLVE_JOB_ID_1=$(sbatch --partition $PARTITION --parsable --array=0-0 -d afterok:$LINK_JOB_ID solve.sh)
else
    SOLVE_JOB_ID_0=$(sbatch --partition $PARTITION --parsable --array=0-$NUM_WINDOWS:2 -d afterok:$LINK_JOB_ID solve.sh)
    SOLVE_JOB_ID_1=$(sbatch --partition $PARTITION --parsable --array=1-$NUM_WINDOWS:2 -d afterok:$SOLVE_JOB_ID_0 solve.sh)
fi

sbatch --mem 500GB --partition $PARTITION --cpus-per-task=50 --job-name EXPORT \
    --output=./slurm_output/export-%j.out -d afterok:$SOLVE_JOB_ID_1 \
    ultrack export zarr-napari -cfg $CFG_FILE -o results \
    --measure -r napari-ome-zarr -i ../fused.zarr
