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

# ---------------------------------------------------------------------------
# PostgreSQL server (create_server.sh / resume_server.sh)
# ---------------------------------------------------------------------------
ULTRACK_PG_MODULE_DEFAULT="PostgreSQL/16.1-GCCcore-12.3.0"

# Make initdb/postgres/... available: the container has them; otherwise load
# ULTRACK_PG_MODULE (set it to "" to use whatever is already on PATH).
load_postgres() {
    if [[ -n "${ULTRACK_SIF:-}" ]]; then
        return 0
    fi
    local mod="${ULTRACK_PG_MODULE-$ULTRACK_PG_MODULE_DEFAULT}"
    if [[ -n "$mod" ]]; then
        module load "$mod"
    fi
    if ! command -v postgres >/dev/null; then
        echo "ERROR: postgres not found (module '$mod'); set ULTRACK_PG_MODULE or ULTRACK_SIF" >&2
        return 1
    fi
}

# `postgres -c` settings sized to this job's actual allocation (pgtune-style
# ratios), passed on every start. Replaces the old ALTER SYSTEM block, which
# was tuned for a 64 GB node regardless of the job's --mem and, in
# resume_server.sh, ran before the server was up so it never applied.
#   $1 memory in MB (default: SLURM_MEM_PER_NODE, or SLURM_MEM_PER_CPU x CPUs, else 4096)
#   $2 CPUs         (default: SLURM_CPUS_PER_TASK, else 2)
pg_tuning_args() {
    local cpus="${2:-${SLURM_CPUS_PER_TASK:-2}}"
    local mem_mb="${1:-}"
    if [[ -z "$mem_mb" && -n "${SLURM_MEM_PER_NODE:-}" ]]; then
        mem_mb="$SLURM_MEM_PER_NODE"
    elif [[ -z "$mem_mb" && -n "${SLURM_MEM_PER_CPU:-}" ]]; then
        mem_mb=$(( SLURM_MEM_PER_CPU * cpus ))
    fi
    mem_mb="${mem_mb:-4096}"
    local max_conn="${ULTRACK_PG_MAX_CONNECTIONS:-500}"
    local shared=$(( mem_mb / 4 ))
    local cache=$(( mem_mb * 3 / 4 ))
    local maint=$(( mem_mb / 16 )); (( maint > 2048 )) && maint=2048
    local work_kb=$(( (mem_mb - shared) * 1024 / (max_conn * 3) )); (( work_kb < 4096 )) && work_kb=4096
    local gather=$(( cpus / 2 )); (( gather < 1 )) && gather=1
    local maint_workers=$gather; (( maint_workers > 4 )) && maint_workers=4
    local args=(
        -c "listen_addresses=*"
        -c "max_connections=$max_conn"
        -c "shared_buffers=${shared}MB"
        -c "effective_cache_size=${cache}MB"
        -c "maintenance_work_mem=${maint}MB"
        -c "work_mem=${work_kb}kB"
        -c "max_worker_processes=$cpus"
        -c "max_parallel_workers=$cpus"
        -c "max_parallel_workers_per_gather=$gather"
        -c "max_parallel_maintenance_workers=$maint_workers"
        -c "checkpoint_completion_target=0.9"
        -c "min_wal_size=1GB"
        -c "max_wal_size=4GB"
        -c "random_page_cost=1.1"
        -c "effective_io_concurrency=200"
        -c "logging_collector=on"
    )
    printf '%s\n' "${args[@]}"
}

# True if something is listening on TCP port $1 on this node.
is_port_in_use() {
    if command -v ss >/dev/null; then
        ss -Hltn "sport = :$1" 2>/dev/null | grep -q .
    else
        lsof -iTCP:"$1" -sTCP:LISTEN -P -n >/dev/null 2>&1
    fi
}

# First free port in [base, base+span], scanning from a random offset so
# several servers starting on one node at once are unlikely to race for the
# same port. Scans the whole range (the old code gave up after 5 random picks).
find_free_port() {
    local base="${1:-5432}" span="${2:-100}"
    local start=$(( RANDOM % (span + 1) )) i port
    for (( i = 0; i <= span; i++ )); do
        port=$(( base + (start + i) % (span + 1) ))
        if ! is_port_in_use "$port"; then
            echo "$port"
            return 0
        fi
    done
    echo "ERROR: no free port in $base-$((base + span))" >&2
    return 1
}

