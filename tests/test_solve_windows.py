"""Odd solve windows depend only on their even neighbours."""
import pytest
from conftest import opt, script_of

FULL = dict(SKIP_SEG="false", SKIP_LINK="false", BATCH="1", POST_PADDING="0", JOB_NAME="j")


def _run(cluster, last_window, **env):
    # window_size 20; frames = 20*(last_window) + 2 gives DS_LENGTH with that last index
    frames = 20 * last_window + 2
    cluster.make_frames(frames)
    r = cluster.run("main.sh", BATCH_SIZE=frames, **FULL, **env)
    assert r.returncode == 0, r.stderr
    calls = cluster.sbatch_calls()
    ids = {i + 1001: c for i, c in enumerate(calls)}
    return calls, ids


@pytest.mark.parametrize("last_window", [1, 2, 3, 4, 7])
def test_each_odd_window_waits_for_exactly_its_existing_neighbours(cluster, last_window):
    calls, ids = _run(cluster, last_window)
    solves = [(i, c) for i, c in ids.items() if script_of(c) == "solve.sh"]
    even_id, even = solves[0]
    assert opt(even, "--array") == f"0-{last_window}:2"
    odd = solves[1:]
    assert [opt(c, "--array") for _, c in odd] == [f"{w}-{w}" for w in range(1, last_window + 1, 2)]
    for _, c in odd:
        w = int(opt(c, "--array").split("-")[0])
        expected = [f"{even_id}_{w - 1}"] + ([f"{even_id}_{w + 1}"] if w + 1 <= last_window else [])
        assert opt(c, "-d") == "afterok:" + ":".join(expected)
    (export,) = [c for c in calls if script_of(c) == "export.sh"]
    waits_for = set(opt(export, "-d").removeprefix("afterok:").split(":"))
    assert waits_for == {str(i) for i, _ in solves}      # every solve job, even and odd


def test_single_window_has_no_odd_pass(cluster):
    calls, ids = _run(cluster, 0)
    solves = [c for c in calls if script_of(c) == "solve.sh"]
    assert [opt(c, "--array") for c in solves] == ["0-0"]


def test_two_pass_layout_still_available(cluster):
    calls, ids = _run(cluster, 4, SOLVE_PER_WINDOW_DEPS="false")
    solves = [(i, c) for i, c in ids.items() if script_of(c) == "solve.sh"]
    assert [opt(c, "--array") for _, c in solves] == ["0-4:2", "1-4:2"]
    assert opt(solves[1][1], "-d") == f"afterok:{solves[0][0]}"


def test_even_pass_throttle(cluster):
    calls, _ = _run(cluster, 4, MAX_SOLVE_JOBS=3)
    even = next(c for c in calls if script_of(c) == "solve.sh")
    assert opt(even, "--array") == "0-4:2%3"
