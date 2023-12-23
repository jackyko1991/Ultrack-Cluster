import os
import dask_image.imread

from ultrack.utils import estimate_parameters_from_labels, labels_to_edges
from ultrack.utils.array import array_apply, create_zarr
from scipy.ndimage import gaussian_filter
from ultrack import segment, MainConfig, load_config

from rich.pretty import pprint
import argparse
import numpy as np

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

    args = parser.parse_args()
    return args

def main(args):
    # read image
    LABEL_PATH_PATTERN = args.path
    label = dask_image.imread.imread(LABEL_PATH_PATTERN)[:100,:,:]

    print(label.shape)

    sigma_xy = 1.0
    sigma_t = 1.2

    # can this be done by multi nodes?
    detection, edges = labels_to_edges(
        label, 
    )

    # perform gaussian blur to create fuzzy edges in space and time
    edges_blur=gaussian_filter(edges, sigma=[sigma_t,sigma_xy,sigma_xy])

    # TODO: Apply array apply for the labels to edges conversion to zarr format
    # convert detection and edges to zarr
    # detection = create_zarr(label.shape, bool, store_or_path="./detection.zarr",overwrite=True)
    # edges = create_zarr(label.shape, np.float, store_or_path="./edge.zarr",overwrite=True)

    # array_apply(
    #     label,
    #     out_array=detection,
    #     func=labels_to_edges,
    #     )

    # load config file
    cfg = load_config(args.cfg)
    pprint(cfg)

    # add segment to database
    segment(
        detection,
        edges,
        cfg,
        batch_index=args.batch_index, # how do the SLURM_ARRAY_TASK_ID work here? slurm array ranges from 0 to $DS_LENGTH%200, not quite sure how the max slurm array task id is obtained
        overwrite=True,
    )

if __name__ == "__main__":
    """
    CLI worker to implement ultrack segment https://royerlab.github.io/ultrack/api.html#ultrack.segment
    Alternative tool to the ultrack CLI tool (https://royerlab.github.io/ultrack/cli.html#ultrack-segment) for tiff to PostgreSQL DB reading
    """
    args = get_args()
    main(args)