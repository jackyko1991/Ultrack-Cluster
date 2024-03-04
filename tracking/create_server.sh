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

# DB_DIR="/hpc/mydata/$USER/postgresql_ultrack"
GROUP_NAME=$(getent group $GROUPS | cut -d: -f1)
DB_DIR="/users/$GROUP_NAME/$USER/work/postgresql_ultrack_$JOB_NAME"
DB_NAME="ultrack"
# DB_SOCKET_DIR="/tmp"
DB_SOCKET_DIR="/users/$GROUP_NAME/$USER/work/tmp_$JOB_NAME"
if [ -d "$DB_SOCKET_DIR" ]; then
    echo "DB socket directory already exists: $DB_SOCKET_DIR"
    rm -rf $DB_SOCKET_DIR
    echo "Previous DB socket directory removed"
fi

mkdir -p "$DB_SOCKET_DIR"
echo "DB socket directory created: $DB_SOCKET_DIR"

# fixing error "FATAL:  unsupported frontend protocol 1234.5679: server supports 2.0 to 3.0"
# reference: https://stackoverflow.com/questions/59190010/psycopg2-operationalerror-fatal-unsupported-frontend-protocol-1234-5679-serve
DB_ADDR="$USER:$ULTRACK_DB_PW@$SLURM_JOB_NODELIST:5432/ultrack?gssencmode=disable"

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
pg_ctl start -D $DB_DIR

# allowing $USER network access
cat << EOF >> $DB_DIR/pg_hba.conf
host    all             $USER           samenet                 md5
EOF

createdb -h $DB_SOCKET_DIR $DB_NAME

# updating user password
psql -h $DB_SOCKET_DIR -c "ALTER USER \"$USER\" PASSWORD '$ULTRACK_DB_PW';" $DB_NAME

# increasing max connections
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET max_connections TO '500';" $DB_NAME

# turn on logging
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET logging_collector TO 'on';" $DB_NAME

# configuration tuned using https://pgtune.leopard.in.ua/
# and SLURM job parameters
# -- WARNING
# -- this tool not being optimal
# -- for very high memory systems
# -- DB Version: 15
# -- OS Type: linux
# -- DB Type: dw
# -- Total Memory (RAM): 300 GB
# -- CPUs num: 20
# -- Connections num: 500
# -- Data Storage: hdd
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET max_connections = '500';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET shared_buffers = '75GB';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET effective_cache_size = '225GB';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET maintenance_work_mem = '2GB';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET checkpoint_completion_target = '0.9';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET wal_buffers = '16MB';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET default_statistics_target = '500';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET random_page_cost = '4';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET effective_io_concurrency = '2';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET work_mem = '7864kB';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET huge_pages = 'try';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET min_wal_size = '4GB';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET max_wal_size = '16GB';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET max_worker_processes = '20';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET max_parallel_workers_per_gather = '10';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET max_parallel_workers = '20';"
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET max_parallel_maintenance_workers = '4';"

# restart database
echo "$(date +'%Y-%m-%d %H:%M:%S') Restarting DB..."
pg_ctl stop -D $DB_DIR
echo "$(date +'%Y-%m-%d %H:%M:%S') Ultrack DB service ready"
postgres -i -D $DB_DIR

# STOP:
# pg_ctl stop -D $DB_DIR

# DUMP
# pg_dump -f data.sql -d ultrack -h <NODE> -p <PORT> -U $USER
