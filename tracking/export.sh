#! /bin/bash

#SBATCH --job-name=EXPORT
#SBATCH --time=24:00:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=15G
#SBATCH --cpus-per-task=1
#SBATCH --output=./slurm_output/export-%j.out

directory="$PWD/results/$JOB_NAME"

if [ ! -d "$directory" ]; then
    mkdir -p "$directory"
    echo "Directory created: $directory"
else
    echo "Directory already exists: $directory"
fi

ultrack export zarr-napari -cfg "$1" -o "$directory" -ow
