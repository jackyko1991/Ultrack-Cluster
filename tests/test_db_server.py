"""create_server.sh / resume_server.sh: shared start path, readiness, tuning, ports."""
import os
import stat

# Stays "up" briefly so the script's `wait` returns, like a server that stops.
POSTGRES_STUB = """#!/bin/bash
echo "postgres $*" >> "$STUB_LOG_DIR/calls.log"
sleep 0.3
"""
NEVER_READY = "#!/bin/bash\nexit 1\n"

# ss stub: ports listed in $BUSY_PORTS are "listening".
SS_STUB = """#!/bin/bash
port="${@: -1}"; port="${port##*:}"
for p in $BUSY_PORTS; do [[ "$p" == "$port" ]] && echo "LISTEN 0 128 *:$p *:*"; done
exit 0
"""


def _db_env(cluster, **extra):
    env = dict(ULTRACK_DB_PW="pw", JOB_NAME="t1", SLURM_JOB_NODELIST="compx001",
               SLURM_MEM_PER_NODE="16384", SLURM_CPUS_PER_TASK="4",
               ULTRACK_DB_READY_FILE=cluster.root / "ready", BUSY_PORTS="")
    env.update(extra)
    return env


def _setup(cluster):
    cluster.stub("postgres", POSTGRES_STUB)
    cluster.stub("ss", SS_STUB)


def test_create_starts_then_initialises_then_publishes_address(cluster):
    _setup(cluster)
    r = cluster.run("create_server.sh", "config.toml", **_db_env(cluster))
    assert r.returncode == 0, r.stderr + r.stdout
    calls = cluster.calls()
    names = [c.split()[0] for c in calls]
    first = {n: names.index(n) for n in ["initdb", "postgres", "createdb", "psql", "dasel"]}
    assert first["initdb"] < first["createdb"] < first["psql"] < first["dasel"]
    assert "postgres" in names
    # every psql call names the database explicitly (the old tuning calls
    # didn't, and failed with 'database "<user>" does not exist')
    assert all(c.split()[-1] == "ultrack" for c in cluster.calls("psql"))
    host_port = (cluster.root / "ready").read_text().strip()
    assert host_port.startswith("compx001:")
    port = host_port.split(":")[1]
    cfg = (cluster.workdir / "config.toml").read_text()
    assert f"address = 'testuser:pw@compx001:{port}/ultrack?gssencmode=disable'" in cfg
    assert stat.S_IMODE(os.stat(cluster.workdir / "config.toml").st_mode) == 0o600


def test_postgres_tuning_follows_the_job_allocation(cluster):
    _setup(cluster)
    r = cluster.run("create_server.sh", "config.toml", **_db_env(cluster))
    assert r.returncode == 0, r.stderr
    (pg,) = cluster.calls("postgres")
    assert "shared_buffers=4096MB" in pg          # 16 GB / 4
    assert "effective_cache_size=12288MB" in pg   # 16 GB * 3/4
    assert "max_worker_processes=4" in pg
    assert "listen_addresses=*" in pg
    assert f"-k {cluster.root}/work/tmp_t1" in pg


def test_tuning_never_exceeds_small_allocations(cluster):
    r = cluster.bash("pg_tuning_args 2048 1")
    args = r.stdout.split()
    assert "shared_buffers=512MB" in args
    assert "max_parallel_workers_per_gather=1" in args
    assert "maintenance_work_mem=128MB" in args


def test_tuning_uses_mem_per_cpu_when_that_is_what_slurm_sets(cluster):
    r = cluster.bash("pg_tuning_args", SLURM_MEM_PER_CPU="2000", SLURM_CPUS_PER_TASK="4")
    assert "shared_buffers=2000MB" in r.stdout.split()   # 2000*4/4


def test_resume_does_not_reinitialise(cluster):
    _setup(cluster)
    (cluster.root / "work" / "postgresql_ultrack_t1").mkdir(parents=True)
    r = cluster.run("resume_server.sh", "config.toml", **_db_env(cluster))
    assert r.returncode == 0, r.stderr + r.stdout
    assert cluster.calls("initdb") == [] and cluster.calls("createdb") == []
    assert len(cluster.calls("postgres")) == 1
    assert (cluster.root / "ready").exists()


def test_resume_without_existing_db_fails_clearly(cluster):
    _setup(cluster)
    r = cluster.run("resume_server.sh", "config.toml", **_db_env(cluster))
    assert r.returncode != 0
    assert "no database to resume" in r.stderr
    assert cluster.calls("postgres") == []


def test_address_is_not_published_if_server_never_becomes_ready(cluster):
    _setup(cluster)
    cluster.stub("pg_isready", NEVER_READY)
    r = cluster.run("create_server.sh", "config.toml",
                    **_db_env(cluster, ULTRACK_DB_START_TIMEOUT=2))
    assert r.returncode != 0
    assert "not ready" in r.stderr
    assert not (cluster.root / "ready").exists()
    assert cluster.calls("dasel") == []


def test_config_file_can_come_from_environment(cluster):
    # manual_run.md documents `export CFG_FILE=...; sbatch create_server.sh`
    _setup(cluster)
    r = cluster.run("create_server.sh", **_db_env(cluster, CFG_FILE="config.toml"))
    assert r.returncode == 0, r.stderr


