#!/usr/bin/env bash
# Κατεβάζει την τελευταία έκδοση από το GitHub και επανεκκινεί την οθόνη.
# Λειτουργεί σε δύο φάσεις: πρώτα το git pull, και μετά ξεκινάει τη ΝΕΑ έκδοση
# του εαυτού του για τα υπόλοιπα βήματα (αλλιώς θα έτρεχαν τα βήματα της παλιάς).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ "$1" != "--after-pull" ]; then
  OLD=$(git rev-parse --short HEAD)
  git pull --ff-only
  exec "$DIR/update.sh" --after-pull "$OLD"
fi

OLD="$2"
NEW=$(git rev-parse --short HEAD)

# Υπηρεσία systemd: ξαναγράφεται πάντα από το template (είναι γρήγορο και ασφαλές).
USER_NAME="${SUDO_USER:-$USER}"
sed -e "s|__DIR__|$DIR|g" -e "s|__USER__|$USER_NAME|g" \
  systemd/zigbee-panel.service.template | sudo tee /etc/systemd/system/zigbee-panel.service >/dev/null
sudo systemctl daemon-reload

# Driver οθόνης: ελέγχεται πάντα. Το display.sh αλλάζει κάτι μόνο αν χρειάζεται.
REBOOT=0
"$DIR/display.sh" || { [ $? -eq 10 ] && REBOOT=1; }

sudo systemctl restart zigbee-panel
if [ "$OLD" = "$NEW" ]; then
  echo "✓ Ήδη στην τελευταία έκδοση ($NEW)."
else
  echo "✓ Ενημερώθηκε $OLD → $NEW"
  git log --oneline "$OLD..$NEW"
fi
[ "$REBOOT" = 1 ] && echo "⚠ Άλλαξε ο driver της οθόνης: κάνε 'sudo reboot'"
exit 0
