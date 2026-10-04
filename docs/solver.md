# Solver settings

## Problem size
The tracking problem is an integer linear program (ILP): one binary variable per candidate segment and per candidate link, plus appearance, disappearance and division variables, with constraints that keep overlapping candidates exclusive and tracks consistent. Its size grows with the candidates and links inside a solve window, i.e. with cell density, candidate hierarchy depth and window length. In the pyCyto benchmark it ranged from 2.7 × 10<sup>5</sup> binary variables (Fluo-N2DL-HeLa 01, 92 frames) to 1.9 × 10<sup>7</sup> (Fluo-N3DL-TRIF 02, one 70-frame window).

The solve job's memory and time follow the ILP size, not the image size; `resource_report_summary.tsv` of a previous run is the best guide for `SOLVE_MEM`.

## Root LP method
By default Gurobi solves the root LP relaxation with primal simplex, dual simplex and barrier concurrently and keeps the first to finish. In every pyCyto benchmark solve a simplex method finished first; for TRIF 02 the barrier alone built a 2.4 × 10<sup>9</sup>-nonzero factorisation (about 30 GB) over 18 min before being discarded. For large windows, solve the root relaxation with dual simplex only:

```toml
[tracking]
method = 1    # root LP: dual simplex (python-mip LP_Method.DUAL, Gurobi Method=1)
```

This changes neither the model nor its optimum.

ultrack passes `method` to python-mip as a plain integer, which python-mip does not recognise, so with ultrack alone every value falls back to Gurobi `Method=3` (concurrent). `ultrack_worker.py solve` converts it (`coerce_lp_method`); the solve log then reports `Set parameter Method to value 1`.

## Other settings
| `[tracking]` key | Effect |
|---|---|
| `window_size`, `overlap_size` | Frames per solve window and frames shared with the next; smaller windows give smaller ILPs but more boundaries to stitch |
| `solution_gap` | Relative optimality gap at which the solve stops (0.001 = 0.1%) |
| `time_limit` | Seconds per window |
| `n_threads` | Solver threads; match `SOLVE_CPUS` |
