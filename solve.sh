#! /bin/bash

#SBATCH --job-name=SOLVE
#SBATCH --time=12:00:00
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=400G
#SBATCH --cpus-per-task=20
#SBATCH --output=./slurm_output/solve-%A_%a.out

env | grep "^SLURM" | sort

module load anaconda/2022.05
conda activate dexpv2

ultrack solve -cfg $CFG_FILE -b $SLURM_ARRAY_TASK_ID
