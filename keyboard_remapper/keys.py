"""Key codes, names and display labels.

Keys are stored in presets by their evdev name without the ``KEY_`` prefix
(``LEFTCTRL``, ``A``, ``KP1`` ...).  Four *generic* modifier names (``CTRL``,
``SHIFT``, ``ALT``, ``META``) match either the left or the right key.
"""

from __future__ import annotations

from evdev import ecodes as e

# --------------------------------------------------------------------------
# name <-> code
# --------------------------------------------------------------------------

_NAME_TO_CODE: dict[str, int] = {}
_CODE_TO_NAME: dict[int, str] = {}

# Highest keyboard key code the virtual device exposes.
MAX_KEY = 0x2FF


def _build() -> None:
    for name, code in e.ecodes.items():
        if not name.startswith("KEY_") or not isinstance(code, int):
            continue
        short = name[4:]
        if code > MAX_KEY or 0x100 <= code < 0x160:
            continue
        _NAME_TO_CODE.setdefault(short, code)
    # prefer the first (canonical) name evdev lists for a code
    for code, names in e.KEY.items():
        if code > MAX_KEY or 0x100 <= code < 0x160:
            continue
        if isinstance(names, (list, tuple)):
            names = names[0]
        _CODE_TO_NAME[code] = names[4:]


_build()

GENERIC_MODIFIERS: dict[str, tuple[int, int]] = {
    "CTRL": (e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL),
    "SHIFT": (e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT),
    "ALT": (e.KEY_LEFTALT, e.KEY_RIGHTALT),
    "META": (e.KEY_LEFTMETA, e.KEY_RIGHTMETA),
    # Apple keyboards report Fn as a key of its own (hid-apple); it is used like a layer modifier.
    "FN": (e.KEY_FN,),
}
MODIFIER_CODES: frozenset[int] = frozenset(c for pair in GENERIC_MODIFIERS.values() for c in pair)
_CODE_TO_GENERIC: dict[int, str] = {c: g for g, pair in GENERIC_MODIFIERS.items() for c in pair}
GENERIC_ORDER = ["CTRL", "SHIFT", "ALT", "META", "FN"]

# Keys whose lone press/release triggers desktop behaviour (Activities
# overview, menu bar focus ...).  A harmless key is slipped in before such a
# modifier is released "silently" so that the tap is not recognised.
TAP_SENSITIVE_CODES: frozenset[int] = frozenset(
    {e.KEY_LEFTMETA, e.KEY_RIGHTMETA, e.KEY_LEFTALT, e.KEY_RIGHTALT}
)
TAP_GUARD_KEY = e.KEY_F24

_ALIASES = {
    "CONTROL": "CTRL", "WIN": "META", "SUPER": "META", "WINDOWS": "META", "CMD": "META",
    "OPTION": "ALT", "RETURN": "ENTER", "ESCAPE": "ESC", "DEL": "DELETE", "INS": "INSERT",
    "PGUP": "PAGEUP", "PGDN": "PAGEDOWN", "SPACEBAR": "SPACE", "CAPS": "CAPSLOCK",
}


def name_to_code(name: str) -> int | None:
    """Return the evdev code for a key name (generic modifiers excluded)."""
    n = name.strip().upper().replace(" ", "")
    n = _ALIASES.get(n, n)
    if n.startswith("KEY_"):
        n = n[4:]
    n = {"LCTRL": "LEFTCTRL", "RCTRL": "RIGHTCTRL", "LSHIFT": "LEFTSHIFT", "RSHIFT": "RIGHTSHIFT",
         "LALT": "LEFTALT", "RALT": "RIGHTALT", "LMETA": "LEFTMETA", "RMETA": "RIGHTMETA"}.get(n, n)
    return _NAME_TO_CODE.get(n)


def code_to_name(code: int) -> str:
    return _CODE_TO_NAME.get(code, f"CODE{code}")


def normalize_name(name: str) -> str | None:
    """Canonical spelling of a key name, or None when it is unknown."""
    n = name.strip().upper().replace(" ", "")
    n = _ALIASES.get(n, n)
    if n in GENERIC_MODIFIERS:
        return n
    code = name_to_code(n)
    return None if code is None else code_to_name(code)


def spec_codes(name: str) -> tuple[int, ...]:
    """Codes matched by a key spec (one code, or two for a generic modifier)."""
    n = normalize_name(name)
    if n is None:
        return ()
    if n in GENERIC_MODIFIERS:
        return GENERIC_MODIFIERS[n]
    return (name_to_code(n),)


def is_generic(name: str) -> bool:
    return name in GENERIC_MODIFIERS


