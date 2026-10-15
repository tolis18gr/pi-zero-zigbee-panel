#!/usr/bin/env bash
# Πρώτη εγκατάσταση: πακέτα, οθόνη, ρυθμίσεις, υπηρεσία εκκίνησης.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"

echo "→ Εγκατάσταση πακέτων…"
sudo apt-get update -qq
sudo apt-get install -y python3-pygame python3-psutil python3-paho-mqtt python3-evdev fonts-dejavu-core git curl

# --- driver οθόνης: LCDwiki 3.2" RPi Display (MPI3201, ILI9341 + XPT2046)
# Χρησιμοποιούμε ΜΟΝΟ το overlay του επίσημου driver (goodtft/LCD-show), όχι το script
# LCD32-show, γιατί εκείνο αντικαθιστά ολόκληρο το config.txt, το rc.local κ.ά.
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
OVL_DIR="$(dirname "$CFG")/overlays"
LCD_COMMIT=a36c00a55e11f0de3b4be0e66f0a2cec47076e23
LCD_SHA=7a1781835011567eb64345001e006b7d4a7b5ecba3528d7125c93665a062ee55
NEED_REBOOT=0
if ! grep -qE "^dtoverlay=(tft9341|waveshare32b)" "$CFG"; then
  read -r -p "→ Να εγκατασταθεί ο driver της οθόνης 3.2\" (LCDwiki MPI3201); [Y/n] " ans
  if [ "${ans:-Y}" != "n" ]; then
    TMP=$(mktemp)
    URL="https://raw.githubusercontent.com/goodtft/LCD-show/$LCD_COMMIT/usr/tft9341-overlay.dtb"
    if curl -fsSL "$URL" -o "$TMP" && echo "$LCD_SHA  $TMP" | sha256sum -c --quiet; then
      sudo install -m 644 "$TMP" "$OVL_DIR/tft9341.dtbo"
      OVERLAY="tft9341:rotate=270"
      echo "→ Εγκαταστάθηκε το overlay tft9341 (LCDwiki)"
    else
      # ίδια pins (DC=GPIO22, RESET=GPIO27, TOUCH=GPIO17), υπάρχει ήδη στον kernel
      OVERLAY="waveshare32b,rotate=270"
      echo "→ Δεν κατέβηκε το overlay της LCDwiki, χρησιμοποιώ το waveshare32b του kernel"
    fi
    rm -f "$TMP"
    echo -e "\n# Zigbee Panel: οθόνη 3.2\" SPI\ndtparam=spi=on\ndtoverlay=$OVERLAY" | sudo tee -a "$CFG" >/dev/null
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
