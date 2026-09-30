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
