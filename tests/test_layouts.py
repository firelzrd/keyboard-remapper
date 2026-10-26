import itertools

import pytest

from keyboard_remapper import keys, layouts


@pytest.mark.parametrize("standard", layouts.STANDARDS)
@pytest.mark.parametrize("size", layouts.SIZE_IDS)
def test_layout_is_sane(standard, size):
    L = layouts.build(standard, size)
    names = [k.name for k in L.keys]
    assert len(names) == len(set(names))
    assert all(keys.name_to_code(n) is not None for n in names)
    rects = [r for k in L.keys for r in k.rects]
    for a, b in itertools.combinations(rects, 2):
        overlap = (a[0] < b[0] + b[2] - 1e-6 and b[0] < a[0] + a[2] - 1e-6
                   and a[1] < b[1] + b[3] - 1e-6 and b[1] < a[1] + a[3] - 1e-6)
        assert not overlap
    assert max(r[0] + r[2] for r in rects) <= L.width + 1e-6


def test_apple_layout_has_fn_and_command():
    L = layouts.build("ansi", "apple")
    n = {k.name for k in L.keys}
    assert {"FN", "LEFTMETA", "RIGHTMETA", "UP", "DOWN"} <= n
    assert "RIGHTCTRL" not in n and "INSERT" not in n
    assert L.apple and L.family == "apple-us"
    assert keys.cap_legend("LEFTMETA", L.family)[1] == "command"
    assert keys.cap_legend("A", L.family)[1] == "A"


def test_jis_hankaku_zenkaku_key_is_grave():
    """xkb: <HZTG> is an alias of <TLDE> - the JIS 半角/全角 key reports KEY_GRAVE, not KEY_ZENKAKUHANKAKU."""
    L = layouts.build("jis", "full")
    assert "GRAVE" in {k.name for k in L.keys} and "ZENKAKUHANKAKU" not in {k.name for k in L.keys}
    assert keys.cap_legend("GRAVE", "jis")[1] == "半/全"
    assert keys.cap_legend("GRAVE", "us")[1] == "`"


def test_zenkaku_output_is_flagged_and_grave_explained():
    note, warn = keys.key_hint("ZENKAKUHANKAKU", "en")
    assert warn and "Grave" in note
    assert keys.key_hint("GRAVE", "ja")[1] is False
    assert keys.key_hint("A") is None


def test_l_shaped_enter_is_inset_like_every_other_key():
    """The outline is shrunk by the key gap (it used to grow, touching its neighbours)."""
    gui = pytest.importorskip("gi")      # the drawing code needs GTK
    gui.require_version("Gtk", "4.0")
    from keyboard_remapper.gui.keyboard import GAP, KeyboardView
    for std in ("jis", "iso"):
        poly = layouts.build(std, "full").by_name()["ENTER"].poly
        pts = KeyboardView._inset_poly(poly, GAP, 0, 0, 1)
        assert min(p[0] for p in pts) > min(p[0] for p in poly)
        assert max(p[0] for p in pts) < max(p[0] for p in poly)
        assert min(p[1] for p in pts) > min(p[1] for p in poly)
        assert max(p[1] for p in pts) < max(p[1] for p in poly)


def _row_names(L, y):
    """Key names of the row at *y*, left to right."""
    return [k.name for k in sorted(L.keys, key=lambda k: k.rects[0][0]) if k.rects[0][1] == y]


@pytest.mark.parametrize("size", ["apple", "apple-num"])
def test_apple_jis_left_column_and_bottom_row(size):
    L = layouts.build("jis", size)
    # bottom row, left to right: Caps Lock, Option, Command, Eisu, Space, Kana, Command (then Fn on the compact one)
    assert _row_names(L, 5.0)[:7] == ["CAPSLOCK", "LEFTALT", "LEFTMETA", "HANJA", "SPACE", "HANGEUL", "RIGHTMETA"]
    if size == "apple":
        assert _row_names(L, 5.0)[7] == "FN"
    # left column, bottom to top: Caps Lock, Shift, Control, Tab
    first = {y: _row_names(L, y)[0] for y in (5.0, 4.0, 3.0, 2.0)}
    assert first == {5.0: "CAPSLOCK", 4.0: "LEFTSHIFT", 3.0: "LEFTCTRL", 2.0: "TAB"}
    assert [k.name for k in L.keys].count("CAPSLOCK") == 1


@pytest.mark.parametrize("standard", ["ansi", "iso"])
def test_other_apple_layouts_keep_fn_first_and_caps_in_place(standard):
    """Only the Apple JIS layout got the new order."""
    L = layouts.build(standard, "apple")
    assert _row_names(L, 5.0)[:4] == ["FN", "LEFTCTRL", "LEFTALT", "LEFTMETA"]
    assert _row_names(L, 3.0)[0] == "CAPSLOCK"


@pytest.mark.parametrize("standard,size", [("ansi", "full"), ("iso", "full"), ("jis", "full"), ("jis", "tkl")])
def test_non_apple_layouts_keep_caps_lock_on_the_home_row(standard, size):
    L = layouts.build(standard, size)
    assert _row_names(L, 3.5)[0] == "CAPSLOCK"
    assert "FN" not in {k.name for k in L.keys}


