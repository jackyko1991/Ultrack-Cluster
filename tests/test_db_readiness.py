"""Workers wait for the DB's ready file + open port, not a fixed delay."""
import socket
import subprocess
import threading
import time

import pytest
from conftest import opt


@pytest.fixture
def listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(16)
    stop = threading.Event()

    def accept():
        s.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = s.accept()
                conn.close()
            except OSError:
                pass

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    yield s.getsockname()[1]
    stop.set()
    s.close()


def test_wait_returns_once_ready_file_appears(cluster, listener):
    ready = cluster.root / "db_ready"
    proc = subprocess.Popen(
        ["bash", "-c", "source ./ultrack_lib.sh; wait_for_db && echo OK"],
        cwd=cluster.workdir, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=cluster.env(ULTRACK_DB_READY_FILE=ready, ULTRACK_DB_POLL_INTERVAL="0.1"),
    )
    time.sleep(0.5)
    assert proc.poll() is None          # still waiting: no ready file yet
    ready.write_text(f"127.0.0.1:{listener}\n")
    out, err = proc.communicate(timeout=10)
    assert proc.returncode == 0, err
    assert "OK" in out


def test_wait_times_out_when_port_never_opens(cluster):
    ready = cluster.root / "db_ready"
    ready.write_text("127.0.0.1:1\n")   # nothing listens on port 1
    r = cluster.bash("wait_for_db", ULTRACK_DB_READY_FILE=ready,
                     ULTRACK_DB_WAIT_TIMEOUT=1, ULTRACK_DB_POLL_INTERVAL="0.1")
    assert r.returncode != 0
    assert "not reachable" in r.stderr


def test_wait_is_a_noop_without_ready_file(cluster):
    r = cluster.bash("wait_for_db && echo OK")
    assert "OK" in r.stdout


def test_worker_waits_for_db_before_running_ultrack(cluster, listener):
    ready = cluster.root / "db_ready"
    ready.write_text(f"127.0.0.1:{listener}\n")
    r = cluster.run_as_slurm_job("link.sh", "config.toml", SLURM_SUBMIT_DIR=cluster.workdir,
                                 SLURM_ARRAY_TASK_ID=0, ULTRACK_DB_READY_FILE=ready)
    assert r.returncode == 0, r.stderr
    assert "DB reachable" in r.stdout
    assert cluster.calls("ultrack") == ["ultrack link -cfg config.toml -b 0"]


def test_worker_does_not_run_ultrack_if_db_never_comes_up(cluster):
    r = cluster.run_as_slurm_job("link.sh", "config.toml", SLURM_SUBMIT_DIR=cluster.workdir,
                                 SLURM_ARRAY_TASK_ID=0, ULTRACK_DB_READY_FILE=cluster.root / "absent",
                                 ULTRACK_DB_WAIT_TIMEOUT=1, ULTRACK_DB_POLL_INTERVAL="0.1")
    assert r.returncode != 0
    assert cluster.calls("ultrack") == []


def test_main_uses_readiness_not_fixed_delays(cluster):
    cluster.make_frames(26)
    stale = cluster.workdir / "slurm_output" / "j" / "db_ready"
    stale.parent.mkdir(parents=True)
    stale.write_text("oldnode:5432\n")
    r = cluster.run("main.sh", BATCH_SIZE=26, JOB_NAME="j", SKIP_SEG="false",
                    SKIP_LINK="false", BATCH="1", POST_PADDING="0")
    assert r.returncode == 0, r.stderr
    deps = [opt(a, "-d") for a in cluster.sbatch_calls() if opt(a, "-d")]
    assert deps and all("+" not in d for d in deps), deps
    assert not stale.exists()           # a previous run's address must not leak in
