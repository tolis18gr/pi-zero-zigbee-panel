# Zigbee Panel

Οθόνη πληροφοριών για Raspberry Pi Zero W με οθόνη αφής 3.5" (480×320).
Δείχνει CPU, RAM, θερμοκρασία, διεργασίες και τις συσκευές Zigbee από το Zigbee2MQTT.

![Οθόνες](docs/preview.png)

## Εγκατάσταση (μία φορά)

```bash
cd ~
git clone https://github.com/<ΤΟ-USERNAME-ΣΟΥ>/zigbee-panel.git
cd zigbee-panel
./install.sh
```

Οι ρυθμίσεις (MQTT host, κωδικοί) είναι στο `panel.env`, που δεν ανεβαίνει στο GitHub.

## Ενημέρωση

```bash
~/zigbee-panel/update.sh
```

## Χρήσιμες εντολές

| Τι | Εντολή |
|---|---|
| Δοκιμή χωρίς Zigbee | `PANEL_DEMO=1 python3 zigbee_panel.py` |
| Logs | `journalctl -u zigbee-panel -f` |
| Επανεκκίνηση | `sudo systemctl restart zigbee-panel` |

## Ρυθμίσεις Zigbee2MQTT

Για σωστή «τελευταία επικοινωνία» και ένδειξη online/offline, στο `configuration.yaml` του Zigbee2MQTT:

```yaml
advanced:
  last_seen: ISO_8601
availability: true
```
