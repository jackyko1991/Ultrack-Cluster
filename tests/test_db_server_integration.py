"""
create_server.sh / resume_server.sh against a real PostgreSQL.

Runs wherever initdb/postgres/psql are on PATH and we are not root -- e.g.
inside the Apptainer/Docker image, or on BMRC after
`module load PostgreSQL/16.1-GCCcore-12.3.0`. Skipped otherwise.
"""
import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ["initdb", "postgres", "psql", "pg_isready", "dasel"])
    or os.geteuid() == 0,
    reason="needs real PostgreSQL tools + dasel on PATH, as a non-root user",
)


def _start(workdir, script, env):
    return subprocess.Popen(["bash", script, "config.toml"], cwd=workdir, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _wait_ready(ready: Path, proc, timeout=90) -> str:
    for _ in range(timeout):
        if ready.exists() and ready.read_text().strip():
            return ready.read_text().strip()
        if proc.poll() is not None:
            pytest.fail(f"server exited early:\n{proc.stdout.read()}")
        time.sleep(1)
    pytest.fail("server never became ready")


def _query(host_port, password, sql):
    host, port = host_port.rsplit(":", 1)
    url = f"postgresql://{os.environ.get('USER', 'u')}:{password}@{host}:{port}/ultrack"
    return subprocess.run(["psql", url, "-Atc", sql], capture_output=True, text=True, timeout=30)


def test_real_server_lifecycle(tmp_path):
    workdir = tmp_path / "tracking"
    shutil.copytree(REPO / "tracking", workdir)
    ready = tmp_path / "ready"
    env = {**os.environ, "ULTRACK_DB_PW": "pw", "JOB_NAME": "itest",
           "ULTRACK_WORK_DIR": str(tmp_path / "work"), "ULTRACK_PG_MODULE": "",
           "ULTRACK_DB_READY_FILE": str(ready),
           "SLURM_MEM_PER_NODE": "2048", "SLURM_CPUS_PER_TASK": "2"}
    for k in ["SLURM_JOB_NODELIST", "ULTRACK_SIF"]:
        env.pop(k, None)

    proc = _start(workdir, "create_server.sh", env)
    try:
        hp = _wait_ready(ready, proc)
        cfg = (workdir / "config.toml").read_text()
        assert f"@{hp}/ultrack" in cfg
        assert stat.S_IMODE((workdir / "config.toml").stat().st_mode) == 0o600

        ok = _query(hp, "pw", "select current_setting('shared_buffers'), current_setting('max_connections')")
        assert ok.returncode == 0, ok.stderr
        assert ok.stdout.strip() == "512MB|500"   # 2048 MB / 4: sized from the allocation
        assert _query(hp, "wrong", "select 1").returncode != 0
    finally:
        proc.send_signal(signal.SIGTERM)       # what scancel sends
        proc.wait(timeout=60)

    assert not (tmp_path / "work" / "postgresql_ultrack_itest" / "postmaster.pid").exists()
    assert not ready.exists()

    proc = _start(workdir, "resume_server.sh", env)
    try:
        hp = _wait_ready(ready, proc)
        assert _query(hp, "pw", "select 1").stdout.strip() == "1"
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)


def test_real_ephemeral_server_runs_without_fsync(tmp_path):
    workdir = tmp_path / "tracking"
    shutil.copytree(REPO / "tracking", workdir)
    ready = tmp_path / "ready"
    env = {**os.environ, "ULTRACK_DB_PW": "pw", "JOB_NAME": "eph",
           "ULTRACK_WORK_DIR": str(tmp_path / "work"), "ULTRACK_PG_MODULE": "",
           "ULTRACK_DB_READY_FILE": str(ready), "ULTRACK_DB_EPHEMERAL": "true",
           "TMPDIR": str(tmp_path / "nodetmp"),
           "SLURM_MEM_PER_NODE": "1024", "SLURM_CPUS_PER_TASK": "1"}
    env.pop("SLURM_JOB_NODELIST", None)
    (tmp_path / "nodetmp").mkdir()
    proc = _start(workdir, "create_server.sh", env)
    try:
        hp = _wait_ready(ready, proc)
        r = _query(hp, "pw", "select current_setting('fsync'), current_setting('synchronous_commit')")
        assert r.stdout.strip() == "off|off", r.stderr
        assert (tmp_path / "nodetmp" / "postgresql_ultrack_eph" / "PG_VERSION").exists()
        assert not (tmp_path / "work" / "postgresql_ultrack_eph").exists()
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)
