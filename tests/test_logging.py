"""Uniform, attributable log lines; clear success/failure summaries; manifest."""
import re

LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[(INFO |WARN |ERROR)\] \[(\S+) (\S+)@(\S+)\] (.*)$")
FAILING = "#!/bin/bash\nexit 3\n"


def _lines(text):
    return [m for m in (LINE.match(l) for l in text.splitlines()) if m]


def test_log_line_carries_stage_array_task_and_host(cluster):
    r = cluster.bash("ULTRACK_STAGE=link log INFO hello world",
                     SLURM_JOB_ID="900", SLURM_ARRAY_JOB_ID="899", SLURM_ARRAY_TASK_ID="7")
    (m,) = _lines(r.stdout)
    assert m.group(1).strip() == "INFO" and m.group(2) == "link" and m.group(3) == "899_7"
    assert m.group(5) == "hello world"


def test_warnings_and_errors_go_to_stderr(cluster):
    r = cluster.bash("log WARN careful; log ERROR broken")
    assert r.stdout == ""
    assert [m.group(1).strip() for m in _lines(r.stderr)] == ["WARN", "ERROR"]


def test_successful_job_logs_start_and_done(cluster):
    r = cluster.run_as_slurm_job("link.sh", "config.toml", SLURM_SUBMIT_DIR=cluster.workdir,
                                 SLURM_ARRAY_TASK_ID=2, SLURM_JOB_ID=55, JOB_NAME="j")
    assert r.returncode == 0, r.stderr
    msgs = [m.group(5) for m in _lines(r.stdout)]
    assert msgs[0].startswith("start: job=j")
    assert "repo=" in msgs[0]
    assert re.match(r"done in \d+s", msgs[-1])


def test_failed_job_names_the_failing_command(cluster):
    cluster.stub("ultrack", FAILING)
    r = cluster.run_as_slurm_job("link.sh", "config.toml", SLURM_SUBMIT_DIR=cluster.workdir,
                                 SLURM_ARRAY_TASK_ID=2)
    assert r.returncode == 3
    errors = [m.group(5) for m in _lines(r.stderr) if m.group(1).strip() == "ERROR"]
    assert any("exit 3" in e and "ultrack link" in e for e in errors), errors
    assert errors[-1].startswith("FAILED (exit 3)")


def test_rc_file_failures_do_not_produce_error_lines(cluster, tmp_path):
    act = tmp_path / "activate"
    act.write_text("false\ntrue\n")   # a failing line inside an rc file, overall OK
    r = cluster.bash("set -euo pipefail; start_stage t; activate_ultrack_env",
                     ULTRACK_ENV_ACTIVATE=act)
    assert r.returncode == 0, r.stderr
    assert not [m for m in _lines(r.stderr) if m.group(1).strip() == "ERROR"]


def test_db_server_stop_by_scancel_is_not_a_failure(cluster):
    import signal, subprocess, time
    cluster.stub("postgres", "#!/bin/bash\nexec sleep 30\n")
    ready = cluster.root / "ready"
    proc = subprocess.Popen(["bash", "create_server.sh", "config.toml"], cwd=cluster.workdir,
                            env=cluster.env(ULTRACK_DB_PW="pw", JOB_NAME="t", ULTRACK_DB_READY_FILE=ready),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        if ready.exists():
            break
        time.sleep(0.1)
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=20)
    assert proc.returncode == 0, err
    assert "stopped by signal" in out
    assert "FAILED" not in err


def test_main_writes_a_submission_manifest(cluster):
    cluster.make_frames(26)
    r = cluster.run("main.sh", BATCH_SIZE=26, JOB_NAME="j", SKIP_SEG="false",
                    SKIP_LINK="false", BATCH="1", POST_PADDING="0")
    assert r.returncode == 0, r.stderr
    manifest = (cluster.workdir / "slurm_output" / "j" / "submission.tsv").read_text().splitlines()
    assert manifest[0].startswith("# submitted") and "repo=" in manifest[0]
    assert "window_size=20" in manifest[1]
    rows = [l.split("\t") for l in manifest[3:]]
    assert [r[0] for r in rows] == ["db-server", "segment", "link", "solve-even", "solve-odd-1", "export", "cleanup"]
    assert [r[1] for r in rows] == [str(1001 + i) for i in range(len(rows))]
    # submit() must print only the job id on stdout, or dependencies break
    deps = [row[2] for row in rows]
    assert "after:1001" in deps[1] and "afterok:1003" in deps[3]


def test_no_useless_error_line_for_function_returns(cluster):
    r = cluster.bash("set -euo pipefail; start_stage t; f() { log ERROR 'real reason'; return 1; }; f")
    errors = [m.group(5) for m in _lines(r.stderr) if m.group(1).strip() == "ERROR"]
    assert errors[0] == "real reason"
    assert not any("return 1" in e for e in errors)
