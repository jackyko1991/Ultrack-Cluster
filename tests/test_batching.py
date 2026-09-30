"""Array sizes follow the config's n_workers, exactly as ultrack splits work."""
import re

import pytest
from conftest import opt, script_of

FULL = dict(SKIP_SEG="false", SKIP_LINK="false", BATCH="1", POST_PADDING="0", JOB_NAME="j")


def ultrack_batch_index_range(total, n_workers, batch_index):
    """ultrack.utils.multiprocessing.batch_index_range (royerlab/ultrack@5dc7839)."""
    start = list(range(0, total, n_workers))[batch_index]   # IndexError past the end
    return range(start, min(start + n_workers, total))


def _set_workers(cluster, seg, link):
    cfg = cluster.workdir / "config.toml"
    text = cfg.read_text()
    text = re.sub(r"(\[segmentation\][^\[]*?n_workers = )\d+", rf"\g<1>{seg}", text, flags=re.S)
    text = re.sub(r"(\[linking\][^\[]*?n_workers = )\d+", rf"\g<1>{link}", text, flags=re.S)
    cfg.write_text(text)


def _array(argv):
    lo, hi = opt(argv, "--array").split("%")[0].split("-")
    return int(lo), int(hi)


@pytest.mark.parametrize("frames,seg,link", [(26, 1, 1), (26, 4, 4), (26, 5, 3), (6, 8, 8), (100, 7, 10)])
def test_arrays_cover_every_item_exactly_once(cluster, frames, seg, link):
    cluster.make_frames(frames)
    _set_workers(cluster, seg, link)
    r = cluster.run("main.sh", BATCH_SIZE=frames, **FULL)
    assert r.returncode == 0, r.stderr
    calls = {}
    for c in cluster.sbatch_calls():
        calls.setdefault(script_of(c), []).append(c)   # segment: init (batch 0) + rest
    for script, total, n in [("segment.sh", frames, seg), ("link.sh", frames - 1, link)]:
        ranges = [_array(c) for c in calls[script]]
        assert ranges[0][0] == 0
        indices = [i for lo, hi in ranges for i in range(lo, hi + 1)]
        covered = [t for i in indices for t in ultrack_batch_index_range(total, n, i)]
        assert covered == list(range(total)), script          # all items, once, in order
        with pytest.raises(IndexError):                         # no task past the end
            ultrack_batch_index_range(total, n, indices[-1] + 1)
        for c in calls[script]:
            assert opt(c, "--cpus-per-task") == str(n)          # one CPU per worker process


def test_connection_budget_warning(cluster):
    cluster.make_frames(26)
    _set_workers(cluster, 50, 1)
    r = cluster.run("main.sh", BATCH_SIZE=26, MAX_JOBS=20, **FULL)
    assert r.returncode == 0
    assert "may exceed max_connections" in r.stderr


@pytest.mark.parametrize("frames,binning", [(12, 2), (13, 2), (91, 3), (6, 1)])
def test_binning_reaches_segment_and_matches_array_sizes(cluster, frames, binning):
    # segment.py reads frames[begin:end+1:binning]; the arrays must be sized
    # for exactly that many steps, and segment.sh must pass the step on
    cluster.make_frames(frames)
    r = cluster.run("main.sh", BATCH_SIZE=frames, BINNING=binning, **FULL)
    assert r.returncode == 0, r.stderr
    steps = len(range(0, frames, binning))
    segs = [c for c in cluster.sbatch_calls() if script_of(c) == "segment.sh"]
    covered = sum(_array(c)[1] - _array(c)[0] + 1 for c in segs)      # n_workers = 1
    assert covered == steps
    link = next(c for c in cluster.sbatch_calls() if script_of(c) == "link.sh")
    assert _array(link) == (0, steps - 2)


def test_segment_job_passes_binning_to_segment_py(cluster):
    r = cluster.run_as_slurm_job("segment.sh", "labels/*.tif", "config.toml", "0", "11",
                                 SLURM_SUBMIT_DIR=cluster.workdir, SLURM_ARRAY_TASK_ID=0, BINNING=3)
    assert r.returncode == 0, r.stderr
    (call,) = cluster.calls("python")
    assert call.split()[-2:] == ["-s", "3"]