def generic_of(code: int) -> str | None:
    return _CODE_TO_GENERIC.get(code)


def is_modifier(code: int) -> bool:
    return code in MODIFIER_CODES


# --------------------------------------------------------------------------
# display
# --------------------------------------------------------------------------

# (english, japanese)
_NAMES: dict[str, tuple[str, str]] = {
    "ESC": ("Esc", "Esc"), "ENTER": ("Enter", "Enter"), "BACKSPACE": ("Backspace", "BackSpace"),
    "TAB": ("Tab", "Tab"), "SPACE": ("Space", "スペース"), "CAPSLOCK": ("Caps Lock", "CapsLock"),
    "LEFTCTRL": ("Left Ctrl", "左Ctrl"), "RIGHTCTRL": ("Right Ctrl", "右Ctrl"),
    "LEFTSHIFT": ("Left Shift", "左Shift"), "RIGHTSHIFT": ("Right Shift", "右Shift"),
    "LEFTALT": ("Left Alt", "左Alt"), "RIGHTALT": ("Right Alt", "右Alt"),
    "LEFTMETA": ("Left Super", "左Super"), "RIGHTMETA": ("Right Super", "右Super"),
    "CTRL": ("Ctrl", "Ctrl"), "SHIFT": ("Shift", "Shift"), "ALT": ("Alt", "Alt"),
    "META": ("Super", "Super"), "FN": ("Fn", "Fn"), "EJECTCD": ("Eject", "イジェクト"),
    "COMPOSE": ("Menu", "メニュー"), "SYSRQ": ("Print Screen", "PrintScreen"),
    "SCROLLLOCK": ("Scroll Lock", "ScrollLock"), "PAUSE": ("Pause", "Pause"),
    "INSERT": ("Insert", "Insert"), "DELETE": ("Delete", "Delete"), "HOME": ("Home", "Home"),
    "END": ("End", "End"), "PAGEUP": ("Page Up", "PageUp"), "PAGEDOWN": ("Page Down", "PageDown"),
    "UP": ("Up", "↑"), "DOWN": ("Down", "↓"), "LEFT": ("Left", "←"), "RIGHT": ("Right", "→"),
    "NUMLOCK": ("Num Lock", "NumLock"), "KPSLASH": ("Num /", "テンキー /"),
    "KPASTERISK": ("Num *", "テンキー *"), "KPMINUS": ("Num -", "テンキー -"),
    "KPPLUS": ("Num +", "テンキー +"), "KPENTER": ("Num Enter", "テンキー Enter"),
    "KPDOT": ("Num .", "テンキー ."), "KPEQUAL": ("Num =", "テンキー ="),
    "GRAVE": ("` ~", "` ~"), "MINUS": ("- _", "- ="), "EQUAL": ("= +", "^ ~"),
    "LEFTBRACE": ("[ {", "@ `"), "RIGHTBRACE": ("] }", "[ {"), "BACKSLASH": ("\\ |", "] }"),
    "SEMICOLON": ("; :", "; +"), "APOSTROPHE": ("' \"", ": *"), "COMMA": (", <", ", <"),
    "DOT": (". >", ". >"), "SLASH": ("/ ?", "/ ?"), "102ND": ("< > |", "< > |"),
    "ZENKAKUHANKAKU": ("半角/全角", "半角/全角"), "MUHENKAN": ("Muhenkan", "無変換"),
    "HENKAN": ("Henkan", "変換"), "KATAKANAHIRAGANA": ("Kana", "かな"), "YEN": ("¥ |", "¥ |"),
    "RO": ("\\ _", "\\ _"), "KATAKANA": ("Katakana", "カタカナ"), "HIRAGANA": ("Hiragana", "ひらがな"),
    "HANGEUL": ("Hangul", "ハングル"), "HANJA": ("Hanja", "漢字"),
    "MUTE": ("Mute", "ミュート"), "VOLUMEDOWN": ("Volume Down", "音量 −"),
    "VOLUMEUP": ("Volume Up", "音量 ＋"), "PLAYPAUSE": ("Play/Pause", "再生/一時停止"),
    "PLAYCD": ("Play", "再生"), "PAUSECD": ("Pause", "一時停止"),
    "STOPCD": ("Stop", "停止"), "NEXTSONG": ("Next Track", "次の曲"),
    "PREVIOUSSONG": ("Previous Track", "前の曲"), "FASTFORWARD": ("Fast Forward", "早送り"),
    "REWIND": ("Rewind", "巻き戻し"), "BRIGHTNESSDOWN": ("Brightness −", "輝度 −"),
    "BRIGHTNESSUP": ("Brightness +", "輝度 ＋"), "MICMUTE": ("Mic Mute", "マイクミュート"),
    "CALC": ("Calculator", "電卓"), "MAIL": ("Mail", "メール"), "WWW": ("Browser", "ブラウザ"),
    "HOMEPAGE": ("Home Page", "ホームページ"), "SEARCH": ("Search", "検索"),
    "BACK": ("Back", "戻る"), "FORWARD": ("Forward", "進む"), "REFRESH": ("Refresh", "更新"),
    "FILE": ("My Computer", "コンピューター"), "COFFEE": ("Lock Screen", "画面ロック"),
    "POWER": ("Power", "電源"), "SLEEP": ("Sleep", "スリープ"), "WAKEUP": ("Wake Up", "ウェイクアップ"),
    "MENU": ("Menu", "メニュー"), "CONFIG": ("Config", "設定"), "HELP": ("Help", "ヘルプ"),
    "UNDO": ("Undo", "元に戻す"), "REDO": ("Redo", "やり直し"), "COPY": ("Copy", "コピー"),
    "PASTE": ("Paste", "貼り付け"), "CUT": ("Cut", "切り取り"), "FIND": ("Find", "検索"),
    "OPEN": ("Open", "開く"), "CLOSE": ("Close", "閉じる"), "PROPS": ("Props", "プロパティ"),
    "SELECTIVE": ("Select", "選択"), "KBDILLUMTOGGLE": ("Kbd Light", "キーボード照明"),
    "KBDILLUMDOWN": ("Kbd Light −", "キーボード照明 −"), "KBDILLUMUP": ("Kbd Light +", "キーボード照明 ＋"),
    "SCREENLOCK": ("Lock Screen", "画面ロック"), "UNKNOWN": ("Unknown", "不明"),
}

