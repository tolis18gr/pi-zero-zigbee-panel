#!/usr/bin/env bash
# Βαθμονόμηση αφής: πατάς τρεις σταυρούς, οι τιμές γράφονται στο panel.env.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
sudo systemctl stop zigbee-panel 2>/dev/null || true
set -a; [ -f "$DIR/panel.env" ] && . "$DIR/panel.env"; set +a
python3 "$DIR/zigbee_panel.py" --calibrate
sudo systemctl start zigbee-panel 2>/dev/null || true
