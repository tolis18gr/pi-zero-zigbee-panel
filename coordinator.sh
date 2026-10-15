#!/usr/bin/env bash
# Ρύθμιση του Pi ως γέφυρα για τον Zigbee coordinator (USB -> δίκτυο) με ser2net.
# Τρέξ' το όταν το USB stick είναι συνδεδεμένο. Μπορείς να το ξανατρέξεις όποτε θες.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ENV="$DIR/panel.env"
PORT=6638

set_env() {  # set_env KEY VALUE -> γράφει/αντικαθιστά στο panel.env
  touch "$ENV"
  grep -v "^$1=" "$ENV" > "$ENV.tmp" || true
  echo "$1=$2" >> "$ENV.tmp" && mv "$ENV.tmp" "$ENV"
}

command -v ser2net >/dev/null || { echo "→ Εγκατάσταση ser2net…"; sudo apt-get install -y ser2net; }

# --- εύρεση του stick
mapfile -t DEVS < <(ls /dev/serial/by-id/* 2>/dev/null || true)
if [ ${#DEVS[@]} -eq 0 ]; then
  echo "✗ Δεν βρέθηκε USB stick στο /dev/serial/by-id/. Σύνδεσέ το (με αντάπτορα OTG) και ξανατρέξε."
  exit 1
fi
if [ ${#DEVS[@]} -eq 1 ]; then
  DEV="${DEVS[0]}"
else
  echo "Βρέθηκαν πολλές σειριακές συσκευές:"
  select DEV in "${DEVS[@]}"; do [ -n "$DEV" ] && break; done
fi
echo "→ Stick: $DEV"

echo "Τι chip έχει ο coordinator;"
echo "  1) Texas Instruments CC2652 / CC1352  (π.χ. SONOFF ZBDongle-P, SMLIGHT SLZB-07p7)"
echo "  2) Silicon Labs EFR32                 (π.χ. SONOFF ZBDongle-E, SMLIGHT SLZB-07)"
read -r -p "Επιλογή [1/2]: " CHIP
case "$CHIP" in 2) ADAPTER=ember ;; *) ADAPTER=zstack ;; esac
read -r -p "Ταχύτητα σειριακής [115200]: " BAUD
BAUD="${BAUD:-115200}"

# --- ρύθμιση ser2net (μορφή YAML, ser2net 4.x)
sudo tee /etc/ser2net.yaml >/dev/null << YAML
%YAML 1.1
---
# Δημιουργήθηκε από το zigbee-panel/coordinator.sh
connection: &zigbee
  accepter: tcp,$PORT
  enable: on
  options:
    kickolduser: true
  connector: serialdev,$DEV,${BAUD}n81,nobreak,local
YAML
sudo systemctl enable ser2net >/dev/null 2>&1
sudo systemctl restart ser2net

# --- σταθερό WiFi: απενεργοποίηση εξοικονόμησης ενέργειας
if command -v nmcli >/dev/null; then
  CON=$(nmcli -t -f NAME,TYPE connection show --active | awk -F: '$2=="802-11-wireless"{print $1; exit}')
  if [ -n "$CON" ]; then
    sudo nmcli connection modify "$CON" 802-11-wireless.powersave 2 && echo "→ WiFi power save: off ($CON)"
  fi
fi

set_env PANEL_COORDINATOR_DEV "$DEV"
set_env PANEL_SER2NET_PORT "$PORT"
sudo systemctl restart zigbee-panel 2>/dev/null || true

IP=$(hostname -I | awk '{print $1}')
cat << MSG

✓ Η γέφυρα τρέχει. Στο Home Assistant, στις ρυθμίσεις του add-on Zigbee2MQTT βάλε:

  serial:
    port: tcp://$IP:$PORT
    adapter: $ADAPTER

Συμβουλή: δώσε σταθερή IP στο Pi από τον router σου, για να μη χαθεί η σύνδεση.
MSG
