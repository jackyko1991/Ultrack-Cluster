#! /bin/bash
# Resolves the `dasel` (github.com/TomWright/dasel) binary main.sh needs to
# read tracking.window_size from config.toml, self-healing instead of
# depending on install_server_dependency.sh having been run and having
# added its install directory to ~/.bashrc: that only works in an
# interactive login shell, breaks the moment dasel's install location
# changes, and silently produces WINDOW_SIZE="" (NUM_WINDOWS=-1, an
# invalid SLURM array spec) in any shell that doesn't source .bashrc
# (e.g. a non-interactive `ssh host 'bash main.sh'`).
#
# Resolution order: PATH, then the conventional install_server_dependency.sh
# location, then a fresh download to that same location (same URL
# install_server_dependency.sh uses). Only called from main.sh, which runs
# on the login node (has internet); create_server.sh/resume_server.sh use
# the exported $DASEL_BIN instead of re-resolving inside the SLURM job, so
# a compute node never needs its own internet access for this.
resolve_dasel() {
    if command -v dasel >/dev/null 2>&1; then
        command -v dasel
        return 0
    fi

    local group_name install_dir bin_path
    group_name=$(getent group "$GROUPS" | cut -d: -f1)
    install_dir="${DASEL_INSTALL_DIR:-/users/$group_name/$USER/work/software/dasel}"
    bin_path="$install_dir/dasel"

    if [[ -x "$bin_path" ]]; then
        echo "$bin_path"
        return 0
    fi

    echo "dasel not found on PATH or at $bin_path -- downloading (see install_server_dependency.sh)" >&2
    mkdir -p "$install_dir"
    if wget -q "https://github.com/TomWright/dasel/releases/download/v2.8.1/dasel_linux_amd64" -O "$bin_path" && chmod +x "$bin_path"; then
        echo "$bin_path"
        return 0
    fi

    echo "ERROR: could not find or install dasel (checked PATH and $bin_path)" >&2
    return 1
}