# Keycap legends.  value: (top legend, main legend) per layout family.
_US_LEGENDS: dict[str, tuple[str, str]] = {
    "GRAVE": ("~", "`"), "1": ("!", "1"), "2": ("@", "2"), "3": ("#", "3"), "4": ("$", "4"),
    "5": ("%", "5"), "6": ("^", "6"), "7": ("&", "7"), "8": ("*", "8"), "9": ("(", "9"),
    "0": (")", "0"), "MINUS": ("_", "-"), "EQUAL": ("+", "="), "LEFTBRACE": ("{", "["),
    "RIGHTBRACE": ("}", "]"), "BACKSLASH": ("|", "\\"), "SEMICOLON": (":", ";"),
    "APOSTROPHE": ("\"", "'"), "COMMA": ("<", ","), "DOT": (">", "."), "SLASH": ("?", "/"),
    "102ND": ("|", "\\"),
}
_JIS_LEGENDS: dict[str, tuple[str, str]] = {
    "GRAVE": ("", "半/全"),     # most JIS keyboards report Hankaku/Zenkaku as KEY_GRAVE (xkb: <HZTG> = <TLDE>)
    "1": ("!", "1"), "2": ("\"", "2"), "3": ("#", "3"), "4": ("$", "4"), "5": ("%", "5"),
    "6": ("&", "6"), "7": ("'", "7"), "8": ("(", "8"), "9": (")", "9"), "0": ("", "0"),
    "MINUS": ("=", "-"), "EQUAL": ("~", "^"), "YEN": ("|", "¥"), "LEFTBRACE": ("`", "@"),
    "RIGHTBRACE": ("{", "["), "SEMICOLON": ("+", ";"), "APOSTROPHE": ("*", ":"),
    "BACKSLASH": ("}", "]"), "COMMA": ("<", ","), "DOT": (">", "."), "SLASH": ("?", "/"),
    "RO": ("_", "\\"),
}

