"""
Label-series input for segment.py and main.sh.

A label source is either
  * a TIFF glob, one 2D frame per file: ``/data/labels/*.tif``; or
  * a Zarr URI in the pyCyto/tanoa convention: ``/data/exp.zarr#labels/Cellpose/TCell``,
    optionally ``...#group?c=<channel>`` to pick one channel of a 5D store.
    The group may be an array or an OME-NGFF multiscale group (level 0 is
    used); Zarr v2 and v3 stores are both understood.

Metadata helpers (``parse_source``, ``frame_count``) use only the standard
library and run on Python 3.6 -- main.sh calls them on the login node:

    python3 label_io.py frames <source>

``open_labels`` returns a lazy dask array (T, Y, X), or (T, Z, Y, X) for real
Z-stacks (a singleton Z axis is dropped), importing dask/zarr only when called.
"""
import glob
import json
import os
import sys


def parse_source(src):
    """Classify a label source; see module docstring."""
    if "#" in src:
        store, _, rest = src.partition("#")
        group, _, channel = rest.partition("?c=")
        group = group.strip("/")
        if not store or not group or "#" in rest:
            raise ValueError("not a valid Zarr URI (expected 'store.zarr#group[?c=channel]'): %r" % src)
        return {"kind": "zarr", "store": store, "group": group, "channel": channel or None}
    return {"kind": "tiff", "pattern": src}


def _read_json(path):
    with open(path) as f:
        return json.load(f)


def _node(store, path):
    """(node type, metadata, attributes) of a Zarr node, v3 or v2."""
    base = os.path.join(store, path) if path else store
    v3 = os.path.join(base, "zarr.json")
    if os.path.exists(v3):
        meta = _read_json(v3)
        return meta["node_type"], meta, meta.get("attributes", {})
    attrs_file = os.path.join(base, ".zattrs")
    attrs = _read_json(attrs_file) if os.path.exists(attrs_file) else {}
    if os.path.exists(os.path.join(base, ".zarray")):
        return "array", _read_json(os.path.join(base, ".zarray")), attrs
    if os.path.exists(os.path.join(base, ".zgroup")):
        return "group", _read_json(os.path.join(base, ".zgroup")), attrs
    raise ValueError("no Zarr array or group at %s" % base)


def resolve_array(store, group):
    """Path of the array to read, its shape, and its axis names (or None).

    A multiscale group resolves to its first (full-resolution) dataset; NGFF
    0.5 keeps the metadata under attributes["ome"], 0.4 at the top level.
    """
    kind, meta, attrs = _node(store, group)
    if kind == "array":
        return group, list(meta["shape"]), None
    ngff = attrs.get("ome", attrs)
    multiscales = ngff.get("multiscales")
    if not multiscales:
        raise ValueError("%s#%s is a group without OME-NGFF multiscales; point at an array" % (store, group))
    ms = multiscales[0]
    path = "%s/%s" % (group, ms["datasets"][0]["path"])
    axes = [a["name"] if isinstance(a, dict) else a for a in ms.get("axes", [])] or None
    _, ameta, _ = _node(store, path)
    return path, list(ameta["shape"]), axes


def frame_count(src):
    """Number of time points in a label source."""
    s = parse_source(src)
    if s["kind"] == "tiff":
        return len(glob.glob(s["pattern"]))
    _, shape, axes = resolve_array(s["store"], s["group"])
    return shape[axes.index("t")] if axes and "t" in axes else shape[0]


def _channel_index(store, group, channel):
    if channel.isdigit():
        return int(channel)
    _, _, attrs = _node(store, group)
    omero = attrs.get("ome", attrs).get("omero", {})
    labels = [c.get("label") for c in omero.get("channels", [])]
    if channel not in labels:
        raise ValueError("channel %r not in %s#%s (have %s)" % (channel, store, group, labels))
    return labels.index(channel)


def open_labels(src, begin=0, end=None, step=1):
    """Lazy dask array of frames begin..end (inclusive), every `step`-th."""
    stop = None if end is None or end < 0 else end + 1
    s = parse_source(src)
    if s["kind"] == "tiff":
        import dask_image.imread
        files = sorted(glob.glob(s["pattern"]))
        if not files:
            raise FileNotFoundError("no files match %s" % s["pattern"])
        return dask_image.imread.imread(s["pattern"])[begin:stop:step]

    import dask.array as da
    import zarr

    path, shape, axes = resolve_array(s["store"], s["group"])
    arr = da.from_zarr(zarr.open(s["store"], mode="r")[path])
    if axes is None:
        # plain array: time first; drop a singleton Z of a (T, 1, Y, X) array
        if arr.ndim == 4 and arr.shape[1] == 1:
            arr = arr[:, 0]
        return arr[begin:stop:step]

    names = list(axes)
    if "c" in names:
        if s["channel"] is None:
            if arr.shape[names.index("c")] != 1:
                raise ValueError("%s has %d channels; select one with ?c=<name>" % (src, arr.shape[names.index("c")]))
            ci = 0
        else:
            ci = _channel_index(s["store"], s["group"], s["channel"])
        arr = da.take(arr, ci, axis=names.index("c"))
        names.remove("c")
    order = [n for n in ("t", "z", "y", "x") if n in names]
    arr = arr.transpose([names.index(n) for n in order])
    if "z" in order and arr.shape[1] == 1:   # order is t, z, y, x
        arr = arr[:, 0]
    return arr[begin:stop:step]


def main(argv):
    if len(argv) == 3 and argv[1] == "frames":
        print(frame_count(argv[2]))
        return 0
    sys.stderr.write("usage: label_io.py frames <label source>\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
