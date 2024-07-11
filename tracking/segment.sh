#! /bin/bash

#SBATCH --job-name=SEGMENT
#SBATCH --time=1-06:00:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=15G
#SBATCH --cpus-per-task=1
#SBATCH --output=./slurm_output/segment/segment-%A_%a.out
#SBATCH --requeue

env | grep "^SLURM" | sort

# conda activate ultrack

# ultrack segment $1 -cfg $CFG_FILE \
#     -b $SLURM_ARRAY_TASK_ID -r napari-ome-zarr -el edge -dl detection

# binning will automatically take care of length of data, for specfic time range edit in main.sh
# reserver length for reference
python segment.py -p "$1" --cfg "$2" -b "$3" -e "$4" -bi $SLURM_ARRAY_TASK_ID -bp 3