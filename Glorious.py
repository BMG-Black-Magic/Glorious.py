#!/usr/bin/env python3

import sys
import argparse
import contextlib
import io
import json
import math
import os
import random

try:
    import hid
except ImportError:
    hid = None

VENDOR_ID = 0x3794

KNOWN_PIDS = {
    0xa000: "Glorious Model O Eternal",
}

REPORT_ID_CMD    = 0x05
REPORT_ID_CONFIG = 0x04
CMD_CONFIG       = 0x11
CMD_DEBOUNCE     = 0x1a
CONFIG_SIZE      = 520
CONFIG_SIZE_USED = 131
NUM_DPIS         = 6

RGB_EFFECTS = {
    "off":        0x00,
    "glorious":   0x01,
    "single":     0x02,
    "breathing7": 0x03,
    "tail":       0x04,
    "breathing":  0x05,
    "rave":       0x07,
    "wave":       0x09,
    "breathing1": 0x0a,
}
RGB_EFFECT_NAMES = {v: k for k, v in RGB_EFFECTS.items()}

EFFECT_COLOR_COUNTS = {
    "single":     1,
    "breathing1": 1,
    "breathing7": 7,
    "rave":       2,
}

PRESETS = {
    "Lava Core":       ("breathing1", ["FF1100"], 4, 2),
    "Neon Plague":     ("rave", ["00FF41", "FF00FF"], 4, 3),
    "Deep Ocean":      ("breathing1", ["00FFCC"], 3, 1),
    "Void Walker":     ("breathing1", ["6600FF"], 2, 1),
    "Synthwave":       ("rave", ["FF00AA", "00FFFF"], 4, 2),
    "Solar Flare":     ("rave", ["FF6600", "FFEE00"], 4, 3),
    "Arctic Ghost":    ("breathing1", ["99EEFF"], 1, 1),
    "Blood Moon":      ("breathing1", ["AA0022"], 3, 1),
    "Full Spectrum":   ("breathing7", ["FF0000", "FF7700", "FFFF00", "00FF00",
                                        "00FFFF", "0000FF", "FF00FF"], 4, 3),
    "Glitch":          ("rave", ["FF0033", "FFFFFF"], 4, 3),
    "Toxic Waste":     ("breathing1", ["CCFF00"], 4, 2),
    "Cyber Samurai":   ("rave", ["FF003C", "00E5FF"], 4, 3),
    "Rose Gold":       ("breathing1", ["FFB6A0"], 2, 1),
    "Vaporwave":       ("rave", ["FF71CE", "01CDFE"], 3, 2),
    "Emerald Circuit": ("single", ["00FF66"], 4, 0),
    "Midnight Signal": ("breathing1", ["1A1AFF"], 1, 1),
    "Amber Warning":   ("breathing1", ["FFA500"], 3, 2),
    "Ghost Protocol":  ("single", ["E0E0E0"], 1, 0),
    "Molten Circuit":  ("breathing7", ["FF0000", "FF3300", "FF6600", "FF9900",
                                        "FFCC00", "FF6600", "FF3300"], 4, 3),
    "Steady Glow":     ("glorious", [], 3, 1),
    "Comet Tail":      ("tail", [], 4, 2),
    "Tidal Wave":      ("wave", [], 3, 2),
    "Lights Out":      ("off", [], 0, 0),
}

EFFECT_ACCENTS = {
    "breathing1": "#ff8fc7",
    "breathing7": "#ff6ec7",
    "rave":       "#ff2e92",
    "single":     "#ffb3dd",
    "glorious":   "#ff4d9e",
    "tail":       "#e0559c",
    "wave":       "#ff8fc7",
    "off":        "#4a2635",
    "breathing":  "#ff9ecf",
}

