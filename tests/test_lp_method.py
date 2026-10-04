"""ultrack passes tracking.method to python-mip as a plain int, but python-mip compares it with
LP_Method enum members (1 != LP_Method.DUAL), so any value fell through to Gurobi Method=3
(concurrent): the setting was silently ignored. The worker coerces it to LP_Method."""
import sys
from pathlib import Path

import pytest

mip = pytest.importorskip("mip")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tracking"))
import ultrack_worker  # noqa: E402


@pytest.mark.parametrize("value,expected", [(0, "AUTO"), (1, "DUAL"), (2, "PRIMAL"), (3, "BARRIER")])
def test_int_lp_method_becomes_the_enum(value, expected):
    ultrack_worker.coerce_lp_method()
    m = mip.Model(solver_name="CBC")
    m.lp_method = value
    assert m.lp_method is mip.LP_Method[expected]


def test_enum_values_pass_through_and_patch_is_idempotent():
    ultrack_worker.coerce_lp_method()
    ultrack_worker.coerce_lp_method()
    m = mip.Model(solver_name="CBC")
    m.lp_method = mip.LP_Method.BARRIER
    assert m.lp_method is mip.LP_Method.BARRIER
