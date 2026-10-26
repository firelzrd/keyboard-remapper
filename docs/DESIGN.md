[日本語](DESIGN.ja.md)

# Design: Keyboard Remapper — a keyboard remapper GUI for Linux

> Status: **implemented (v0.1)**. See "9. Implementation notes" for deviations from the original plan.

## 1. Goals

- A GUI to map keys and key combinations to actions, like input-remapper 2.
- Draw the connected keyboard realistically; click a key or press it to see and change its mapping.
- **Never stall on modifier + key combos** (the input-remapper 2 bug, see §2).
- Japanese setups (JIS layout, Japanese UI) are first-class.

Out of scope for v0.1: mouse / gamepad remapping, running commands (map to F13–F24 and bind that in the desktop instead).

## 2. The stall and how it is avoided

### Cause
input-remapper 2 emits through **two** virtual devices: pass-through keys (e.g. Ctrl) from
`input-remapper <device> forwarded`, remapped keys from `input-remapper keyboard`. X (and XWayland)
copies the key source device's keymap to the master keyboard whenever the source device changes and
sends `XkbNewKeyboardNotify` / `MappingNotify` to every client. GNOME Shell / KWin react by
re-grabbing **all** global shortcuts, which takes tens to hundreds of milliseconds. "Ctrl (device A) →
remapped key (device B)", or the reverse order, switches the source every time.

### Solution
1. **One** output device: pass-through and remapped keys leave through the same virtual keyboard.
2. It is created once at daemon start and never re-created (applying, changing or stopping a preset,
   recording, hotplug), because appearing / disappearing devices also trigger desktop reconfiguration.
3. Its capabilities are declared up front (all keyboard keys + LEDs) and never change.
4. Sibling nodes of one physical keyboard (e.g. `... Keyboard` and `... Consumer Control`) are grabbed
   together and output to the same device.
5. Several keyboards share the same output device. `--grab-all` also routes keyboards that have no
   mapping through it.

Automated tests assert that every output goes to a single device and that it is never re-created.

## 3. Architecture

```
GUI (user)  ──JSON over Unix socket──▶  keyboard-remapperd (root/systemd)
 GTK4 + libadwaita                       ├ device discovery / hotplug
 keyboard drawing, editing, autosave     ├ evdev grab
                                         ├ Engine (translation logic)
 keyboard-remapper-ctl (CLI)                  ├ single uinput virtual keyboard
                                         └ LED state relayed to the physical keyboards
```

| Module | Role |
|---|---|
| `keyboard_remapper/keys.py` | key codes, names (en/ja), modifier definitions |
| `keyboard_remapper/layouts.py` | physical layout geometry (ANSI / ISO / JIS × full / TKL) |
| `keyboard_remapper/mapping.py` | preset / mapping data model, JSON I/O |
| `keyboard_remapper/engine.py` | input → output state machine (pure logic, device independent) |
| `keyboard_remapper/backend.py` | real evdev/uinput backend and an in-memory fake |
| `keyboard_remapper/daemon.py` | asyncio daemon: devices, IPC server, capture, persistence |
| `keyboard_remapper/ipc.py`, `cli.py` | client library and `keyboard-remapper-ctl` |
| `keyboard_remapper/config.py` | per-user configuration |
| `keyboard_remapper/gui/` | application, keyboard widget, editor, key chooser |
| `data/` | systemd unit, .desktop file, icon, modules-load |

UI: **GTK4 + libadwaita** (PyGObject): follows the GNOME look, light/dark, HiDPI, Wayland and X11.

## 4. Engine

### Mapping model
```jsonc
{ "trigger": ["CTRL", "J"], "action": {"type": "key", "output": ["DOWN"]} }
{ "trigger": ["META", "E"], "action": {"type": "sequence", "steps": ["Ctrl+C", "wait 50", "Ctrl+V"]} }
{ "trigger": ["CTRL", "Q"], "action": {"type": "disable"} }
```
- Trigger = keys held plus, last, the key whose press fires it. Held keys are unordered.
- `CTRL`, `SHIFT`, `ALT`, `META` match either side; `LEFTCTRL` etc. match one side. A side-specific spec beats a generic one; more held keys beat fewer.

