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

# Activate the environment ultrack runs in, explicitly and inside the job,
# rather than relying on whatever the submitting shell happened to have
# active (sbatch copies that environment, so a submission from a fresh shell
# silently ran with no ultrack/python at all). First match wins:
#   ULTRACK_SIF           -> nothing to activate; run_ultrack uses the image
#   ULTRACK_ENV_ACTIVATE  -> file to source (e.g. a venv's bin/activate)
#   ULTRACK_CONDA_ENV     -> conda env prefix (a directory) or name
#   (none)                -> legacy: source ~/.bashrc; mamba activate cyto
activate_ultrack_env() {
    if [[ -n "${ULTRACK_SIF:-}" ]]; then
        echo "Environment: container $ULTRACK_SIF"
        return 0
    fi
    # rc files and activate scripts are rarely safe under `set -euo pipefail`.
    # (Save flags from $-, not $(set +o): command substitution runs in a
    # subshell that drops errexit, so that would silently disable set -e.)
    local saved_flags=$-
    set +eu
    if [[ -n "${ULTRACK_ENV_ACTIVATE:-}" ]]; then
        source "$ULTRACK_ENV_ACTIVATE"
    elif [[ -n "${ULTRACK_CONDA_ENV:-}" && -d "$ULTRACK_CONDA_ENV" ]]; then
        export CONDA_PREFIX="$ULTRACK_CONDA_ENV"
        export PATH="$ULTRACK_CONDA_ENV/bin:$PATH"
    elif [[ -n "${ULTRACK_CONDA_ENV:-}" ]]; then
        source "$(conda info --base)/etc/profile.d/conda.sh" && conda activate "$ULTRACK_CONDA_ENV"
    else
        [[ -f ~/.bashrc ]] && source ~/.bashrc
        mamba activate cyto
    fi
    local rc=$?
    if [[ $saved_flags == *u* ]]; then set -u; fi
    if [[ $saved_flags == *e* ]]; then set -e; fi
    if [[ $rc -ne 0 ]]; then
        echo "ERROR: failed to activate the ultrack environment" >&2
        return 1
    fi
    echo "Environment: python=$(command -v python || echo MISSING)"
}

# Run an ultrack/python command, inside ULTRACK_SIF when set. Bind mounts
# default to the BMRC filesystems that exist on this node; override with
# ULTRACK_SIF_ARGS.
run_ultrack() {
    if [[ -z "${ULTRACK_SIF:-}" ]]; then
        "$@"
        return
    fi
    local args
    if [[ -n "${ULTRACK_SIF_ARGS+x}" ]]; then
        read -r -a args <<< "$ULTRACK_SIF_ARGS"
    else
        args=()
        local p
        for p in /gpfs3 /well /users; do
            [[ -d "$p" ]] && args+=(--bind "$p")
        done
    fi
    apptainer exec "${args[@]}" "$ULTRACK_SIF" "$@"
}
