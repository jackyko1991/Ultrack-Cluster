#! /bin/bash

#SBATCH --job-name=SOLVE
#SBATCH --time=1-06:00:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=32G
#SBATCH --cpus-per-task=4
#SBATCH --output=./slurm_output/solve/solve-%A_%a.out

set -euo pipefail  # after the #SBATCH block: sbatch stops reading directives at the first command

# Locate this repo's tracking/ directory. Inside a SLURM job $0 is SLURM's
# spooled copy of this script (e.g. /var/spool/slurmd/job123/slurm_script),
# not this file, so dirname "$0" alone cannot find sibling files.
for _dir in "${ULTRACK_CLUSTER_DIR:-}" "${SLURM_SUBMIT_DIR:-}" "$(dirname "$0")"; do
    if [[ -n "$_dir" && -f "$_dir/ultrack_lib.sh" ]]; then
        ULTRACK_CLUSTER_DIR="$(cd "$_dir" && pwd)"
        break
    fi
done
if [[ ! -f "${ULTRACK_CLUSTER_DIR:-}/ultrack_lib.sh" ]]; then
    echo "ERROR: cannot find ultrack_lib.sh; export ULTRACK_CLUSTER_DIR=<path to tracking/>" >&2
    exit 1
fi
export ULTRACK_CLUSTER_DIR
source "$ULTRACK_CLUSTER_DIR/ultrack_lib.sh"

: "${1:?usage: solve.sh <config.toml>}"

start_stage solve

activate_ultrack_env || exit 1
wait_for_db || exit 1
setup_gurobi_license
# ultrack's own CLI needs Qt/OpenGL/fontconfig just to start (0.8.0); see ultrack_worker.py
run_ultrack python "$ULTRACK_CLUSTER_DIR/ultrack_worker.py" solve -cfg "$1" -b "${SLURM_ARRAY_TASK_ID:?must run as a SLURM array task (sbatch --array)}"
