"""DB server is stopped after export (any outcome); resources are reported."""
from conftest import opt, script_of

FULL = dict(SKIP_SEG="false", SKIP_LINK="false", BATCH="1", POST_PADDING="0", JOB_NAME="j")

# Real numbers from the 2026-09-30 BMRC smoke test (6 frames, patch 04).
SACCT = """JobID|JobName|State|ExitCode|Elapsed|ElapsedRaw|ReqMem|MaxRSS|AllocCPUS|TotalCPU
1002_0|SEGMENT_j|COMPLETED|0:0|00:01:18|78|15G||1|00:14.668
1002_0.batch|batch|COMPLETED|0:0|00:01:18|78||654764K|1|00:14.666
1002_1|SEGMENT_j|COMPLETED|0:0|00:01:18|78|15G||1|00:13.881
1002_1.batch|batch|COMPLETED|0:0|00:01:18|78||572044K|1|00:13.880
1004_0|SOLVE_j|COMPLETED|0:0|00:11:37|697|16G||2|10:19.223
1004_0.batch|batch|COMPLETED|0:0|00:11:37|697||3718324K|2|10:19.221
1005|EXPORT_j|FAILED|1:0|00:00:05|5|4000Mc||2|00:01.000
1005.batch|batch|FAILED|1:0|00:00:05|5||102400K|2|00:01.000
"""


def test_cleanup_job_follows_export_whatever_its_outcome(cluster):
    cluster.make_frames(26)
    r = cluster.run("main.sh", BATCH_SIZE=26, **FULL)
    assert r.returncode == 0, r.stderr
    calls = cluster.sbatch_calls()
    last = calls[-1]
    assert script_of(last) == "cleanup.sh"
    export_id = str(1000 + [script_of(c) for c in calls].index("export.sh") + 1)
    assert opt(last, "-d") == f"afterany:{export_id}"
    assert last[-2] == "1001"                      # the DB server job id
    assert last[-1].endswith("slurm_output/j/submission.tsv")


def test_keep_db_skips_cleanup(cluster):
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, KEEP_DB="true", **FULL)
    assert r.returncode == 0, r.stderr
    assert "cleanup.sh" not in [script_of(c) for c in cluster.sbatch_calls()]
    assert "KEEP_DB=true" in r.stderr


def test_every_dependent_job_is_cancelled_if_its_upstream_fails(cluster):
    # otherwise a failed stage leaves its dependents pending forever and the
    # afterany cleanup (and so the DB shutdown) never happens
    cluster.make_frames(26)
    cluster.run("main.sh", BATCH_SIZE=26, **FULL)
    for argv in cluster.sbatch_calls():
        dep = opt(argv, "-d")
        if dep and not dep.startswith("afterany"):
            assert "--kill-on-invalid-dep=yes" in argv, script_of(argv)


def _manifest(cluster):
    m = cluster.root / "run" / "submission.tsv"
    m.parent.mkdir()
    m.write_text("# submitted ...\n# data=...\nstage\tjob_id\tsbatch_args\n"
                 "db-server\t1001\tx\nsegment\t1002\tx\nlink\t1003\tx\nsolve\t1004\tx\nexport\t1005\tx\n")
    return m


def test_cleanup_stops_server_and_reports_resources(cluster):
    cluster.stub("sacct", "#!/bin/bash\necho \"sacct $*\" >> \"$STUB_LOG_DIR/calls.log\"\ncat <<'X'\n" + SACCT + "X\n")
    m = _manifest(cluster)
    r = cluster.run_as_slurm_job("cleanup.sh", "1001", str(m), SLURM_SUBMIT_DIR=cluster.workdir)
    assert r.returncode == 0, r.stderr + r.stdout
    assert cluster.calls("scancel") == ["scancel 1001"]
    assert "-j 1001,1002,1003,1004,1005" in cluster.calls("sacct")[0]
    summary = (m.parent / "resource_report_summary.tsv").read_text().splitlines()
    rows = {l.split("\t")[0]: dict(zip(summary[0].split("\t"), l.split("\t"))) for l in summary[1:]}
    seg, solve, exp = rows["segment"], rows["solve"], rows["export"]
    assert seg["tasks"] == "2" and seg["states"] == "COMPLETED:2"
    assert seg["req_mem_mb"] == "15360" and seg["max_rss_mb"] == "639"
    assert seg["mem_used_pct"] == "4" and seg["suggested_mem_gb"] == "1"
    assert seg["cpu_eff_pct"] == "18"
    assert solve["max_rss_mb"] == "3631" and solve["suggested_mem_gb"] == "6"
    assert solve["cpu_eff_pct"] == "44"          # one core busy out of two
    assert exp["req_mem_mb"] == "8000"           # 4000M per CPU x 2
    assert exp["states"] == "FAILED:1"


def test_report_failure_does_not_fail_cleanup(cluster):
    cluster.stub("sacct", "#!/bin/bash\nexit 1\n")
    r = cluster.run_as_slurm_job("cleanup.sh", "1001", str(_manifest(cluster)),
                                 SLURM_SUBMIT_DIR=cluster.workdir)
    assert r.returncode == 0, r.stderr
    assert cluster.calls("scancel") == ["scancel 1001"]
