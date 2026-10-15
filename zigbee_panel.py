#!/usr/bin/env python3
"""
Zigbee Panel - μικρή οθόνη πληροφοριών για Raspberry Pi Zero W (οθόνη αφής 3.2", 320x240)

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
    "width": int(os.getenv("PANEL_WIDTH", "320")),
    "height": int(os.getenv("PANEL_HEIGHT", "240")),
    "fullscreen": os.getenv("PANEL_FULLSCREEN", "1") == "1",
    "demo": os.getenv("PANEL_DEMO", "0") == "1",
    # "fb": γράφει απευθείας στο framebuffer (οθόνες SPI στις GPIO), "sdl": παράθυρο / HDMI
    "output": os.getenv("PANEL_OUTPUT", "fb"),
    "fbdev": os.getenv("PANEL_FB", "/dev/fb1"),
    # Coordinator μέσω ser2net (το Pi κάνει γέφυρα USB -> δίκτυο για το Home Assistant)
    "ser2net_port": int(os.getenv("PANEL_SER2NET_PORT", "6638")),
    "coordinator_dev": os.getenv("PANEL_COORDINATOR_DEV", ""),
    # Βαθμονόμηση αφής (γράφεται αυτόματα από: python3 zigbee_panel.py --calibrate)
    "touch_swap": os.getenv("PANEL_TOUCH_SWAP", "0") == "1",
    "touch_x_min": float(os.getenv("PANEL_TOUCH_X_MIN", "0")),
    "touch_x_max": float(os.getenv("PANEL_TOUCH_X_MAX", "4095")),
    "touch_y_min": float(os.getenv("PANEL_TOUCH_Y_MIN", "0")),
    "touch_y_max": float(os.getenv("PANEL_TOUCH_Y_MAX", "4095")),
    # 5σημειακή βαθμονόμηση: sx = a*rx + b*ry + c, sy = d*rx + e*ry + f (υπερισχύει των παραπάνω)
    "touch_affine": [float(v) for v in os.getenv("PANEL_TOUCH_AFFINE", "").split(",") if v.strip()],
}
W, H = CONFIG["width"], CONFIG["height"]
K = min(W / 480, H / 320)        # κλίμακα γεωμετρίας (σχεδιασμένο αρχικά για 480x320)
KF = (K + 1) / 2                 # τα γράμματα μικραίνουν λιγότερο, για να διαβάζονται


def S(n):
    return int(round(n * K))


def F(n):
    return max(11, int(round(n * KF)))

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
    f = font(F(size), bold)
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
        self.coord = ("—", MUTED)
        self._coord_at = 0
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
        if time.time() - self._coord_at > 5:
            self.coord = self._read_coord()
            self._coord_at = time.time()

    @staticmethod
    def _read_coord():
        """Κατάσταση γέφυρας: υπάρχει το USB stick; τρέχει το ser2net; έχει συνδεθεί το HA;"""
        if CONFIG["demo"]:
            return "Σε HA", GREEN
        dev = CONFIG["coordinator_dev"]
        if dev:
            present = os.path.exists(dev)
        else:
            present = os.path.isdir("/dev/serial/by-id") and bool(os.listdir("/dev/serial/by-id"))
        if not present:
            return "Χωρίς stick", RED
        port = CONFIG["ser2net_port"]
        listening = connected = False
        try:
            for c in psutil.net_connections("tcp"):
                if c.laddr and c.laddr.port == port:
                    if c.status == psutil.CONN_LISTEN:
                        listening = True
                    elif c.status == psutil.CONN_ESTABLISHED:
                        connected = True
        except (psutil.AccessDenied, OSError):
            return "Άγνωστο", MUTED
        if connected:
            return "Σε HA", GREEN
        if listening:
            return "Αναμονή HA", AMBER
        return "ser2net off", RED

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
    def __init__(self, screen):
        self.screen = screen
        self.HEADER = max(26, S(40))
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

    def header(self, title, back=True, right=None, dot=None):
        s, hh = self.screen, self.HEADER
        cy = hh // 2
        x0 = S(14)
        if back:
            a = max(5, S(8))
            pygame.draw.polygon(s, AMBER, [(x0 + a, cy - a), (x0, cy), (x0 + a, cy + a)])
            pygame.draw.line(s, AMBER, (x0, cy), (x0 + 2 * a + 2, cy), 3)
            # όλο το αριστερό μέρος της κεφαλίδας είναι «πίσω» (η γωνία πιάνει δύσκολα)
            self.hits.append((pygame.Rect(0, 0, int(W * 0.6), hh + S(6)), self.back))
            x0 += 2 * a + S(14)
        rr = text(s, right or time.strftime("%H:%M"), (W - S(12), cy), 15, MUTED, anchor="midright")
        if dot is not None:
            pygame.draw.circle(s, dot, (rr.left - S(12), cy), max(3, S(5)))
            rr.left -= S(20)
        text(s, title, (x0, cy), 18, TEXT, True, "midleft", maxw=rr.left - x0 - S(10))
        pygame.draw.line(s, TRACK, (0, hh - 1), (W, hh - 1))

    def _card(self, r, label):
        pygame.draw.rect(self.screen, CARD, r, border_radius=S(10))
        text(self.screen, label, (r.x + S(12), r.y + S(8)), 15, MUTED)

    def draw_home(self):
        s = self.screen
        ok = self.zb.mqtt_ok and self.zb.bridge != "offline"
        self.header(socket.gethostname(), back=False, dot=GREEN if ok else RED)
        gap = max(5, S(8))
        top = self.HEADER + gap
        stat_h = max(40, S(56))
        ch = H - top - stat_h - 2 * gap
        cw = (W - gap * 4) // 3
        devs = self.zb.snapshot()
        rad = min(cw // 2 - S(14), int(ch * 0.27))
        thick = max(6, S(10))
        ring_cy = top + int(ch * 0.50)

        for i, (label, pct, foot, fcol, target) in enumerate([
            ("CPU", self.sys.cpu, "διεργασίες", AMBER, "procs"),
            ("RAM", self.sys.ram,
             f"{self.sys.ram_used / 1048576:.0f}/{self.sys.ram_total / 1048576:.0f} MB", MUTED, None),
        ]):
            r = pygame.Rect(gap + i * (cw + gap), top, cw, ch)
            self._card(r, label)
            c = (r.centerx, ring_cy)
            ring(s, c, rad, thick, pct, level_color(pct))
            text(s, f"{pct:.0f}%", c, 22, TEXT, True, "center")
            text(s, foot, (r.centerx, r.bottom - S(14)), 13, fcol, anchor="center", maxw=cw - 6)
            if target:
                self.hits.append((r, lambda t=target: self.go(t)))

        r = pygame.Rect(gap * 3 + cw * 2, top, cw, ch)
        self._card(r, "Zigbee")
        nr = text(s, str(len(devs)), (r.centerx, ring_cy - S(8)), 52, TEXT, True, "center")
        online = sum(1 for d in devs if d["avail"] == "online")
        known = any(d["avail"] is not None for d in devs)
        sub, col = (f"{online} online", GREEN) if known else ("συσκευές", MUTED)
        text(s, sub, (r.centerx, nr.bottom + S(6)), 13, col, anchor="midtop")
        text(s, "λίστα", (r.centerx, r.bottom - S(14)), 13, AMBER, anchor="center")
        self.hits.append((r, lambda: self.go("devices")))

        # γραμμή κατάστασης: τρεις στήλες, ετικέτα πάνω και τιμή κάτω
        br = pygame.Rect(gap, H - gap - stat_h, W - 2 * gap, stat_h)
        pygame.draw.rect(s, CARD, br, border_radius=S(10))
        t = self.sys.temp
        items = [
            ("Θερμοκρασία", f"{t:.0f}°C" if t is not None else "—", level_color((t or 0) * 1.25)),
            ("Coordinator", self.sys.coord[0], self.sys.coord[1]),
            ("IP", self.sys.ip, TEXT),
        ]
        colw = [0.28, 0.32, 0.40]
        x = br.x + S(12)
        for (label, val, c), fr in zip(items, colw):
            w = int((br.width - S(12)) * fr) - S(6)
            text(s, label, (x, br.y + S(8)), 12, MUTED, maxw=w)
            text(s, val, (x, br.bottom - S(8)), 14, c, True, "bottomleft", maxw=w)
            x += w + S(6)

    def draw_procs(self):
        s = self.screen
        procs = self.sys.procs
        self.header("Διεργασίες", right=f"ενεργό {fmt_uptime(self.sys.uptime)}")
        show_pid = W >= 400
        x_cpu, x_ram = W - S(90), W - S(16)
        cols = [(S(14), "Όνομα", "topleft")]
        if show_pid:
            cols.append((W - S(220), "PID", "topleft"))
        cols += [(x_cpu, "CPU", "topright"), (x_ram, "RAM", "topright")]
        y0 = self.HEADER + S(6)
        for x, label, anc in cols:
            text(s, label, (x, y0), 12, MUTED, anchor=anc)
        list_top = y0 + F(12) + S(10)
        row_h = max(22, S(30))
        area = pygame.Rect(0, list_top, W, H - list_top)
        self.max_scroll = max(0, len(procs) * row_h - area.height)
        name_w = (W - S(220) if show_pid else x_cpu - F(14) * 4) - S(20)
        s.set_clip(area)
        for i, p in enumerate(procs):
            y = list_top + i * row_h - self.scroll
            if y + row_h < list_top or y > H:
                continue
            if i % 2 == 0:
                pygame.draw.rect(s, CARD, (S(6), y, W - S(12), row_h - 2), border_radius=S(6))
            cy = y + row_h // 2 - 1
            text(s, p["name"], (S(14), cy), 14, TEXT, anchor="midleft", maxw=name_w)
            if show_pid:
                text(s, p["pid"], (W - S(220), cy), 13, MUTED, anchor="midleft")
            text(s, f"{p['cpu']:.1f}%", (x_cpu, cy), 14,
                 level_color(p["cpu"]) if p["cpu"] > 1 else TEXT, anchor="midright")
            text(s, f"{p['mem']:.1f}%", (x_ram, cy), 14, TEXT, anchor="midright")
        s.set_clip(None)
        self._scrollbar(area, len(procs) * row_h)

    def draw_devices(self):
        s = self.screen
        devs = self.zb.snapshot()
        self.header("Συσκευές Zigbee", right=f"{len(devs)}")
        list_top = self.HEADER + S(6)
        row_h = max(42, S(56))
        area = pygame.Rect(0, list_top, W, H - list_top)
        if not devs:
            text(s, "Δεν βρέθηκαν συσκευές", (W // 2, H // 2 - S(10)), 16, TEXT, anchor="center")
            text(s, f"{self.zb.status_msg} ({CONFIG['mqtt_host']})", (W // 2, H // 2 + S(18)), 12,
                 MUTED, anchor="center", maxw=W - 20)
            return
        self.max_scroll = max(0, len(devs) * row_h - area.height)
        s.set_clip(area)
        right_w = max(80, S(120))
        for i, d in enumerate(devs):
            y = list_top + i * row_h - self.scroll
            if y + row_h < list_top or y > H:
                continue
            r = pygame.Rect(S(6), y, W - S(12), row_h - S(6))
            pygame.draw.rect(s, CARD, r, border_radius=S(8))
            dot = GREEN if d["avail"] == "online" else RED if d["avail"] == "offline" else MUTED
            lx = r.x + S(24)
            name_r = text(s, d["name"], (lx, r.y + S(6)), 15, TEXT, True, maxw=r.width - right_w - S(30))
            pygame.draw.circle(s, dot, (r.x + S(12), name_r.centery), max(3, S(4)))
            sub = d["ieee"]
            if d["battery"] is not None:
                sub += f"  {d['battery']}%"
            elif d["type"] == "Router":
                sub += "  router"
            text(s, sub, (lx, r.bottom - S(6)), 12, MUTED, anchor="bottomleft", maxw=r.width - right_w - S(10))
            lqi = d["lqi"]
            num = text(s, lqi if lqi is not None else "—", (r.right - S(10), name_r.centery), 14,
                       lqi_color(lqi), True, "midright")
            bw = right_w - num.width - S(16)
            bar(s, (num.left - S(8) - bw, num.centery - S(4), bw, max(5, S(8))), (lqi or 0) / 255, lqi_color(lqi))
            text(s, ago(d["last_seen"]), (r.right - S(10), r.bottom - S(6)), 12, MUTED, anchor="bottomright")
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
            text(s, "Η συσκευή δεν υπάρχει πια", (W // 2, H // 2), 15, MUTED, anchor="center")
            return
        self.header(d["name"])
        lqi = d["lqi"]
        nwk = f"0x{d['nwk']:04X}" if isinstance(d["nwk"], int) else "—"
        rows = [
            ("Σήμα (LQI)", f"{lqi} / 255" if lqi is not None else "—", lqi_color(lqi)),
            ("Τελ. επικοινωνία", ago(d["last_seen"]), TEXT),
            ("Κατάσταση", {"online": "Online", "offline": "Offline"}.get(d["avail"], "Άγνωστη"),
             GREEN if d["avail"] == "online" else RED if d["avail"] == "offline" else MUTED),
            ("IEEE (MAC)", d["ieee"], TEXT),
            ("Διεύθ. δικτύου", nwk, TEXT),
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

        top = self.HEADER + S(4)
        row_h = max(22, S(30))
        area = pygame.Rect(0, top, W, H - top)
        self.max_scroll = max(0, len(rows) * row_h + 8 - area.height)
        lw = int(W * 0.42)
        s.set_clip(area)
        for i, (k, v, col) in enumerate(rows):
            y = top + S(4) + i * row_h - self.scroll
            cy = y + row_h // 2
            text(s, k, (S(14), cy), 13, MUTED, anchor="midleft", maxw=lw - S(14))
            text(s, v, (W - S(14), cy), 13, col, True, "midright", maxw=W - lw - S(20))
            pygame.draw.line(s, CARD, (S(14), y + row_h - 1), (W - S(14), y + row_h - 1))
        s.set_clip(None)
        self._scrollbar(area, len(rows) * row_h + 8)

    def _scrollbar(self, area, content_h):
        if content_h <= area.height or self.max_scroll <= 0:
            return
        h = max(20, int(area.height * area.height / content_h))
        y = area.y + int((area.height - h) * (self.scroll / self.max_scroll))
        pygame.draw.rect(self.screen, TRACK, (W - 4, y, 3, h), border_radius=2)


# ---------------------------------------------------------------- ΕΞΟΔΟΣ ΕΙΚΟΝΑΣ
class FramebufferOutput:
    """Γράφει απευθείας στο /dev/fbX (π.χ. οθόνες ILI9341 με fbtft). Χωρίς numpy:
    το pygame μετατρέπει σε RGB565 μέσω μιας επιφάνειας 16-bit."""

    def __init__(self, dev):
        name = os.path.basename(dev)
        base = f"/sys/class/graphics/{name}"
        with open(f"{base}/virtual_size") as f:
            self.fw, self.fh = (int(v) for v in f.read().strip().split(","))
        with open(f"{base}/bits_per_pixel") as f:
            self.bpp = int(f.read().strip())
        if (self.fw, self.fh) != (W, H):
            print(f"Προσοχή: το {dev} είναι {self.fw}x{self.fh}, η εφαρμογή {W}x{H}. "
                  f"Βάλε PANEL_WIDTH/PANEL_HEIGHT ή άλλαξε το rotate στο config.txt.")
        if self.bpp == 16:
            self.conv = pygame.Surface((W, H), 0, 16, (0xF800, 0x07E0, 0x001F, 0))
        else:
            self.conv = pygame.Surface((W, H), 0, 32, (0xFF0000, 0x00FF00, 0x0000FF, 0))
        self.fd = os.open(dev, os.O_RDWR)
        self.surface = pygame.Surface((W, H))

    def present(self):
        self.conv.blit(self.surface, (0, 0))
        data = self.conv.get_buffer().raw
        os.pwrite(self.fd, data, 0)

    def clear(self):
        self.surface.fill((0, 0, 0))
        self.present()


class SDLOutput:
    def __init__(self):
        flags = pygame.FULLSCREEN if CONFIG["fullscreen"] else 0
        self.surface = pygame.display.set_mode((W, H), flags)
        pygame.display.set_caption("Zigbee Panel")
        if CONFIG["fullscreen"]:
            pygame.mouse.set_visible(False)

    def present(self):
        pygame.display.flip()

    def clear(self):
        pass


# ---------------------------------------------------------------- ΑΦΗ (evdev)
class EvdevTouch:
    """Διαβάζει την οθόνη αφής (ADS7846/XPT2046) από το /dev/input και βγάζει
    γεγονότα ("down"|"move"|"up", raw_x, raw_y) σε μια ουρά."""

    def __init__(self):
        import queue
        from evdev import InputDevice, ecodes, list_devices
        self.ec = ecodes
        self.q = queue.Queue()
        self.dev = None
        for path in list_devices():
            d = InputDevice(path)
            caps = d.capabilities()
            abs_codes = [c[0] if isinstance(c, tuple) else c for c in caps.get(ecodes.EV_ABS, [])]
            if ecodes.ABS_X in abs_codes and ecodes.BTN_TOUCH in caps.get(ecodes.EV_KEY, []):
                self.dev = d
                break
        if not self.dev:
            raise RuntimeError("Δεν βρέθηκε οθόνη αφής στο /dev/input")
        print(f"Αφή: {self.dev.name} ({self.dev.path})")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        """Οι resistive οθόνες στέλνουν θόρυβο στην αρχή κάθε πατήματος, και ο driver
        στέλνει το «πατήθηκε» πριν από τις νέες συντεταγμένες. Γι' αυτό σε κάθε νέο
        πάτημα ξεχνάμε τις παλιές τιμές και περιμένουμε φρέσκες X και Y."""
        ec = self.ec
        x = y = None
        fresh_x = fresh_y = False
        pressed = False
        samples = []
        started = False
        stale_reports = 0
        for ev in self.dev.read_loop():
            if ev.type == ec.EV_ABS:
                if ev.code == ec.ABS_X:
                    x, fresh_x = ev.value, True
                elif ev.code == ec.ABS_Y:
                    y, fresh_y = ev.value, True
            elif ev.type == ec.EV_KEY and ev.code == ec.BTN_TOUCH:
                if ev.value == 1 and not pressed:
                    fresh_x = fresh_y = False   # νέο πάτημα: οι παλιές τιμές δεν ισχύουν
                    stale_reports = 0
                pressed = ev.value == 1
            elif ev.type == ec.EV_SYN and ev.code == ec.SYN_REPORT:
                if pressed and x is not None and y is not None:
                    if not (fresh_x and fresh_y):
                        # ο kernel δεν στέλνει τιμή που δεν άλλαξε: μετά από λίγες
                        # αναφορές δεχόμαστε τον άξονα που δεν «ήρθε»
                        stale_reports += 1
                        if stale_reports < 4 or not (fresh_x or fresh_y):
                            continue
                        fresh_x = fresh_y = True
                    samples.append((x, y))
                    if len(samples) <= self.SKIP:
                        continue
                    pos = self._median(samples[-5:])
                    self.q.put(("move" if started else "down", *pos))
                    started = True
                elif not pressed and samples:
                    pos = self._median(samples[-5:]) if len(samples) > self.SKIP else self._median(samples)
                    if not started:  # πολύ σύντομο πάτημα: στέλνουμε κι ένα down
                        self.q.put(("down", *pos))
                    self.q.put(("up", *pos))
                    samples, started = [], False
                elif not pressed:
                    started = False

    SKIP = 2

    @staticmethod
    def _median(pts):
        xs = sorted(p[0] for p in pts)
        ys = sorted(p[1] for p in pts)
        return xs[len(xs) // 2], ys[len(ys) // 2]

    def events(self):
        while not self.q.empty():
            yield self.q.get_nowait()


def raw_to_screen(rx, ry):
    c = CONFIG
    if len(c["touch_affine"]) == 6:
        a, b, cc, d, e, f = c["touch_affine"]
        sx, sy = a * rx + b * ry + cc, d * rx + e * ry + f
        return int(max(0, min(W - 1, sx))), int(max(0, min(H - 1, sy)))
    if c["touch_swap"]:
        rx, ry = ry, rx
    sx = (rx - c["touch_x_min"]) / ((c["touch_x_max"] - c["touch_x_min"]) or 1) * W
    sy = (ry - c["touch_y_min"]) / ((c["touch_y_max"] - c["touch_y_min"]) or 1) * H
    return int(max(0, min(W - 1, sx))), int(max(0, min(H - 1, sy)))


# ---------------------------------------------------------------- ΒΑΘΜΟΝΟΜΗΣΗ
def _solve3(m, v):
    """Λύνει σύστημα 3x3 (Gauss με οδήγηση)."""
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        a[col], a[piv] = a[piv], a[col]
        if abs(a[col][col]) < 1e-9:
            raise ValueError("τα σημεία δεν αρκούν")
        for r in range(3):
            if r != col:
                k = a[r][col] / a[col][col]
                a[r] = [x - k * y for x, y in zip(a[r], a[col])]
    return [a[i][3] / a[i][i] for i in range(3)]


def fit_affine(raw, scr):
    """Ελάχιστα τετράγωνα: βρίσκει a..f ώστε raw -> οθόνη. Χειρίζεται μόνο του
    αναστροφές, εναλλαγή αξόνων και μικρή κλίση της επιφάνειας αφής."""
    m = [[0.0] * 3 for _ in range(3)]
    vx, vy = [0.0] * 3, [0.0] * 3
    for (rx, ry), (sx, sy) in zip(raw, scr):
        row = (rx, ry, 1.0)
        for i in range(3):
            for j in range(3):
                m[i][j] += row[i] * row[j]
            vx[i] += row[i] * sx
            vy[i] += row[i] * sy
    return _solve3(m, vx) + _solve3(m, vy)


def _wait_press(touch, min_samples=4):
    """Περιμένει ένα πάτημα που κρατήθηκε αρκετά και επιστρέφει τη διάμεσο των raw
    τιμών του. Τα πολύ σύντομα πατήματα αγνοούνται (δεν είναι αξιόπιστα)."""
    while not touch.q.empty():
        touch.q.get_nowait()
    samples = []
    while True:
        kind, rx, ry = touch.q.get()
        if kind == "down":
            samples = [(rx, ry)]
        elif kind == "move":
            samples.append((rx, ry))
        elif kind == "up":
            if len(samples) >= min_samples:
                return EvdevTouch._median(samples[len(samples) // 4:])
            samples = []


def calibrate(out, touch, env_path):
    """Πέντε στόχοι (4 γωνίες + κέντρο). Αν κάποιο πάτημα δεν ταιριάζει με τα άλλα,
    η βαθμονόμηση ξαναρχίζει αντί να αποθηκευτεί λάθος."""
    m = max(20, S(30))
    targets = [(m, m), (W - m, m), (W - m, H - m), (m, H - m), (W // 2, H // 2)]
    s = out.surface
    for attempt in range(1, 4):
        raw = []
        for n, (tx, ty) in enumerate(targets, 1):
            s.fill(BG)
            msg = "Βαθμονόμηση αφής" + (f" (προσπάθεια {attempt})" if attempt > 1 else "")
            cy = H // 2 + (30 if ty < H // 2 else -30) if (tx, ty) != (W // 2, H // 2) else H // 2 - 50
            text(s, msg, (W // 2, cy - 12), 15, TEXT, True, "center")
            text(s, f"Πάτα και κράτα τον σταυρό ({n}/5)", (W // 2, cy + 12), 12, MUTED, anchor="center")
            pygame.draw.line(s, AMBER, (tx - 14, ty), (tx + 14, ty), 2)
            pygame.draw.line(s, AMBER, (tx, ty - 14), (tx, ty + 14), 2)
            pygame.draw.circle(s, AMBER, (tx, ty), 7, 1)
            out.present()
            r = _wait_press(touch)
            raw.append(r)
            print(f"στόχος {n} ({tx},{ty}) -> raw {r}")
            pygame.draw.circle(s, GREEN, (tx, ty), 9)
            out.present()
            time.sleep(0.4)
        try:
            coef = fit_affine(raw, targets)
        except ValueError:
            coef = None
        err = 999
        if coef:
            a, b, c, d, e, f = coef
            err = max(math.hypot(a * rx + b * ry + c - tx, d * rx + e * ry + f - ty)
                      for (rx, ry), (tx, ty) in zip(raw, targets))
        print(f"μέγιστο σφάλμα: {err:.1f} px")
        if err <= max(12, S(18)):
            break
        s.fill(BG)
        text(s, "Κάποιο πάτημα δεν ήταν ακριβές", (W // 2, H // 2 - 12), 15, AMBER, True, "center")
        text(s, "Ξεκινάμε ξανά…", (W // 2, H // 2 + 12), 12, MUTED, anchor="center")
        out.present()
        time.sleep(2)
    else:
        s.fill(BG)
        text(s, "Η βαθμονόμηση απέτυχε", (W // 2, H // 2 - 12), 15, RED, True, "center")
        text(s, "Δες το μήνυμα στο SSH", (W // 2, H // 2 + 12), 12, MUTED, anchor="center")
        out.present()
        print("Η βαθμονόμηση απέτυχε 3 φορές. Στείλε τις γραμμές 'στόχος ...' παραπάνω.")
        time.sleep(3)
        return

    vals = {"PANEL_TOUCH_AFFINE": ",".join(f"{v:.6g}" for v in coef)}
    old = {"PANEL_TOUCH_SWAP", "PANEL_TOUCH_X_MIN", "PANEL_TOUCH_X_MAX",
           "PANEL_TOUCH_Y_MIN", "PANEL_TOUCH_Y_MAX", *vals}
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.split("=")[0].strip() not in old]
    lines += [f"{k}={v}" for k, v in vals.items()]
    with open(env_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    CONFIG["touch_affine"] = coef
    print(f"PANEL_TOUCH_AFFINE={vals['PANEL_TOUCH_AFFINE']}")
    s.fill(BG)
    text(s, "Η βαθμονόμηση αποθηκεύτηκε", (W // 2, H // 2 - 12), 15, GREEN, True, "center")
    text(s, f"ακρίβεια ±{err:.0f} pixels", (W // 2, H // 2 + 12), 12, MUTED, anchor="center")
    out.present()
    time.sleep(2)


def touch_test(out, touch):
    """Δείχνει πού «βλέπει» το πάτημα η εφαρμογή. Τέλος με Ctrl+C ή 30″ χωρίς άγγιγμα."""
    s = out.surface
    pos = raw = None
    trail = []
    last = time.time()

    def redraw():
        s.fill(BG)
        text(s, "Δοκιμή αφής", (W // 2, 14), 15, TEXT, True, "midtop")
        text(s, "Ζωγράφισε με το δάχτυλο", (W // 2, 36), 12, MUTED, anchor="midtop")
        for p in trail:
            pygame.draw.circle(s, AMBER, p, 2)
        if pos:
            pygame.draw.line(s, GREEN, (pos[0], 0), (pos[0], H), 1)
            pygame.draw.line(s, GREEN, (0, pos[1]), (W, pos[1]), 1)
            pygame.draw.circle(s, GREEN, pos, 8, 2)
            text(s, f"οθόνη {pos[0]},{pos[1]}   raw {raw[0]},{raw[1]}", (W // 2, H - 10), 12, TEXT,
                 anchor="midbottom")
        out.present()

    redraw()
    print("Δοκιμή αφής: άγγιξε την οθόνη (Ctrl+C για έξοδο)")
    while time.time() - last < 30:
        changed = False
        for kind, rx, ry in touch.events():
            raw, pos = (rx, ry), raw_to_screen(rx, ry)
            trail.append(pos)
            trail[:] = trail[-300:]
            print(f"{kind:4s} raw=({rx},{ry}) -> οθόνη={pos}")
            last, changed = time.time(), True
        if changed:
            redraw()
        time.sleep(0.03)


# ---------------------------------------------------------------- ΚΥΡΙΟΣ ΒΡΟΧΟΣ
def main():
    import sys
    use_fb = CONFIG["output"] == "fb"
    if use_fb:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    out = FramebufferOutput(CONFIG["fbdev"]) if use_fb else SDLOutput()
    touch = None
    if use_fb:
        try:
            touch = EvdevTouch()
        except Exception as e:  # noqa: BLE001
            print(f"Αφή μη διαθέσιμη: {e}")

    if "--touch-test" in sys.argv:
        if not touch:
            sys.exit("Δεν βρέθηκε οθόνη αφής. Δες: ls /dev/input/  και  dmesg | grep -i ads7846")
        try:
            touch_test(out, touch)
        except KeyboardInterrupt:
            pass
        out.clear()
        return

    if "--calibrate" in sys.argv:
        if not touch:
            sys.exit("Η βαθμονόμηση χρειάζεται οθόνη αφής (PANEL_OUTPUT=fb).")
        env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel.env")
        calibrate(out, touch, env)
        return

    app = App(out.surface)
    clock = pygame.time.Clock()
    st = {"down": None, "last_y": 0, "drag": False}
    dirty = True

    drag_px = max(16, H // 12)  # πόση κίνηση μετράει ως σύρσιμο και όχι πάτημα

    def on_down(pos):
        st.update(down=pos, last_y=pos[1], drag=False)

    def on_move(pos):
        nonlocal dirty
        if not st["down"]:
            return
        if not st["drag"] and abs(pos[1] - st["down"][1]) > drag_px:
            st["drag"] = True
            st["last_y"] = pos[1]
        if st["drag"]:
            app.drag(pos[1] - st["last_y"])
            st["last_y"] = pos[1]
            dirty = True

    def on_up(pos):
        nonlocal dirty
        if st["down"]:
            dx, dy = pos[0] - st["down"][0], pos[1] - st["down"][1]
            if dx > W // 4 and abs(dy) < dx / 2:   # σύρσιμο προς τα δεξιά = πίσω
                app.back()
                st.update(down=None, drag=False)
                dirty = True
                return
        if st["down"] and not st["drag"]:
            app.tap(pos)
        st.update(down=None, drag=False)
        dirty = True

    running = True
    try:
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    on_down(e.pos)
                elif e.type == pygame.MOUSEMOTION:
                    on_move(e.pos)
                elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                    on_up(e.pos)
            if touch:
                for kind, rx, ry in touch.events():
                    pos = raw_to_screen(rx, ry)
                    {"down": on_down, "move": on_move, "up": on_up}[kind](pos)
            if app.tick():
                dirty = True
            if dirty:
                app.draw()
                out.present()
                dirty = False
            clock.tick(20)  # η οθόνη ξανασχεδιάζεται μόνο όταν αλλάζει κάτι
    except KeyboardInterrupt:
        pass
    finally:
        out.clear()
        pygame.quit()


if __name__ == "__main__":
    main()
