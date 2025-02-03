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

echo "Config file: $1"
# check if the output dir is provided
if [[ -z "$2" ]]; then
    directory="$PWD/results/$JOB_NAME"
else
    directory="$2"
fi

if [ ! -d "$directory" ]; then
    mkdir -p "$directory"
    echo "Output directory created: $directory"
else
    echo "Output directory already exists: $directory"
fi

echo "Exporting Ultrack results...."
ultrack export zarr-napari -cfg "$1" -o "$directory" -ow
echo "Exporting Ultrack results complete"