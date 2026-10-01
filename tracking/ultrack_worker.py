"""
Headless entry points for the link, solve and export stages.

Calls ultrack's Python API directly instead of the `ultrack` CLI: the CLI
imports its napari/Qt widgets at start-up (ultrack 0.8.0), so on a headless
compute node it fails unless fontconfig, OpenGL ES and Qt bindings are all
installed. The API itself needs none of them. Works with ultrack 0.4 and 0.8.

    python ultrack_worker.py link   -cfg config.toml -b 3
    python ultrack_worker.py solve  -cfg config.toml -b 3
    python ultrack_worker.py export -cfg config.toml -o results/ [-ow]
"""
import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

LOG = logging.getLogger("ultrack-cluster")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("link", "solve"):
        p = sub.add_parser(name)
        p.add_argument("-cfg", "--config", required=True, type=Path)
        p.add_argument("-b", "--batch-index", type=int, default=None)
        p.add_argument("-ow", "--overwrite", action="store_true")
    p = sub.add_parser("export", help="tracks.csv + segments.zarr (as `ultrack export zarr-napari`)")
    p.add_argument("-cfg", "--config", required=True, type=Path)
    p.add_argument("-o", "--output-directory", required=True, type=Path)
    p.add_argument("-ow", "--overwrite", action="store_true")
    return parser.parse_args(argv)


def _prepare_output(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"{path} exists; pass -ow to overwrite")
        shutil.rmtree(path) if path.is_dir() else path.unlink()


def link_scale(config):
    """Voxel scale for link distances: ULTRACK_SCALE ("z,y,x" or "y,x", e.g.
    "11.1,1,1" for an anisotropic stack) wins over the run's metadata.toml."""
    env = os.environ.get("ULTRACK_SCALE")
    if env:
        return [float(v) for v in env.split(",")]
    return getattr(config.data_config, "metadata", {}).get("scale")


def run_link(config, batch_index, overwrite):
    from ultrack import link
    scale = link_scale(config)
    LOG.info("link scale: %s", scale)
    link(config, images=[], scale=scale, batch_index=batch_index, overwrite=overwrite)


def require_gurobi() -> None:
    """
    Fail unless Gurobi is usable. ultrack itself falls back to CBC silently
    when Gurobi is missing or unlicensed (even with solver_name = "GUROBI"),
    and CBC can take hours to prove what Gurobi proves in minutes -- so a
    lost licence must stop the job, not quietly change the solver.
    ULTRACK_ALLOW_CBC=1 accepts CBC explicitly.
    """
    if os.environ.get("ULTRACK_ALLOW_CBC") == "1":
        LOG.warning("ULTRACK_ALLOW_CBC=1: CBC accepted if Gurobi is unavailable")
        return
    import mip
    try:
        mip.Model(solver_name=mip.GRB)
    except Exception as e:   # mip's InterfacingError, or a Gurobi licence error
        raise SystemExit(f"Gurobi is not available ({e}). Set GRB_LICENSE_FILE to a valid licence "
                         f"(BMRC: solve.sh sets the site licence), or ULTRACK_ALLOW_CBC=1 to accept CBC.")
    LOG.info("Gurobi available (GRB_LICENSE_FILE=%s)", os.environ.get("GRB_LICENSE_FILE", "unset"))


def run_solve(config, batch_index, overwrite):
    from ultrack import solve
    require_gurobi()
    solve(config, batch_index, overwrite)


def run_export(config, out_dir: Path, overwrite: bool):
    from ultrack.core.export import to_tracks_layer, tracks_to_zarr
    tracks_path = out_dir / "tracks.csv"
    segments_path = out_dir / "segments.zarr"
    _prepare_output(tracks_path, overwrite)
    _prepare_output(segments_path, overwrite)
    out_dir.mkdir(parents=True, exist_ok=True)
    tracks, _ = to_tracks_layer(config, include_parents=True)
    tracks.to_csv(tracks_path, index=False)
    tracks_to_zarr(config, tracks, store_or_path=str(segments_path))
    LOG.info("exported %d track points (%d tracks) to %s",
             len(tracks), tracks["track_id"].nunique(), out_dir)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s [%(levelname)-5s] [%(name)s] %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    from ultrack.config import load_config
    config = load_config(args.config)
    start = time.time()
    if args.command == "link":
        run_link(config, args.batch_index, args.overwrite)
    elif args.command == "solve":
        run_solve(config, args.batch_index, args.overwrite)
    else:
        run_export(config, args.output_directory, args.overwrite)
    LOG.info("%s finished in %.1fs", args.command, time.time() - start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
