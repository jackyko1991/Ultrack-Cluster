import os
import sys

from ultrack.utils import labels_to_edges
from ultrack.utils.array import create_zarr
from scipy.ndimage import gaussian_filter
from ultrack import segment, load_config
from ultrack.utils.multiprocessing import batch_index_range

import zarr
from rich.pretty import pprint
import argparse
import numpy as np
import socket
import time
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from label_io import open_labels  # noqa: E402

def get_args():
    parser = argparse.ArgumentParser(description="CLI worker for ultrack segment task")
    
    parser.add_argument(
        '-p', '--path', 
        type=str,
        metavar="PATH_PATTERN",
        dest="path",
        help="Label source: a TIFF glob ('/data/*.tif') or a Zarr URI ('/data/exp.zarr#labels/Cellpose/TCell[?c=channel]')"
        )
    parser.add_argument(
        '-c', '--cfg', 
        type=str,
        metavar="PATH",
        dest="cfg",
        help='Path to Ultrack configuration file (.toml)'
        )
    parser.add_argument(
        '-bi', '--batch_index',
        default=None,
        type=int,
        metavar="INT",
        dest="batch_index",
        help="Batch index to process a subset of time points. ATTENTION: this it not the time index."
        )
    parser.add_argument(
        '-v', '--verbosity', 
        type=int, 
        choices=[0, 1, 2], 
        default=1,
        help='Verbosity level (0, 1 or 2, default is 1)'
        )
    parser.add_argument(
        '-b', '--begin',
        metavar="INT",
        dest="begin",
        type=int,
        default=0,
        help='First time steps to process'
    )
    parser.add_argument(
        '-e', '--end',
        metavar="INT",
        dest="end",
        type=int,
        default=-1,
        help='Last time steps to process'
    )
    parser.add_argument(
        '-bp','--blur_padding',
        metavar="INT",
        dest="blur_padding",
        type=int,
        default=0,
        help='Temporal Gaussian blur stack padding. Default is zero'
    )
    parser.add_argument(
        '-bz','--batch_size',
        metavar="INT",
        dest="batch_size",
        type=int,
        default=50,
        help="Batch size for labels to edges conversion"
    )
    parser.add_argument(
        '-s','--scale',
        metavar="INT",
        dest="scale",
        type=int,
        default=1,
        help='Temporal binning scale, default to be 1'
    )

    args = parser.parse_args()
    return args

def main(args):
    # load config file
    cfg = load_config(args.cfg)
    MAX_RETRIES=3
    pprint(cfg)

    # read labels: (T, Y, X), or (T, Z, Y, X) for real Z-stacks
    label = open_labels(args.path, begin=args.begin, end=args.end, step=args.scale)

    # same function used in `segment` call below
    time_points = list(batch_index_range(
        label.shape[0],
        cfg.segmentation_config.n_workers,
        args.batch_index,
    ))

    # TODO: exterior sigma control
    sigma_xy = 1.0
    sigma_t = 1.2

    # Full-length arrays, as segment() indexes them by absolute frame; only
    # this task's frames (plus blur padding) are written, so the in-memory
    # store holds just those chunks.
    detection = create_zarr(label.shape, dtype=np.bool_, store_or_path=zarr.storage.MemoryStore())
    edges = create_zarr(label.shape, dtype=np.float32, store_or_path=zarr.storage.MemoryStore())

    # frames to convert: the batch plus padding for temporal blurring
    first = max(time_points[0] - args.blur_padding, 0)
    last = min(time_points[-1] + args.blur_padding, label.shape[0] - 1)

    # compute edges and detection, batch_size frames at a time
    for t in tqdm(range(first, last + 1, args.batch_size), desc="Images to Edges"):
        stop = min(t + args.batch_size, last + 1)
        t_det, t_edges = labels_to_edges(np.asarray(label[t:stop]))
        detection[t:stop] = t_det[:]
        edges[t:stop] = t_edges[:]

    # perform gaussian blur to create fuzzy edges in space and time
    if sigma_t > 0 and args.blur_padding != 0:
        sigma = [sigma_t] + [sigma_xy] * (label.ndim - 1)
        edges[first:last + 1] = gaussian_filter(edges[first:last + 1], sigma=sigma)

    # Only batch 0 (or an unbatched run) may clear the database: ultrack
    # creates the tables in that batch and clear_all_data()s them when
    # overwrite=True. Any other batch passing overwrite=True is harmless only
    # because ultrack ignores it there -- but batch 0 must never run after the
    # others have inserted (main.sh runs it as its own job first; a late or
    # requeued batch 0 with overwrite would silently wipe their segments).
    overwrite = args.batch_index in (None, 0)

    # add segment to database
    if cfg.data_config.database == "postgresql":
        ip = cfg.data_config.address.split("@")[1].split(":")[0]
        port = int(cfg.data_config.address.split(':')[2].split('/')[0])

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Create a TCP socket
                print(f"Attempting connect to DB@{ip} on port {port} ({attempt}/{MAX_RETRIES})")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Set a timeout for the connection attempt
                s.settimeout(5)
                # Attempt to connect to the IP and port
                s.connect((ip, port))
                # If connection is successful, print a success message
                print(f"Connected to DB@{ip} on port {port}")
                # Close the socket after use
                s.close()
                print("Adding segmentation to PostgreSQL DB...")
                segment(
                    detection,
                    edges,
                    cfg,
                    batch_index=args.batch_index,
                    overwrite=overwrite,
                    insertion_throttle_rate=50
                )
                print("Adding segmentation to PostgreSQL DB success")
                break
            except Exception as e:
                # If connection fails, print an error message
                print(f"Attempt {attempt}/{MAX_RETRIES}: Add segment to DB@{ip} on port {port} failed: \n{e}")
                print(e)
                if attempt < MAX_RETRIES:
                    WAIT_TIME=120 # in second
                    # WAIT_TIME=5 # in second
                    print(f"DB may be busy, wait for {WAIT_TIME}s before retry")
                    time.sleep(WAIT_TIME)
                    print("Retrying...")
                    continue
                else:
                    print("Max retries {} reached.".format(MAX_RETRIES))
                    exit(1)
    else:
        print("Adding segmentation to Sqlite DB...")
        segment(
            detection,
            edges,
            cfg,
            batch_index=args.batch_index,
            overwrite=overwrite,
            insertion_throttle_rate=50
        )
        print("Adding segmentation to Sqlite DB success")

if __name__ == "__main__":
    """
    CLI worker to implement ultrack segment https://royerlab.github.io/ultrack/api.html#ultrack.segment
    Alternative tool to the ultrack CLI tool (https://royerlab.github.io/ultrack/cli.html#ultrack-segment) for tiff to PostgreSQL DB reading
    """
    args = get_args()
    main(args)
