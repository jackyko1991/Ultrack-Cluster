"""segment.py's slab-wise space-time blur equals one gaussian_filter over the block."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ultrack")
from scipy.ndimage import gaussian_filter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tracking"))
spec = importlib.util.spec_from_file_location("segment_mod", Path(__file__).resolve().parents[1] / "tracking" / "segment.py")
segment_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(segment_mod)


@pytest.mark.parametrize("shape", [(12, 40, 33), (9, 3, 37, 21)])
@pytest.mark.parametrize("max_bytes", [1, 2000, 10 ** 9])   # 1 row per slab ... one slab
def test_slab_blur_matches_whole_block(shape, max_bytes):
    rng = np.random.default_rng(0)
    edges = rng.random(shape, dtype=np.float32)
    first, last = 2, shape[0] - 3
    sigma = [1.2] + [1.0] * (len(shape) - 1)
    expected = edges.copy()
    expected[first:last + 1] = gaussian_filter(edges[first:last + 1], sigma=sigma)
    got = edges.copy()
    segment_mod.blur_edges(got, first, last, sigma, max_block_bytes=max_bytes)
    np.testing.assert_allclose(got, expected, rtol=1e-5, atol=1e-6)
    assert np.array_equal(got[:first], edges[:first]) and np.array_equal(got[last + 1:], edges[last + 1:])
