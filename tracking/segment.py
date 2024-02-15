import os
import dask_image.imread

from ultrack.utils import estimate_parameters_from_labels, labels_to_edges
from ultrack.utils.array import array_apply, create_zarr
from scipy.ndimage import gaussian_filter
from ultrack import segment, MainConfig, load_config
from ultrack.utils.multiprocessing import batch_index_range

import zarr
from rich.pretty import pprint
import argparse
import numpy as np
import socket

def get_args():
    parser = argparse.ArgumentParser(description="CLI worker for ultrack segment task")
    
    parser.add_argument(
        '-p', '--path', 
        type=str,
        metavar="PATH_PATTERN",
        dest="path",
        help='Path pattern of the label files'
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

    # read image
    LABEL_PATH_PATTERN = args.path
    if args.end != -1:
        label = dask_image.imread.imread(LABEL_PATH_PATTERN)[args.begin:args.end+1:args.scale]
    else:
        label = dask_image.imread.imread(LABEL_PATH_PATTERN)[args.begin,-1,args.scale]

    # same function used in `segment` call below
    time_points = list(batch_index_range(
        label.shape[0],
        cfg.segmentation_config.n_workers,
        args.batch_index,
    ))

    # TODO: exterior sigma control
    sigma_xy = 1.0
    sigma_t = 1.2

    # I'm assuming it fits into memory, zarr.TempStore could be used otherwise
    detection = create_zarr(label.shape, dtype=np.bool_,store_or_path=zarr.MemoryStore())
    edges = create_zarr(label.shape, dtype=np.float32,store_or_path=zarr.MemoryStore())

    if args.blur_padding != 0:
        # load padding slices for temporal blurring
        for _ in range(args.blur_padding):
            time_points.insert(0,time_points[0]-1)
            time_points.append(time_points[-1]+1)

        # filter out of range indices
        time_points = [x for x in time_points if 0 <= x <= label.shape[0]]

    # compute edges and detection for a subset of points
    for t in time_points:
        t_det, t_edges = labels_to_edges(np.asarray(label[t:t+1,:,:])) # accept only list of labels, retains time dim for readability
        detection[t:t+1,:,:] = t_det
        edges[t:t+1,:,:] = t_edges

    # perform gaussian blur to create fuzzy edges in space and time
    if sigma_t > 0 and args.blur_padding != 0:
        edges[time_points[0]:time_points[-1]+1] = gaussian_filter(edges[time_points[0]:time_points[-1]+1], sigma=[sigma_t,sigma_xy,sigma_xy])

    # add segment to database
    ip = cfg.data_config.address.split("@")[1].split(":")[0]
    port = 5432

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
            print("Adding segmentation to DB...")
            segment(
                detection,
                edges,
                cfg,
                batch_index=args.batch_index,
                overwrite=True,
            )
            print("Adding segmentation to DB success")
            break
        except Exception as e:
            # If connection fails, print an error message
            print(f"Attempt {attempt}/{MAX_RETRIES}: Add segment to DB@{ip} on port {port} failed: \n{e}")
            if attempt < MAX_RETRIES:
                print("Retrying...")
                continue
            else:
                print("Max retries {} reached.".format(MAX_RETRIES))
                exit(1)

if __name__ == "__main__":
    """
    CLI worker to implement ultrack segment https://royerlab.github.io/ultrack/api.html#ultrack.segment
    Alternative tool to the ultrack CLI tool (https://royerlab.github.io/ultrack/cli.html#ultrack-segment) for tiff to PostgreSQL DB reading
    """
    args = get_args()
    main(args)