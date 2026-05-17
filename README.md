## How it works

squeak talks directly to the mouse over USB HID using the Sinowealth protocol, the same chipset used across most Glorious mice. It reads and writes a 131-byte config block stored in the mouse's onboard flash.

Protocol originally reverse engineered by [enkore/gloriousctl](https://github.com/enkore/gloriousctl).
Much of the work was done b him i just ported everything to python. Please give him love!


---
A Linux CLI tool for configuring the Glorious Model O Eternal mouse without needing Windows or Glorious CORE software. Controls DPI, RGB effects, lift-off distance, and debounce time over USB HID.

Tested on CachyOS / Arch Linux with Wayland.

---

## Requirements

```bash
sudo pacman -S hidapi python-hid
```

## Setup

Run once to allow access without sudo:

```bash
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3794", MODE="0666"' \
    | sudo tee /etc/udev/rules.d/99-glorious.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Usage

```bash
python squeak.py info
python squeak.py dpi 400,800,1600,3200
python squeak.py dpi-color FF0000,00FF00,0000FF,FFFFFF
python squeak.py effect glorious --brightness 3 --speed 2
python squeak.py effect single --colors FF0000 --brightness 4
python squeak.py effect breathing1 --colors 8800FF --speed 2
python squeak.py effect breathing7 --colors FF0000,FF7700,FFFF00,00FF00,00FFFF,0000FF,FF00FF
python squeak.py effect rave --colors FF00AA,00FFFF --brightness 4 --speed 3
python squeak.py effect off
python squeak.py lod 2
python squeak.py debounce
python squeak.py debounce 8
```

### Effects

| Name | Description |
|------|-------------|
| `off` | Lights off |
| `glorious` | Rainbow cycle |
| `single` | Solid color |
| `breathing` | RGB breathing |
| `breathing1` | Single color breathing |
| `breathing7` | 7-color breathing |
| `tail` | Tail effect |
| `rave` | Two-color alternating |
| `wave` | Wave effect |

### Options

| Flag | Values | Description |
|------|--------|-------------|
| `--colors` | `RRGGBB,...` | Hex color(s) for the effect |
| `--brightness` | `0–4` | Brightness level |
| `--speed` | `0–3` | Animation speed |

---

---

## Notes

- Settings are written to the mouse's onboard memory and persist across reboots and across OSes.
- If your device isn't detected, run `lsusb | grep -i 3794` to verify it's connected, then pass `--pid 0xXXXX` manually.
- Factory reset: hold left click + right click + scroll wheel for 5 seconds until the mouse flashes green.

---
