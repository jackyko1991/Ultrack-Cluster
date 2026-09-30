"""Every stage gets explicit, right-sized, overridable resource requests."""
import re

from conftest import opt, script_of
from test_batching import _set_workers

FULL = dict(SKIP_SEG="false", SKIP_LINK="false", BATCH="1", POST_PADDING="0", JOB_NAME="j")


def _by_script(cluster):
    out = {}
    for argv in cluster.sbatch_calls():
        out.setdefault(script_of(argv), argv)
    return out


def test_default_requests(cluster):
    cluster.make_frames(26)
    r = cluster.run("main.sh", BATCH_SIZE=26, **FULL)
    assert r.returncode == 0, r.stderr
    c = _by_script(cluster)
    assert (opt(c["create_server.sh"], "--mem"), opt(c["create_server.sh"], "--cpus-per-task"),
            opt(c["create_server.sh"], "--time")) == ("64G", "8", "7-00:00:00")
    assert opt(c["segment.sh"], "--mem") == "4G"
    assert opt(c["link.sh"], "--mem") == "4G"
    assert (opt(c["solve.sh"], "--mem"), opt(c["solve.sh"], "--cpus-per-task")) == ("32G", "4")
    assert opt(c["export.sh"], "--mem") == "32G"


def test_segment_link_memory_scales_with_frames_per_task(cluster):
    cluster.make_frames(26)
    _set_workers(cluster, 3, 5)
    cluster.run("main.sh", BATCH_SIZE=26, **FULL)
    c = _by_script(cluster)
    assert opt(c["segment.sh"], "--mem") == "12G"
    assert opt(c["link.sh"], "--mem") == "20G"


def test_requests_are_overridable(cluster):
    cluster.make_frames(26)
    cluster.run("main.sh", BATCH_SIZE=26, SOLVE_MEM="8G", SOLVE_CPUS=2, DB_MEM="16G",
                SEG_MEM_GB_PER_WORKER=1, EXPORT_TIME="02:00:00", **FULL)
    c = _by_script(cluster)
    assert opt(c["solve.sh"], "--mem") == "8G" and opt(c["solve.sh"], "--cpus-per-task") == "2"
    assert opt(c["create_server.sh"], "--mem") == "16G"
    assert opt(c["segment.sh"], "--mem") == "1G"
    assert opt(c["export.sh"], "--time") == "02:00:00"


def test_every_submission_states_its_memory(cluster):
    cluster.make_frames(26)
    cluster.run("main.sh", BATCH_SIZE=26, **FULL)
    for argv in cluster.sbatch_calls():
        if script_of(argv) != "cleanup.sh":
            assert opt(argv, "--mem"), script_of(argv)


def test_solver_thread_warning(cluster):
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, **FULL)
    assert "tracking.n_threads = 0" in r.stderr
    cfg = cluster.workdir / "config.toml"
    cfg.write_text(re.sub(r"n_threads = 0", "n_threads = 4", cfg.read_text()))
    r = cluster.run("main.sh", BATCH_SIZE=6, **FULL)
    assert "n_threads" not in r.stderr
