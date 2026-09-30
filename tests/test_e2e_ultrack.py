"""
End to end with real ultrack: segment.py -> ultrack_worker.py link / solve /
export, on synthetic moving cells, with an SQLite database (no cluster, no
PostgreSQL). Batches run one after another in the order main.sh's jobs do:
segment batch 0 first (it creates the tables), then the others; link; solve
even windows then odd; export.

Skipped unless ultrack is importable (e.g. the pixi `default` environment or
the container image).
"""
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ultrack")
zarr = pytest.importorskip("zarr")

TRACKING = Path(__file__).resolve().parents[1] / "tracking"
T, Y, X = 10, 64, 64
N_CELLS = 3
FRAMES_PER_TASK = 5      # segmentation/linking n_workers
WINDOW = 5               # tracking.window_size -> windows 0 and 1 for 10 frames


def _moving_cells():
    labels = np.zeros((T, Y, X), dtype=np.uint16)
    yy, xx = np.mgrid[:Y, :X]
    for t in range(T):
        for c in range(N_CELLS):
            cy, cx = 12 + 20 * c, 10 + 3 * t          # each cell drifts right 3 px/frame
            labels[t][(yy - cy) ** 2 + (xx - cx) ** 2 <= 36] = c + 1
    return labels


def _zarr_source(tmp_path, labels):
    root = zarr.open_group(str(tmp_path / "exp.zarr"), mode="w")
    group = root.require_group("labels/Cellpose/TCell")
    group.create_array("0", data=labels[:, None], chunks=(1, 1, Y, X))   # TZYX, Z=1 (pyCyto layout)
    group.attrs["ome"] = {"version": "0.5", "multiscales": [
        {"axes": [{"name": a} for a in "tzyx"], "datasets": [{"path": "0"}]}]}
    return f"{tmp_path}/exp.zarr#labels/Cellpose/TCell"


def _config(tmp_path):
    text = (TRACKING / "config_sqlite.toml").read_text()
    text = re.sub(r"working_dir = .*", f"working_dir = '{tmp_path / 'db'}'", text)
    text = re.sub(r"n_workers = \d+", f"n_workers = {FRAMES_PER_TASK}", text)
    text = re.sub(r"window_size = \d+", f"window_size = {WINDOW}", text)
    text = re.sub(r"min_area = \d+", "min_area = 20", text)
    text = re.sub(r"max_area = \d+", "max_area = 400", text)
    cfg = tmp_path / "config.toml"
    cfg.write_text(text)
    (tmp_path / "db").mkdir()
    return cfg


def _run(*args):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"{args}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}"
    return r


def test_full_pipeline_recovers_every_track(tmp_path):
    src = _zarr_source(tmp_path, _moving_cells())
    cfg = _config(tmp_path)

    for batch in range(-(-T // FRAMES_PER_TASK)):                     # segment: 0 first
        _run(TRACKING / "segment.py", "-p", src, "-c", cfg, "-b", 0, "-e", T - 1,
             "-bi", batch, "-bp", 1)
    for batch in range(-(-(T - 1) // FRAMES_PER_TASK)):               # link
        _run(TRACKING / "ultrack_worker.py", "link", "-cfg", cfg, "-b", batch)
    last_window = -(-(T - 1) // WINDOW) - 1
    for window in list(range(0, last_window + 1, 2)) + list(range(1, last_window + 1, 2)):
        _run(TRACKING / "ultrack_worker.py", "solve", "-cfg", cfg, "-b", window)
    out = tmp_path / "results"
    _run(TRACKING / "ultrack_worker.py", "export", "-cfg", cfg, "-o", out)

    import pandas as pd
    tracks = pd.read_csv(out / "tracks.csv")
    assert tracks["track_id"].nunique() == N_CELLS, tracks.groupby("track_id")["t"].agg(["min", "max"])
    for _, track in tracks.groupby("track_id"):
        assert sorted(track["t"]) == list(range(T))                   # unbroken, every frame
        assert np.all(np.diff(track.sort_values("t")["x"]) > 0)       # moving right, as simulated
    segments = zarr.open(str(out / "segments.zarr"), mode="r")
    assert segments.shape[0] == T

    # export refuses to clobber without -ow, and replaces with it
    r = subprocess.run([sys.executable, TRACKING / "ultrack_worker.py", "export", "-cfg", cfg, "-o", out],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "exists" in r.stderr
    _run(TRACKING / "ultrack_worker.py", "export", "-cfg", cfg, "-o", out, "-ow")


def test_segment_batch_zero_alone_owns_the_reset(tmp_path):
    """A later batch must never clear what earlier batches inserted."""
    from sqlalchemy import create_engine, text

    src = _zarr_source(tmp_path, _moving_cells())
    cfg = _config(tmp_path)
    db = create_engine(f"sqlite:///{tmp_path / 'db' / 'data.db'}")

    _run(TRACKING / "segment.py", "-p", src, "-c", cfg, "-e", T - 1, "-bi", 0)
    _run(TRACKING / "segment.py", "-p", src, "-c", cfg, "-e", T - 1, "-bi", 1)
    with db.connect() as c:
        frames = {r[0] for r in c.execute(text("select distinct t from nodes"))}
    assert frames == set(range(T))            # batch 1 kept batch 0's frames 0-4
