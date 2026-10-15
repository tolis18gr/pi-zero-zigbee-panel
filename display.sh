#!/usr/bin/env bash
# Εγκαθιστά (ή ενημερώνει) τον driver της οθόνης 3.2" από το drivers/zigbee-lcd32-overlay.dts.
# Χρήση: ./display.sh            (κρατάει την περιστροφή που υπάρχει ήδη, αλλιώς 270)
#        ./display.sh 90         (άλλη περιστροφή)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
OVL_DIR="$(dirname "$CFG")/overlays"
PAT='^dtoverlay=(tft9341|waveshare32b|zigbee-lcd32)'

command -v dtc >/dev/null || sudo apt-get install -y device-tree-compiler
TMP=$(mktemp --suffix=.dtbo)
dtc -@ -q -I dts -O dtb -o "$TMP" "$DIR/drivers/zigbee-lcd32-overlay.dts"
if cmp -s "$TMP" "$OVL_DIR/zigbee-lcd32.dtbo"; then CHANGED=0; else CHANGED=1; fi
sudo install -m 644 "$TMP" "$OVL_DIR/zigbee-lcd32.dtbo"
rm -f "$TMP"

ROT="$1"
[ -n "$ROT" ] || ROT=$(grep -E "$PAT" "$CFG" | grep -oE 'rotate=[0-9]+' | head -1 | cut -d= -f2)
ROT="${ROT:-270}"
LINE="dtoverlay=zigbee-lcd32,rotate=$ROT"

if grep -qE "$PAT" "$CFG"; then
  if ! grep -qxF "$LINE" "$CFG"; then
    sudo cp "$CFG" "$CFG.bak-zigbee-panel"
    sudo sed -i -E "s#${PAT}.*#${LINE}#" "$CFG"
    CHANGED=1
  fi
else
  echo -e "\n# Zigbee Panel: οθόνη 3.2\" SPI\ndtparam=spi=on\n$LINE" | sudo tee -a "$CFG" >/dev/null
  CHANGED=1
fi

if [ "$CHANGED" = 1 ]; then
  echo "✓ Driver οθόνης: $LINE  →  χρειάζεται 'sudo reboot'"
  exit 10   # σήμα για τα άλλα scripts ότι χρειάζεται επανεκκίνηση
fi
echo "✓ Ο driver της οθόνης είναι ήδη ενημερωμένος."
