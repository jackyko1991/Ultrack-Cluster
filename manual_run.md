# BMRC Ultrack Step-by-Step Manual Run

1. Change the working directory to `tracking`
2. Activate python virtual environment. More preferred than in-script loading.
    ```bash
    mamba activate ultrack
    ```
2. Start PostgreSQL DB server
    ```bash
    # script based run from head node
    export ULTRACK_DB_PW="ultrack_pw"
    export CFG_FILE=./config.toml
    sbatch create_server.sh

    # pty bash session run
    srun -p short --pty bash
    export ULTRACK_DB_PW="ultrack_pw"
    export CFG_FILE=./config.toml
    bash create_server.sh
    ```

    Check output log in `./slurm_output` or `config.toml` for the DB address. You should see the DB node URL as following:
    ```
    address = 'oyk357:ultrack_pw@compe009:5432/ultrack?gssencmode=disable'
    ```

    On BMRC you will need port forwarding on `5432` with headnode proxy tunneling to access the database from local:
    ```bash
    ssh -L <local-port>:<node-name>:<remote-port> <username>@cluster2.bmrc.ox.ac.uk

    # example
    ssh -L 5432:compe009:5432 oyk357@cluster2.bmrc.ox.ac.uk
    ```

    Then you can access the childnode DB with URI [localhost:5432](localhost:5432)

    ## Resume Existing PostgreSQL
    ```bash
    # script based run from head node
    export ULTRACK_DB_PW="ultrack_pw"
    export CFG_FILE=./config.toml
    sbatch resume_server.sh

    # pty bash session run
    srun -p short --pty bash
    export ULTRACK_DB_PW="ultrack_pw"
    export CFG_FILE=./config.toml
    bash resume_server.sh
    ```

3. (Optional) DB clean up
    ```bash
    srun -p short --pty bash
    mamba activate ultrack
    ultrack clear_database -cfg ./config.toml {all|links|solutions}
    ```

3. Load pre-segmented label file to DB. This step can be accelerated by GPU for image preprocessing.
    ```bash
    # environment variables
    export DS_LENGTH=<max-time-steps>
    export LABEL_PATH_PATTERN=<path-to-label-tiff-dir>

    # cpu only, change the values within <brackets>
    sbatch --array=0-$DS_LENGTH%<MAX-JOBS> segment.sh "$LABEL_PATH_PATTERN"

    # gpu
    sbatch -p gpu_short --gres gpu:1 --array=0-$DS_LENGTH%<MAX-JOBS> segment.sh "$LABEL_PATH_PATTERN"
    ```
5. Link the loaded labels after segment label to DB task has been finished.

    In the segmentation task sbatch will return the `SLURM_ARRAY_JOB_ID`. This is exported as `$SEGM_JOB_ID` for convenience.
    ```bash
    sbatch --array=0-$((DS_LENGTH - 1))%<MAX-JOBS> -d afterok:$SEGM_JOB_ID link.sh
    ```

6. Solve the tracking optimization problem. To achieve so first check the `$NUM_WINDOWS`, where 
    ```bash
    NUM_WINDOWS = ceil($DS_LENGTH / <window_size>) - 1 # <window_size> is the value in config.toml under [tracking]
    ```
    
    ```bash
    if (($NUM_WINDOWS == 0)); then
        SOLVE_JOB_ID_1=$(sbatch --array=0-0 -d afterok:$LINK_JOB_ID solve.sh)
    else
        SOLVE_JOB_ID_0=$(sbatch --array=0-$NUM_WINDOWS:2 -d afterok:$LINK_JOB_ID solve.sh)
        SOLVE_JOB_ID_1=$(sbatch --array=1-$NUM_WINDOWS:2 -d afterok:$SOLVE_JOB_ID_0 solve.sh)
    fi
    ```

7. Result merging
    ```bash
    sbatch -d afterok:$SOLVE_JOB_ID_1 export.sh
    ```

