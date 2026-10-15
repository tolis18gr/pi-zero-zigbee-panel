#!/usr/bin/env bash
# Πρώτη εγκατάσταση: πακέτα, ρυθμίσεις, υπηρεσία εκκίνησης.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"

echo "→ Εγκατάσταση πακέτων…"
sudo apt-get update -qq
sudo apt-get install -y python3-pygame python3-psutil python3-paho-mqtt fonts-dejavu-core git

if [ ! -f "$DIR/panel.env" ]; then
  cp "$DIR/config.example.env" "$DIR/panel.env"
  echo "→ Δημιουργήθηκε το panel.env — άλλαξέ το αν χρειάζεται: nano $DIR/panel.env"
fi

echo "→ Ρύθμιση υπηρεσίας systemd…"
sed -e "s|__DIR__|$DIR|g" -e "s|__USER__|$USER_NAME|g" \
  "$DIR/systemd/zigbee-panel.service.template" | sudo tee /etc/systemd/system/zigbee-panel.service >/dev/null
sudo usermod -aG video,input,render "$USER_NAME" || true
sudo systemctl daemon-reload
sudo systemctl enable --now zigbee-panel
echo "✓ Έτοιμο. Κατάσταση: sudo systemctl status zigbee-panel"
