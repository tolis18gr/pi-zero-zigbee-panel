#!/usr/bin/env python3
"""
Zigbee Panel - μικρή οθόνη πληροφοριών για Raspberry Pi Zero W (οθόνη αφής 3.5", 480x320)

Οθόνες:
  Αρχική      -> CPU, RAM, πλήθος συσκευών Zigbee, θερμοκρασία, uptime, IP
  Διεργασίες  -> (πάτημα στην κάρτα CPU) λίστα διεργασιών με CPU% / RAM%
  Συσκευές    -> (πάτημα στην κάρτα Συσκευές) λίστα συσκευών Zigbee με σήμα (LQI)
  Λεπτομέρειες-> (πάτημα σε συσκευή) IEEE/MAC, διεύθυνση δικτύου, τύπος, μπαταρία κ.λπ.

Τα δεδομένα Zigbee έρχονται από Zigbee2MQTT μέσω MQTT.
Ρυθμίσεις μέσω μεταβλητών περιβάλλοντος (βλ. CONFIG παρακάτω).
Με PANEL_DEMO=1 τρέχει με εικονικές συσκευές, χωρίς MQTT.
"""
import json
import math
import os
import socket
import threading
import time
from datetime import datetime, timezone

import psutil
import pygame

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# ---------------------------------------------------------------- CONFIG
CONFIG = {
    "mqtt_host": os.getenv("PANEL_MQTT_HOST", "localhost"),
    "mqtt_port": int(os.getenv("PANEL_MQTT_PORT", "1883")),
    "mqtt_user": os.getenv("PANEL_MQTT_USER", ""),
    "mqtt_pass": os.getenv("PANEL_MQTT_PASS", ""),
    "base_topic": os.getenv("PANEL_BASE_TOPIC", "zigbee2mqtt"),
    "width": int(os.getenv("PANEL_WIDTH", "480")),
    "height": int(os.getenv("PANEL_HEIGHT", "320")),
    "fullscreen": os.getenv("PANEL_FULLSCREEN", "1") == "1",
    "demo": os.getenv("PANEL_DEMO", "0") == "1",
}
W, H = CONFIG["width"], CONFIG["height"]

# ---------------------------------------------------------------- ΧΡΩΜΑΤΑ
BG = (16, 25, 36)
CARD = (27, 38, 51)
CARD_HI = (36, 50, 66)
TRACK = (44, 59, 76)
TEXT = (232, 237, 242)
MUTED = (138, 154, 171)
AMBER = (242, 169, 59)
GREEN = (91, 196, 137)
RED = (229, 103, 92)
BLUE = (96, 165, 230)

# ---------------------------------------------------------------- ΓΡΑΜΜΑΤΟΣΕΙΡΕΣ
FONT_PATHS = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}
_fonts = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        path = FONT_PATHS[bold]
        _fonts[key] = pygame.font.Font(path if os.path.exists(path) else None, size)
    return _fonts[key]


def text(surf, s, pos, size=15, color=TEXT, bold=False, anchor="topleft", maxw=None):
    f = font(size, bold)
    s = str(s)
    if maxw and f.size(s)[0] > maxw:
        while s and f.size(s + "…")[0] > maxw:
            s = s[:-1]
        s += "…"
    img = f.render(s, True, color)
    rect = img.get_rect(**{anchor: pos})
    surf.blit(img, rect)
    return rect


def level_color(pct):
    return GREEN if pct < 60 else AMBER if pct < 85 else RED


def lqi_color(lqi):
    if lqi is None:
        return MUTED
    return GREEN if lqi >= 150 else AMBER if lqi >= 80 else RED


def ago(ts):
    if not ts:
        return "—"
    d = max(0, time.time() - ts)
    if d < 10:
        return "τώρα"
    if d < 60:
        return f"πριν {int(d)}δ"
    if d < 3600:
        return f"πριν {int(d // 60)}λ"
    if d < 86400:
        return f"πριν {int(d // 3600)}ω"
    return f"πριν {int(d // 86400)}μ"


def fmt_uptime(sec):
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}μ {h}ω" if d else f"{h}ω {m}λ"


