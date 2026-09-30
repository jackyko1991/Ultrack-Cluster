#! /bin/bash
# Shared helpers for the Ultrack-Cluster SLURM scripts. Source it, don't run it.
# Everything here is a plain function so it can be unit-tested in isolation
# (see tests/).

ULTRACK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$ULTRACK_LIB_DIR/find_dasel.sh"

# ceil(a / b) for non-negative integers a, b > 0.
ceil_div() {
    echo $(( ($1 + $2 - 1) / $2 ))
}

# Last 0-based batch index when `total` items are cut into batches of `size`
# -- the same split ultrack's batch_index_range(total, size, index) uses, so a
# SLURM array of 0..last_batch_index covers every item exactly once.
last_batch_index() {
    echo $(( $(ceil_div "$1" "$2") - 1 ))
}

# ultrack solves through python-mip, which uses Gurobi only if it can obtain a
# license and otherwise silently falls back to the much slower CBC solver.
# BMRC's Gurobi token-server license is a plain file; the retired
# `Gurobi/10.0.1-GCCcore-12.2.0` module used to export it, nothing does now.
# Sets GRB_LICENSE_FILE unless the caller already did; never fails the job
# (CBC still works), but says so loudly.
ULTRACK_GUROBI_LICENSE_DEFAULT="/gpfs3/apps/eb/licenses/gurobi.lic"
setup_gurobi_license() {
    if [[ -n "${GRB_LICENSE_FILE:-}" ]]; then
        echo "Gurobi license: $GRB_LICENSE_FILE (preset)"
        return 0
    fi
    local lic="${ULTRACK_GUROBI_LICENSE:-$ULTRACK_GUROBI_LICENSE_DEFAULT}"
    if [[ -f "$lic" ]]; then
        export GRB_LICENSE_FILE="$lic"
        echo "Gurobi license: $GRB_LICENSE_FILE"
    else
        echo "WARNING: no Gurobi license at $lic (set ULTRACK_GUROBI_LICENSE); ultrack will fall back to the slower CBC solver" >&2
    fi
}
