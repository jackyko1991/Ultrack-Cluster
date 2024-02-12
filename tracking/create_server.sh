#!/usr/bin/sh

#SBATCH --job-name=DATABASE
#SBATCH --time=1-00:00:00
#SBATCH --partition=long
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --mem=100G
#SBATCH --cpus-per-task=10
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
if [ ! -d "$DB_SOCKET_DIR" ]; then
    mkdir -p "$DB_SOCKET_DIR"
    echo "DB socket directory created: $DB_SOCKET_DIR"
else
    echo "DB socket directory already exists: $DB_SOCKET_DIR"
fi

# fixing error "FATAL:  unsupported frontend protocol 1234.5679: server supports 2.0 to 3.0"
# reference: https://stackoverflow.com/questions/59190010/psycopg2-operationalerror-fatal-unsupported-frontend-protocol-1234-5679-serve
DB_ADDR="$USER:$ULTRACK_DB_PW@$SLURM_JOB_NODELIST:5432/ultrack?gssencmode=disable"

# update config file
echo ""
echo "$(date +'%Y-%m-%d %H:%M:%S') Server running on uri $DB_ADDR"
dasel put -t string -f $CFG_FILE -v $DB_ADDR "data.address" 
# dasel put string -f $CFG_FILE "data.address" $DB_ADDR
echo "$(date +'%Y-%m-%d %H:%M:%S') Updated $CFG_FILE"

rm -r $DB_DIR
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

# increases WAL size to improve performance
# https://www.postgresql.org/docs/current/wal-configuration.html
psql -h $DB_SOCKET_DIR -c "ALTER SYSTEM SET max_wal_size TO '10GB';" $DB_NAME

# restart database
echo "$(date +'%Y-%m-%d %H:%M:%S') Restarting DB..."
pg_ctl stop -D $DB_DIR
echo "$(date +'%Y-%m-%d %H:%M:%S') Ultrack DB service ready"
postgres -i -D $DB_DIR

# STOP:
# pg_ctl stop -D $DB_DIR

# DUMP
# pg_dump -f data.sql -d ultrack -h <NODE> -p <PORT> -U $USER
