import os
import dask_image.imread

from ultrack.utils import estimate_parameters_from_labels, labels_to_edges
from ultrack.utils.array import array_apply, create_zarr
from scipy.ndimage import gaussian_filter
from ultrack import segment, MainConfig, load_config
from ultrack.utils.multiprocessing import batch_index_range

from rich.pretty import pprint
import argparse
import numpy as np

def valid_blur_steps_type(value):
    """
    Custom argparse type for temporal Gaussian blur steps given from the command line
    """
    if value is None or value.lower=="none":
        return None
    elif int(value) % 2 != 0:
        return value
    else:
        raise argparse.ArgumentTypeError("Value must be an odd integer, or None")


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
        '-b', '--batch_index',
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
        '-l', '--length',
        metavar="INT",
        dest="length",
        type=int,
        default=-1,
        help='Maximum time steps to process'
    )
    parser.add_argument(
        '-bs','--blur_steps',
        metavar="ODD INT",
        dest="blur_steps",
        type=valid_blur_steps_type,
        default=None,
        help='Temporal Gaussian blur stack size. Has to be odd integer for symmetry. If None or 1 then temporal blur is skipped (default is None)'
    )

    args = parser.parse_args()
    return args

def main(args):
    # load config file
    cfg = load_config(args.cfg)
    pprint(cfg)

    # read image
    LABEL_PATH_PATTERN = args.path
    label = dask_image.imread.imread(LABEL_PATH_PATTERN)[0:args.length+1]

    # same function used in `segment` call below
    time_points = list(batch_index_range(
        label.shape[0],
        cfg.segmentation_config.n_workers,
        args.batch_index,
    ))

    sigma_xy = 1.0
    sigma_t = 1.2

    # I'm assuming it fits into memory, zarr.TempStore could be used otherwise
    detection = create_zarr(label.shape, dtype=np.bool_)
    edges = create_zarr(label.shape, dtype=np.float32)

    if args.blur_steps not in ["1", None]:
        # load padding slices for temporal blurring
        padding_t = int(args.blur_steps)%2
        for _ in range(padding_t):
            time_points.insert(0,time_points[0]-1)
            time_points.append(time_points[-1]+1)

        # filter out of range indices
        time_points = [x for x in time_points if 0 <= x < args.length]

    # compute edges and detection for a subset of points
    for t in time_points:
        t_det, t_edges = labels_to_edges(np.asarray(label[t:t+1,:,:])) # accept only list of labels, retains time dim for readability
        detection[t:t+1,:,:] = t_det
        edges[t:t+1,:,:] = t_edges

    # perform gaussian blur to create fuzzy edges in space and time
    if sigma_t > 0 and args.blur_steps not in ["1", None]:
        edges[time_points[0]:time_points[-1]+1] = gaussian_filter(edges[time_points[0]:time_points[-1]+1], sigma=[sigma_t,sigma_xy,sigma_xy])

    # add segment to database
    segment(
        detection,
        edges,
        cfg,
        batch_index=args.batch_index,
        overwrite=True,
    )

if __name__ == "__main__":
    """
    CLI worker to implement ultrack segment https://royerlab.github.io/ultrack/api.html#ultrack.segment
    Alternative tool to the ultrack CLI tool (https://royerlab.github.io/ultrack/cli.html#ultrack-segment) for tiff to PostgreSQL DB reading
    """
    args = get_args()
    main(args)