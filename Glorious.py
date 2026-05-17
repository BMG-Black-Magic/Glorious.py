# Shout out https://github.com/enkore/gloriousctl for doing the orignal work <3
import sys
import argparse

try:
    import hid
except ImportError:
    sys.exit("Missing dependency: sudo pacman -S python-hid")

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


def open_device(pid=None):
    path, found_pid = find_device(pid)
    if not path:
        print("Device not found. Check with: lsusb | grep -i 3794")
        print("Or specify manually: --pid 0xXXXX")
        sys.exit(1)
    name = KNOWN_PIDS.get(found_pid, f"Unknown (PID 0x{found_pid:04x})")
    print(f"Opened: {name}", file=sys.stderr)
    return hid.Device(path=path)


def send_feature(dev, data):
    dev.send_feature_report(bytes(data))


def get_feature(dev, report_id, size):
    return bytearray(dev.get_feature_report(report_id, size))


def read_config(dev):
    cmd = bytearray(6)
    cmd[0] = REPORT_ID_CMD
    cmd[1] = CMD_CONFIG
    send_feature(dev, cmd)
    return get_feature(dev, REPORT_ID_CONFIG, CONFIG_SIZE)


def write_config(dev, cfg):
    cfg[O_CONFIG_WRITE] = CONFIG_SIZE_USED - 8
    buf = bytearray(cfg) + b'\x00' * (CONFIG_SIZE - len(cfg))
    dev.send_feature_report(bytes(buf[:CONFIG_SIZE]))


