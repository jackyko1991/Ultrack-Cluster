#!/usr/bin/sh

#SBATCH --job-name=DATABASE
#SBATCH --time=1-06:00:00
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