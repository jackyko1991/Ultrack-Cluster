"""segment.py never logs the coordination DB password and parses any password."""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("ultrack")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tracking"))
import segment  # noqa: E402

PW = "p@ss:w/rd'x"


def test_redact_address():
    assert segment.redact_address(f"me:{PW}@node7:5522/ultrack?gssencmode=disable") == \
        "me:***@node7:5522/ultrack?gssencmode=disable"
    assert segment.redact_address("") == ""


def test_host_port_parsed_as_url_even_with_special_characters(tmp_path):
    from urllib.parse import quote
    from ultrack import load_config
    f = tmp_path / "c.toml"
    f.write_text(f"[data]\ndatabase = 'postgresql'\naddress = 'me:{quote(PW, safe='')}@node7:5522/ultrack'\n")
    assert segment.db_host_port(load_config(f)) == ("node7", 5522)


def test_printed_config_has_no_password(tmp_path):
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(f"[data]\ndatabase = 'postgresql'\naddress = 'me:SeCrEt123@127.0.0.1:9/none'\n"
                   "[segmentation]\nn_workers = 1\n[linking]\nn_workers = 1\n[tracking]\nwindow_size = 5\n")
    labels = tmp_path / "l"
    labels.mkdir()
    import numpy as np
    import tifffile
    for t in range(2):
        tifffile.imwrite(labels / f"im{t}.tif", np.ones((16, 16), np.uint16))
    code = ("import sys, time; sys.argv=['segment.py','-p',sys.argv[1],'-c',sys.argv[2],'-bi','0']; "
            "time.sleep=lambda s: None; import runpy; runpy.run_path(sys.argv[0] if False else "
            f"{str(Path(segment.__file__))!r}, run_name='__main__')")
    r = subprocess.run([sys.executable, "-c", code, f"{labels}/*.tif", str(cfg)],
                       capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    assert "me:***@127.0.0.1:9/none" in out          # config was printed, redacted
    assert "SeCrEt123" not in out
