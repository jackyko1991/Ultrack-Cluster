"""The Apptainer definition must stay pinned and self-checking."""
import re
from pathlib import Path

DEF = Path(__file__).resolve().parents[1] / "containers" / "ultrack-cluster.def"


def _section(text, name):
    m = re.search(rf"^%{name}\n(.*?)(?=^%|\Z)", text, re.M | re.S)
    assert m, f"missing %{name} section"
    return m.group(1)


def test_ultrack_is_pinned_to_a_commit_or_version():
    post = _section(DEF.read_text(), "post")
    assert re.search(r"ultrack( @ git\+\S+@[0-9a-f]{7,}|==\d)", post)


def test_every_pip_requirement_is_pinned():
    post = _section(DEF.read_text(), "post")
    pip = post[post.index("pip install"):post.index("curl")]
    reqs = [t for t in pip.replace("\\\n", " ").split() if not t.startswith("-") and t not in ("pip", "install")]
    unpinned = [r for r in reqs if "==" not in r and "@" not in r and not r.startswith('"')]
    assert unpinned == [], unpinned


def test_image_provides_every_tool_the_scripts_call():
    test = _section(DEF.read_text(), "test")
    for tool in ["initdb", "pg_ctl", "postgres", "psql", "createdb", "pg_isready", "dasel", "ultrack"]:
        assert tool in test, tool
    assert "import ultrack, gurobipy, mip" in test
