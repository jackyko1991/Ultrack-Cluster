"""
Summarise a run's SLURM accounting per pipeline stage: requested vs peak
memory and CPU efficiency, i.e. the numbers needed to right-size the
resource requests in main.sh.

    python3 resource_report.py <submission.tsv> <sacct -P output>

Writes <sacct output stem>_summary.tsv and prints it. Standard library only,
Python 3.6+ (the system python3 on BMRC nodes).
"""
import csv
import math
import re
import sys
from collections import OrderedDict

_UNITS = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}


def mem_mb(value, cpus=1):
    """'654764K' / '3.5G' / '16000Mc' (per CPU) / '16Gn' -> MB (float), '' -> None."""
    if not value:
        return None
    m = re.match(r"^([\d.]+)([KMGT]?)([cn]?)$", value)
    if not m:
        return None
    number, unit, per = m.groups()
    mb = float(number) * _UNITS[unit or "M"]
    return mb * cpus if per == "c" else mb


def cpu_seconds(value):
    """'[DD-][HH:]MM:SS[.sss]' -> seconds."""
    if not value:
        return 0.0
    days = 0
    if "-" in value:
        d, value = value.split("-", 1)
        days = int(d)
    parts = [float(p) for p in value.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return days * 86400 + h * 3600 + m * 60 + s


def stages_by_job(manifest):
    """{job id: (stage, job name)} from a main.sh submission manifest; the job
    name (the submitted --job-name) guards against Slurm job-id reuse, as
    sacct -j can also return an older, unrelated job with the same id."""
    out = {}
    with open(manifest) as f:
        for line in f:
            if line.startswith("#") or line.startswith("stage\t"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) >= 2 and cols[1].isdigit():
                name = re.search(r"--job-name[ =](\S+)", cols[2]) if len(cols) > 2 else None
                out[cols[1]] = (cols[0], name.group(1) if name else None)
    return out


def summarise(manifest, sacct_file):
    stage_of = stages_by_job(manifest)
    stats = OrderedDict()
    with open(sacct_file) as f:
        rows = list(csv.DictReader(f, delimiter="|"))
    ours = set()   # job/array-task ids whose name matched the manifest
    for row in rows:
        job_id = row["JobID"]
        base = re.split(r"[_.]", job_id)[0]
        if base not in stage_of:
            continue
        stage, name = stage_of[base]
        if "." not in job_id:
            if name and row.get("JobName") != name:
                continue                            # same id, someone else's job
            ours.add(job_id)
        elif job_id.split(".")[0] not in ours:
            continue
        st = stats.setdefault(stage, {"tasks": 0, "states": OrderedDict(), "req": 0.0,
                                      "rss": 0.0, "cpu": 0.0, "wall_cpu": 0.0, "elapsed": []})
        cpus = int(row.get("AllocCPUS") or 1)
        if "." not in job_id:                       # the job/array-task row
            st["tasks"] += 1
            state = (row["State"] or "?").split()[0]
            st["states"][state] = st["states"].get(state, 0) + 1
            st["req"] = max(st["req"], mem_mb(row.get("ReqMem", ""), cpus) or 0.0)
            elapsed = int(row.get("ElapsedRaw") or 0)
            st["elapsed"].append(elapsed)
            st["wall_cpu"] += elapsed * cpus
            st["cpu"] += cpu_seconds(row.get("TotalCPU", ""))
        else:                                       # .batch / .extern steps carry MaxRSS
            st["rss"] = max(st["rss"], mem_mb(row.get("MaxRSS", "")) or 0.0)
    return stats


def format_rows(stats):
    header = ["stage", "tasks", "states", "req_mem_mb", "max_rss_mb", "mem_used_pct",
              "suggested_mem_gb", "mean_elapsed_s", "max_elapsed_s", "cpu_eff_pct"]
    rows = [header]
    for stage, st in stats.items():
        used = 100 * st["rss"] / st["req"] if st["req"] else 0
        eff = 100 * st["cpu"] / st["wall_cpu"] if st["wall_cpu"] else 0
        elapsed = st["elapsed"] or [0]
        rows.append([
            stage, str(st["tasks"]),
            ",".join("%s:%d" % kv for kv in st["states"].items()),
            "%.0f" % st["req"], "%.0f" % st["rss"], "%.0f" % used,
            # 1.5x headroom over the observed peak, at least 1 GB
            str(max(1, int(math.ceil(st["rss"] * 1.5 / 1024)))),
            "%.0f" % (sum(elapsed) / len(elapsed)), str(max(elapsed)), "%.0f" % eff,
        ])
    return rows


def main(argv):
    manifest, sacct_file = argv[1], argv[2]
    rows = format_rows(summarise(manifest, sacct_file))
    out = re.sub(r"\.tsv$", "", sacct_file) + "_summary.tsv"
    with open(out, "w") as f:
        for r in rows:
            f.write("\t".join(r) + "\n")
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
