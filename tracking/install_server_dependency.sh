#! /bin/bash

GROUP_NAME=$(getent group $GROUPS | cut -d: -f1)
TMP_DIR="/users/$GROUP_NAME/$USER/work/tmp"
INSTALL_DIR="/users/$GROUP_NAME/$USER/work/software"

# ======== dasel ========
DASEL_DIR=$INSTALL_DIR/dasel
mkdir $DASEL_DIR
wget https://github.com/TomWright/dasel/releases/latest/download/dasel_linux_amd64 -O $DASEL_DIR/dasel -r
chmod a+x $DASEL_DIR
chmod a+x $DASEL_DIR/dasel

# add dasel to bashrc
echo "export PATH=$DASEL_DIR:$PATH" >> ~/.bashrc