# Ultrack-Cluster
BMRC cluster run test script for [Ultrack](https://github.com/royerlab/ultrack)

## Brief Intro

This version of distributed running is not available on pypi yet. Users may install the nightly code until the next release: 

```bash
# TODO: update to conda env.yml + requirements.txt install
$ mamba create -n ultrack python=3.10
$ mamba activate ultrack
$ pip install -r requirements.txt

# if pip exceed system tmp size
$ TMPDIR=~/work/tmp pip install -r requirements.txt
```

This repository contains essential SLURM scripts that calls ultrack CLI run. The files are equivalent to `segment`, `link` and `solve` function in the ultrack Python API.

Details are modified to fit the BMRC SLURM and infrastructure setup. It provides a reference code for cluster run modification.

### PostgreSQL Server Setup
Most cluster environment may not come with all necessary tools for the PostgreSQL server setup in [create_server.sh](./tracking/create_server.sh). For an automated software installation (script dedicated to BMRC folder structure but you may modify to fit your system's installation environment), edit `$INSTALL_DIR` in `install_server_dependency.sh` then run:
```bash
bash install_server_dependency.sh
source ~/.bashrc
```

### Environment Variable
You need a environment variable `$ULTRACK_DB_PW` used in the `create_server.sh`

### Quick Run
#### Data Perquisite
For convenience data IO, the segmentation file input is in zarr format. For quick data conversion from tiff format to zarr, check [tiff_to_zarr.py](./preprocess/tiff_to_zarr.py). Cluster run script is available in [tiff_to_zarr.sbatch](./preprocess/tiff_to_zarr.sbatch)

#### Folder Structures
It assumes the following directory structure, you can modify the file paths as you wish on the `main.sh`

```
root/
    segments.zarr  # boundary and detection maps
    tracking/
        config.toml
        main.sh
        create_server.sh
        ... # other .sh files
```

In the `main.sh`, you must fill `DS_LENGTH` and `NUM_WINDOWS` variables. These files are used as a template in my workflow, and a Python script fills this information.

For example, for a dataset with 225 time points and `window_size` of 50 (from the [`config.toml`](./tracking/config.toml)) we have:
``` bash
DS_LENGTH = 224  # 225 - 1
NUM_WINDOWS = 4  # ceil(225 / 50) - 1
```

#### Automated Scripts
And then you execute `bash main.sh`. You must stop the database job once the tracking is done.

#### Manual Run
1. Start PostgreSQL DB server
    ```bash
    # script based run from head node
    export ULTRACK_DB_PW="ultrack_pw"
    sbatch create_server.sh

    # pty bash session run
    srun -p short --pty bash
    export ULTRACK_DB_PW="ultrack_pw"
    bash create_server.sh
    ```

## FAQ
1. **Can the label information in the SQL database being reused at different tracking stages?**

    Yes, within the original python script the data is initially transformed from labeled image format to SQL database for potential optimization at a later stage. This process may often take a very long time if the tracking scale is large. For extensive parameter grid search for the tracking parameter settings, users may employ the database server establishment script and subsequently share and reuse the intermediate results to reduce overall computation time.

    Users may only need to run staring from the tracking step that you have changed the parameter from the grid search. E.g. if you change a parameter from `config.linking_config` you can continue from the `ultrack link` step and `ultrack solve` for the `config.tracking_config` parameters. Because building the hierarchies (`ultrack segment`) is the first step, `config.segmentation_config`, it cannot be run from a partially computed database.

    The Ultrack CLI provides the `--overwrite` flag to clean the partial results before re-executing most steps. However, they don't work on distributed computing because not all jobs are executed simultaneously. The database would be cleaned for each job call with `--overwrite` flag. So you must use our helper command `ultrack clear_database -cfg config.toml <STAGE TO CLEAN (e.g. link)>` before executing the respective step.

2. **Is there any available documentation detailing the structure of the database and its associated Python interface for data retrieval?**
    
    [This](https://github.com/royerlab/ultrack/blob/main/ultrack/core/README.md) is the current documentation of the SQL schema implemented [here](https://github.com/royerlab/ultrack/blob/main/ultrack/core/database.py). We use [SQLAlchemy](https://www.sqlalchemy.org/) to interact with it in Python through the code base.

3. **In which circumstances PostgreSQL is recommended over SQLite for ultrack?**
    
    SQLite is used in default for everything in ultrack except for SLURM large dataset run for its simpleness and straightforward that works most of the time.

    However SQLite is not the most performant, and it fails when running several workers. If performance is a concern and don't mind spinning up a server, Postgres is a better option.