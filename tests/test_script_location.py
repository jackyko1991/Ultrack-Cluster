"""Job scripts must find their sibling files even when run from SLURM's spool."""


def test_segment_job_finds_segment_py_from_spool_copy(cluster):
    r = cluster.run_as_slurm_job(
        "segment.sh", "labels/*.tif", "config.toml", "0", "5",
        SLURM_SUBMIT_DIR=cluster.workdir, SLURM_ARRAY_TASK_ID=0,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    (call,) = cluster.calls("python")
    assert call.split()[1] == f"{cluster.workdir}/segment.py"


def test_explicit_cluster_dir_wins_over_submit_dir(cluster):
    r = cluster.run_as_slurm_job(
        "link.sh", "config.toml",
        ULTRACK_CLUSTER_DIR=cluster.workdir, SLURM_SUBMIT_DIR=cluster.root,
        SLURM_ARRAY_TASK_ID=0,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert cluster.calls("python") == [f"python {cluster.workdir}/ultrack_worker.py link -cfg config.toml -b 0"]


def test_job_fails_clearly_when_repo_cannot_be_found(cluster):
    r = cluster.run_as_slurm_job(
        "link.sh", "config.toml", SLURM_SUBMIT_DIR=cluster.root, SLURM_ARRAY_TASK_ID=0,
    )
    assert r.returncode != 0
    assert "ULTRACK_CLUSTER_DIR" in r.stderr
    assert cluster.calls("python") == []


def test_main_exports_cluster_dir_for_jobs(cluster):
    # sbatch propagates the submitting environment (--export=ALL), so what
    # sbatch sees is what the job scripts see.
    cluster.stub("sbatch", """#!/bin/bash
echo "$ULTRACK_CLUSTER_DIR" >> "$STUB_LOG_DIR/sbatch_env"
echo 1001
""")
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, SKIP_SEG="false", SKIP_LINK="false",
                    BATCH="1", POST_PADDING="0")
    assert r.returncode == 0, r.stderr + r.stdout
    seen = set((cluster.logdir / "sbatch_env").read_text().split())
    assert seen == {str(cluster.workdir)}


def test_dasel_downloads_are_pinned_to_v2(cluster):
    # dasel v3 may change the CLI; main.sh and run_db_server use v2 syntax
    for script in ["find_dasel.sh", "install_server_dependency.sh"]:
        text = (cluster.workdir / script).read_text()
        assert "releases/latest" not in text, script
        assert "releases/download/v2." in text, script
