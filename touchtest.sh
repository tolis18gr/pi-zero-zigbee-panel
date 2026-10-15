#!/usr/bin/env bash
# Δοκιμή αφής: δείχνει στην οθόνη πού καταγράφεται κάθε πάτημα.
DIR="$(cd "$(dirname "$0")" && pwd)"
sudo systemctl stop zigbee-panel 2>/dev/null || true
set -a; [ -f "$DIR/panel.env" ] && . "$DIR/panel.env"; set +a
python3 "$DIR/zigbee_panel.py" --touch-test
sudo systemctl start zigbee-panel 2>/dev/null || true