O_REPORT_ID         = 0
O_CMD_ID            = 1
O_CONFIG_WRITE      = 3
O_CONFIG1           = 10
O_DPI_NIBBLES       = 11
O_DPI_ENABLED       = 12
O_DPI               = 13
O_DPI_COLOR         = 29
O_RGB_EFFECT        = 53
O_GLORIOUS_MODE     = 54
O_SINGLE_MODE       = 56
O_SINGLE_COLOR      = 57
O_BREATHING7_MODE   = 60
O_BREATHING7_COUNT  = 61
O_BREATHING7_COLORS = 62
O_TAIL_MODE         = 83
O_RAVE_MODE         = 117
O_RAVE_COLORS       = 118
O_WAVE_MODE         = 124
O_BREATHING1_MODE   = 125
O_BREATHING1_COLOR  = 126
O_LIFT_OFF          = 130

def find_device(pid=None):
    devs = hid.enumerate(VENDOR_ID, pid or 0)
    for d in devs:
        if d['interface_number'] == 1:
            return d['path'], d['product_id']
    if devs:
        return devs[0]['path'], devs[0]['product_id']
    return None, None

class DryRunDevice:

    def send_feature_report(self, data: bytes):
        print(f"[dry-run] send_feature_report ({len(data)} bytes): {data.hex()}")

    def get_feature_report(self, report_id: int, size: int) -> bytes:
        print(f"[dry-run] get_feature_report(report_id=0x{report_id:02x}, size={size})")
        return bytes(size)

    def close(self):
        pass

def open_device(pid=None, dry_run=False):
    if dry_run:
        print("[dry-run] Skipping device detection; no bytes will be written.", file=sys.stderr)
        return DryRunDevice()

    if hid is None:
        sys.exit("Install hid: pip install hid --break-system-packages")

    path, found_pid = find_device(pid)
    if not path:
        print(f"No Glorious/Sinowealth device found (VID 0x{VENDOR_ID:04x}).")
        print(f"Check with: lsusb | grep -i {VENDOR_ID:04x}")
        print("Then retry with: --pid 0xXXXX")
        sys.exit(1)
    name = KNOWN_PIDS.get(found_pid, f"Unknown device (PID 0x{found_pid:04x})")
    print(f"Opened: {name}", file=sys.stderr)
    d = hid.Device(path=path)
    return d

def send_feature(dev, data: bytes):
    dev.send_feature_report(bytes(data))

def get_feature(dev, report_id: int, size: int) -> bytearray:
    return bytearray(dev.get_feature_report(report_id, size))

def read_config(dev) -> bytearray:
    cmd = bytearray(6)
    cmd[0] = REPORT_ID_CMD
    cmd[1] = CMD_CONFIG
    send_feature(dev, cmd)
    return get_feature(dev, REPORT_ID_CONFIG, CONFIG_SIZE)

def write_config(dev, cfg: bytearray):
    cfg[O_CONFIG_WRITE] = CONFIG_SIZE_USED - 8
    buf = bytearray(cfg)
    buf += b'\x00' * (CONFIG_SIZE - len(buf))
    dev.send_feature_report(bytes(buf[:CONFIG_SIZE]))