def test_find_free_port_scans_whole_range(cluster):
    cluster.stub("ss", SS_STUB)
    busy = " ".join(str(p) for p in range(5432, 5533) if p != 5500)
    for _ in range(5):
        r = cluster.bash("find_free_port 5432 100", BUSY_PORTS=busy)
        assert r.stdout.strip() == "5500", r.stderr


def test_find_free_port_fails_when_range_is_full(cluster):
    cluster.stub("ss", SS_STUB)
    busy = " ".join(str(p) for p in range(5432, 5443))
    r = cluster.bash("find_free_port 5432 10", BUSY_PORTS=busy)
    assert r.returncode != 0


def test_postgres_module_is_configurable(cluster):
    _setup(cluster)
    cluster.run("create_server.sh", "config.toml", **_db_env(cluster))
    assert cluster.calls("module") == ["module load PostgreSQL/16.1-GCCcore-12.3.0"]


def test_container_mode_runs_postgres_in_image_without_modules(cluster):
    _setup(cluster)
    cluster.stub("apptainer", """#!/bin/bash
echo "apptainer $*" >> "$STUB_LOG_DIR/calls.log"
shift; while [[ "$1" == --* ]]; do shift 2; done; shift   # drop exec, opts, image
exec "$@"
""")
    r = cluster.run("create_server.sh", "config.toml",
                    **_db_env(cluster, ULTRACK_SIF="/img.sif", ULTRACK_SIF_ARGS=""))
    assert r.returncode == 0, r.stderr + r.stdout
    assert cluster.calls("module") == []
    tools = {c.split()[3] for c in cluster.calls("apptainer")}
    assert {"initdb", "postgres", "pg_isready", "createdb", "psql"} <= tools


def test_port_check_falls_back_to_lsof_without_ss(cluster):
    # no `ss` on PATH: hide the host's by pointing PATH at the stub dir + coreutils only
    cluster.stub("lsof", '#!/bin/bash\n[[ "$*" == *":5433 "* ]] && exit 0; exit 1\n')
    r = cluster.bash('PATH="$STUB_BIN:/bin:/usr/bin"; command -v ss >/dev/null && echo HAS_SS; '
                     'is_port_in_use 5433 && echo busy5433; is_port_in_use 5434 || echo free5434',
                     STUB_BIN=cluster.bindir)
    if "HAS_SS" in r.stdout:
        import pytest
        pytest.skip("ss is in /bin or /usr/bin here; fallback not reachable")
    assert "busy5433" in r.stdout and "free5434" in r.stdout


def test_ephemeral_db_is_node_local_with_fsync_off(cluster):
    _setup(cluster)
    r = cluster.run("create_server.sh", "config.toml",
                    **_db_env(cluster, ULTRACK_DB_EPHEMERAL="true", TMPDIR=cluster.root / "nodetmp"))
    assert r.returncode == 0, r.stderr
    (pg,) = cluster.calls("postgres")
    assert f"-D {cluster.root}/nodetmp/postgresql_ultrack_t1" in pg
    for flag in ["fsync=off", "synchronous_commit=off", "full_page_writes=off"]:
        assert flag in pg


def test_durable_db_is_the_default(cluster):
    _setup(cluster)
    cluster.run("create_server.sh", "config.toml", **_db_env(cluster))
    (pg,) = cluster.calls("postgres")
    assert "fsync=off" not in pg
    assert f"-D {cluster.root}/work/postgresql_ultrack_t1" in pg


def test_ephemeral_resume_is_refused(cluster):
    _setup(cluster)
    r = cluster.run("resume_server.sh", "config.toml", **_db_env(cluster, ULTRACK_DB_EPHEMERAL="true"))
    assert r.returncode != 0
    assert "no database to resume" in r.stderr
    assert cluster.calls("postgres") == []


def test_main_refuses_ephemeral_with_resume(cluster):
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, BATCH="1", POST_PADDING="0",
                    SKIP_SEG="true", ULTRACK_DB_EPHEMERAL="true")
    assert r.returncode != 0
    assert cluster.sbatch_calls() == []


def test_db_server_uses_postgres_from_configured_runtime(cluster, tmp_path):
    # e.g. the pixi env with ULTRACK_PG_MODULE="": postgres is only on PATH
    # after activation, and no module is loaded
    env_dir = tmp_path / "env"
    (env_dir / "bin").mkdir(parents=True)
    for tool in ["postgres", "initdb"]:
        p = env_dir / "bin" / tool
        p.write_text(f'#!/bin/bash\necho "env-{tool} $*" >> "$STUB_LOG_DIR/calls.log"\nsleep 0.3\n')
        p.chmod(0o755)
    _setup(cluster)
    (cluster.bindir / "postgres").unlink()    # not on the base PATH
    r = cluster.run("create_server.sh", "config.toml",
                    **_db_env(cluster, ULTRACK_CONDA_ENV=env_dir, ULTRACK_PG_MODULE=""))
    assert r.returncode == 0, r.stderr
    assert cluster.calls("module") == []
    assert len(cluster.calls("env-postgres")) == 1 and len(cluster.calls("env-initdb")) == 1
