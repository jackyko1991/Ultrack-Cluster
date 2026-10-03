"""The export job runs ultrack's frame pool with data.n_workers processes, so it
must request that many CPUs (it requested 1: 8 workers shared one CPU), and its
memory default must be overridable."""
import re

from conftest import opt
from test_resources import FULL, _by_script


def _set_data_workers(cluster, n):
    cfg = cluster.workdir / "config.toml"
    text = cfg.read_text()
    if re.search(r"\[data\][^\[]*?n_workers", text, flags=re.S):
        text = re.sub(r"(\[data\][^\[]*?n_workers = )\d+", rf"\g<1>{n}", text, flags=re.S)
    else:
        text = text.replace("[data]\n", f"[data]\nn_workers = {n}\n", 1)
    cfg.write_text(text)


def test_export_cpus_follow_data_n_workers(cluster):
    cluster.make_frames(26)
    _set_data_workers(cluster, 6)
    r = cluster.run("main.sh", BATCH_SIZE=26, **FULL)
    assert r.returncode == 0, r.stderr
    assert opt(_by_script(cluster)["export.sh"], "--cpus-per-task") == "6"


def test_export_cpus_and_memory_overridable(cluster):
    cluster.make_frames(26)
    r = cluster.run("main.sh", BATCH_SIZE=26, EXPORT_CPUS="3", EXPORT_MEM="500G", **FULL)
    assert r.returncode == 0, r.stderr
    c = _by_script(cluster)["export.sh"]
    assert opt(c, "--cpus-per-task") == "3" and opt(c, "--mem") == "500G"
