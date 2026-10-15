#!/usr/bin/env bash
# Πρώτη εγκατάσταση: πακέτα, οθόνη, ρυθμίσεις, υπηρεσία εκκίνησης.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"

echo "→ Εγκατάσταση πακέτων…"
sudo apt-get update -qq
sudo apt-get install -y python3-pygame python3-psutil python3-paho-mqtt python3-evdev fonts-dejavu-core git

# --- driver οθόνης 3.2" (Waveshare / ILI9341 + XPT2046)
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
NEED_REBOOT=0
if ! grep -q "^dtoverlay=waveshare32b" "$CFG"; then
  read -r -p "→ Να προστεθεί ο driver της οθόνης 3.2\" στο $CFG; [Y/n] " ans
  if [ "${ans:-Y}" != "n" ]; then
    echo -e "\n# Zigbee Panel: οθόνη 3.2\" SPI\ndtparam=spi=on\ndtoverlay=waveshare32b,rotate=270" | sudo tee -a "$CFG" >/dev/null
    NEED_REBOOT=1
  fi
fi

if [ ! -f "$DIR/panel.env" ]; then
  cp "$DIR/config.example.env" "$DIR/panel.env"
  echo "→ Στοιχεία MQTT του Home Assistant (Mosquitto add-on). Enter = προεπιλογή."
  read -r -p "  IP του Home Assistant: " HA_IP
  read -r -p "  Χρήστης MQTT: " MQ_USER
  read -r -s -p "  Κωδικός MQTT: " MQ_PASS; echo
  esc() { printf '%s' "$1" | sed -e 's/[\\/&|]/\\&/g'; }
  sed -i -e "s|^PANEL_MQTT_HOST=.*|PANEL_MQTT_HOST=$(esc "${HA_IP:-localhost}")|" \
         -e "s|^PANEL_MQTT_USER=.*|PANEL_MQTT_USER=$(esc "$MQ_USER")|" \
         -e "s|^PANEL_MQTT_PASS=.*|PANEL_MQTT_PASS=$(esc "$MQ_PASS")|" "$DIR/panel.env"
  chmod 600 "$DIR/panel.env"
  echo "→ Αποθηκεύτηκε στο panel.env (nano $DIR/panel.env για αλλαγές)"
fi

echo "→ Ρύθμιση υπηρεσίας systemd…"
sed -e "s|__DIR__|$DIR|g" -e "s|__USER__|$USER_NAME|g" \
  "$DIR/systemd/zigbee-panel.service.template" | sudo tee /etc/systemd/system/zigbee-panel.service >/dev/null
sudo usermod -aG video,input "$USER_NAME" || true
sudo systemctl daemon-reload
sudo systemctl enable zigbee-panel

echo "→ Εγκατάσταση ser2net (γέφυρα για τον coordinator)…"
sudo apt-get install -y ser2net >/dev/null
if ls /dev/serial/by-id/* >/dev/null 2>&1; then
  read -r -p "→ Βρέθηκε USB stick. Ρύθμιση coordinator τώρα; [Y/n] " ans
  [ "${ans:-Y}" != "n" ] && "$DIR/coordinator.sh"
else
  echo "→ Δεν υπάρχει ακόμα USB stick. Όταν το συνδέσεις, τρέξε: ./coordinator.sh"
fi

if [ "$NEED_REBOOT" = 1 ]; then
  echo "✓ Έτοιμο. Κάνε 'sudo reboot' και μετά τρέξε ./calibrate.sh για την αφή."
else
  sudo systemctl restart zigbee-panel
  echo "✓ Έτοιμο. Αν η αφή δεν πέφτει σωστά: ./calibrate.sh"
fi
