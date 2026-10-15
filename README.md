# Zigbee Panel

Οθόνη πληροφοριών για Raspberry Pi Zero W με οθόνη αφής 3.2" SPI (320×240, Waveshare ILI9341 / XPT2046).
Δείχνει CPU, RAM, θερμοκρασία, διεργασίες και τις συσκευές Zigbee από το Zigbee2MQTT.

![Οθόνες](docs/preview.png)

## Εγκατάσταση (μία φορά)

```bash
cd ~
git clone https://github.com/<ΤΟ-USERNAME-ΣΟΥ>/zigbee-panel.git
cd zigbee-panel
./install.sh
```

Το `install.sh` προσθέτει τον driver της οθόνης στο `config.txt`. Μετά το reboot:

```bash
./calibrate.sh     # πατάς τρεις σταυρούς για να ευθυγραμμιστεί η αφή
```

Οι ρυθμίσεις (MQTT, οθόνη, αφή) είναι στο `panel.env`, που δεν ανεβαίνει στο GitHub.

## Ενημέρωση

```bash
~/zigbee-panel/update.sh
```

## Χρήσιμες εντολές

| Τι | Εντολή |
|---|---|
| Δοκιμή χωρίς Zigbee | `PANEL_DEMO=1 python3 zigbee_panel.py` |
| Δοκιμή στον υπολογιστή (παράθυρο) | `PANEL_DEMO=1 PANEL_OUTPUT=sdl PANEL_FULLSCREEN=0 python3 zigbee_panel.py` |
| Βαθμονόμηση αφής | `./calibrate.sh` |
| Logs | `journalctl -u zigbee-panel -f` |
| Επανεκκίνηση | `sudo systemctl restart zigbee-panel` |

## Ρυθμίσεις Zigbee2MQTT

Για σωστή «τελευταία επικοινωνία» και ένδειξη online/offline, στο `configuration.yaml` του Zigbee2MQTT:

```yaml
advanced:
  last_seen: ISO_8601
availability: true
```