def parse_last_seen(v):
    """Το Zigbee2MQTT στέλνει last_seen ως ISO string ή epoch ms."""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            return v / 1000.0
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------- ΣΤΟΙΧΕΙΑ ΣΥΣΤΗΜΑΤΟΣ
class SysStats:
    def __init__(self):
        self.cpu = 0.0
        self.ram = 0.0
        self.ram_used = 0
        self.ram_total = 0
        self.temp = None
        self.uptime = 0
        self.ip = "—"
        self.procs = []
        self._ip_at = 0
        psutil.cpu_percent(None)
        self.update_procs()  # αρχικοποίηση μετρητών CPU ανά διεργασία

    def update(self):
        self.cpu = psutil.cpu_percent(None)
        vm = psutil.virtual_memory()
        self.ram, self.ram_used, self.ram_total = vm.percent, vm.used, vm.total
        self.uptime = time.time() - psutil.boot_time()
        self.temp = self._read_temp()
        if time.time() - self._ip_at > 30:
            self.ip = self._read_ip()
            self._ip_at = time.time()

    def update_procs(self):
        ncpu = psutil.cpu_count() or 1
        out = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            i = p.info
            out.append({
                "pid": i["pid"],
                "name": i["name"] or "?",
                "cpu": (i["cpu_percent"] or 0) / ncpu,
                "mem": i["memory_percent"] or 0,
                "status": i["status"],
            })
        out.sort(key=lambda x: (x["cpu"], x["mem"]), reverse=True)
        self.procs = out

    @staticmethod
    def _read_temp():
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            return None

    @staticmethod
    def _read_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "χωρίς δίκτυο"


# ---------------------------------------------------------------- ZIGBEE (MQTT)
class Zigbee:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg["base_topic"]
        self.lock = threading.Lock()
        self.devices = {}        # friendly_name -> πληροφορίες από bridge/devices
        self.states = {}         # friendly_name -> τελευταίο payload
        self.avail = {}          # friendly_name -> "online"/"offline"
        self.rx = {}             # friendly_name -> ώρα τελευταίου μηνύματος
        self.mqtt_ok = False
        self.bridge = None       # "online"/"offline"/None
        self.status_msg = "Σύνδεση…"

    def start(self):
        if self.cfg["demo"]:
            self._load_demo()
            return
        if mqtt is None:
            self.status_msg = "Λείπει το paho-mqtt"
            return
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"panel-{socket.gethostname()}")
        if self.cfg["mqtt_user"]:
            c.username_pw_set(self.cfg["mqtt_user"], self.cfg["mqtt_pass"])
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        c.reconnect_delay_set(2, 30)
        try:
            c.connect_async(self.cfg["mqtt_host"], self.cfg["mqtt_port"], keepalive=30)
            c.loop_start()
        except Exception as e:  # noqa: BLE001
            self.status_msg = f"MQTT: {e}"
        self.client = c

    def _on_connect(self, client, userdata, flags, rc, props=None):
        self.mqtt_ok = not rc.is_failure
        self.status_msg = "MQTT ΟΚ" if self.mqtt_ok else f"MQTT: {rc}"
        client.subscribe(f"{self.base}/#")

    def _on_disconnect(self, client, userdata, flags, rc, props=None):
        self.mqtt_ok = False
        self.status_msg = "MQTT αποσυνδέθηκε"

    def _on_message(self, client, userdata, msg):
        topic = msg.topic[len(self.base) + 1:]
        try:
            payload = json.loads(msg.payload.decode() or "null")
        except (ValueError, UnicodeDecodeError):
            payload = msg.payload.decode(errors="ignore")
        with self.lock:
            if topic == "bridge/devices" and isinstance(payload, list):
                self.devices = {d["friendly_name"]: d for d in payload
                                if d.get("type") != "Coordinator"}
            elif topic == "bridge/state":
                self.bridge = payload.get("state") if isinstance(payload, dict) else payload
            elif topic.startswith("bridge/"):
                return
            elif topic.endswith("/availability"):
                name = topic[: -len("/availability")]
                st = payload.get("state") if isinstance(payload, dict) else payload
                self.avail[name] = st
            elif isinstance(payload, dict) and "/" not in topic:
                self.states.setdefault(topic, {}).update(payload)
                self.rx[topic] = time.time()

    def snapshot(self):
        """Λίστα συσκευών με όλα τα στοιχεία ενωμένα, ταξινομημένη κατά όνομα."""
        with self.lock:
            out = []
            for name, d in self.devices.items():
                st = self.states.get(name, {})
                definition = d.get("definition") or {}
                seen = parse_last_seen(st.get("last_seen")) or self.rx.get(name)
                out.append({
                    "name": name,
                    "ieee": d.get("ieee_address", "—"),
                    "nwk": d.get("network_address"),
                    "type": d.get("type", "—"),
                    "power": d.get("power_source", "—"),
                    "vendor": definition.get("vendor") or d.get("manufacturer") or "—",
                    "model": definition.get("model") or d.get("model_id") or "—",
                    "desc": definition.get("description", ""),
                    "interview": d.get("interview_completed"),
                    "lqi": st.get("linkquality"),
                    "battery": st.get("battery"),
                    "last_seen": seen,
                    "avail": self.avail.get(name),
                    "state": dict(st),
                })
            return sorted(out, key=lambda x: x["name"].lower())

    def _load_demo(self):
        now = time.time()
        demo = [
            ("Σαλόνι θερμοκρασία", "0x00158d0008a1b2c3", 0x1a2b, "EndDevice", "Battery", "Aqara", "WSDCGQ11LM", 142, 87, 40),
            ("Κουζίνα φως", "0x0017880104c5d6e7", 0x3c4d, "Router", "Mains (single phase)", "Philips", "9290022166", 212, None, 5),
            ("Είσοδος πόρτα", "0x00158d000412abcd", 0x5e6f, "EndDevice", "Battery", "Aqara", "MCCGQ11LM", 96, 64, 620),
            ("Υπνοδωμάτιο πρίζα", "0xa4c138f1e2d3c4b5", 0x7a8b, "Router", "Mains (single phase)", "Tuya", "TS011F", 188, None, 12),
            ("Μπάνιο υγρασία", "0x00124b0022aabbcc", 0x9c0d, "EndDevice", "Battery", "SONOFF", "SNZB-02", 58, 23, 4300),
            ("Μπαλκόνι κίνηση", "0x00158d0007ff0011", 0xe1f2, "EndDevice", "Battery", "Aqara", "RTCGQ11LM", 120, 91, 180),
            ("Γραφείο διακόπτης", "0x0c4314fffe9a8b7c", 0x0f1e, "EndDevice", "Battery", "IKEA", "E1743", 75, 45, 95000),
        ]
        with self.lock:
            for name, ieee, nwk, typ, pw, vendor, model, lqi, bat, age in demo:
                self.devices[name] = {
                    "friendly_name": name, "ieee_address": ieee, "network_address": nwk,
                    "type": typ, "power_source": pw, "interview_completed": True,
                    "definition": {"vendor": vendor, "model": model},
                }
                st = {"linkquality": lqi, "last_seen": int((now - age) * 1000)}
                if bat is not None:
                    st["battery"] = bat
                if "θερμοκρασία" in name:
                    st.update(temperature=21.4, humidity=48)
                if "πρίζα" in name:
                    st.update(state="ON", power=63.5)
                self.states[name] = st
                self.avail[name] = "offline" if age > 86400 else "online"
            self.bridge = "online"
        self.mqtt_ok = True
        self.status_msg = "Demo"


