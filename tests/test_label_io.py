"""Label sources: TIFF glob or pyCyto/tanoa Zarr URI (v2/v3, NGFF multiscales)."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tracking"))
import label_io  # noqa: E402

zarr = pytest.importorskip("zarr")
pytest.importorskip("dask")

T, Y, X = 7, 16, 12


def _labels(t=T, z=None):
    shape = (t, Y, X) if z is None else (t, z, Y, X)
    a = np.zeros(shape, dtype=np.uint16)
    for i in range(t):
        a[i, ..., 2 + i % 3: 6 + i % 3, 3:7] = i + 1     # one object per frame, moving
    return a


def _ngff_group(path, data, axes, zarr_format=3, extra_attrs=None):
    """A multiscale group like cyto.io.zarr writes (NGFF 0.5 under 'ome' for v3)."""
    root = zarr.open_group(str(path), mode="a", zarr_format=zarr_format)
    group = root.require_group("labels/Cellpose/TCell")
    group.create_array("0", data=data, chunks=(1,) + data.shape[1:])
    ms = {"axes": [{"name": a} for a in axes], "datasets": [{"path": "0"}]}
    attrs = {"multiscales": [ms], **(extra_attrs or {})}
    if zarr_format == 3:
        group.attrs["ome"] = {"version": "0.5", **attrs}
    else:
        group.attrs.update(attrs)
    return f"{path}#labels/Cellpose/TCell"


def test_parse_source():
    assert label_io.parse_source("/d/*.tif") == {"kind": "tiff", "pattern": "/d/*.tif"}
    assert label_io.parse_source("/d/e.zarr#labels/A/B?c=GFP") == \
        {"kind": "zarr", "store": "/d/e.zarr", "group": "labels/A/B", "channel": "GFP"}
    for bad in ["#g", "/d/e.zarr#", "/a#b#c"]:
        with pytest.raises(ValueError):
            label_io.parse_source(bad)


def test_pycyto_v3_tzyx_store_with_singleton_z(tmp_path):
    data = _labels(z=1)
    src = _ngff_group(tmp_path / "exp.zarr", data, ["t", "z", "y", "x"])
    assert (tmp_path / "exp.zarr" / "labels" / "Cellpose" / "TCell" / "zarr.json").exists()
    assert label_io.frame_count(src) == T
    arr = label_io.open_labels(src, begin=2, end=5)
    assert arr.shape == (4, Y, X)                     # Z=1 dropped, frames 2..5
    np.testing.assert_array_equal(arr.compute(), data[2:6, 0])


def test_real_z_stack_is_kept(tmp_path):
    data = _labels(z=3)
    src = _ngff_group(tmp_path / "exp.zarr", data, ["t", "z", "y", "x"])
    assert label_io.open_labels(src).shape == (T, 3, Y, X)


def test_v2_plain_array(tmp_path):
    data = _labels()
    root = zarr.open_group(str(tmp_path / "g.zarr"), mode="w", zarr_format=2)
    root.create_array("frames", data=data)
    assert (tmp_path / "g.zarr" / "frames" / ".zarray").exists()   # really v2
    src = f"{tmp_path}/g.zarr#frames"
    assert label_io.frame_count(src) == T
    np.testing.assert_array_equal(label_io.open_labels(src, step=2).compute(), data[::2])


def test_tanoa_style_channel_selection(tmp_path):
    a = _labels(z=1)
    data = np.stack([a, a * 0, a + 100], axis=1)      # T, C, Z, Y, X
    src = _ngff_group(tmp_path / "t.zarr", data, ["t", "c", "z", "y", "x"],
                      extra_attrs={"omero": {"channels": [{"label": "GFP"}, {"label": "PI"}, {"label": "CTFR"}]}})
    np.testing.assert_array_equal(label_io.open_labels(src + "?c=CTFR").compute(), (a + 100)[:, 0])
    np.testing.assert_array_equal(label_io.open_labels(src + "?c=0").compute(), a[:, 0])
    with pytest.raises(ValueError, match="select one"):
        label_io.open_labels(src)
    with pytest.raises(ValueError, match="not in"):
        label_io.open_labels(src + "?c=DAPI")


def test_group_without_multiscales_is_rejected(tmp_path):
    zarr.open_group(str(tmp_path / "e.zarr"), mode="w").require_group("labels")
    with pytest.raises(ValueError, match="multiscales"):
        label_io.frame_count(f"{tmp_path}/e.zarr#labels")


def test_tiff_glob(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    pytest.importorskip("dask_image")
    data = _labels()
    for t in range(T):
        tifffile.imwrite(tmp_path / f"im{t:05d}.tif", data[t])
    src = f"{tmp_path}/*.tif"
    assert label_io.frame_count(src) == T
    np.testing.assert_array_equal(label_io.open_labels(src, begin=1, end=3).compute(), data[1:4])


def test_frames_cli(tmp_path):
    src = _ngff_group(tmp_path / "exp.zarr", _labels(z=1), ["t", "z", "y", "x"])
    r = subprocess.run([sys.executable, str(Path(label_io.__file__)), "frames", src],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == str(T)


def test_v2_ngff_04_multiscale_group(tmp_path):
    data = _labels(z=1)
    src = _ngff_group(tmp_path / "old.zarr", data, ["t", "z", "y", "x"], zarr_format=2)
    assert label_io.frame_count(src) == T
    np.testing.assert_array_equal(label_io.open_labels(src).compute(), data[:, 0])
