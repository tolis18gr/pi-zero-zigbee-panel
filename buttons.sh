#!/usr/bin/env bash
# Κουμπιά K1, K2, K3 στο πλάι της οθόνης (LCDwiki MPI3201: pins 12, 16, 18).
#   ./buttons.sh            δοκιμή και μετά ερώτηση για εγκατάσταση
#   ./buttons.sh test       μόνο δοκιμή (δείχνει ποιο κουμπί πατιέται)
#   ./buttons.sh install    εγκατάσταση (dtoverlay=gpio-key στο config.txt)
#   ./buttons.sh remove     αφαίρεση
set -e
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
PINS=(18 23 24)
NAMES=(K1 K2 K3)
CODES=(103 28 108)            # KEY_UP, KEY_ENTER, KEY_DOWN
ROLES=("πάνω" "επιλογή / κράτημα = πίσω" "κάτω")
MARK="# Zigbee Panel: κουμπιά K1-K3"
ACTIVE_LOW=1

level() {   # τυπώνει 1 ή 0
  if command -v pinctrl >/dev/null; then
    pinctrl get "$1" | grep -oE '\| (hi|lo)' | awk '{print ($2=="hi")?1:0}'
  else
    raspi-gpio get "$1" | grep -oE 'level=[01]' | cut -d= -f2
  fi
}
pullup() {
  if command -v pinctrl >/dev/null; then sudo pinctrl set "$1" ip pu
  else sudo raspi-gpio set "$1" ip pu; fi
}

do_test() {
  echo "→ Ρύθμιση των pins ως είσοδοι με pull-up…"
  for p in "${PINS[@]}"; do pullup "$p"; done
  sleep 0.2
  declare -a IDLE NOW SEEN
  for i in 0 1 2; do IDLE[$i]=$(level "${PINS[$i]}"); SEEN[$i]=0; done
  echo "  Αρχική κατάσταση: K1=${IDLE[0]} K2=${IDLE[1]} K3=${IDLE[2]}  (1 = ψηλά, 0 = χαμηλά)"
  echo "→ Πάτα ένα-ένα τα K1, K2, K3 (έχεις 20 δευτερόλεπτα, Ctrl+C για τέλος)"
  END=$((SECONDS + 20))
  declare -a LAST=("${IDLE[@]}")
  while [ $SECONDS -lt $END ]; do
    for i in 0 1 2; do
      NOW[$i]=$(level "${PINS[$i]}")
      if [ "${NOW[$i]}" != "${LAST[$i]}" ]; then
        if [ "${NOW[$i]}" != "${IDLE[$i]}" ]; then
          echo "  ${NAMES[$i]} (GPIO${PINS[$i]}) πατήθηκε"; SEEN[$i]=1
        else
          echo "  ${NAMES[$i]} (GPIO${PINS[$i]}) αφέθηκε"
        fi
        LAST[$i]=${NOW[$i]}
      fi
    done
    sleep 0.03
  done
  echo
  OK=0
  for i in 0 1 2; do
    if [ "${SEEN[$i]}" = 1 ]; then echo "  ✓ ${NAMES[$i]} δουλεύει"; OK=$((OK+1))
    else echo "  ✗ ${NAMES[$i]} δεν ανιχνεύτηκε"; fi
  done
  # αν σε ηρεμία είναι χαμηλά, το κουμπί δίνει 3.3V όταν πατιέται (active high)
  if [ "${IDLE[0]}${IDLE[1]}${IDLE[2]}" = "000" ]; then ACTIVE_LOW=0; echo "  (τα κουμπιά δίνουν ψηλή στάθμη όταν πατιούνται)"; fi
  [ "$OK" -gt 0 ]
}

do_remove() {
  sudo sed -i -e "/^$MARK/d" -e '/^dtoverlay=gpio-key,gpio=\(18\|23\|24\),/d' "$CFG"
}

do_install() {
  sudo cp "$CFG" "$CFG.bak-buttons"
  do_remove
  PULL=2; [ "$ACTIVE_LOW" = 0 ] && PULL=1
  {
    echo "$MARK"
    for i in 0 1 2; do
      echo "dtoverlay=gpio-key,gpio=${PINS[$i]},active_low=$ACTIVE_LOW,gpio_pull=$PULL,keycode=${CODES[$i]},label=${NAMES[$i]}"
    done
  } | sudo tee -a "$CFG" >/dev/null
  echo "✓ Τα κουμπιά προστέθηκαν στο $CFG:"
  for i in 0 1 2; do echo "    ${NAMES[$i]} = ${ROLES[$i]}"; done
  echo "→ Κάνε 'sudo reboot'. Αν τα K1/K3 είναι ανάποδα, βάλε PANEL_KEYS_REVERSED=1 στο panel.env."
}

case "${1:-}" in
  test)    do_test || true ;;
  install) do_install ;;
  remove)  do_remove; echo "✓ Αφαιρέθηκαν. Κάνε 'sudo reboot'." ;;
  *)
    if do_test; then
      read -r -p "→ Να εγκατασταθούν τα κουμπιά; [Y/n] " ans
      [ "${ans:-Y}" != "n" ] && do_install
    else
      echo "✗ Κανένα κουμπί δεν ανιχνεύτηκε. Στείλε το αποτέλεσμα παραπάνω."
    fi ;;
esac
