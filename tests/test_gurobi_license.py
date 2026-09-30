"""solve.sh must hand ultrack a Gurobi license, or python-mip silently uses CBC."""

ULTRACK_ENV_STUB = """#!/bin/bash
echo "ultrack $* GRB_LICENSE_FILE=${GRB_LICENSE_FILE:-}" >> "$STUB_LOG_DIR/calls.log"
"""


def test_license_set_from_default_when_unset(cluster, tmp_path):
    lic = tmp_path / "gurobi.lic"
    lic.write_text("TOKENSERVER=127.0.0.1\n")
    r = cluster.bash('setup_gurobi_license; echo "GRB=$GRB_LICENSE_FILE"',
                     ULTRACK_GUROBI_LICENSE=lic)
    assert r.returncode == 0
    assert f"GRB={lic}" in r.stdout


def test_preset_license_is_not_overridden(cluster, tmp_path):
    lic = tmp_path / "gurobi.lic"
    lic.touch()
    r = cluster.bash('setup_gurobi_license; echo "GRB=$GRB_LICENSE_FILE"',
                     GRB_LICENSE_FILE="/my/own.lic", ULTRACK_GUROBI_LICENSE=lic)
    assert "GRB=/my/own.lic" in r.stdout


def test_missing_license_warns_but_does_not_fail(cluster, tmp_path):
    r = cluster.bash('setup_gurobi_license; echo "rc=$? GRB=${GRB_LICENSE_FILE:-}"',
                     ULTRACK_GUROBI_LICENSE=tmp_path / "absent.lic")
    assert "rc=0 GRB=" in r.stdout
    assert "CBC" in r.stderr


def test_solve_job_passes_license_to_ultrack_and_skips_dead_module(cluster, tmp_path):
    lic = tmp_path / "gurobi.lic"
    lic.touch()
    cluster.stub("ultrack", ULTRACK_ENV_STUB)
    r = cluster.run_as_slurm_job("solve.sh", "config.toml", SLURM_SUBMIT_DIR=cluster.workdir,
                                 SLURM_ARRAY_TASK_ID=3, ULTRACK_GUROBI_LICENSE=lic)
    assert r.returncode == 0, r.stderr + r.stdout
    assert cluster.calls("ultrack") == [f"ultrack solve -cfg config.toml -b 3 GRB_LICENSE_FILE={lic}"]
    assert not any("Gurobi" in c for c in cluster.calls("module"))
