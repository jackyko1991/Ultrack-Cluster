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
    calls = {script_of(c): c for c in cluster.sbatch_calls()}
    for script, total, n in [("segment.sh", frames, seg), ("link.sh", frames - 1, link)]:
        lo, hi = _array(calls[script])
        assert lo == 0
        covered = [t for i in range(lo, hi + 1) for t in ultrack_batch_index_range(total, n, i)]
        assert covered == list(range(total)), script          # all items, once, in order
        with pytest.raises(IndexError):                         # no task past the end
            ultrack_batch_index_range(total, n, hi + 1)
        assert opt(calls[script], "--cpus-per-task") == str(n)  # one CPU per worker process


def test_connection_budget_warning(cluster):
    cluster.make_frames(26)
    _set_workers(cluster, 50, 1)
    r = cluster.run("main.sh", BATCH_SIZE=26, MAX_JOBS=20, **FULL)
    assert r.returncode == 0
    assert "may exceed max_connections" in r.stderr
