# Changelog

## Unreleased

- **Undo / Redo for every change** (header buttons), unlimited while the app runs, per keyboard. Consecutive
  changes to the same key are one step; removing, clearing all, importing and reordering are steps of their own.
  Before, only a deletion could be undone, and only from a 6-second toast.
- Apple Magic Keyboard layouts measured from real keyboards (14.5 key units wide):
  with or without numeric keypad; US, ISO and JIS. One layout serves every generation: the top-right key (Eject on the
  2015 keyboards, Lock on later ones, Touch ID on some) is drawn as one cap that reacts to both KEY_EJECTCD and KEY_COFFEE.
  The JIS drawing is measured from a photo of the real keyboard: Esc and Tab 1 wide, "1" 1.5 wide (no
  Hankaku/Zenkaku key), Control above Shift, Caps Lock bottom-left and Fn right of the right Command.
  The numeric-keypad JIS keyboard is drawn from a photo too (F13-F19, Fn / Home / PageUp, Delete / End / PageDown,
  inverted-T arrows, Option and Control at the right end of the bottom row).
  The size (compact / numeric keypad) is picked automatically from the USB/Bluetooth product id, JIS from the keys
  the keyboard reports.
  Apple's function row sits flush on the number row (no gap), unlike other keyboards.
  Layouts of non-Apple keyboards are unchanged.

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
- `--version` on every command; the GUI warns when the running service is not the installed version.
