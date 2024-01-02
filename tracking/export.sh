#! /bin/bash

#SBATCH --job-name=EXPORT
#SBATCH --time=00:25:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=500G
#SBATCH --cpus-per-task=50
#SBATCH --output=./slurm_output/export-%j.out

ultrack export zarr-napari -cfg $CFG_FILE -o results --measure -r napari-ome-zarr -i ../result.zarr