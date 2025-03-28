#!/usr/bin/sh

#SBATCH --job-name=DATABASE
#SBATCH --time=10-00:00:00
#SBATCH --partition=long
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=300G
#SBATCH --cpus-per-task=20
#SBATCH --dependency=singleton
#SBATCH --output=./slurm_output/database-%j.out

env | grep "^SLURM" | sort

module load PostgreSQL/15.2-GCCcore-12.2.0

CFG_FILE=$1

# DB_DIR="/hpc/mydata/$USER/postgresql_ultrack"
GROUP_NAME=$(getent group $GROUPS | cut -d: -f1)
if [ -z "$JOB_NAME" ]; then
    DB_DIR="/users/$GROUP_NAME/$USER/work/postgresql_ultrack_$SLURM_JOB_ID"
else
    DB_DIR="/users/$GROUP_NAME/$USER/work/postgresql_ultrack_$JOB_NAME"
fi

DB_NAME="ultrack"
# DB_SOCKET_DIR="/tmp"
if [ -z "$JOB_NAME" ]; then
    DB_SOCKET_DIR="/users/$GROUP_NAME/$USER/work/tmp_$SLURM_JOB_ID"
else
    DB_SOCKET_DIR="/users/$GROUP_NAME/$USER/work/tmp_$JOB_NAME"
fi

if [ -d "$DB_SOCKET_DIR" ]; then
    echo "DB socket directory already exists: $DB_SOCKET_DIR"
    rm -rf $DB_SOCKET_DIR
    echo "Previous DB socket directory removed"
fi

mkdir -p "$DB_SOCKET_DIR"
echo "DB socket directory created: $DB_SOCKET_DIR"

# fixing error "FATAL:  unsupported frontend protocol 1234.5679: server supports 2.0 to 3.0"
# reference: https://stackoverflow.com/questions/59190010/psycopg2-operationalerror-fatal-unsupported-frontend-protocol-1234-5679-serve

# known issue: 
# When using SLURM batch submission to start multiple tasks simultaneously, race conditions can occur during port detection, resulting in port conflicts
# Attemp to solve with random port offset
# if problem persist use centralised port assignment, i.e. each creation task write to port lock file
# default postgresql port
DESIRED_PORT=5432
MAX_OFFSET=100
RETRIES=5

# Function to check if a port is in use
is_port_in_use() {
  lsof -i -P -n | grep LISTEN | grep ":$1" > /dev/null
  return $?
}

# Function to find a free port with a random offset and retries
find_free_port() {
  for ((i=0; i<RETRIES; i++)); do
    OFFSET=$((RANDOM % (MAX_OFFSET + 1)))
    PORT=$((DESIRED_PORT + OFFSET))
    if ! is_port_in_use $PORT; then
      echo $PORT
      return 0
    fi
    sleep 1 # brief pause before retrying
  done
  echo "No free port found after $RETRIES retries within the range $DESIRED_PORT to $((DESIRED_PORT + MAX_OFFSET))" >&2
  return 1
}

# Main script
AVAILABLE_PORT=$(find_free_port)
if [[ $? -ne 0 ]]; then
  echo "Failed to obtain a free port"
  exit 1
fi

# # Check if the desired port is in use
# if is_port_in_use $DESIRED_PORT; then
#     echo "Port $DESIRED_PORT is in use."
#     # Find the next available port starting from DESIRED_PORT + 1
#     AVAILABLE_PORT=$((DESIRED_PORT + 1))
#     while is_port_in_use $AVAILABLE_PORT; do
#         AVAILABLE_PORT=$((AVAILABLE_PORT + 1))
#     done
#     echo "Assigning available port: $AVAILABLE_PORT"
# else
#     AVAILABLE_PORT=$DESIRED_PORT
#     echo "Port $DESIRED_PORT is available."
# fi

# Use AVAILABLE_PORT for your PostgreSQL configuration
echo "Using port $AVAILABLE_PORT for PostgreSQL."

DB_ADDR="$USER:$ULTRACK_DB_PW@$SLURM_JOB_NODELIST:$AVAILABLE_PORT/ultrack?gssencmode=disable"