# Block until the server on socket dir $1 / port $2 accepts connections, or
# fail after ULTRACK_DB_START_TIMEOUT seconds (default 300).
wait_for_local_postgres() {
    local socket_dir="$1" port="$2" timeout="${ULTRACK_DB_START_TIMEOUT:-300}" waited=0
    until run_ultrack pg_isready -q -h "$socket_dir" -p "$port"; do
        if (( waited >= timeout )); then
            echo "ERROR: PostgreSQL not ready after ${timeout}s" >&2
            return 1
        fi
        sleep 1
        waited=$(( waited + 1 ))
    done
}

# Shared body of create_server.sh (mode=create) and resume_server.sh
# (mode=resume). Starts PostgreSQL in the background, waits until it accepts
# connections, then -- and only then -- writes the address into the config
# and the ready file workers wait on, and stays up until scancel'd.
#   $1 mode (create|resume)   $2 ultrack config file
run_db_server() {
    local mode="$1" cfg="$2"
    : "${ULTRACK_DB_PW:?ULTRACK_DB_PW must be set}"
    local tag="${JOB_NAME:-${SLURM_JOB_ID:?set JOB_NAME or run under SLURM}}"
    local group
    group=$(getent group "$(id -g)" | cut -d: -f1)
    local work="${ULTRACK_WORK_DIR:-/users/$group/$USER/work}"
    local db_dir="$work/postgresql_ultrack_$tag"
    local socket_dir="$work/tmp_$tag"
    local db_name="ultrack"
    local host="${SLURM_JOB_NODELIST:-$(hostname)}"

    load_postgres || return 1
    mkdir -p "$socket_dir"
    rm -f "$socket_dir"/.s.PGSQL.*

    if [[ "$mode" == create ]]; then
        rm -rf "$db_dir"
        mkdir -p "$db_dir"
        run_ultrack initdb -D "$db_dir" || return 1
        echo "host    all             $USER           samenet                 md5" >> "$db_dir/pg_hba.conf"
    elif [[ ! -d "$db_dir" ]]; then
        echo "ERROR: no database to resume at $db_dir (run create_server.sh first)" >&2
        return 1
    fi

    local port
    port=$(find_free_port 5432 100) || return 1
    local tuning=()
    mapfile -t tuning < <(pg_tuning_args)
    echo "Starting PostgreSQL ($mode) on $host:$port, data $db_dir"
    run_ultrack postgres -D "$db_dir" -p "$port" -k "$socket_dir" "${tuning[@]}" &
    ULTRACK_PG_PID=$!
    # scancel sends SIGTERM to this script: shut PostgreSQL down cleanly so
    # the data directory stays consistent for a later resume.
    trap 'run_ultrack pg_ctl stop -D "'"$db_dir"'" -m fast || true; rm -f "${ULTRACK_DB_READY_FILE:-/nonexistent}"' TERM INT
    if ! wait_for_local_postgres "$socket_dir" "$port"; then
        kill "$ULTRACK_PG_PID" 2>/dev/null || true
        return 1
    fi

    if [[ "$mode" == create ]]; then
        run_ultrack createdb -h "$socket_dir" -p "$port" "$db_name" || return 1
        run_ultrack psql -h "$socket_dir" -p "$port" -c "ALTER USER \"$USER\" PASSWORD '$ULTRACK_DB_PW';" "$db_name" || return 1
    fi

    local addr="$USER:$ULTRACK_DB_PW@$host:$port/$db_name?gssencmode=disable"
    ${DASEL_BIN:-dasel} put -t string -f "$cfg" -v "$addr" "data.address" || return 1
    # the config now carries the DB password in plaintext (ultrack's address
    # format has no separate credential field): owner-only
    chmod 600 "$cfg"
    if [[ -n "${ULTRACK_DB_READY_FILE:-}" ]]; then
        mkdir -p "$(dirname "$ULTRACK_DB_READY_FILE")"
        echo "$host:$port" > "$ULTRACK_DB_READY_FILE"
    fi
    echo "Ultrack DB service ready at $host:$port"
    wait "$ULTRACK_PG_PID"
}
