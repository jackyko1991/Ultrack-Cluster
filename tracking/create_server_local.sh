#!/usr/bin/sh

CFG_FILE="/home/$USER/Projects/Ultrack-Cluster/tracking/config.toml"
POSTGRES_DIR="/usr/lib/postgresql/12/bin"
export PATH=$POSTGRES_DIR:$PATH
ULTRACK_DB_PW="ultrack_pw"

# DB_DIR="/hpc/mydata/$USER/postgresql_ultrack"
DB_DIR="/home/$USER/work/postgresql_ultrack"
DB_NAME="ultrack"
# DB_SOCKET_DIR="/tmp"
DB_SOCKET_DIR="/home/$USER/work/tmp"

# fixing error "FATAL:  unsupported frontend protocol 1234.5679: server supports 2.0 to 3.0"
# reference: https://stackoverflow.com/questions/59190010/psycopg2-operationalerror-fatal-unsupported-frontend-protocol-1234-5679-serve
DB_ADDR="$USER:$ULTRACK_DB_PW@localhost:5432/ultrack?gssencmode=disable"

# update config file
echo ""
echo "Server running on uri $DB_ADDR"
dasel put -t string -f $CFG_FILE -v $DB_ADDR "data.address" 
echo "Updated $CFG_FILE"

rm -r $DB_DIR
mkdir -p $DB_DIR
initdb $DB_DIR

# setting new lock directory
cat << EOF >> $DB_DIR/postgresql.conf
unix_socket_directories = '$DB_SOCKET_DIR'
EOF

# creating database
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
pg_ctl stop -D $DB_DIR
postgres -i -D $DB_DIR

# STOP:
# pg_ctl stop -D $DB_DIR

# DUMP
# pg_dump -f data.sql -d ultrack -h <NODE> -p <PORT> -U $USER
