#!/bin/bash
MNT_PATH="/mnt"
DBS_DIR="/home/$USER/.local/share/ulauncher/extensions/com.github.darioque.everywhere/dbs"
mkdir -p "$DBS_DIR"
rm -f "$DBS_DIR"/mnt_*.db
for drive in "$MNT_PATH"/*/; do
  [ -d "$drive" ] || continue
  safe=$(basename "$drive" | tr ":" "_" | tr " " "_")
  updatedb -l 0 -o "$DBS_DIR/mnt_${safe}.db" -U "$drive"
done
