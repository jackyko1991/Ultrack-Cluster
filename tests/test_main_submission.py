"""main.sh job-graph submission, checked against a fake sbatch."""
from conftest import opt, script_of

FULL_RUN = dict(SKIP_SEG="false", SKIP_LINK="false", BATCH="1", POST_PADDING="0")


def _by_script(calls):
    out = {}
    for argv in calls:
        out.setdefault(script_of(argv), []).append(argv)
    return out


def test_last_batch_index_matches_ultrack_batch_split(cluster):
    cases = {(5, 20): 0, (20, 20): 0, (21, 20): 1, (40, 20): 1, (41, 20): 2, (1, 1): 0, (7, 3): 2}
    for (total, size), expected in cases.items():
        r = cluster.bash(f"last_batch_index {total} {size}")
        assert r.returncode == 0, r.stderr
        assert int(r.stdout) == expected, (total, size)


def test_single_window_submits_one_solve_task(cluster):
    # 6 frames -> DS_LENGTH=5, window_size=20 -> one window (index 0): the
    # case PR #2 fixed (the old "-eq 1" check mishandled it).
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, **FULL_RUN)
    assert r.returncode == 0, r.stderr + r.stdout
    solves = _by_script(cluster.sbatch_calls())["solve.sh"]
    assert len(solves) == 1
    assert opt(solves[0], "--array") == "0-0"


def test_two_windows_submit_even_then_odd(cluster):
    # 26 frames -> DS_LENGTH=25 -> ceil(25/20)-1 = 1 -> windows 0 and 1.
    cluster.make_frames(26)
    r = cluster.run("main.sh", BATCH_SIZE=26, **FULL_RUN)
    assert r.returncode == 0, r.stderr + r.stdout
    solves = _by_script(cluster.sbatch_calls())["solve.sh"]
    arrays = [opt(a, "--array").split("%")[0] for a in solves]
    assert arrays == ["0-1:2", "1-1:2"]


def test_config_is_overridable_from_environment(cluster):
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, JOB_NAME="my_job", **FULL_RUN)
    assert r.returncode == 0, r.stderr + r.stdout
    names = [opt(a, "--job-name") for a in cluster.sbatch_calls()]
    assert "DATABASE_my_job" in names
    assert "SEGMENT_my_job" in names