def dpi_to_cfg(dpi: int) -> int:
    return max(0, min(0x77, dpi // 100 - 1))

def cfg_to_dpi(v: int) -> int:
    return (v + 1) * 100

def parse_color(s: str):
    hexpart = s.lstrip('#')
    if len(hexpart) != 6:
        sys.exit(f"Invalid color '{s}': expected 6 hex digits, e.g. FF00AA")
    try:
        v = int(hexpart, 16)
    except ValueError:
        sys.exit(f"Invalid color '{s}': not valid hex")
    return (v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff

def set_rbg(cfg: bytearray, offset: int, r: int, g: int, b: int):
    cfg[offset], cfg[offset+1], cfg[offset+2] = r, b, g

def make_mode(brightness: int, speed: int) -> int:
    return ((brightness & 0xf) << 4) | (speed & 0xf)

def cmd_info(dev):
    cfg = read_config(dev)
    xy = bool(cfg[O_CONFIG1] & 0x80)
    nibble = cfg[O_DPI_NIBBLES]
    count  = nibble & 0x0f
    active = (nibble >> 4) & 0x0f
    ena    = cfg[O_DPI_ENABLED]

    print(f"XY independent DPI : {'yes' if xy else 'no'}")
    print(f"Active DPI slot    : {active + 1}")
    print("DPI slots:")
    for i in range(NUM_DPIS):
        on  = not bool(ena & (1 << i))
        cur = " [active]" if i == active else ""
        tag = "on " if on else "off"
        if xy:
            x = cfg_to_dpi(cfg[O_DPI + i*2])
            y = cfg_to_dpi(cfg[O_DPI + i*2 + 1])
            dstr = f"{x}/{y}"
        else:
            dstr = str(cfg_to_dpi(cfg[O_DPI + i]))
        r = cfg[O_DPI_COLOR + i*3]
        g = cfg[O_DPI_COLOR + i*3 + 1]
        b = cfg[O_DPI_COLOR + i*3 + 2]
        print(f"  [{tag}] {i+1}. {dstr:>10} DPI  #{r:02X}{g:02X}{b:02X}{cur}")
    effect = cfg[O_RGB_EFFECT]
    lod = cfg[O_LIFT_OFF] + 1
    print(f"RGB effect         : {RGB_EFFECT_NAMES.get(effect, hex(effect))}")
    print(f"Lift-off distance  : {lod}mm")

def cmd_set_dpi(dev, dpis: list):
    if not 1 <= len(dpis) <= NUM_DPIS:
        sys.exit(f"Provide between 1 and {NUM_DPIS} DPI values, got {len(dpis)}")
    for dpi in dpis:
        if not 100 <= dpi <= 12000 or dpi % 100:
            sys.exit(f"Invalid DPI '{dpi}': must be a multiple of 100 between 100 and 12000")

    cfg = read_config(dev)
    nibble = cfg[O_DPI_NIBBLES]
    cfg[O_DPI_NIBBLES] = (nibble & 0xf0) | (len(dpis) & 0x0f)
    enabled = 0xff
    for i, dpi in enumerate(dpis):
        cfg[O_DPI + i] = dpi_to_cfg(dpi)
        enabled &= ~(1 << i)
    cfg[O_DPI_ENABLED] = enabled
    write_config(dev, cfg)
    print(f"DPI set: {dpis}")

def cmd_set_dpi_color(dev, colors: list):
    cfg = read_config(dev)
    for i, (r, g, b) in enumerate(colors[:NUM_DPIS]):
        cfg[O_DPI_COLOR + i*3]     = r
        cfg[O_DPI_COLOR + i*3 + 1] = g
        cfg[O_DPI_COLOR + i*3 + 2] = b
    write_config(dev, cfg)
    print("DPI colors set.")

def cmd_set_effect(dev, effect: str, colors: list, brightness: int, speed: int):
    eid = RGB_EFFECTS.get(effect)
    if eid is None:
        sys.exit(f"Unknown effect: {effect}")

    needed = EFFECT_COLOR_COUNTS.get(effect)
    if needed is not None and colors and len(colors) != needed:
        sys.exit(f"Effect '{effect}' needs exactly {needed} color(s), got {len(colors)}")
    if needed is None and colors:
        print(f"Note: effect '{effect}' doesn't use --colors; ignoring.", file=sys.stderr)

    cfg = read_config(dev)
    cfg[O_RGB_EFFECT] = eid
    mode = make_mode(brightness, speed)

    if eid == 0x01:
        cfg[O_GLORIOUS_MODE] = mode
    elif eid == 0x02:
        cfg[O_SINGLE_MODE] = mode
        if colors:
            set_rbg(cfg, O_SINGLE_COLOR, *colors[0])
    elif eid == 0x03:
        cfg[O_BREATHING7_MODE]  = mode
        cfg[O_BREATHING7_COUNT] = 7
        for i, c in enumerate(colors[:7]):
            set_rbg(cfg, O_BREATHING7_COLORS + i*3, *c)
    elif eid == 0x04:
        cfg[O_TAIL_MODE] = mode
    elif eid == 0x05:
        cfg[O_GLORIOUS_MODE] = mode
    elif eid == 0x07:
        cfg[O_RAVE_MODE] = mode
        for i, c in enumerate(colors[:2]):
            set_rbg(cfg, O_RAVE_COLORS + i*3, *c)
    elif eid == 0x09:
        cfg[O_WAVE_MODE] = mode
    elif eid == 0x0a:
        cfg[O_BREATHING1_MODE] = mode
        if colors:
            set_rbg(cfg, O_BREATHING1_COLOR, *colors[0])

    write_config(dev, cfg)
    print(f"Effect set: {effect}")

def cmd_list_presets():
    name_w = max(len(n) for n in PRESETS) + 2
    print(f"{'Name':<{name_w}}{'Effect':<12}Colors")
    print("-" * (name_w + 12 + 30))
    for name, (effect, colors, brightness, speed) in PRESETS.items():
        color_str = ",".join(colors) if colors else "-"
        print(f"{name:<{name_w}}{effect:<12}{color_str}")

def cmd_preset(dev, name: str, brightness: int = None, speed: int = None):
    preset = PRESETS.get(name)
    if preset is None:
        match = next((k for k in PRESETS if k.lower() == name.lower()), None)
        preset = PRESETS.get(match)
        name = match or name
    if preset is None:
        sys.exit(f"Unknown preset: '{name}'. Run 'list-presets' to see options.")

    effect, colors, def_brightness, def_speed = preset
    b = def_brightness if brightness is None else brightness
    s = def_speed if speed is None else speed
    parsed_colors = [parse_color(c) for c in colors]
    cmd_set_effect(dev, effect, parsed_colors, b, s)
    print(f"Preset applied: {name}")

def cmd_set_lod(dev, mm: int):
    cfg = read_config(dev)
    cfg[O_LIFT_OFF] = mm - 1
    write_config(dev, cfg)
    print(f"Lift-off distance set: {mm}mm")

def cmd_debounce(dev, ms=None):
    if ms is None:
        cmd = bytearray(6)
        cmd[0] = REPORT_ID_CMD
        cmd[1] = CMD_DEBOUNCE
        send_feature(dev, cmd)
        raw = get_feature(dev, REPORT_ID_CMD, 6)
        print(f"Debounce time: {raw[2] * 2}ms")
    else:
        if ms < 4 or ms > 16 or ms % 2:
            sys.exit("Debounce must be an even number between 4 and 16.")
        cmd = bytearray(6)
        cmd[0] = REPORT_ID_CMD
        cmd[1] = CMD_DEBOUNCE
        cmd[2] = ms // 2
        send_feature(dev, cmd)
        print(f"Debounce set: {ms}ms")

GUI_CONFIG_DIR = os.path.expanduser("~/.config/squeak-gui")
GUI_CONFIG_PATH = os.path.join(GUI_CONFIG_DIR, "config.json")

def _load_gui_config():
    try:
        with open(GUI_CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_gui_config(cfg):
    os.makedirs(GUI_CONFIG_DIR, exist_ok=True)
    with open(GUI_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def _draw_swatch(canvas, colors, effect):
    canvas.delete("all")
    w = int(canvas["width"])
    h = int(canvas["height"])
    if colors:
        n = len(colors)
        seg = w / n
        for i, c in enumerate(colors):
            canvas.create_rectangle(i * seg, 0, (i + 1) * seg, h,
                                     fill=f"#{c}", outline="")
    elif effect == "off":
        canvas.create_rectangle(0, 0, w, h, fill="#000000", outline="")
        canvas.create_line(6, 6, w - 6, h - 6, fill="#4a2635", width=2)
        canvas.create_line(w - 6, 6, 6, h - 6, fill="#4a2635", width=2)
    elif effect == "glorious":
        spectrum = ["#ff2e92", "#ff6ec7", "#ff8fc7", "#ffb3dd", "#ff8fc7", "#ff2e92"]
        seg = w / len(spectrum)
        for i, c in enumerate(spectrum):
            canvas.create_rectangle(i * seg, 0, (i + 1) * seg, h, fill=c, outline="")
    elif effect == "wave":
        canvas.create_rectangle(0, 0, w, h, fill="#000000", outline="")
        pts = []
        for x in range(0, w + 1, 4):
            y = h / 2 + (h / 2 - 3) * math.sin(x / 8)
            pts += [x, y]
        if len(pts) >= 4:
            canvas.create_line(*pts, fill="#ff8fc7", width=2, smooth=True)
    elif effect == "tail":
        canvas.create_rectangle(0, 0, w, h, fill="#000000", outline="")
        for i, r in enumerate(range(3, 10)):
            x = 8 + i * (w - 16) / 6
            shade = 40 + i * 20
            canvas.create_oval(x - r/2, h/2 - r/2, x + r/2, h/2 + r/2,
                                fill=f"#ff{shade:02x}{shade + 40:02x}", outline="")
    else:
        canvas.create_rectangle(0, 0, w, h, fill="#1a0011", outline="")

def launch_gui(pid=None):
    import threading
    import tkinter as tk
    from tkinter import messagebox

    BG        = "#000000"
    BG_PANEL  = "#000000"
    BG_ROW    = "#140009"
    BG_ROW_HOVER = "#2a0016"
    FG        = "#ffe6f2"
    FG_DIM    = "#8a5a72"
    ACCENT    = "#ff2e92"
    ACCENT2   = "#ff8fc7"
    GOOD      = "#4dffb8"
    BAD       = "#ff4d6d"
    STAR_ON   = "#ff2e92"
    STAR_OFF  = "#4a2635"
    FONT       = ("JetBrains Mono", 10)
    FONT_BOLD  = ("JetBrains Mono", 11, "bold")
    FONT_TITLE = ("JetBrains Mono", 15, "bold")

    class SqueakGUI:
        def __init__(self, root):
            self.root = root
            self.root.title("🐭 Squeak Control Panel")
            self.root.configure(bg=BG)
            self.root.geometry("560x700")
            self.root.minsize(480, 500)

            self.cfg = _load_gui_config()
            self.favorites = set(self.cfg.get("favorites", []))
            self.pid = pid

            self.dry_run = tk.BooleanVar(value=False)
            self.override = tk.BooleanVar(value=False)
            self.brightness = tk.IntVar(value=4)
            self.speed = tk.IntVar(value=3)
            self.filter_text = tk.StringVar()

            self._build_header()
            self._build_controls()
            self._build_list()
            self._build_log()

            self.filter_text.trace_add("write", lambda *_: self.render_list())
            self.render_list()
            self.log("ready. presets talk directly to squeak.py's device code — no subprocess.", "dim")

        def _build_header(self):
            header = tk.Frame(self.root, bg=BG_PANEL, pady=14)
            header.pack(fill="x")
            tk.Label(header, text="🐭  Squeak Control Panel", font=FONT_TITLE,
                     bg=BG_PANEL, fg=ACCENT).pack(side="left", padx=16)
            tk.Button(header, text="🎲 Surprise Me", font=FONT, bg=ACCENT2, fg="#000000",
                      activebackground="#ffb3dd", relief="flat", padx=10, pady=4,
                      command=self.surprise_me).pack(side="right", padx=16)

        def _build_controls(self):
            bar = tk.Frame(self.root, bg=BG, pady=8)
            bar.pack(fill="x", padx=16)

            search = tk.Entry(bar, textvariable=self.filter_text, font=FONT,
                               bg=BG_ROW, fg=FG, insertbackground=FG, relief="flat")
            search.pack(side="left", fill="x", expand=True, ipady=4)
            self._placeholder(search, "Search presets…")

            tk.Checkbutton(bar, text="dry-run", variable=self.dry_run, font=FONT,
                            bg=BG, fg=FG_DIM, selectcolor=BG_ROW, activebackground=BG,
                            activeforeground=FG).pack(side="left", padx=8)

            override_bar = tk.Frame(self.root, bg=BG)
            override_bar.pack(fill="x", padx=16, pady=(0, 6))
            tk.Checkbutton(override_bar, text="override brightness/speed",
                            variable=self.override, font=FONT, bg=BG, fg=FG_DIM,
                            selectcolor=BG_ROW, activebackground=BG,
                            activeforeground=FG).pack(side="left")
            tk.Label(override_bar, text="brightness", font=FONT, bg=BG, fg=FG_DIM).pack(side="left", padx=(12, 2))
            tk.Scale(override_bar, from_=0, to=4, orient="horizontal", variable=self.brightness,
                     length=90, bg=BG, fg=FG, troughcolor=BG_ROW, highlightthickness=0,
                     showvalue=True, font=FONT).pack(side="left")
            tk.Label(override_bar, text="speed", font=FONT, bg=BG, fg=FG_DIM).pack(side="left", padx=(12, 2))
            tk.Scale(override_bar, from_=0, to=3, orient="horizontal", variable=self.speed,
                     length=90, bg=BG, fg=FG, troughcolor=BG_ROW, highlightthickness=0,
                     showvalue=True, font=FONT).pack(side="left")

        def _build_list(self):
            wrap = tk.Frame(self.root, bg=BG)
            wrap.pack(fill="both", expand=True, padx=16)

            self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
            scrollbar = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
            self.list_frame = tk.Frame(self.canvas, bg=BG)

            self.list_frame.bind("<Configure>",
                                  lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
            self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
            self.canvas.configure(yscrollcommand=scrollbar.set)

            self.canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))
            self.canvas.bind_all("<MouseWheel>",
                                  lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        def _build_log(self):
            panel = tk.Frame(self.root, bg=BG_PANEL)
            panel.pack(fill="x", side="bottom")
            tk.Label(panel, text="log", font=FONT, bg=BG_PANEL, fg=FG_DIM, anchor="w").pack(fill="x", padx=12, pady=(6, 0))
            self.log_box = tk.Text(panel, height=6, bg="#000000", fg=FG, font=("JetBrains Mono", 9),
                                    relief="flat", state="disabled", wrap="word")
            self.log_box.pack(fill="x", padx=12, pady=(0, 12))
            for tag, color in (("good", GOOD), ("bad", BAD), ("dim", FG_DIM)):
                self.log_box.tag_config(tag, foreground=color)

        def _placeholder(self, entry, text):
            entry.insert(0, text)
            entry.config(fg=FG_DIM)

            def on_focus_in(_):
                if entry.get() == text:
                    entry.delete(0, "end")
                    entry.config(fg=FG)

            def on_focus_out(_):
                if not entry.get():
                    entry.insert(0, text)
                    entry.config(fg=FG_DIM)

            entry.bind("<FocusIn>", on_focus_in)
            entry.bind("<FocusOut>", on_focus_out)

        def render_list(self):
            if not hasattr(self, "list_frame"):
                return
            for child in self.list_frame.winfo_children():
                child.destroy()

            query = self.filter_text.get().strip().lower()
            if query == "search presets…":
                query = ""

            names = list(PRESETS.keys())
            names.sort(key=lambda n: (n not in self.favorites, n))
            matches = [n for n in names if query in n.lower()]

            if not matches:
                tk.Label(self.list_frame, text="no presets match that search",
                          font=FONT, bg=BG, fg=FG_DIM).pack(pady=20)
                return

            last_was_fav = None
            for name in matches:
                is_fav = name in self.favorites
                if last_was_fav is True and not is_fav and not query:
                    tk.Frame(self.list_frame, bg="#3a1a28", height=1).pack(fill="x", padx=4, pady=6)
                last_was_fav = is_fav
                self._build_row(name, is_fav)

        def _build_row(self, name, is_fav):
            effect, colors, brightness, speed = PRESETS[name]
            row = tk.Frame(self.list_frame, bg=BG_ROW, pady=6, padx=8)
            row.pack(fill="x", pady=3)

            def set_bg_recursive(widget, color):
                for child in widget.winfo_children():
                    cls = child.winfo_class()
                    if cls == "Frame":
                        child.configure(bg=color)
                        set_bg_recursive(child, color)
                    elif cls == "Label":
                        child.configure(bg=color)

            def on_enter(_):
                row.configure(bg=BG_ROW_HOVER)
                set_bg_recursive(row, BG_ROW_HOVER)

            def on_leave(_):
                row.configure(bg=BG_ROW)
                set_bg_recursive(row, BG_ROW)

            row.bind("<Enter>", on_enter)
            row.bind("<Leave>", on_leave)

            star = tk.Label(row, text="★" if is_fav else "☆", font=FONT_BOLD,
                             fg=STAR_ON if is_fav else STAR_OFF, bg=BG_ROW, cursor="hand2")
            star.pack(side="left", padx=(0, 8))
            star.bind("<Button-1>", lambda e, n=name: self.toggle_favorite(n))

            swatch = tk.Canvas(row, width=64, height=26, highlightthickness=1,
                                highlightbackground="#4a2635", bd=0)
            swatch.pack(side="left", padx=(0, 10))
            _draw_swatch(swatch, colors, effect)

            info = tk.Frame(row, bg=BG_ROW)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=name, font=FONT_BOLD, bg=BG_ROW, fg=FG, anchor="w").pack(anchor="w")
            tk.Label(info, text=effect, font=("JetBrains Mono", 8), bg=BG_ROW,
                     fg=EFFECT_ACCENTS.get(effect, FG_DIM), anchor="w").pack(anchor="w")

            for w in (row, star, swatch, info):
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)

            apply_btn = tk.Button(row, text="Apply", font=FONT, bg=ACCENT, fg="#000000",
                                   activebackground="#ff8fc7", relief="flat", padx=10,
                                   command=lambda n=name: self.apply_preset(n))
            apply_btn.pack(side="right")

        def toggle_favorite(self, name):
            if name in self.favorites:
                self.favorites.discard(name)
            else:
                self.favorites.add(name)
            self.cfg["favorites"] = sorted(self.favorites)
            _save_gui_config(self.cfg)
            self.render_list()

        def surprise_me(self):
            name = random.choice(list(PRESETS.keys()))
            self.log(f"🎲 rolled: {name}", "dim")
            self.apply_preset(name)

        def log(self, text, tag=None):
            self.log_box.configure(state="normal")
            self.log_box.insert("end", text + "\n", tag or ())
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        def apply_preset(self, name):
            dry_run = self.dry_run.get()
            override_b = self.brightness.get() if self.override.get() else None
            override_s = self.speed.get() if self.override.get() else None
            self.log(f"$ preset \"{name}\"" + (" --dry-run" if dry_run else ""), "dim")
            threading.Thread(target=self._run, args=(name, dry_run, override_b, override_s),
                              daemon=True).start()

        def _run(self, name, dry_run, override_b, override_s):
            buf = io.StringIO()
            ok, err = True, ""
            try:
                with contextlib.redirect_stdout(buf):
                    dev = open_device(self.pid, dry_run=dry_run)
                    try:
                        cmd_preset(dev, name, override_b, override_s)
                    finally:
                        dev.close()
            except SystemExit as e:
                ok, err = False, str(e.code)
            except Exception as e:
                ok, err = False, str(e)

            output = buf.getvalue().strip()

            def update():
                if output:
                    self.log(output, "good" if ok else None)
                if err:
                    self.log(err, "bad")
                self.log(f"{'✓' if ok else '✗'} {name} {'applied' if ok else 'failed'}\n",
                          "good" if ok else "bad")

            self.root.after(0, update)

    root = tk.Tk()
    try:
        SqueakGUI(root)
    except Exception as e:
        messagebox.showerror("Squeak Control Panel", f"Failed to start: {e}")
        raise
    root.mainloop()

def main():
    ap = argparse.ArgumentParser(
        description="Glorious mouse config tool for Linux",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    ap.add_argument("--pid", type=lambda x: int(x, 16),
                    metavar="0xXXXX",
                    help="Override USB PID (hex). Auto-detected if omitted.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the bytes that would be sent instead of touching the device")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("info", help="Print current mouse configuration")

    sub.add_parser("list-presets", help="List built-in lighting presets")

    p = sub.add_parser("preset", help="Apply a named lighting preset")
    p.add_argument("name", help="Preset name, e.g. \"Lava Core\" (see list-presets)")
    p.add_argument("--brightness", type=int, default=None, choices=range(5),
                   metavar="0-4", help="Override preset's default brightness")
    p.add_argument("--speed", type=int, default=None, choices=range(4),
                   metavar="0-3", help="Override preset's default speed")

    sub.add_parser("gui", help="Launch the graphical Squeak Control Panel (needs tk)")

    p = sub.add_parser("dpi", help="Set DPI values (up to 6)")
    p.add_argument("values", help="Comma-separated DPIs, e.g. 400,800,1600")

    p = sub.add_parser("dpi-color", help="Set per-slot DPI indicator colors")
    p.add_argument("colors", help="RRGGBB,... e.g. FF0000,00FF00,0000FF")

    p = sub.add_parser("effect", help="Set RGB lighting effect")
    p.add_argument("name", choices=list(RGB_EFFECTS),
                   help="Effect: off, glorious, single, breathing, breathing1, "
                        "breathing7, tail, rave, wave")
    p.add_argument("--colors", default="",
                   help="RRGGBB,... colors used by the effect")
    p.add_argument("--brightness", type=int, default=4, choices=range(5),
                   metavar="0-4")
    p.add_argument("--speed", type=int, default=3, choices=range(4),
                   metavar="0-3")

    p = sub.add_parser("lod", help="Set lift-off distance")
    p.add_argument("mm", type=int, choices=[1, 2], help="1 or 2 mm")

    p = sub.add_parser("debounce", help="Get or set click debounce time")
    p.add_argument("ms", type=int, nargs="?",
                   help="Even number 4–16 ms. Omit to read current value.")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        sys.exit(0)

    if args.cmd == "list-presets":
        cmd_list_presets()
        return

    if args.cmd == "gui":
        launch_gui(args.pid)
        return

    dev = open_device(args.pid, dry_run=args.dry_run)
    try:
        if args.cmd == "info":
            cmd_info(dev)
        elif args.cmd == "dpi":
            cmd_set_dpi(dev, [int(x) for x in args.values.split(",")])
        elif args.cmd == "dpi-color":
            cmd_set_dpi_color(dev, [parse_color(c) for c in args.colors.split(",")])
        elif args.cmd == "effect":
            colors = [parse_color(c) for c in args.colors.split(",")] if args.colors else []
            cmd_set_effect(dev, args.name, colors, args.brightness, args.speed)
        elif args.cmd == "preset":
            cmd_preset(dev, args.name, args.brightness, args.speed)
        elif args.cmd == "lod":
            cmd_set_lod(dev, args.mm)
        elif args.cmd == "debounce":
            cmd_debounce(dev, args.ms)
    finally:
        dev.close()

if __name__ == "__main__":
    main()