# ---------------------------------------------------------------- ΣΧΕΔΙΑΣΗ
def ring(surf, center, r, thick, pct, color):
    cx, cy = center
    pygame.draw.circle(surf, TRACK, center, r, thick)
    pct = max(0.0, min(100.0, pct))
    if pct <= 0:
        return
    steps = max(2, int(72 * pct / 100))
    outer, inner = [], []
    for i in range(steps + 1):
        a = -math.pi / 2 + 2 * math.pi * (pct / 100) * i / steps
        outer.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        inner.append((cx + (r - thick) * math.cos(a), cy + (r - thick) * math.sin(a)))
    pygame.draw.polygon(surf, color, outer + inner[::-1])


def bar(surf, rect, frac, color):
    pygame.draw.rect(surf, TRACK, rect, border_radius=3)
    if frac > 0:
        r = pygame.Rect(rect)
        r.width = max(4, int(r.width * min(1.0, frac)))
        pygame.draw.rect(surf, color, r, border_radius=3)


class App:
    HEADER = 40

    def __init__(self, screen):
        self.screen = screen
        self.sys = SysStats()
        self.zb = Zigbee(CONFIG)
        self.zb.start()
        self.stack = ["home"]
        self.selected = None
        self.scroll = 0
        self.max_scroll = 0
        self.hits = []
        self.last_sys = 0
        self.last_procs = 0

    # ---- πλοήγηση
    @property
    def view(self):
        return self.stack[-1]

    def go(self, name):
        self.stack.append(name)
        self.scroll = 0
        if name == "procs":
            self.sys.update_procs()
            self.last_procs = time.time()

    def back(self):
        if len(self.stack) > 1:
            self.stack.pop()
            self.scroll = 0

    def tap(self, pos):
        for rect, cb in reversed(self.hits):
            if rect.collidepoint(pos):
                cb()
                return

    def drag(self, dy):
        self.scroll = max(0, min(self.max_scroll, self.scroll - dy))

    # ---- ενημέρωση δεδομένων
    def tick(self):
        now = time.time()
        changed = False
        if now - self.last_sys >= 1.0:
            self.sys.update()
            self.last_sys = now
            changed = True
        if self.view == "procs" and now - self.last_procs >= 2.0:
            self.sys.update_procs()
            self.last_procs = now
            changed = True
        return changed

    # ---- σχεδίαση
    def draw(self):
        self.hits = []
        self.screen.fill(BG)
        getattr(self, f"draw_{self.view}")()
        pygame.display.flip()

    def header(self, title, back=True, right=None):
        s = self.screen
        if back:
            r = pygame.Rect(0, 0, 56, self.HEADER)
            pygame.draw.polygon(s, AMBER, [(24, 12), (14, 20), (24, 28)])
            pygame.draw.line(s, AMBER, (14, 20), (34, 20), 3)
            self.hits.append((r, self.back))
            text(s, title, (52, self.HEADER // 2), 18, TEXT, True, "midleft")
        else:
            text(s, title, (14, self.HEADER // 2), 18, TEXT, True, "midleft")
        text(s, right or time.strftime("%H:%M"), (W - 12, self.HEADER // 2), 15, MUTED, anchor="midright")
        pygame.draw.line(s, TRACK, (0, self.HEADER - 1), (W, self.HEADER - 1))

    def draw_home(self):
        s = self.screen
        self.header(socket.gethostname(), back=False)
        top, ch = self.HEADER + 10, 200
        gap = 8
        cw = (W - gap * 4) // 3
        devs = self.zb.snapshot()

        # CPU
        r = pygame.Rect(gap, top, cw, ch)
        pygame.draw.rect(s, CARD, r, border_radius=10)
        text(s, "CPU", (r.x + 12, r.y + 10), 15, MUTED)
        c = (r.centerx, r.y + 104)
        ring(s, c, 52, 10, self.sys.cpu, level_color(self.sys.cpu))
        text(s, f"{self.sys.cpu:.0f}%", c, 24, TEXT, True, "center")
        text(s, "διεργασίες", (r.centerx, r.bottom - 16), 13, AMBER, anchor="center")
        self.hits.append((r, lambda: self.go("procs")))

        # RAM
        r = pygame.Rect(gap * 2 + cw, top, cw, ch)
        pygame.draw.rect(s, CARD, r, border_radius=10)
        text(s, "RAM", (r.x + 12, r.y + 10), 15, MUTED)
        c = (r.centerx, r.y + 104)
        ring(s, c, 52, 10, self.sys.ram, level_color(self.sys.ram))
        text(s, f"{self.sys.ram:.0f}%", c, 24, TEXT, True, "center")
        mb = lambda b: f"{b / 1048576:.0f}"
        text(s, f"{mb(self.sys.ram_used)} / {mb(self.sys.ram_total)} MB",
             (r.centerx, r.bottom - 16), 13, MUTED, anchor="center")

        # Συσκευές
        r = pygame.Rect(gap * 3 + cw * 2, top, cw, ch)
        pygame.draw.rect(s, CARD, r, border_radius=10)
        text(s, "Zigbee", (r.x + 12, r.y + 10), 15, MUTED)
        text(s, str(len(devs)), (r.centerx, r.y + 92), 56, TEXT, True, "center")
        text(s, "συσκευές", (r.centerx, r.y + 132), 14, MUTED, anchor="center")
        online = sum(1 for d in devs if d["avail"] == "online")
        known = sum(1 for d in devs if d["avail"] is not None)
        if known:
            text(s, f"{online} online", (r.centerx, r.y + 152), 13, GREEN, anchor="center")
        text(s, "λίστα", (r.centerx, r.bottom - 16), 13, AMBER, anchor="center")
        self.hits.append((r, lambda: self.go("devices")))

        # Γραμμή κατάστασης
        y = top + ch + 12
        bh = H - y - 8
        br = pygame.Rect(gap, y, W - gap * 2, bh)
        pygame.draw.rect(s, CARD, br, border_radius=10)
        cy = br.centery
        t = self.sys.temp
        items = [
            ("Θερμ.", f"{t:.0f}°C" if t is not None else "—", level_color((t or 0) * 1.25)),
            ("Ενεργό", fmt_uptime(self.sys.uptime), TEXT),
            ("IP", self.sys.ip, TEXT),
        ]
        x = br.x + 12
        for label, val, col in items:
            lr = text(s, label, (x, cy), 13, MUTED, anchor="midleft")
            vr = text(s, val, (lr.right + 6, cy), 14, col, True, "midleft")
            x = vr.right + 16
        ok = self.zb.mqtt_ok and self.zb.bridge != "offline"
        pygame.draw.circle(s, GREEN if ok else RED, (br.right - 14, cy), 5)

    def draw_procs(self):
        s = self.screen
        procs = self.sys.procs
        self.header("Διεργασίες", right=f"{len(procs)} συνολικά")
        y0 = self.HEADER + 4
        cols = [(14, "Όνομα"), (260, "PID"), (340, "CPU"), (412, "RAM")]
        for x, label in cols:
            text(s, label, (x, y0 + 4), 13, MUTED)
        list_top = y0 + 26
        row_h = 30
        area = pygame.Rect(0, list_top, W, H - list_top)
        self.max_scroll = max(0, len(procs) * row_h - area.height)
        s.set_clip(area)
        for i, p in enumerate(procs):
            y = list_top + i * row_h - self.scroll
            if y + row_h < list_top or y > H:
                continue
            if i % 2 == 0:
                pygame.draw.rect(s, CARD, (6, y, W - 12, row_h - 2), border_radius=6)
            cy = y + row_h // 2 - 1
            text(s, p["name"], (14, cy), 14, TEXT, anchor="midleft", maxw=236)
            text(s, p["pid"], (260, cy), 13, MUTED, anchor="midleft")
            text(s, f"{p['cpu']:.1f}%", (390, cy), 14, level_color(p["cpu"]) if p["cpu"] > 1 else TEXT,
                 anchor="midright")
            text(s, f"{p['mem']:.1f}%", (466, cy), 14, TEXT, anchor="midright")
        s.set_clip(None)
        self._scrollbar(area, len(procs) * row_h)

    def draw_devices(self):
        s = self.screen
        devs = self.zb.snapshot()
        self.header("Συσκευές Zigbee", right=f"{len(devs)}")
        list_top = self.HEADER + 6
        row_h = 56
        area = pygame.Rect(0, list_top, W, H - list_top)
        if not devs:
            text(s, "Δεν βρέθηκαν συσκευές", (W // 2, H // 2 - 10), 17, TEXT, anchor="center")
            text(s, f"{self.zb.status_msg} · {CONFIG['mqtt_host']}", (W // 2, H // 2 + 16), 13, MUTED,
                 anchor="center")
            return
        self.max_scroll = max(0, len(devs) * row_h - area.height)
        s.set_clip(area)
        for i, d in enumerate(devs):
            y = list_top + i * row_h - self.scroll
            if y + row_h < list_top or y > H:
                continue
            r = pygame.Rect(6, y, W - 12, row_h - 6)
            pygame.draw.rect(s, CARD, r, border_radius=8)
            dot = GREEN if d["avail"] == "online" else RED if d["avail"] == "offline" else MUTED
            pygame.draw.circle(s, dot, (r.x + 14, r.y + 16), 4)
            text(s, d["name"], (r.x + 26, r.y + 7), 15, TEXT, True, maxw=280)
            sub = d["ieee"]
            if d["battery"] is not None:
                sub += f"   μπατ. {d['battery']}%"
            elif d["type"] == "Router":
                sub += "   router"
            text(s, sub, (r.x + 26, r.y + 28), 12, MUTED, maxw=290)
            # σήμα
            lqi = d["lqi"]
            bx = r.right - 120
            bar(s, (bx, r.y + 12, 70, 8), (lqi or 0) / 255, lqi_color(lqi))
            text(s, lqi if lqi is not None else "—", (r.right - 12, r.y + 16), 14, lqi_color(lqi), True,
                 "midright")
            text(s, ago(d["last_seen"]), (r.right - 12, r.y + 34), 12, MUTED, anchor="midright")
            name = d["name"]
            self.hits.append((r.clip(area), lambda n=name: self._open(n)))
        s.set_clip(None)
        self._scrollbar(area, len(devs) * row_h)

    def _open(self, name):
        self.selected = name
        self.go("detail")

    def draw_detail(self):
        s = self.screen
        d = next((x for x in self.zb.snapshot() if x["name"] == self.selected), None)
        if not d:
            self.header("Συσκευή")
            text(s, "Η συσκευή δεν υπάρχει πια", (W // 2, H // 2), 16, MUTED, anchor="center")
            return
        self.header(d["name"])
        lqi = d["lqi"]
        nwk = f"0x{d['nwk']:04X}" if isinstance(d["nwk"], int) else "—"
        rows = [
            ("Ισχύς σήματος (LQI)", f"{lqi} / 255" if lqi is not None else "—", lqi_color(lqi)),
            ("Τελευταία επικοινωνία", ago(d["last_seen"]), TEXT),
            ("Κατάσταση", {"online": "Online", "offline": "Offline"}.get(d["avail"], "Άγνωστη"),
             GREEN if d["avail"] == "online" else RED if d["avail"] == "offline" else MUTED),
            ("IEEE (MAC)", d["ieee"], TEXT),
            ("Διεύθυνση δικτύου", nwk, TEXT),
            ("Τύπος", {"EndDevice": "Τελική συσκευή", "Router": "Router"}.get(d["type"], d["type"]), TEXT),
            ("Τροφοδοσία", "Μπαταρία" if d["power"] == "Battery" else "Ρεύμα" if "Mains" in str(d["power"])
             else d["power"], TEXT),
        ]
        if d["battery"] is not None:
            rows.append(("Μπαταρία", f"{d['battery']}%", level_color(100 - d["battery"])))
        rows += [("Κατασκευαστής", d["vendor"], TEXT), ("Μοντέλο", d["model"], TEXT)]
        skip = {"linkquality", "last_seen", "battery"}
        for k, v in d["state"].items():
            if k not in skip and not isinstance(v, (dict, list)):
                rows.append((k, v, BLUE))

        top = self.HEADER + 4
        row_h = 30
        area = pygame.Rect(0, top, W, H - top)
        self.max_scroll = max(0, len(rows) * row_h + 8 - area.height)
        s.set_clip(area)
        for i, (k, v, col) in enumerate(rows):
            y = top + 4 + i * row_h - self.scroll
            cy = y + row_h // 2
            text(s, k, (14, cy), 14, MUTED, anchor="midleft", maxw=200)
            text(s, v, (W - 14, cy), 14, col, True, "midright", maxw=250)
            pygame.draw.line(s, CARD, (14, y + row_h - 1), (W - 14, y + row_h - 1))
        s.set_clip(None)
        self._scrollbar(area, len(rows) * row_h + 8)

    def _scrollbar(self, area, content_h):
        if content_h <= area.height:
            return
        frac = area.height / content_h
        h = max(24, int(area.height * frac))
        y = area.y + int((area.height - h) * (self.scroll / self.max_scroll))
        pygame.draw.rect(self.screen, TRACK, (W - 4, y, 3, h), border_radius=2)


# ---------------------------------------------------------------- ΚΥΡΙΟΣ ΒΡΟΧΟΣ
def main():
    pygame.init()
    flags = pygame.FULLSCREEN if CONFIG["fullscreen"] else 0
    screen = pygame.display.set_mode((W, H), flags)
    pygame.display.set_caption("Zigbee Panel")
    if CONFIG["fullscreen"]:
        pygame.mouse.set_visible(False)
    app = App(screen)
    clock = pygame.time.Clock()
    down_pos, last_y, dragging = None, None, False
    dirty = True
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                down_pos, last_y, dragging = e.pos, e.pos[1], False
            elif e.type == pygame.MOUSEMOTION and down_pos:
                if abs(e.pos[1] - down_pos[1]) > 10:
                    dragging = True
                if dragging:
                    app.drag(e.pos[1] - last_y)
                    last_y = e.pos[1]
                    dirty = True
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                if down_pos and not dragging:
                    app.tap(e.pos)
                down_pos, dragging = None, False
                dirty = True
        if app.tick():
            dirty = True
        if dirty:
            app.draw()
            dirty = False
        clock.tick(20)  # χαμηλό FPS: η οθόνη ξανασχεδιάζεται μόνο όταν αλλάζει κάτι
    pygame.quit()


if __name__ == "__main__":
    main()
