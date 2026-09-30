"""Job scripts activate their Python environment explicitly (not inherited)."""
import os

WHICH_PYTHON_STUB = """#!/bin/bash
echo "python-from-env $*" >> "$STUB_LOG_DIR/calls.log"
"""


def test_conda_prefix_is_put_first_on_path(cluster, tmp_path):
    env_dir = tmp_path / "envs" / "ultrack"
    (env_dir / "bin").mkdir(parents=True)
    py = env_dir / "bin" / "python"
    py.write_text(WHICH_PYTHON_STUB)
    py.chmod(0o755)
    r = cluster.bash("activate_ultrack_env && python segment.py", ULTRACK_CONDA_ENV=env_dir)
    assert r.returncode == 0, r.stderr
    assert "python-from-env segment.py" in cluster.calls("python-from-env")[0]


def test_activate_file_is_sourced(cluster, tmp_path):
    act = tmp_path / "activate"
    act.write_text("export MARKER=activated\n")
    r = cluster.bash('activate_ultrack_env && echo "m=$MARKER"', ULTRACK_ENV_ACTIVATE=act)
    assert "m=activated" in r.stdout


def test_failing_activation_is_an_error_even_without_strict_mode(cluster, tmp_path):
    act = tmp_path / "activate"
    act.write_text("false\n")
    r = cluster.bash("activate_ultrack_env; echo rc=$?", ULTRACK_ENV_ACTIVATE=act)
    assert "rc=1" in r.stdout


def test_activation_restores_strict_mode(cluster, tmp_path):
    # rc files run with -eu relaxed, but the caller's options must come back
    act = tmp_path / "activate"
    act.write_text("echo $UNSET_VARIABLE_IN_RCFILE >/dev/null\n")
    r = cluster.bash("set -euo pipefail; activate_ultrack_env; set -o | grep -E '^(errexit|nounset|pipefail)'",
                     ULTRACK_ENV_ACTIVATE=act)
    assert r.returncode == 0, r.stderr
    assert all(line.split()[1] == "on" for line in r.stdout.strip().splitlines()[-3:])


def test_run_ultrack_uses_container_when_sif_set(cluster):
    r = cluster.bash("run_ultrack ultrack link -cfg c.toml -b 0",
                     ULTRACK_SIF="/imgs/ultrack.sif", ULTRACK_SIF_ARGS="--bind /data")
    assert r.returncode == 0, r.stderr
    assert cluster.calls("apptainer") == ["apptainer exec --bind /data /imgs/ultrack.sif ultrack link -cfg c.toml -b 0"]
    assert cluster.calls("ultrack") == []


def test_run_ultrack_runs_directly_without_sif(cluster):
    cluster.bash("run_ultrack ultrack solve -cfg c.toml -b 1")
    assert cluster.calls("ultrack") == ["ultrack solve -cfg c.toml -b 1"]
    assert cluster.calls("apptainer") == []


def test_worker_scripts_no_longer_hardcode_an_env(cluster):
    for script in ["segment.sh", "link.sh", "solve.sh", "export.sh"]:
        text = (cluster.workdir / script).read_text()
        assert "mamba activate" not in text, script
        assert "activate_ultrack_env" in text, script


def test_pixi_env_is_activated_from_repo_manifest(cluster):
    cluster.stub("pixi", '#!/bin/bash\necho "pixi $*" >> "$STUB_LOG_DIR/calls.log"\necho "export MARKER=pixi-$3"\n')
    r = cluster.bash('activate_ultrack_env && echo "m=$MARKER"', ULTRACK_PIXI_ENV="gpu")
    assert r.returncode == 0, r.stderr
    assert "m=pixi-gpu" in r.stdout
    call = next(c for c in cluster.calls("pixi") if c.startswith("pixi shell-hook"))
    assert call.startswith("pixi shell-hook -e gpu --manifest-path ") and call.endswith("/pixi.toml")


def test_container_gets_nv_only_on_gpu_allocations(cluster):
    base = dict(ULTRACK_SIF="/imgs/u.sif", ULTRACK_SIF_ARGS="--bind /data")
    cluster.bash("run_ultrack python segment.py", **base)
    cluster.bash("run_ultrack python segment.py", SLURM_JOB_GPUS="0", **base)
    assert cluster.calls("apptainer") == [
        "apptainer exec --bind /data /imgs/u.sif python segment.py",
        "apptainer exec --nv --bind /data /imgs/u.sif python segment.py",
    ]


def test_pixi_found_in_default_install_dir_when_not_on_path(cluster, tmp_path):
    home = tmp_path / "h"
    (home / ".pixi" / "bin").mkdir(parents=True)
    pixi = home / ".pixi" / "bin" / "pixi"
    pixi.write_text('#!/bin/bash\necho "export MARKER=found-$3"\n')
    pixi.chmod(0o755)
    r = cluster.bash('activate_ultrack_env && echo "m=$MARKER"', ULTRACK_PIXI_ENV="default", HOME=home,
                     PATH=f"{cluster.bindir}:/usr/bin:/bin")      # no pixi on PATH
    assert r.returncode == 0, r.stderr
    assert "m=found-default" in r.stdout


def test_pixi_for_another_architecture_on_path_is_skipped(cluster, tmp_path):
    # ~/.pixi-aarch64/bin first on PATH (BMRC login shells): found, but cannot run on x86
    bad = tmp_path / "pixi-aarch64" / "pixi"
    bad.parent.mkdir()
    bad.write_text("#!/bin/bash\nexit 126\n")
    bad.chmod(0o755)
    good = tmp_path / "home-pixi" / "bin" / "pixi"
    good.parent.mkdir(parents=True)
    good.write_text('#!/bin/bash\n[[ $1 == --version ]] && { echo pixi 0.71; exit 0; }\necho "export MARKER=good-$3"\n')
    good.chmod(0o755)
    # PATH = the ARM pixi + system tools only (no host pixi to fall back on)
    r = cluster.bash(f'PATH="{bad.parent}:{cluster.bindir}:/usr/bin:/bin"; activate_ultrack_env && echo "m=$MARKER"',
                     ULTRACK_PIXI_ENV="default", PIXI_HOME=good.parent.parent)
    assert r.returncode == 0, r.stderr
    assert "m=good-default" in r.stdout


def test_ultrack_pixi_bin_overrides_path(cluster, tmp_path):
    good = tmp_path / "pixi"
    good.write_text('#!/bin/bash\n[[ $1 == --version ]] && exit 0\necho "export MARKER=explicit"\n')
    good.chmod(0o755)
    r = cluster.bash('activate_ultrack_env && echo "m=$MARKER"', ULTRACK_PIXI_ENV="default", ULTRACK_PIXI_BIN=good)
    assert "m=explicit" in r.stdout
