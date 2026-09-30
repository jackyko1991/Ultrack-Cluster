"""
Test harness for the Ultrack-Cluster bash scripts.

The real scripts are run unmodified in a temporary copy of `tracking/`, with
every cluster tool they call (sbatch, scancel, sacct, psql, pg_ctl, postgres,
dasel, ultrack, python, ...) replaced by a small fake on PATH. Fakes record
their argv so tests can assert on exactly what would have been submitted or
executed, without SLURM, PostgreSQL or ultrack installed.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TRACKING = REPO / "tracking"

# Records one call per file (argv one-per-line) and prints a fake job id.
SBATCH_STUB = r"""#!/bin/bash
n=$(( $(cat "$STUB_LOG_DIR/sbatch.count" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$STUB_LOG_DIR/sbatch.count"
printf '%s\n' "$@" > "$STUB_LOG_DIR/sbatch.$n"
echo $(( 1000 + n ))
"""

# Minimal dasel: `dasel -f FILE key.path` and `dasel put -t string -f FILE -v VALUE key.path`.
DASEL_STUB = r"""#!/usr/bin/env python3
import re, sys, tomllib
args = sys.argv[1:]
with open(f"{__import__('os').environ['STUB_LOG_DIR']}/calls.log", "a") as log:
    log.write("dasel " + " ".join(args) + "\n")
path = args[args.index("-f") + 1]
key = args[-1]
if args[0] == "put":
    value = args[args.index("-v") + 1]
    leaf = key.split(".")[-1]
    text = open(path).read()
    text = re.sub(rf"^{leaf}\s*=.*$", f"{leaf} = '{value}'", text, count=1, flags=re.M)
    open(path, "w").write(text)
else:
    data = tomllib.load(open(path, "rb"))
    for part in key.split("."):
        data = data[part]
    print(data)
"""

# Every other tool: log `name args...` and succeed.
GENERIC_STUB = r"""#!/bin/bash
echo "$(basename "$0") $*" >> "$STUB_LOG_DIR/calls.log"
"""

GENERIC_TOOLS = [
    "scancel", "sacct", "squeue", "module", "initdb", "pg_ctl", "createdb",
    "psql", "postgres", "lsof", "ultrack", "python", "apptainer", "mamba",
]


class Cluster:
    def __init__(self, root: Path):
        self.root = root
        self.workdir = root / "tracking"
        shutil.copytree(TRACKING, self.workdir)
        self.bindir = root / "bin"
        self.bindir.mkdir()
        self.logdir = root / "logs"
        self.logdir.mkdir()
        self.datadir = root / "labels"
        self.datadir.mkdir()
        (root / ".bashrc").touch()
        self.stub("sbatch", SBATCH_STUB)
        self.stub("dasel", DASEL_STUB)
        self.stub("getent", "#!/bin/bash\necho 'testgroup:x:1000:'\n")
        self.stub("pg_isready", GENERIC_STUB)
        for tool in GENERIC_TOOLS:
            self.stub(tool, GENERIC_STUB)

    def stub(self, name: str, body: str) -> None:
        path = self.bindir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def make_frames(self, n: int) -> None:
        for t in range(n):
            (self.datadir / f"im{t:05d}.tif").touch()

    def env(self, **overrides) -> dict:
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("SLURM", "ULTRACK", "GRB_"))
        }
        env.update(
            PATH=f"{self.bindir}:{env['PATH']}",
            STUB_LOG_DIR=str(self.logdir),
            HOME=str(self.root),
            USER="testuser",
            DATA_DIR=str(self.datadir),
            CFG_FILE="config.toml",
            ULTRACK_WORK_DIR=str(self.root / "work"),
        )
        env.update({k: str(v) for k, v in overrides.items()})
        return env

    def run(self, script: str, *args: str, **env) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", script, *args], cwd=self.workdir, env=self.env(**env),
            capture_output=True, text=True, timeout=60,
        )

    def run_as_slurm_job(self, script: str, *args: str, **env) -> subprocess.CompletedProcess:
        """Run a job script the way sbatch does: from a spooled copy elsewhere."""
        spool = self.root / "spool" / script
        spool.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.workdir / script, spool / "slurm_script")
        return subprocess.run(
            ["bash", str(spool / "slurm_script"), *args], cwd=self.workdir,
            env=self.env(**env), capture_output=True, text=True, timeout=60,
        )

    def bash(self, snippet: str, **env) -> subprocess.CompletedProcess:
        """Run a snippet with ultrack_lib.sh sourced."""
        return subprocess.run(
            ["bash", "-c", f"source ./ultrack_lib.sh\n{snippet}"], cwd=self.workdir,
            env=self.env(**env), capture_output=True, text=True, timeout=60,
        )

    def sbatch_calls(self) -> list[list[str]]:
        count_file = self.logdir / "sbatch.count"
        if not count_file.exists():
            return []
        n = int(count_file.read_text())
        return [
            (self.logdir / f"sbatch.{i}").read_text().splitlines() for i in range(1, n + 1)
        ]

    def calls(self, tool: str | None = None) -> list[str]:
        log = self.logdir / "calls.log"
        if not log.exists():
            return []
        lines = log.read_text().splitlines()
        return [l for l in lines if tool is None or l.split(" ", 1)[0] == tool]


def opt(argv: list[str], flag: str) -> str | None:
    """Value of `--flag value` / `-f value` / `--flag=value` in an argv list."""
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def script_of(argv: list[str]) -> str:
    """The batch script (first *.sh argument) of an sbatch call, or '--wrap'."""
    if "--wrap" in argv or any(a.startswith("--wrap=") for a in argv):
        return "--wrap"
    return next(a for a in argv if a.endswith(".sh"))


@pytest.fixture
def cluster(tmp_path) -> Cluster:
    return Cluster(tmp_path)