### Behaviour
- Keys without a mapping pass through immediately (modifiers are never delayed, so Ctrl+click etc. is unaffected).
- Every held physical key owns a *claim* on output keys; the keys down on the virtual device are the union of non-suppressed claims.
- When a mapping fires, the trigger's modifiers are **suppressed** (hidden from the output), not released permanently, and **restored lazily**: only when a later key press needs them. Holding Ctrl and pressing J ten times gives ten `Down` taps and no Ctrl events; Ctrl then C gives Ctrl+C.
- Modifiers outside the trigger stay active (`Ctrl+J → ↓` plus Shift = Shift+↓).
- Suppressing Super / Alt first slips in a harmless key (F24) so the desktop does not treat it as a lone tap (Activities overview, menu-bar focus).
- A key remapped to a single key counts as that key for triggers (`CapsLock → Ctrl` + `Ctrl+J → ↓`).
- Auto-repeat from the input side is dropped; the desktop repeats held keys itself.
- Stopping, switching presets or unplugging releases every held output.

## 5. GUI

```
┌ [keyboard ▾]            [status] [on/off] [☰] ┐
├───────────────────────────────────────┬──────────────┤
│ Modifiers [Ctrl][Shift][Alt][Super]   │ Mappings (9) │
│ ┌───────────────────────────────────┐ │ search       │
│ │ keyboard, 3D keycaps; mapped keys │ │ Caps → Ctrl  │
│ │ show "→ output"                   │ │ Ctrl+J → ↓   │
│ └───────────────────────────────────┘ │ ...          │
│ ┌ editor: trigger, action, output ──┐ │              │
│ └───────────────────────────────────┘ │              │
└───────────────────────────────────────┴──────────────┘
```
1. **Click a key**, or **press it**, to select it. Holding Ctrl (or toggling the on-screen modifier) shows the Ctrl layer.
2. In the editor choose the action and output (press keys, search a list, or toggle modifiers).
3. **Autosave and instant apply**; deleting offers Undo. The output is only saved once you pick it.
4. The header switch turns remapping on/off for that keyboard.

Also: layout (ANSI/ISO/JIS) remembered per keyboard, guessed from XKB / locale; recording grabs the
keyboard exclusively (with a timeout); English/Japanese UI; offline editing when the daemon is down.

## 6. Permissions

- The daemon runs as root (systemd) and listens on `/run/keyboard-remapper/keyboard-remapper.sock`.
- Because input streaming could be abused as a keylogger, peers are checked with `SO_PEERCRED`: root or a user with an active local login session.
- Presets live in `~/.config/keyboard-remapper/`; the daemon also persists applied state in `/var/lib/keyboard-remapper/`.

## 7. Tests

- `tests/test_engine*.py`: translation logic incl. randomised stress (outputs never stick or double-press).
- `tests/test_daemon.py`: fake devices + IPC; **one virtual device only, never re-created**.
- `tests/test_gui.py`: real window under Xvfb against a fake daemon.

## 8. Decisions

Name: Remapper. v0.1 actions: key/shortcut, sequence, disable. Combinations fire on the last key. Pressed keys auto-select.

## 9. Implementation notes

| Topic | Plan | Implemented |
|---|---|---|
| Presets | several, switchable | one set per keyboard (more later) |
| Layouts | ANSI/ISO/JIS × full/TKL/75% | 75% later |
| "Any order" trigger mode | considered | skipped, to pass key→modifier order without delay |
| Trigger matching | physical keys | physical keys **plus** outputs of single-key remaps |
| Daemon offline | banner + start button | also keeps remembered keyboards editable; applied on reconnect |
| Grabbing | — | waits until no key is held (otherwise the desktop never sees the release → stuck key) |
| Extra | — | `--grab-all` |

### Not verified
The development environment had no `/dev/uinput` and no real keyboard, so the **real evdev/uinput
path (`Evdev*` in `keyboard_remapper/backend.py`) and the absence of the stall on a real desktop are untested**.
The logic is covered with a fake backend; the hardware layer is kept thin.
