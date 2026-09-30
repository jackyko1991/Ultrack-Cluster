#! /bin/bash

#SBATCH --job-name=CLEANUP
#SBATCH --time=00:15:00
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=1G
#SBATCH --cpus-per-task=1
#SBATCH --output=./slurm_output/cleanup-%j.out

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

: "${2:?usage: cleanup.sh <DB server job id> <submission manifest>}"
SERVER_JOB_ID="$1"
MANIFEST="$2"
start_stage cleanup

# Runs after the export job ends in any state (main.sh: afterany). Without
# this the DB server holds its node until its --time runs out (10 days in the
# old defaults) unless someone remembers to scancel it.
log INFO "stopping DB server job $SERVER_JOB_ID"
scancel "$SERVER_JOB_ID" || log WARN "scancel $SERVER_JOB_ID failed (already finished?)"

report="$(dirname "$MANIFEST")/resource_report.tsv"
write_resource_report "$MANIFEST" "$report"
log INFO "resource report: $report"
