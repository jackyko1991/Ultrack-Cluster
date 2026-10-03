"""ultrack logs its whole config at INFO, including the coordination DB URL
with its password; the worker's log handler must mask it."""
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tracking"))
import ultrack_worker  # noqa: E402


def test_db_password_is_masked_in_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ultrack_worker.RedactSecrets())
    log = logging.getLogger("ultrack.config.config.test")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.info("%s", {"data": {"address": "oyk357:s3cr3t-Pw_x@cloudcomp100:5505/ultrack?gssencmode=disable"}})
    log.info("postgresql://user:another.secret@host:5432/db")
    out = stream.getvalue()
    assert "s3cr3t-Pw_x" not in out and "another.secret" not in out
    assert "oyk357:***@cloudcomp100:5505" in out and "postgresql://user:***@host" in out


def test_main_installs_the_filter_on_its_handlers():
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        for h in list(root.handlers):
            root.removeHandler(h)
        ultrack_worker.setup_logging()
        assert root.handlers and all(any(isinstance(f, ultrack_worker.RedactSecrets) for f in h.filters)
                                     for h in root.handlers)
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in before:
            root.addHandler(h)
