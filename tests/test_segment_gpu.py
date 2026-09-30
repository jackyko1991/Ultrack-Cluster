"""Segment tasks are CPU by default; GPUs, partition and env are opt-in."""
from conftest import opt, script_of

FULL = dict(SKIP_SEG="false", SKIP_LINK="false", BATCH="1", POST_PADDING="0", JOB_NAME="j")


def _segment(cluster):
    return next(a for a in cluster.sbatch_calls() if script_of(a) == "segment.sh")


def test_segment_requests_no_gpu_by_default(cluster):
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, **FULL)
    assert r.returncode == 0, r.stderr
    seg = _segment(cluster)
    assert opt(seg, "--gres") is None
    assert opt(seg, "--partition") == "short"
    assert opt(seg, "--export") is None


def test_seg_gpus_requests_gpu_partition_and_switches_pixi_env(cluster):
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, SEG_GPUS=1, ULTRACK_PIXI_ENV="default", **FULL)
    assert r.returncode == 0, r.stderr
    seg = _segment(cluster)
    assert opt(seg, "--gres") == "gpu:1"
    assert opt(seg, "--partition") == "gpu_short"
    assert opt(seg, "--export") == "ALL,ULTRACK_PIXI_ENV=gpu"
    # only segment moves: the other stages stay on the CPU env and partitions
    others = [a for a in cluster.sbatch_calls() if script_of(a) != "segment.sh"]
    assert all(opt(a, "--gres") is None and opt(a, "--export") is None for a in others)


def test_seg_gpu_env_and_partition_are_overridable(cluster):
    cluster.make_frames(6)
    cluster.run("main.sh", BATCH_SIZE=6, SEG_GPUS=2, ULTRACK_PIXI_ENV="default",
                SEG_PIXI_ENV="cuda11", GPU_PARTITION="gpu_long", **FULL)
    seg = _segment(cluster)
    assert (opt(seg, "--gres"), opt(seg, "--partition"), opt(seg, "--export")) == \
        ("gpu:2", "gpu_long", "ALL,ULTRACK_PIXI_ENV=cuda11")


def test_seg_gpus_without_pixi_warns_that_env_must_have_cupy(cluster):
    cluster.make_frames(6)
    r = cluster.run("main.sh", BATCH_SIZE=6, SEG_GPUS=1, **FULL)
    assert r.returncode == 0, r.stderr
    assert "cupy" in r.stderr + r.stdout
    assert opt(_segment(cluster), "--export") is None


def test_zarr_label_source_sets_frame_count(cluster, tmp_path):
    # a plain v3 array, written by hand so the test needs no zarr install
    import json
    arr = tmp_path / "exp.zarr" / "labels"
    arr.mkdir(parents=True)
    (tmp_path / "exp.zarr" / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "group"}))
    (arr / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "array", "shape": [6, 1, 8, 8]}))
    src = f"{tmp_path}/exp.zarr#labels"
    r = cluster.run("main.sh", BATCH_SIZE=100, LABEL_SOURCE=src, **FULL)
    assert r.returncode == 0, r.stderr
    assert "6 [0:5]" in r.stderr + r.stdout
    assert src in _segment(cluster)


def test_segment_batch_zero_runs_alone_before_the_rest(cluster):
    cluster.make_frames(26)
    r = cluster.run("main.sh", BATCH_SIZE=26, **FULL)
    assert r.returncode == 0, r.stderr
    calls = cluster.sbatch_calls()
    ids = {1001 + i: c for i, c in enumerate(calls)}  # fake sbatch: job ids 1001, 1002, ...
    segs = [(n, c) for n, c in ids.items() if script_of(c) == "segment.sh"]
    (init_n, init), (rest_n, rest) = segs
    assert opt(init, "--array") == "0-0"
    assert opt(rest, "--array").startswith("1-")
    assert opt(rest, "-d").startswith("afterok:") and str(init_n) in opt(rest, "-d")
    link = next(c for c in calls if script_of(c) == "link.sh")
    assert set(opt(link, "-d").split(":")[1:]) >= {str(init_n), str(rest_n)}


def test_single_segment_batch_submits_only_the_init_job(cluster):
    cluster.make_frames(6)
    from test_batching import _set_workers
    _set_workers(cluster, 8, 8)
    cluster.run("main.sh", BATCH_SIZE=6, **FULL)
    segs = [c for c in cluster.sbatch_calls() if script_of(c) == "segment.sh"]
    assert [opt(c, "--array") for c in segs] == ["0-0"]