def _by(L, name):
    return L.by_name()[name]


def test_apple_us_geometry_matches_the_real_keyboard():
    """Measured from a photo of the 2021 US Magic Keyboard: 14.5 key units wide."""
    L = layouts.build("ansi", "apple")
    assert L.width == 14.5
    w = lambda n: _by(L, n).rects[0][2]
    assert (w("ESC"), w("BACKSPACE"), w("TAB"), w("BACKSLASH")) == (1.5, 1.5, 1.5, 1.0)
    assert (w("CAPSLOCK"), w("ENTER"), w("LEFTSHIFT"), w("RIGHTSHIFT")) == (1.75, 1.75, 2.25, 2.25)
    assert _row_names(L, 5.0)[:7] == ["FN", "LEFTCTRL", "LEFTALT", "LEFTMETA", "SPACE", "RIGHTMETA", "RIGHTALT"]
    # every main-block row ends exactly at the right edge
    for y in (0, 1.0, 2.0, 3.0, 4.0):
        assert max(r[0] + r[2] for k in L.keys for r in k.rects if r[1] == y and r[0] < 14.6) == 14.5


@pytest.mark.parametrize("size", ["apple"])
def test_apple_jis_geometry_matches_the_photographed_keyboard(size):
    """Measured from a photo of the 2015 JIS Magic Keyboard (key pitch = 1 unit; 14.5 units wide)."""
    L = layouts.build("jis", size)
    assert L.width == 14.5
    w = lambda n: _by(L, n).rects[0][2]
    x = lambda n: _by(L, n).rects[0][0]
    assert (w("ESC"), w("1"), w("TAB"), w("BACKSPACE")) == (1.0, 1.5, 1.0, 1.0)     # Tab as wide as Q
    assert w("TAB") == w("Q") and x("Q") == 1.0
    assert (w("LEFTCTRL"), w("LEFTSHIFT"), w("RIGHTSHIFT")) == (1.25, 1.75, 1.75)
    assert x("2") == 1.5                                                         # "1" fills the Hankaku/Zenkaku slot
    # bottom row: Caps Lock, Option, Command, Eisu, Space, Kana, Command, Fn
    assert [w(n) for n in ("CAPSLOCK", "LEFTALT", "LEFTMETA", "HANJA", "SPACE", "HANGEUL", "RIGHTMETA", "FN")] == \
        [1.0, 1.0, 1.25, 1.25, 3.5, 1.25, 1.25, 1.0]
    names = {k.name for k in L.keys}
    assert "GRAVE" not in names and "ZENKAKUHANKAKU" not in names
    enter = _by(L, "ENTER")
    assert [r[0] for r in enter.rects] == [13.0, 13.25]                          # L shape: upper 1.5, lower 1.25
    for y in (0, 1.0, 2.0, 3.0, 4.0, 5.0):                                       # the main block ends flush
        assert max(r[0] + r[2] for k in L.keys for r in k.rects if r[1] == y and r[0] < 14.6) == 14.5


@pytest.mark.parametrize("standard", layouts.STANDARDS)
def test_top_right_key_is_one_cap_for_eject_and_lock(standard):
    eject = keys.name_to_code("EJECTCD")
    for size, code, label in (("apple", eject, "eject/lock"), ("apple-num", eject, "eject/lock")):
        L = layouts.build(standard, size)
        top = next(k for k in L.keys if k.rects[0][1] == 0 and k.name == "EJECTCD")
        assert keys.name_to_code(top.name) == code and top.label == label, (standard, size)


def test_product_ids_map_to_generations_and_all_sizes_exist():
    p = layouts.APPLE_PRODUCT_SIZE
    assert p[0x0267] == "apple" and p[0x026C] == "apple-num"                # 2015 (eject)
    assert p[0x029C] == "apple" and p[0x029A] == "apple"                    # 2021 (Touch ID: no layout of its own)
    assert p[0x029F] == "apple-num"                                         # 2021 numpad (Touch ID)
    assert p[0x0320] == "apple" and p[0x0321] == "apple" and p[0x0322] == "apple-num"   # 2024
    assert set(p.values()) <= set(layouts.SIZE_IDS)
    assert {"apple", "apple-num"} <= set(layouts.SIZE_IDS)                  # ids saved by 1.0.0 stay valid


def test_old_saved_apple_sizes_still_load(tmp_path):
    from keyboard_remapper.config import DeviceConfig
    for size in ("apple", "apple-num"):
        assert DeviceConfig.from_dict({"size": size, "standard": "jis"}).size == size


