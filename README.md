# Zigbee Panel

Οθόνη πληροφοριών για Raspberry Pi Zero W με οθόνη αφής 3.2" SPI (320×240, Waveshare ILI9341 / XPT2046).
Δείχνει CPU, RAM, θερμοκρασία, διεργασίες και τις συσκευές Zigbee.
Το Pi κάνει γέφυρα για τον USB Zigbee coordinator (ser2net) προς το Home Assistant.

```
[USB stick] ── Pi Zero W (ser2net :6638) ── WiFi ──> Home Assistant
                     ▲                                 ├─ Zigbee2MQTT add-on
                     └──────── MQTT (συσκευές) ─────── └─ Mosquitto add-on
```

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

## Coordinator

Όταν συνδέσεις το USB stick:

```bash
./coordinator.sh
```

Στο τέλος σου δείχνει τι να βάλεις στο add-on Zigbee2MQTT του Home Assistant
(`serial: port: tcp://<IP-του-Pi>:6638`). Στην αρχική οθόνη, η ένδειξη Coordinator δείχνει:
«Χωρίς stick», «ser2net off», «Αναμονή HA» ή «Σε HA».

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

## Ρυθμίσεις Zigbee2MQTT (στο Home Assistant)

Για σωστή «τελευταία επικοινωνία» και ένδειξη online/offline, στο `configuration.yaml` του Zigbee2MQTT:

```yaml
advanced:
  last_seen: ISO_8601
availability: true
```