_CAP_LABELS: dict[str, tuple[str, str]] = {
    "ESC": ("Esc", "Esc"), "ENTER": ("Enter", "Enter"), "BACKSPACE": ("⌫", "⌫"),
    "TAB": ("Tab", "Tab"), "SPACE": ("", ""), "CAPSLOCK": ("Caps", "Caps"),
    "LEFTCTRL": ("Ctrl", "Ctrl"), "RIGHTCTRL": ("Ctrl", "Ctrl"),
    "LEFTSHIFT": ("Shift", "Shift"), "RIGHTSHIFT": ("Shift", "Shift"),
    "LEFTALT": ("Alt", "Alt"), "RIGHTALT": ("Alt", "Alt"),
    "LEFTMETA": ("Super", "Super"), "RIGHTMETA": ("Super", "Super"),
    "COMPOSE": ("Menu", "Menu"), "SYSRQ": ("PrtSc", "PrtSc"), "SCROLLLOCK": ("ScrLk", "ScrLk"),
    "PAUSE": ("Pause", "Pause"), "INSERT": ("Ins", "Ins"), "DELETE": ("Del", "Del"),
    "HOME": ("Home", "Home"), "END": ("End", "End"), "PAGEUP": ("PgUp", "PgUp"),
    "PAGEDOWN": ("PgDn", "PgDn"), "UP": ("▲", "▲"), "DOWN": ("▼", "▼"), "LEFT": ("◀", "◀"),
    "RIGHT": ("▶", "▶"), "NUMLOCK": ("Num", "Num"), "KPSLASH": ("/", "/"), "KPASTERISK": ("*", "*"),
    "KPMINUS": ("-", "-"), "KPPLUS": ("+", "+"), "KPENTER": ("Enter", "Enter"), "KPDOT": (".", "."),
    "ZENKAKUHANKAKU": ("半/全", "半/全"), "MUHENKAN": ("無変換", "無変換"), "HENKAN": ("変換", "変換"),
    "KATAKANAHIRAGANA": ("かな", "かな"), "FN": ("fn", "fn"), "EJECTCD": ("⏏", "⏏"),
    "KPEQUAL": ("=", "="), "KPJPCOMMA": (",", ","),
}

# Apple keycaps: (top, main).  Used for the "apple-*" layout families.
_APPLE_LEGENDS: dict[str, tuple[str, str]] = {
    "LEFTCTRL": ("⌃", "control"), "RIGHTCTRL": ("⌃", "control"),
    "LEFTALT": ("⌥", "option"), "RIGHTALT": ("⌥", "option"),
    "LEFTMETA": ("⌘", "command"), "RIGHTMETA": ("⌘", "command"),
    "FN": ("", "fn"), "BACKSPACE": ("", "delete"), "ENTER": ("", "return"),
    "CAPSLOCK": ("", "caps lock"), "TAB": ("", "tab"), "ESC": ("", "esc"),
    "LEFTSHIFT": ("", "shift"), "RIGHTSHIFT": ("", "shift"), "EJECTCD": ("", "⏏"),
    "HANJA": ("", "英数"), "HANGEUL": ("", "かな"),
    "NUMLOCK": ("", "clear"), "DELETE": ("", "⌦"), "HOME": ("", "home"), "END": ("", "end"),
    "PAGEUP": ("", "pg up"), "PAGEDOWN": ("", "pg dn"),
}


def _tr(pair: tuple[str, str], lang: str) -> str:
    return pair[1] if lang == "ja" else pair[0]


def key_name(spec: str, lang: str = "ja") -> str:
    """Human readable name of a key spec (for lists and tooltips)."""
    n = normalize_name(spec)
    if n is None:
        return spec
    if n == "GRAVE" and lang == "ja":
        return "` (半角/全角)"
    if n in _NAMES:
        return _tr(_NAMES[n], lang)
    if n.startswith("KP") and n[2:].isdigit():
        return ("テンキー " if lang == "ja" else "Num ") + n[2:]
    if n.startswith("F") and n[1:].isdigit():
        return n
    if len(n) == 1:
        return n
    return n.title().replace("_", " ")


def cap_legend(spec: str, family: str = "us", lang: str = "ja") -> tuple[str, str]:
    """(top, main) text printed on a keycap.  *family* is ``us`` or ``jis``."""
    n = normalize_name(spec) or spec
    if family.startswith("apple"):
        if n in _APPLE_LEGENDS:
            return _APPLE_LEGENDS[n]
        family = family.split("-", 1)[1]
    table = _JIS_LEGENDS if family == "jis" else _US_LEGENDS
    if n in table:
        return table[n]
    if n in _CAP_LABELS:
        return "", _tr(_CAP_LABELS[n], lang)
    if n.startswith("KP") and n[2:].isdigit():
        return "", n[2:]
    return "", key_name(n, lang)


# Keys drawn on another key's cap when the layout has no shape of their own.
# (only used where the layout has no cap for the key itself).  COFFEE is the Lock key of newer Apple keyboards,
# which sits where older ones have Eject.
DISPLAY_ALIASES: dict[str, str] = {"ZENKAKUHANKAKU": "GRAVE", "COFFEE": "EJECTCD"}

