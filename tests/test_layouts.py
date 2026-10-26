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
    assert {"FN", "LEFTMETA", "RIGHTMETA", "EJECTCD", "UP", "DOWN"} <= n
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