def dpi_to_cfg(dpi):
    return max(0, min(0x77, dpi // 100 - 1))


def cfg_to_dpi(v):
    return (v + 1) * 100


def parse_color(s):
    v = int(s.lstrip('#'), 16)
    return (v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff


def set_rbg(cfg, offset, r, g, b):
    cfg[offset], cfg[offset+1], cfg[offset+2] = r, b, g


def make_mode(brightness, speed):
    return ((brightness & 0xf) << 4) | (speed & 0xf)


def cmd_info(dev):
    cfg = read_config(dev)
    xy     = bool(cfg[O_CONFIG1] & 0x80)
    nibble = cfg[O_DPI_NIBBLES]
    active = (nibble >> 4) & 0x0f
    ena    = cfg[O_DPI_ENABLED]

    print(f"XY independent DPI : {'yes' if xy else 'no'}")
    print(f"Active DPI slot    : {active + 1}")
    print("DPI slots:")
    for i in range(NUM_DPIS):
        on   = not bool(ena & (1 << i))
        cur  = " [active]" if i == active else ""
        tag  = "on " if on else "off"
        dstr = f"{cfg_to_dpi(cfg[O_DPI+i*2])}/{cfg_to_dpi(cfg[O_DPI+i*2+1])}" if xy \
               else str(cfg_to_dpi(cfg[O_DPI + i]))
        r, g, b = cfg[O_DPI_COLOR+i*3], cfg[O_DPI_COLOR+i*3+1], cfg[O_DPI_COLOR+i*3+2]
        print(f"  [{tag}] {i+1}. {dstr:>10} DPI  #{r:02X}{g:02X}{b:02X}{cur}")

    print(f"RGB effect         : {RGB_EFFECT_NAMES.get(cfg[O_RGB_EFFECT], hex(cfg[O_RGB_EFFECT]))}")
    print(f"Lift-off distance  : {cfg[O_LIFT_OFF] + 1}mm")


def cmd_set_dpi(dev, dpis):
    cfg = read_config(dev)
    cfg[O_DPI_NIBBLES] = (cfg[O_DPI_NIBBLES] & 0xf0) | (len(dpis) & 0x0f)
    enabled = 0xff
    for i, dpi in enumerate(dpis):
        cfg[O_DPI + i] = dpi_to_cfg(dpi)
        enabled &= ~(1 << i)
    cfg[O_DPI_ENABLED] = enabled
    write_config(dev, cfg)
    print(f"DPI set: {dpis}")


def cmd_set_dpi_color(dev, colors):
    cfg = read_config(dev)
    for i, (r, g, b) in enumerate(colors[:NUM_DPIS]):
        cfg[O_DPI_COLOR+i*3], cfg[O_DPI_COLOR+i*3+1], cfg[O_DPI_COLOR+i*3+2] = r, g, b
    write_config(dev, cfg)
    print("DPI colors set.")


def cmd_set_effect(dev, effect, colors, brightness, speed):
    cfg  = read_config(dev)
    eid  = RGB_EFFECTS.get(effect)
    if eid is None:
        sys.exit(f"Unknown effect: {effect}")
    cfg[O_RGB_EFFECT] = eid
    mode = make_mode(brightness, speed)

    if   eid == 0x01: cfg[O_GLORIOUS_MODE] = mode
    elif eid == 0x02:
        cfg[O_SINGLE_MODE] = mode
        if colors: set_rbg(cfg, O_SINGLE_COLOR, *colors[0])
    elif eid == 0x03:
        cfg[O_BREATHING7_MODE]  = mode
        cfg[O_BREATHING7_COUNT] = 7
        for i, c in enumerate(colors[:7]): set_rbg(cfg, O_BREATHING7_COLORS + i*3, *c)
    elif eid == 0x04: cfg[O_TAIL_MODE] = mode
    elif eid == 0x05: cfg[O_GLORIOUS_MODE] = mode
    elif eid == 0x07:
        cfg[O_RAVE_MODE] = mode
        for i, c in enumerate(colors[:2]): set_rbg(cfg, O_RAVE_COLORS + i*3, *c)
    elif eid == 0x09: cfg[O_WAVE_MODE] = mode
    elif eid == 0x0a:
        cfg[O_BREATHING1_MODE] = mode
        if colors: set_rbg(cfg, O_BREATHING1_COLOR, *colors[0])

    write_config(dev, cfg)
    print(f"Effect set: {effect}")


def cmd_set_lod(dev, mm):
    cfg = read_config(dev)
    cfg[O_LIFT_OFF] = mm - 1
    write_config(dev, cfg)
    print(f"Lift-off distance set: {mm}mm")


def cmd_debounce(dev, ms=None):
    cmd = bytearray(6)
    cmd[0] = REPORT_ID_CMD
    cmd[1] = CMD_DEBOUNCE
    if ms is None:
        send_feature(dev, cmd)
        raw = get_feature(dev, REPORT_ID_CMD, 6)
        print(f"Debounce time: {raw[2] * 2}ms")
    else:
        if ms < 4 or ms > 16 or ms % 2:
            sys.exit("Debounce must be an even number between 4 and 16.")
        cmd[2] = ms // 2
        send_feature(dev, cmd)
        print(f"Debounce set: {ms}ms")


def main():
    ap = argparse.ArgumentParser(
        description="squeak.py — Glorious Model O Eternal config tool for Linux",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    ap.add_argument("--pid", type=lambda x: int(x, 16), metavar="0xXXXX",
                    help="Override USB PID (hex). Auto-detected if omitted.")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("info", help="Print current mouse configuration")

    p = sub.add_parser("dpi", help="Set DPI values (up to 6)")
    p.add_argument("values", help="e.g. 400,800,1600")

    p = sub.add_parser("dpi-color", help="Set per-slot DPI indicator colors")
    p.add_argument("colors", help="e.g. FF0000,00FF00,0000FF")

    p = sub.add_parser("effect", help="Set RGB lighting effect")
    p.add_argument("name", choices=list(RGB_EFFECTS))
    p.add_argument("--colors", default="", help="RRGGBB,... colors for the effect")
    p.add_argument("--brightness", type=int, default=4, choices=range(5), metavar="0-4")
    p.add_argument("--speed", type=int, default=3, choices=range(4), metavar="0-3")

    p = sub.add_parser("lod", help="Set lift-off distance (1 or 2mm)")
    p.add_argument("mm", type=int, choices=[1, 2])

    p = sub.add_parser("debounce", help="Get or set click debounce time")
    p.add_argument("ms", type=int, nargs="?", help="Even number 4-16ms. Omit to read.")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        sys.exit(0)

    dev = open_device(args.pid)
    try:
        if   args.cmd == "info":      cmd_info(dev)
        elif args.cmd == "dpi":       cmd_set_dpi(dev, [int(x) for x in args.values.split(",")])
        elif args.cmd == "dpi-color": cmd_set_dpi_color(dev, [parse_color(c) for c in args.colors.split(",")])
        elif args.cmd == "effect":
            colors = [parse_color(c) for c in args.colors.split(",") if args.colors]
            cmd_set_effect(dev, args.name, colors, args.brightness, args.speed)
        elif args.cmd == "lod":       cmd_set_lod(dev, args.mm)
        elif args.cmd == "debounce":  cmd_debounce(dev, args.ms)
    finally:
        dev.close()

if __name__ == "__main__":
    main()
