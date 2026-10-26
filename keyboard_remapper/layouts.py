"""Physical keyboard layouts (key positions in key-unit coordinates)."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import keys


@dataclass(frozen=True)
class KeyShape:
    name: str                                   # canonical key name
    rects: tuple[tuple[float, float, float, float], ...]   # (x, y, w, h) in key units
    poly: tuple[tuple[float, float], ...] = ()              # outline for non-rectangular keys
    label: str = ""                                          # overrides the keycap legend when set

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
    "apple": ("Apple Magic Keyboard", "Apple Magic Keyboard"),
    "apple-num": ("Apple Magic Keyboard with numpad", "Apple Magic Keyboard テンキー付き"),
}
# Sizes that existed in development builds, mapped to the nearest layout that is still offered.
# One Apple layout serves every generation: they differ only in the top-right key (Eject on the 2015
# keyboards, Lock on the later ones, Touch ID on some), which the drawing treats as one key.
LEGACY_SIZES = {"apple-2015": "apple", "apple-touchid": "apple", "apple-2015-num": "apple-num"}
SIZE_IDS = list(SIZES)
APPLE_SIZES = [s for s in SIZE_IDS if s.startswith("apple")]

# Linux USB product id (hid-ids.h; USB vendor 0x05ac, Bluetooth vendor 0x004c) -> Magic Keyboard size.
# The product id does not tell ANSI / ISO / JIS apart: the layout comes from the keys the keyboard reports.
APPLE_PRODUCT_SIZE = {
    0x0267: "apple",               # Magic Keyboard (2015)
    0x026C: "apple-num",           # Magic Keyboard with numeric keypad (2015)
    0x029C: "apple",               # Magic Keyboard (2021)
    0x029A: "apple",               # Magic Keyboard with Touch ID (2021)
    0x029F: "apple-num",           # Magic Keyboard with Touch ID and numeric keypad (2021)
    0x0320: "apple",               # 2024 (USB-C): no layout change found
    0x0321: "apple",
    0x0322: "apple-num",
}
APPLE_VENDORS = (0x05AC, 0x004C)
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


def _flush_function_row(keys_: list[KeyShape]) -> list[KeyShape]:
    """Apple keyboards have no gap between the function row and the number row: pull every lower row up."""
    gap = 0.5

    def up(y: float) -> float:
        return y - gap if y >= 1.5 else y

    return [KeyShape(k.name, tuple((x, up(y), w, h) for x, y, w, h in k.rects),
                     tuple((px, up(py)) for px, py in k.poly), k.label) for k in keys_]


def _apple_jis_numeric(L: list[KeyShape], right: float, size: str) -> Layout:
    """Add the F13-F19 row, the navigation cluster and the keypad of the numeric-keypad JIS keyboard."""
    nx, px = right + 0.25, right + 3.5               # navigation cluster / keypad left edges
    L += _row(0, nx, ["F13", "F14", "F15"])
    L += _row(0, px, ["F16", "F17", "F18", "F19"])
    L += _row(1.5, nx, ["FN", "HOME", "PAGEUP"])
    L += _row(2.5, nx, ["DELETE", "END", "PAGEDOWN"])
    L += _row(4.5, nx, [1, "UP"])
    L += _row(5.5, nx, ["LEFT", "DOWN", "RIGHT"])
    L += _row(1.5, px, ["NUMLOCK", "KPEQUAL", "KPSLASH", "KPASTERISK"])
    L += _row(2.5, px, ["KP7", "KP8", "KP9", "KPMINUS"])
    L += _row(3.5, px, ["KP4", "KP5", "KP6", "KPPLUS"])
    L += _row(4.5, px, ["KP1", "KP2", "KP3"])
    L += _row(5.5, px, ["KP0", "KPDOT", "KPJPCOMMA"])
    L.append(KeyShape("KPENTER", ((px + 3, 4.5, 1, 2),)))
    L = [k for k in L if keys.name_to_code(k.name) is not None]
    return Layout(id=f"jis-{size}", family="apple-jis", keys=_flush_function_row(L), width=px + 4, height=6.0,
                  apple=True)


def _build_apple(standard: str, size: str) -> Layout:
    """Apple Magic Keyboard (compact, 14.5 key units wide; optionally with a numeric keypad).

    US/ISO measured from a 2021 US keyboard (Esc / Backspace / Tab 1.5, Caps Lock / Enter 1.75, Shifts 2.25,
    bottom row Fn Control Option Command Space Command Option).  JIS measured from a 2015 JIS keyboard (see
    the comments below): Esc and Tab are only 1 wide, "1" is 1.5 wide (no Hankaku/Zenkaku key), Control sits
    in the Caps Lock position, Caps Lock is bottom-left and Fn is right of the right Command.
    """
    num = size == "apple-num"
    top = ("EJECTCD", "eject/lock")        # KEY_COFFEE (the Lock key) is drawn on this same cap, see keys.DISPLAY_ALIASES
    digits = list("1234567890")
    qrow, arow, zrow = list("QWERTYUIOP"), list("ASDFGHJKL"), list("ZXCVBNM")
    right = 14.5
    arrows_x = right - 3                              # the arrow cluster is 3 units wide
    jis = standard == "jis"

    if jis:
        L: list[KeyShape] = _row(0, 0, [("ESC", 1.0), *[f"F{i}" for i in range(1, 13)]])
        L.append(KeyShape(top[0], ((13.0, 0, 1.5, 1),), label=top[1]))
        ex0, ex1 = 13.0, 13.25                        # Enter: left edge of its upper / lower part
    else:
        L = _row(0, 0, [("ESC", 1.5), *[f"F{i}" for i in range(1, 13)]])
        L.append(KeyShape(top[0], ((13.5, 0, 1.0, 1),), label=top[1]))
        ex0, ex1 = 13.5, 13.75
    enter_poly = ((ex0, 2.5), (right, 2.5), (right, 4.5), (ex1, 4.5), (ex1, 3.5), (ex0, 3.5))
    enter_l = KeyShape("ENTER", ((ex0, 2.5, right - ex0, 1), (ex1, 3.5, right - ex1, 1)), poly=enter_poly)

    if jis:
        L += _row(1.5, 0, [("1", 1.5), *digits[1:], "MINUS", "EQUAL", "YEN", "BACKSPACE"])
        L += _row(2.5, 0, [("TAB", 1.0), *qrow, "LEFTBRACE", "RIGHTBRACE"])
        L += _row(3.5, 0, [("LEFTCTRL", 1.25), *arow, "SEMICOLON", "APOSTROPHE", "BACKSLASH"])
        L.append(enter_l)
        L += _row(4.5, 0, [("LEFTSHIFT", 1.75), *zrow, "COMMA", "DOT", "SLASH", "RO", ("RIGHTSHIFT", 1.75)])
        if num:
            # numeric-keypad JIS: Fn and the arrows moved to the navigation cluster; Option and Control
            # (both 2 wide) take the right end of the row (measured from a photo of the 2015 JIS keyboard)
            L += _row(5.5, 0, ["CAPSLOCK", "LEFTALT", ("LEFTMETA", 1.25), ("HANJA", 1.25), ("SPACE", 3.5),
                               ("HANGEUL", 1.25), ("RIGHTMETA", 1.25), ("RIGHTALT", 2.0), ("RIGHTCTRL", 2.0)])
        else:
            L += _row(5.5, 0, ["CAPSLOCK", "LEFTALT", ("LEFTMETA", 1.25), ("HANJA", 1.25), ("SPACE", 3.5),
                               ("HANGEUL", 1.25), ("RIGHTMETA", 1.25), "FN"])
    else:
        L += _row(1.5, 0, ["GRAVE", *digits, "MINUS", "EQUAL", ("BACKSPACE", 1.5)])
        if standard == "iso":
            L += _row(2.5, 0, [("TAB", 1.5), *qrow, "LEFTBRACE", "RIGHTBRACE"])
            L += _row(3.5, 0, [("CAPSLOCK", 1.75), *arow, "SEMICOLON", "APOSTROPHE", "BACKSLASH"])
            L.append(enter_l)
            L += _row(4.5, 0, [("LEFTSHIFT", 1.25), "102ND", *zrow, "COMMA", "DOT", "SLASH", ("RIGHTSHIFT", 2.25)])
        else:
            L += _row(2.5, 0, [("TAB", 1.5), *qrow, "LEFTBRACE", "RIGHTBRACE", "BACKSLASH"])
            L += _row(3.5, 0, [("CAPSLOCK", 1.75), *arow, "SEMICOLON", "APOSTROPHE", ("ENTER", 1.75)])
            L += _row(4.5, 0, [("LEFTSHIFT", 2.25), *zrow, "COMMA", "DOT", "SLASH", ("RIGHTSHIFT", 2.25)])
        L += _row(5.5, 0, ["FN", "LEFTCTRL", "LEFTALT", ("LEFTMETA", 1.25), ("SPACE", 5.0),
                           ("RIGHTMETA", 1.25), "RIGHTALT"])
    ax = arrows_x
    if not (jis and num):
        L += [KeyShape("LEFT", ((ax, 5.5, 1, 1),)), KeyShape("UP", ((ax + 1, 5.5, 1, 0.5),)),
              KeyShape("DOWN", ((ax + 1, 6.0, 1, 0.5),)), KeyShape("RIGHT", ((ax + 2, 5.5, 1, 1),))]
    width = right
    if jis and num:
        return _apple_jis_numeric(L, right, size)
    if num:
        px = right + 0.25
        L += _row(1.5, px, ["NUMLOCK", "KPSLASH", "KPASTERISK", "KPMINUS"])
        L += _row(2.5, px, ["KP7", "KP8", "KP9"])
        L += _row(3.5, px, ["KP4", "KP5", "KP6"])
        L += _row(4.5, px, ["KP1", "KP2", "KP3"])
        L += _row(5.5, px, [("KP0", 2), "KPDOT"])
        L.append(KeyShape("KPPLUS", ((px + 3, 2.5, 1, 2),)))
        L.append(KeyShape("KPENTER", ((px + 3, 4.5, 1, 2),)))
        width = px + 4
    L = [k for k in L if keys.name_to_code(k.name) is not None]
    fam = "apple-" + ("jis" if jis else "us")
    return Layout(id=f"{standard}-{size}", family=fam, keys=_flush_function_row(L), width=width, height=6.0,
                  apple=True)


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
