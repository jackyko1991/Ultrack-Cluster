#! /bin/bash

#SBATCH --job-name=LINK
#SBATCH --time=1-06:00:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=15G
#SBATCH --cpus-per-task=1
#SBATCH --output=./slurm_output/link/link-%A_%a.out

env | grep "^SLURM" | sort

# module load anaconda/2022.05
# conda activate dexpv2

ultrack link -cfg "$1" -b $SLURM_ARRAY_TASK_ID $@