# Notes shown next to keys in the chooser: name -> (english, japanese, is_warning)
_HINTS: dict[str, tuple[str, str, bool]] = {
    "ZENKAKUHANKAKU": (
        "The desktop's key tables (xkb) define no symbol for this key code, so it normally does nothing. "
        "To send Hankaku/Zenkaku use Grave (`) on a Japanese (jp) layout.",
        "デスクトップのキー配列表 (xkb) にこのキーコードの記号が無く、通常は何も起きません。"
        "半角/全角を送るには、日本語 (jp) 配列で Grave (`) を使います。", True),
    "GRAVE": (
        "Only on a Japanese (jp) layout does the desktop treat this key code as Hankaku/Zenkaku (elsewhere it is a backtick)",
        "日本語 (jp) 配列のときだけ、デスクトップがこのキーコードを「半角/全角」として扱います (他の配列ではバッククォート)", False),
    "HENKAN": ("Works on every layout (Henkan_Mode)", "どの配列でも使えます (変換)", False),
    "MUHENKAN": ("Works on every layout (Muhenkan)", "どの配列でも使えます (無変換)", False),
    "KATAKANAHIRAGANA": ("Works on every layout (Hiragana_Katakana)", "どの配列でも使えます (ひらがな/カタカナ)", False),
}


def key_hint(spec: str, lang: str = "ja") -> tuple[str, bool] | None:
    """(note, is_warning) for keys that deserve an explanation, else None."""
    n = normalize_name(spec)
    h = _HINTS.get(n or "")
    if h is None:
        return None
    return (h[1] if lang == "ja" else h[0]), h[2]


def chord_name(specs, lang: str = "ja", sep: str = " + ") -> str:
    return sep.join(key_name(s, lang) for s in specs)


# --------------------------------------------------------------------------
# key picker catalogue
# --------------------------------------------------------------------------

def _names(*items: str) -> list[str]:
    return [i for i in items if name_to_code(i) is not None]


CATEGORIES: list[tuple[str, str, list[str]]] = [
    ("letters", "Letters", _names(*[chr(c) for c in range(ord("A"), ord("Z") + 1)])),
    ("digits", "Numbers", _names(*"1234567890")),
    ("symbols", "Symbols", _names("GRAVE", "MINUS", "EQUAL", "LEFTBRACE", "RIGHTBRACE", "BACKSLASH",
                                   "SEMICOLON", "APOSTROPHE", "COMMA", "DOT", "SLASH", "102ND", "YEN", "RO")),
    ("modifiers", "Modifiers", ["LEFTCTRL", "RIGHTCTRL", "LEFTSHIFT", "RIGHTSHIFT", "LEFTALT",
                                "RIGHTALT", "LEFTMETA", "RIGHTMETA", "FN"]),
    ("editing", "Editing & navigation", _names("ESC", "ENTER", "BACKSPACE", "TAB", "SPACE", "CAPSLOCK",
                                                "INSERT", "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN",
                                                "UP", "DOWN", "LEFT", "RIGHT", "COMPOSE", "SYSRQ",
                                                "SCROLLLOCK", "PAUSE")),
    ("function", "Function keys", _names(*[f"F{i}" for i in range(1, 25)])),
    ("numpad", "Numpad", _names("NUMLOCK", "KPSLASH", "KPASTERISK", "KPMINUS", "KPPLUS", "KPENTER",
                                 "KPDOT", *[f"KP{i}" for i in range(10)])),
    ("japanese", "Japanese", _names("GRAVE", "MUHENKAN", "HENKAN", "KATAKANAHIRAGANA",
                                     "KATAKANA", "HIRAGANA", "ZENKAKUHANKAKU")),
    ("media", "Media & system", _names("MUTE", "VOLUMEDOWN", "VOLUMEUP", "PLAYPAUSE", "STOPCD",
                                        "NEXTSONG", "PREVIOUSSONG", "REWIND", "FASTFORWARD",
                                        "EJECTCD", "MICMUTE", "BRIGHTNESSDOWN", "BRIGHTNESSUP", "CALC", "MAIL",
                                        "WWW", "HOMEPAGE", "SEARCH", "BACK", "FORWARD", "REFRESH",
                                        "FILE", "SCREENLOCK", "SLEEP", "POWER", "MENU", "HELP",
                                        "UNDO", "REDO", "COPY", "PASTE", "CUT", "FIND",
                                        "KBDILLUMTOGGLE", "KBDILLUMDOWN", "KBDILLUMUP")),
]
CATEGORY_TITLES_JA = {
    "letters": "文字", "digits": "数字", "symbols": "記号", "modifiers": "修飾キー",
    "editing": "編集・移動", "function": "ファンクション", "numpad": "テンキー",
    "japanese": "日本語", "media": "メディア・システム",
}


def keyboard_codes() -> list[int]:
    """All key codes the virtual output device must be able to emit."""
    return sorted(c for c in _CODE_TO_NAME if 0 < c <= MAX_KEY)
