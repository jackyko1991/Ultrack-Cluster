#! /bin/bash

#SBATCH --job-name=EXPORT
#SBATCH --time=00:25:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=100G
#SBATCH --cpus-per-task=16
#SBATCH --output=./slurm_output/export-%j.out

directory="$PWD/results"

if [ ! -d "$directory" ]; then
    mkdir -p "$directory"
    echo "Directory created: $directory"
else
    echo "Directory already exists: $directory"
fi


ultrack export zarr-napari -cfg $CFG_FILE -o "$directory"