# Changelog

## 1.0.0

First stable release.

- **No stall on modifier + key combos**: all output goes through one virtual keyboard created at start-up and
  never re-created, so the desktop never re-registers its global shortcuts.
- GTK4 + libadwaita GUI: realistic keyboard drawing (ANSI / ISO / JIS, full / tenkeyless, Apple Magic Keyboard),
  live key feedback, per-modifier layers, light / dark theme, English / Japanese.
- Actions: key / shortcut, key sequence with pauses, disable. Triggers: key, modifier + key,
  modifier-only chords fired on release (e.g. `Left Shift + Left Ctrl → Caps Lock`).
- A key remapped to a modifier counts as that modifier in triggers (`CapsLock → Ctrl` + `Ctrl+J → ↓`).
- Apple keyboards: `Fn` as a layer key, Eject, "Other keys" strip for keys the drawing lacks.
- Mapping list: drag to reorder, sortable column headers, right-click delete with Undo, clear all,
  export / import.
- Record triggers and outputs by pressing real keys (exclusive capture while recording).
- `keyboard-remapperd` (root, systemd) with persistent state, hotplug, LED relay, peer-checked socket;
  `keyboard-remapper-ctl` (`list`, `apply`, `start`, `stop`, `monitor [--output]`, `doctor`).
- Runs on Ubuntu 22.04 or newer (GTK 4.6+, libadwaita 1.0+, Python 3.10+).
- Settings written under the former name "Remapper" are carried over automatically.
- `--version` on every command; the GUI warns when the running service is not the installed version.
