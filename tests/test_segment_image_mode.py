"""segment.py --mode image: foreground/contours from raw images (ultrack's own recipe)."""
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ultrack")
tifffile = pytest.importorskip("tifffile")

TRACKING = Path(__file__).resolve().parents[1] / "tracking"


def test_image_mode_segments_bright_blobs(tmp_path):
    yy, xx = np.mgrid[:96, :96]
    for t in range(4):
        img = np.full((96, 96), 100.0)
        for cy, cx in [(25, 20 + 3 * t), (65, 60 - 2 * t)]:
            img += 2000 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 6.0 ** 2))
        tifffile.imwrite(tmp_path / f"t{t:03d}.tif", img.astype(np.uint16))
    (tmp_path / "out").mkdir()
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(f"[data]\ndatabase = 'sqlite'\nworking_dir = '{tmp_path / 'out'}'\n"
                   "[segmentation]\nn_workers = 4\nmin_area = 20\nmax_area = 2000\n"
                   "[linking]\nn_workers = 1\n[tracking]\nwindow_size = 20\n")
    r = subprocess.run([sys.executable, str(TRACKING / "segment.py"), "-p", f"{tmp_path}/t*.tif",
                        "-c", str(cfg), "-bi", "0", "-m", "image", "--contour-sigma", "3.0"],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    rows = sqlite3.connect(tmp_path / "out" / "data.db").execute(
        "select t, count(*) from nodes group by t").fetchall()
    assert [t for t, _ in rows] == [0, 1, 2, 3] and all(n >= 2 for _, n in rows)
