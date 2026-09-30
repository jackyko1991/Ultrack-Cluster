#! /bin/bash

#SBATCH --job-name=EXPORT
#SBATCH --time=24:00:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=16G
#SBATCH --cpus-per-task=1
#SBATCH --output=./slurm_output/export-%j.out

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

activate_ultrack_env

env | grep "^SLURM" | sort

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
run_ultrack ultrack export zarr-napari -cfg "$1" -o "$directory" -ow
echo "Exporting Ultrack results complete"