def test_there_is_no_touch_id_layout_and_old_ids_map_to_the_nearest():
    from keyboard_remapper.config import DeviceConfig
    assert not [s for s in layouts.SIZE_IDS if "touch" in s.lower()]
    assert not [t for pair in layouts.SIZES.values() for t in pair if "touch id" in t.lower()]
    # sizes saved by development builds still load
    assert DeviceConfig.from_dict({"size": "apple-touchid"}).size == "apple"
    assert DeviceConfig.from_dict({"size": "apple-2015-num"}).size == "apple-num"
    assert DeviceConfig.from_dict({"size": "apple-2015"}).size == "apple"
    assert DeviceConfig.from_dict({"size": "nonsense"}).size == "full"


def test_numpad_variants_add_the_keypad_to_the_right():
    L = layouts.build("ansi", "apple-num")
    assert L.width == 18.75 and "KP5" in _by(L, "KP5").name
    assert _by(L, "KPENTER").rects[0][0] == 14.75 + 3


@pytest.mark.parametrize("size", ["apple-num"])
def test_apple_jis_numeric_keyboard_matches_the_photo(size):
    """Numeric-keypad JIS keyboard: Fn / Home / PageUp, Delete / End / PageDown, inverted-T arrows, keypad."""
    L = layouts.build("jis", size)
    assert L.width == 22.0 and L.id == f"jis-{size}"
    w = lambda n: _by(L, n).rects[0][2]
    x = lambda n: _by(L, n).rects[0][0]
    y = lambda n: _by(L, n).rects[0][1]
    # bottom row of the main block: no Fn, no arrows; Option (2) and Control (2) at the right end
    assert _row_names(L, 5.0)[:9] == ["CAPSLOCK", "LEFTALT", "LEFTMETA", "HANJA", "SPACE", "HANGEUL",
                                      "RIGHTMETA", "RIGHTALT", "RIGHTCTRL"]
    assert (w("RIGHTALT"), w("RIGHTCTRL"), x("RIGHTCTRL") + w("RIGHTCTRL")) == (2.0, 2.0, 14.5)
    # navigation cluster under F13-F15
    cols = [14.75, 15.75, 16.75]
    for name, col, row in (("F13", 0, 0), ("F14", 1, 0), ("F15", 2, 0), ("FN", 0, 1.0), ("HOME", 1, 1.0),
                           ("PAGEUP", 2, 1.0), ("DELETE", 0, 2.0), ("END", 1, 2.0), ("PAGEDOWN", 2, 2.0),
                           ("UP", 1, 4.0), ("LEFT", 0, 5.0), ("DOWN", 1, 5.0), ("RIGHT", 2, 5.0)):
        assert (x(name), y(name)) == (cols[col], row), name
    # keypad: F16-F19, then clear = / *, 7 8 9 -, 4 5 6 +, 1 2 3 + tall Enter, 0 . ,
    assert [n for n in ("F16", "F17", "F18", "F19") if n in _row_names(L, 0)] == ["F16", "F17", "F18", "F19"]
    assert _row_names(L, 1.0)[-4:] == ["NUMLOCK", "KPEQUAL", "KPSLASH", "KPASTERISK"]
    assert _row_names(L, 2.0)[-4:] == ["KP7", "KP8", "KP9", "KPMINUS"]
    assert _row_names(L, 3.0)[-4:] == ["KP4", "KP5", "KP6", "KPPLUS"]
    assert _row_names(L, 5.0)[-3:] == ["KP0", "KPDOT", "KPJPCOMMA"]
    enter = _by(L, "KPENTER").rects[0]
    assert enter[1] == 4.0 and enter[3] == 2 and enter[0] + enter[2] == 22.0


def _top_edge(L, name):
    return _by(L, name).rects[0][1]


@pytest.mark.parametrize("standard", layouts.STANDARDS)
@pytest.mark.parametrize("size", layouts.APPLE_SIZES)
def test_apple_function_row_sits_flush_on_the_number_row(standard, size):
    """No gap between Esc/F1... and the number row on a Magic Keyboard (rows are 1 unit apart, height 6)."""
    L = layouts.build(standard, size)
    assert _top_edge(L, "ESC") == 0 and _top_edge(L, "F1") == 0
    number_row = _top_edge(L, "2")
    assert number_row == 1.0                       # directly under the 1-unit-high function row
    assert L.height == 6.0
    assert max(r[1] + r[3] for k in L.keys for r in k.rects) <= L.height


@pytest.mark.parametrize("standard,size", [("ansi", "full"), ("iso", "full"), ("jis", "full"), ("jis", "tkl")])
def test_non_apple_keyboards_keep_the_gap_below_the_function_row(standard, size):
    L = layouts.build(standard, size)
    assert _top_edge(L, "F1") == 0 and _top_edge(L, "2") == 1.5 and L.height == 6.5


def test_lock_key_is_drawn_on_the_eject_cap():
    """Newer Apple keyboards have a Lock key (KEY_COFFEE) where older ones have Eject: one cap for both."""
    assert keys.DISPLAY_ALIASES["COFFEE"] == "EJECTCD"
    for size in layouts.APPLE_SIZES:
        assert "EJECTCD" in layouts.build("ansi", size).by_name() and "COFFEE" not in layouts.build("ansi", size).by_name()
    assert "COFFEE" not in layouts.build("ansi", "full").by_name()      # other keyboards: no alias in play
