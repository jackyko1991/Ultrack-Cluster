"""Batched segmentation (the SLURM array) gives the same candidates as one process."""
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ultrack")
tifffile = pytest.importorskip("tifffile")

TRACKING = Path(__file__).resolve().parents[1] / "tracking"


def _labels(tmp_path, T=12):
    d = tmp_path / "labels"
    d.mkdir()
    rng = np.random.default_rng(0)
    for t in range(T):
        a = np.zeros((64, 64), np.uint16)
        for k, (cy, cx) in enumerate([(15, 10 + t), (40, 50 - t), (30, 30)]):
            r = 5 + (t + k) % 3
            yy, xx = np.ogrid[:64, :64]
            a[(yy - cy) ** 2 + (xx - cx) ** 2 <= r * r] = k + 1
        tifffile.imwrite(d / f"im{t:05d}.tif", a)
    return f"{d}/*.tif"


def _run(tmp_path, name, src, batches):
    out = tmp_path / name
    out.mkdir()
    cfg = tmp_path / f"{name}.toml"
    cfg.write_text(f"[data]\ndatabase = 'sqlite'\nworking_dir = '{out}'\n"
                   "[segmentation]\nn_workers = 3\nmin_area = 10\n[linking]\nn_workers = 1\n[tracking]\nwindow_size = 20\n")
    for b in batches:
        args = [sys.executable, str(TRACKING / "segment.py"), "-p", src, "-c", str(cfg)]
        if b is not None:
            args += ["-bi", str(b)]
        r = subprocess.run(args, capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    rows = sqlite3.connect(out / "data.db").execute(
        "select t, area, round(y, 3), round(x, 3), round(height, 5) from nodes").fetchall()
    return sorted(rows)


def test_batches_with_auto_padding_match_a_single_process(tmp_path):
    src = _labels(tmp_path)
    single = _run(tmp_path, "single", src, [None])
    batched = _run(tmp_path, "batched", src, [0, 1, 2, 3])        # 12 frames, 3 per batch
    assert len(single) > 0
    assert batched == single
