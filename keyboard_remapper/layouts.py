"""Physical keyboard layouts (key positions in key-unit coordinates)."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import keys


@dataclass(frozen=True)
class KeyShape:
    name: str                                   # canonical key name
    rects: tuple[tuple[float, float, float, float], ...]   # (x, y, w, h) in key units
    poly: tuple[tuple[float, float], ...] = ()              # outline for non-rectangular keys

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        x0 = min(r[0] for r in self.rects)
        y0 = min(r[1] for r in self.rects)
        x1 = max(r[0] + r[2] for r in self.rects)
        y1 = max(r[1] + r[3] for r in self.rects)
        return x0, y0, x1 - x0, y1 - y0


@dataclass
class Layout:
    id: str
    family: str                                 # legends: "us", "jis", "apple-us" or "apple-jis"
    keys: list[KeyShape] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    apple: bool = False

    def by_name(self) -> dict[str, KeyShape]:
        return {k.name: k for k in self.keys}


TITLES = {
    "ansi": ("ANSI (US)", "ANSI (US配列)"),
    "iso": ("ISO (EU)", "ISO (欧州配列)"),
    "jis": ("JIS (Japanese)", "JIS (日本語配列)"),
}
SIZES = {
    "full": ("Full size", "フルサイズ"),
    "tkl": ("Tenkeyless", "テンキーレス"),
    "apple": ("Apple (compact)", "Apple (テンキーなし)"),
    "apple-num": ("Apple (numpad)", "Apple (テンキーあり)"),
}
SIZE_IDS = list(SIZES)
STANDARDS = list(TITLES)


def _row(y: float, x: float, items) -> list[KeyShape]:
    out = []
    for it in items:
        if isinstance(it, (int, float)):
            x += it
            continue
        name, w = it if isinstance(it, tuple) else (it, 1)
        out.append(KeyShape(name, ((x, y, w, 1),)))
        x += w
    return out


def _build_apple(standard: str, size: str) -> Layout:
    """Apple Magic Keyboard style: fn key, control/option/command, half-height arrows."""
    base = build(standard, "tkl")
    drop = {"SYSRQ", "SCROLLLOCK", "PAUSE", "INSERT", "HOME", "PAGEUP", "DELETE", "END", "PAGEDOWN",
            "UP", "DOWN", "LEFT", "RIGHT", "LEFTCTRL", "LEFTMETA", "LEFTALT", "RIGHTALT", "RIGHTMETA",
            "COMPOSE", "RIGHTCTRL", "SPACE", "MUHENKAN", "HENKAN", "KATAKANAHIRAGANA", "ESC",
            "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"}
    L = [k for k in base.keys if k.name not in drop]
    L += _row(0, 0, [("ESC", 1.5), *[f"F{i}" for i in range(1, 13)], ("EJECTCD", 1.5)])
    if standard == "jis":
        L += _row(5.5, 0, ["FN", "LEFTCTRL", "LEFTALT", ("LEFTMETA", 1.25), ("HANJA", 1.25), ("SPACE", 4.0),
                           ("HANGEUL", 1.25), ("RIGHTMETA", 1.25)])
    else:
        L += _row(5.5, 0, ["FN", "LEFTCTRL", "LEFTALT", ("LEFTMETA", 1.25), ("SPACE", 5.5),
                           ("RIGHTMETA", 1.25), "RIGHTALT"])
    L += [KeyShape("LEFT", ((12, 5.5, 1, 1),)), KeyShape("UP", ((13, 5.5, 1, 0.5),)),
          KeyShape("DOWN", ((13, 6.0, 1, 0.5),)), KeyShape("RIGHT", ((14, 5.5, 1, 1),))]
    width = 15.0
    if size == "apple-num":
        px = 15.25
        L += _row(1.5, px, ["NUMLOCK", "KPSLASH", "KPASTERISK", "KPMINUS"])
        L += _row(2.5, px, ["KP7", "KP8", "KP9"])
        L += _row(3.5, px, ["KP4", "KP5", "KP6"])
        L += _row(4.5, px, ["KP1", "KP2", "KP3"])
        L += _row(5.5, px, [("KP0", 2), "KPDOT"])
        L.append(KeyShape("KPPLUS", ((px + 3, 2.5, 1, 2),)))
        L.append(KeyShape("KPENTER", ((px + 3, 4.5, 1, 2),)))
        width = px + 4
    L = [k for k in L if keys.name_to_code(k.name) is not None]
    fam = "apple-" + ("jis" if standard == "jis" else "us")
    return Layout(id=f"{standard}-{size}", family=fam, keys=L, width=width, height=6.5, apple=True)


def build(standard: str = "ansi", size: str = "full") -> Layout:
    if size.startswith("apple"):
        return _build_apple(standard, size)
    L: list[KeyShape] = []
    fam = "jis" if standard == "jis" else "us"

    # function row
    L += _row(0, 0, ["ESC", 1, "F1", "F2", "F3", "F4", 0.5, "F5", "F6", "F7", "F8", 0.5,
                     "F9", "F10", "F11", "F12"])
    L += _row(0, 15.25, ["SYSRQ", "SCROLLLOCK", "PAUSE"])

    # number row
    digits = list("1234567890")
    if standard == "jis":
        L += _row(1.5, 0, ["GRAVE", *digits, "MINUS", "EQUAL", "YEN", "BACKSPACE"])   # Hankaku/Zenkaku
    else:
        L += _row(1.5, 0, ["GRAVE", *digits, "MINUS", "EQUAL", ("BACKSPACE", 2)])

    # QWERTY row
    qrow = list("QWERTYUIOP")
    if standard == "ansi":
        L += _row(2.5, 0, [("TAB", 1.5), *qrow, "LEFTBRACE", "RIGHTBRACE", ("BACKSLASH", 1.5)])
    else:
        L += _row(2.5, 0, [("TAB", 1.5), *qrow, "LEFTBRACE", "RIGHTBRACE"])
    # home row
    arow = list("ASDFGHJKL")
    if standard == "ansi":
        L += _row(3.5, 0, [("CAPSLOCK", 1.75), *arow, "SEMICOLON", "APOSTROPHE", ("ENTER", 2.25)])
    else:
        extra = "BACKSLASH"  # '#' on ISO, ']' on JIS
        L += _row(3.5, 0, [("CAPSLOCK", 1.75), *arow, "SEMICOLON", "APOSTROPHE", extra])
        # L-shaped Enter spanning two rows
        L.append(KeyShape("ENTER", ((13.5, 2.5, 1.5, 1), (13.75, 3.5, 1.25, 1)),
                          poly=((13.5, 2.5), (15, 2.5), (15, 4.5), (13.75, 4.5), (13.75, 3.5), (13.5, 3.5))))
    # bottom letter row
    zrow = list("ZXCVBNM")
    if standard == "ansi":
        L += _row(4.5, 0, [("LEFTSHIFT", 2.25), *zrow, "COMMA", "DOT", "SLASH", ("RIGHTSHIFT", 2.75)])
    elif standard == "iso":
        L += _row(4.5, 0, [("LEFTSHIFT", 1.25), "102ND", *zrow, "COMMA", "DOT", "SLASH",
                           ("RIGHTSHIFT", 2.75)])
    else:
        L += _row(4.5, 0, [("LEFTSHIFT", 2.25), *zrow, "COMMA", "DOT", "SLASH", "RO",
                           ("RIGHTSHIFT", 1.75)])
    # space row
    if standard == "jis":
        L += _row(5.5, 0, [("LEFTCTRL", 1.25), ("LEFTMETA", 1.25), ("LEFTALT", 1.25),
                           ("MUHENKAN", 1.25), ("SPACE", 3.75), ("HENKAN", 1.25),
                           ("KATAKANAHIRAGANA", 1.25), ("RIGHTALT", 1.25), ("COMPOSE", 1.25),
                           ("RIGHTCTRL", 1.25)])
    else:
        L += _row(5.5, 0, [("LEFTCTRL", 1.25), ("LEFTMETA", 1.25), ("LEFTALT", 1.25),
                           ("SPACE", 6.25), ("RIGHTALT", 1.25), ("RIGHTMETA", 1.25),
                           ("COMPOSE", 1.25), ("RIGHTCTRL", 1.25)])

    # navigation cluster
    nx = 15.25
    L += _row(1.5, nx, ["INSERT", "HOME", "PAGEUP"])
    L += _row(2.5, nx, ["DELETE", "END", "PAGEDOWN"])
    L += _row(4.5, nx, [1, "UP"])
    L += _row(5.5, nx, ["LEFT", "DOWN", "RIGHT"])

    width = nx + 3
    if size == "full":
        px = nx + 3.25
        L += _row(1.5, px, ["NUMLOCK", "KPSLASH", "KPASTERISK", "KPMINUS"])
        L += _row(2.5, px, ["KP7", "KP8", "KP9"])
        L += _row(3.5, px, ["KP4", "KP5", "KP6"])
        L += _row(4.5, px, ["KP1", "KP2", "KP3"])
        L += _row(5.5, px, [("KP0", 2), "KPDOT"])
        L.append(KeyShape("KPPLUS", ((px + 3, 2.5, 1, 2),)))
        L.append(KeyShape("KPENTER", ((px + 3, 4.5, 1, 2),)))
        width = px + 4

    L = [k for k in L if keys.name_to_code(k.name) is not None]
    return Layout(id=f"{standard}-{size}", family=fam, keys=L, width=width, height=6.5)


def guess_standard(lang_hint: str | None = None, xkb_layout: str | None = None) -> str:
    """Pick a layout standard from XKB layout / locale information."""
    x = (xkb_layout or "").lower()
    if x.startswith("jp") or x.startswith("ja"):
        return "jis"
    if x and x.split(",")[0] not in ("us", "") and not x.startswith("us"):
        return "iso"
    h = (lang_hint or "").lower()
    if h.startswith("ja"):
        return "jis"
    return "ansi"
