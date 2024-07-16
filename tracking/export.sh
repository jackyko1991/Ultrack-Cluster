#! /bin/bash

#SBATCH --job-name=EXPORT
#SBATCH --time=24:00:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=16G
#SBATCH --cpus-per-task=1
#SBATCH --output=./slurm_output/export-%j.out

source ~/.bashrc
mamba activate cyto

if [[ -v "$2" ]]; then
    directory=$2
else
    directory="$PWD/results/$JOB_NAME"
fi

if [ ! -d "$directory" ]; then
    mkdir -p "$directory"
    echo "Directory created: $directory"
else
    echo "Directory already exists: $directory"
fi

ultrack export zarr-napari -cfg "$1" -o "$directory" -ow