# update config file
echo ""
echo "$(date +'%Y-%m-%d %H:%M:%S') Server running on uri $DB_ADDR"
dasel put -t string -f $CFG_FILE -v $DB_ADDR "data.address" 
# dasel put string -f $CFG_FILE "data.address" $DB_ADDR
echo "$(date +'%Y-%m-%d %H:%M:%S') Updated $CFG_FILE"

rm -rf $DB_DIR
mkdir -p $DB_DIR
initdb $DB_DIR

# setting new lock directory
cat << EOF >> $DB_DIR/postgresql.conf
unix_socket_directories = '$DB_SOCKET_DIR'
EOF

# creating database
echo "$(date +'%Y-%m-%d %H:%M:%S') Initializing DB..."
pg_ctl start -D $DB_DIR -o "-p $AVAILABLE_PORT"

# allowing $USER network access
cat << EOF >> $DB_DIR/pg_hba.conf
host    all             $USER           samenet                 md5
EOF

echo "$(date +'%Y-%m-%d %H:%M:%S') Creating database $DB_NAME..."
createdb -h $DB_SOCKET_DIR -p $AVAILABLE_PORT $DB_NAME

# updating user password
echo "$(date +'%Y-%m-%d %H:%M:%S') user password updated"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER USER \"$USER\" PASSWORD '$ULTRACK_DB_PW';" $DB_NAME

# increasing max connections
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_connections TO '500';" $DB_NAME

# turn on logging
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET logging_collector TO 'on';" $DB_NAME

# # configuration tuned using https://pgtune.leopard.in.ua/
# # and SLURM job parameters
# # -- WARNING
# # -- this tool not being optimal
# # -- for very high memory systems
# # -- DB Version: 15
# # -- OS Type: linux
# # -- DB Type: dw
# # -- Total Memory (RAM): 300 GB
# # -- CPUs num: 20
# # -- Connections num: 500
# # -- Data Storage: hdd
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_connections = '500';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET shared_buffers = '75GB';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET effective_cache_size = '225GB';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET maintenance_work_mem = '2GB';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET checkpoint_completion_target = '0.9';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET wal_buffers = '16MB';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET default_statistics_target = '500';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET random_page_cost = '4';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET effective_io_concurrency = '2';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET work_mem = '7864kB';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET huge_pages = 'try';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET min_wal_size = '4GB';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_wal_size = '16GB';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_worker_processes = '20';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_parallel_workers_per_gather = '10';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_parallel_workers = '20';"
# psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_parallel_maintenance_workers = '4';"

# configuration tuned using https://pgtune.leopard.in.ua/
# and SLURM job parameters
# -- WARNING
# -- this tool not being optimal
# -- for very high memory systems
# -- DB Version: 15
# -- OS Type: linux
# -- DB Type: dw
# -- Total Memory (RAM): 64 GB
# -- CPUs num: 16
# -- Connections num: 500
# -- Data Storage: hdd
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_connections = '500';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET shared_buffers = '16GB';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET effective_cache_size = '48GB';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET maintenance_work_mem = '2GB';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET checkpoint_completion_target = '0.9';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET wal_buffers = '16MB';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET default_statistics_target = '500';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET random_page_cost = '4';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET effective_io_concurrency = '2';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET work_mem = '2097kB';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET huge_pages = 'try';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET min_wal_size = '4GB';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_wal_size = '16GB';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_worker_processes = '16';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_parallel_workers_per_gather = '8';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_parallel_workers = '16';"
psql -h $DB_SOCKET_DIR -p $AVAILABLE_PORT -c "ALTER SYSTEM SET max_parallel_maintenance_workers = '4';"

# restart database
echo "$(date +'%Y-%m-%d %H:%M:%S') Restarting DB..."
pg_ctl stop -D $DB_DIR  -o "-p $AVAILABLE_PORT"
echo "$(date +'%Y-%m-%d %H:%M:%S') Ultrack DB service ready"
postgres -i -D $DB_DIR -p $AVAILABLE_PORT

# STOP:
# pg_ctl stop -D $DB_DIR

# DUMP
# pg_dump -f data.sql -d ultrack -h <NODE> -p <PORT> -U $USER
