#!/usr/bin/env bash
# Κατεβάζει την τελευταία έκδοση από το GitHub και επανεκκινεί την οθόνη.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
OLD=$(git rev-parse --short HEAD)
git pull --ff-only
NEW=$(git rev-parse --short HEAD)
if [ "$OLD" = "$NEW" ]; then
  echo "✓ Ήδη στην τελευταία έκδοση ($NEW)."
  exit 0
fi
# Αν άλλαξε το template της υπηρεσίας, ξαναγράψ' το.
if git diff --name-only "$OLD" "$NEW" | grep -q '^systemd/'; then
  USER_NAME="${SUDO_USER:-$USER}"
  sed -e "s|__DIR__|$DIR|g" -e "s|__USER__|$USER_NAME|g" \
    systemd/zigbee-panel.service.template | sudo tee /etc/systemd/system/zigbee-panel.service >/dev/null
  sudo systemctl daemon-reload
fi
sudo systemctl restart zigbee-panel
echo "✓ Ενημερώθηκε $OLD → $NEW"
git log --oneline "$OLD..$NEW"
