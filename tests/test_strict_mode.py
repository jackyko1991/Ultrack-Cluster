"""Failures must fail the job (no more 'COMPLETED' with nothing done)."""
import pytest

SCRIPTS = ["main.sh", "segment.sh", "link.sh", "solve.sh", "export.sh", "cleanup.sh",
           "create_server.sh", "resume_server.sh"]
FAILING = "#!/bin/bash\necho \"$(basename \"$0\") $*\" >> \"$STUB_LOG_DIR/calls.log\"\nexit 3\n"


@pytest.mark.parametrize("script", SCRIPTS)
def test_strict_mode_is_on_and_after_sbatch_directives(cluster, script):
    lines = (cluster.workdir / script).read_text().splitlines()
    assert lines[0] in ("#!/bin/bash", "#! /bin/bash"), script
    strict = [i for i, l in enumerate(lines) if l.startswith("set -euo pipefail")]
    assert strict, f"{script} lacks set -euo pipefail"
    sbatch = [i for i, l in enumerate(lines) if l.startswith("#SBATCH")]
    # sbatch ignores #SBATCH lines after the first command
    assert not sbatch or max(sbatch) < strict[0], script


def test_export_failure_is_not_reported_as_success(cluster):
    # export.sh used to end with `echo "... complete"`, masking ultrack's exit code
    cluster.stub("ultrack", FAILING)
    r = cluster.run_as_slurm_job("export.sh", "config.toml", SLURM_SUBMIT_DIR=cluster.workdir)
    assert r.returncode != 0
    assert "complete" not in r.stdout.split("\n")[-2:]


def test_segment_without_python_fails(cluster):
    # the 2026-09-30 smoke test: python missing, job still exited 0
    cluster.stub("python", FAILING)
    r = cluster.run_as_slurm_job("segment.sh", "labels/*.tif", "config.toml", "0", "5",
                                 SLURM_SUBMIT_DIR=cluster.workdir, SLURM_ARRAY_TASK_ID=0)
    assert r.returncode != 0


@pytest.mark.parametrize("script", ["link.sh", "solve.sh"])
def test_missing_arguments_give_usage_errors(cluster, script):
    r = cluster.run_as_slurm_job(script, SLURM_SUBMIT_DIR=cluster.workdir, SLURM_ARRAY_TASK_ID=0)
    assert r.returncode != 0
    assert "usage" in r.stderr
    assert cluster.calls("ultrack") == []


def test_worker_outside_an_array_job_fails_clearly(cluster):
    r = cluster.run_as_slurm_job("link.sh", "config.toml", SLURM_SUBMIT_DIR=cluster.workdir)
    assert r.returncode != 0
    assert "array task" in r.stderr


def test_main_with_missing_data_dir_submits_nothing(cluster):
    r = cluster.run("main.sh", DATA_DIR=cluster.root / "nope", SKIP_SEG="false", SKIP_LINK="false")
    assert r.returncode != 0
    assert cluster.sbatch_calls() == []


def test_main_refuses_fewer_than_two_frames(cluster):
    cluster.make_frames(1)
    r = cluster.run("main.sh", BATCH_SIZE=1, BATCH="1", POST_PADDING="0",
                    SKIP_SEG="false", SKIP_LINK="false")
    assert r.returncode != 0
    assert "at least 2 time points" in r.stderr
    assert cluster.sbatch_calls() == []


def test_main_stops_if_a_submission_fails(cluster):
    cluster.make_frames(6)
    cluster.stub("sbatch", "#!/bin/bash\necho 'sbatch: error: invalid partition' >&2\nexit 1\n")
    r = cluster.run("main.sh", BATCH_SIZE=6, BATCH="1", POST_PADDING="0",
                    SKIP_SEG="false", SKIP_LINK="false")
    assert r.returncode != 0


def test_run_ultrack_with_empty_container_args_under_nounset(cluster):
    r = cluster.bash("set -u; run_ultrack ultrack link -b 0", ULTRACK_SIF="/i.sif", ULTRACK_SIF_ARGS="")
    assert r.returncode == 0, r.stderr
    assert cluster.calls("apptainer") == ["apptainer exec /i.sif ultrack link -b 0"]
