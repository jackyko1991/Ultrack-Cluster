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

: "${4:?usage: segment.sh <label path pattern> <config.toml> <begin time> <end time>}"

env | grep "^SLURM" | sort || true

activate_ultrack_env || exit 1
wait_for_db || exit 1

# ultrack segment $1 -cfg $CFG_FILE \
#     -b $SLURM_ARRAY_TASK_ID -r napari-ome-zarr -el edge -dl detection

# binning will automatically take care of length of data, for specfic time range edit in main.sh
# reserver length for reference
run_ultrack python "$ULTRACK_CLUSTER_DIR/segment.py" -p "$1" --cfg "$2" -b "$3" -e "$4" -bi "${SLURM_ARRAY_TASK_ID:?must run as a SLURM array task (sbatch --array)}" -bp 3