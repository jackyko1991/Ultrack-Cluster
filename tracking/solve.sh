#! /bin/bash

#SBATCH --job-name=SOLVE
#SBATCH --time=1-06:00:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=480G
#SBATCH --cpus-per-task=32
#SBATCH --output=./slurm_output/solve/solve-%A_%a.out

env | grep "^SLURM" | sort

module load Gurobi/10.0.1-GCCcore-12.2.0
# module load anaconda/2022.05
# conda activate dexpv2

ultrack solve -cfg $CFG_FILE -b $SLURM_ARRAY_TASK_ID
