#!/usr/bin/sh

#SBATCH --job-name=DATABASE
#SBATCH --time=24:00:00
#SBATCH --partition=short
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
DB_DIR="/users/$GROUP_NAME/$USER/work/postgresql_ultrack"
DB_NAME="ultrack"
# DB_SOCKET_DIR="/tmp"
DB_SOCKET_DIR="/users/$GROUP_NAME/$USER/work/tmp"

# fixing error "FATAL:  unsupported frontend protocol 1234.5679: server supports 2.0 to 3.0"
# reference: https://stackoverflow.com/questions/59190010/psycopg2-operationalerror-fatal-unsupported-frontend-protocol-1234-5679-serve
DB_ADDR="$USER:$ULTRACK_DB_PW@$SLURM_JOB_NODELIST:5432/ultrack?gssencmode=disable"

# update config file
echo ""
echo "Server running on uri $DB_ADDR"
dasel put -t string -f $CFG_FILE -v $DB_ADDR "data.address" 
# dasel put string -f $CFG_FILE "data.address" $DB_ADDR
echo "Updated $CFG_FILE"

postgres -i -D $DB_DIR