"""Reusable widgets: key chips, the key recorder and the key chooser popover."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import keys  # noqa: E402
from ..i18n import LANG, T  # noqa: E402
from .compat import set_placeholder  # noqa: E402


def chip(text: str, accent: bool = False, big: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.add_css_class("keychip")
    if accent:
        lbl.add_css_class("accent")
    if big:
        lbl.add_css_class("big")
    lbl.set_valign(Gtk.Align.CENTER)
    return lbl


def chord_box(specs, accent: bool = False, big: bool = False, empty_text: str = "") -> Gtk.Box:
    box = Gtk.Box(spacing=4)
    box.set_valign(Gtk.Align.CENTER)
    if not specs:
        if empty_text:
            l = Gtk.Label(label=empty_text)
            l.add_css_class("dim")
            box.append(l)
        return box
    for i, s in enumerate(specs):
        if i:
            plus = Gtk.Label(label="+")
            plus.add_css_class("chip-plus")
            box.append(plus)
        box.append(chip(keys.key_name(s, LANG), accent, big))
    return box


def short_chord(specs) -> str:
    """Compact text for keycap overlays."""
    names = []
    for s in specs:
        n = keys.normalize_name(s) or s
        if n in keys.GENERIC_MODIFIERS or n.endswith(("CTRL", "SHIFT", "ALT", "META")) or n == "FN":
            names.append({"CTRL": "Ctrl", "SHIFT": "Shift", "ALT": "Alt", "META": "Super", "FN": "fn"}[
                keys.generic_of(keys.name_to_code(n)) if n not in keys.GENERIC_MODIFIERS else n])
        else:
            top, main = keys.cap_legend(n, "us", LANG)
            names.append(main or top or keys.key_name(n, LANG))
    return "+".join(names)


# --------------------------------------------------------------------------
# recorder
# --------------------------------------------------------------------------

def trigger_from_codes(codes: list[int]) -> tuple[str, ...]:
    """Held keys (modifiers generic) followed by the last-pressed key."""
    if len(codes) == 1:
        return (keys.code_to_name(codes[0]),)
    if all(keys.is_modifier(c) for c in codes):        # modifier-only chord: keep the exact keys
        return tuple(dict.fromkeys(keys.code_to_name(c) for c in codes))
    out = []
    for c in codes[:-1]:
        g = keys.generic_of(c)
        out.append(g if g else keys.code_to_name(c))
    out.append(keys.code_to_name(codes[-1]))
    # de-duplicate (Ctrl left+right)
    seen, res = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            res.append(n)
    return tuple(res)


def output_from_codes(codes: list[int]) -> tuple[str, ...]:
    if len(codes) == 1:
        return (keys.code_to_name(codes[0]),)
    mods = [keys.generic_of(c) for c in codes if keys.generic_of(c)]
    rest = [keys.code_to_name(c) for c in codes if not keys.generic_of(c)]
    seen, out = set(), []
    for n in mods + rest:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return tuple(out)


class Recorder:
    """Collects one key combination: finishes when the first key is released."""

    TIMEOUT_S = 12

    def __init__(self, window):
        self.win = window
        self.active = False
        self.seq: list[int] = []
        self.down: set[int] = set()
        self._on_done: Callable | None = None
        self._on_progress: Callable | None = None
        self._timer = 0

    def start(self, on_done: Callable[[list[int]], None],
              on_progress: Callable[[list[int]], None] | None = None) -> None:
        self.cancel()
        self.active = True
        self.seq, self.down = [], set()
        self._on_done, self._on_progress = on_done, on_progress
        self.win.capture_keys(True)
        self._timer = GLib.timeout_add_seconds(self.TIMEOUT_S, self._timeout)

    def _timeout(self) -> bool:
        self._timer = 0
        self.cancel(notify=True)
        return False

    def cancel(self, notify: bool = False) -> None:
        if not self.active:
            return
        self.active = False
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self.win.capture_keys(False)
        cb = self._on_done
        self._on_done = self._on_progress = None
        if notify and cb:
            cb([])

    def feed(self, code: int, value: int) -> None:
        if not self.active or value == 2:
            return
        if value == 1:
            if code not in self.seq:
                self.seq.append(code)
            self.down.add(code)
            if self._on_progress:
                self._on_progress(list(self.seq))
        elif value == 0 and self.seq:
            result = [c for c in self.seq]
            cb = self._on_done
            self.active = False
            if self._timer:
                GLib.source_remove(self._timer)
                self._timer = 0
            self.win.capture_keys(False)
            self._on_done = self._on_progress = None
            if cb:
                cb(result)


# --------------------------------------------------------------------------
# key chooser popover
# --------------------------------------------------------------------------

class KeyChooserPanel(Gtk.Box):
    """Pick modifiers + one key from a searchable list, or press them.

    ``on_change(chord, final)``: *final* is True once the user made a definite pick (a key chosen
    from the list, or a recorded combination) - the host may close / collapse the panel then.
    """

    def __init__(self, window, chord: tuple[str, ...], on_change: Callable[[tuple[str, ...], bool], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.win = window
        self.on_change = on_change
        self.mods: list[str] = []
        self.main: list[str] = []
        self._load(chord)
        box = self

        self.rec_btn = Gtk.Button()
        self.rec_btn.add_css_class("suggested-action")
        self.rec_btn.connect("clicked", self._toggle_record)
        self._set_rec_label(False)
        box.append(self.rec_btn)

        sep = Gtk.Box(spacing=8)
        l1, l2 = Gtk.Separator(), Gtk.Separator()
        l1.set_hexpand(True)
        l2.set_hexpand(True)
        l1.set_valign(Gtk.Align.CENTER)
        l2.set_valign(Gtk.Align.CENTER)
        mid = Gtk.Label(label=T("または一覧から選ぶ", "or choose from the list"))
        mid.add_css_class("dim")
        mid.add_css_class("caption")
        sep.append(l1)
        sep.append(mid)
        sep.append(l2)
        box.append(sep)

        modrow = Gtk.Box(spacing=6, homogeneous=True)
        self._mod_btns: dict[str, Gtk.ToggleButton] = {}
        for g, label in (("CTRL", "Ctrl"), ("SHIFT", "Shift"), ("ALT", "Alt"), ("META", "Super")):
            b = Gtk.ToggleButton(label=label)
            b.set_active(g in self.mods)
            b.connect("toggled", self._mod_toggled, g)
            self._mod_btns[g] = b
            modrow.append(b)
        box.append(modrow)

        self.search = Gtk.SearchEntry()
        set_placeholder(self.search, T("キーを検索 (例: Enter, 変換, F5, 音量)", "Search keys (e.g. Enter, F5, volume)"))
        self.search.connect("search-changed", lambda *_: self.list.invalidate_filter())
        box.append(self.search)

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list.add_css_class("picker-list")
        self.list.set_filter_func(self._filter)
        self.list.connect("row-activated", self._row_activated)
        self._rows: list[tuple[Gtk.ListBoxRow, str | None, str]] = []
        self._build_rows()
        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(200)
        sw.set_max_content_height(200)
        sw.set_child(self.list)
        sw.set_propagate_natural_height(True)
        box.append(sw)
        self._counted = False
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def _on_map(self, *_) -> None:
        if not self._counted:
            self._counted = True
            self.win.modal_open += 1
        GLib.idle_add(self._focus_search)

    def _on_unmap(self, *_) -> None:
        self._stop_record()
        if self._counted:
            self._counted = False
            self.win.modal_open = max(0, self.win.modal_open - 1)

    def _focus_search(self):
        self.search.grab_focus()
        return False

    # -- model -----------------------------------------------------------

    def _load(self, chord) -> None:
        for n in chord:
            g = n if n in keys.GENERIC_MODIFIERS else keys.generic_of(keys.name_to_code(n) or -1)
            if g:
                if g not in self.mods:
                    self.mods.append(g)
            else:
                self.main.append(n)

    def chord(self) -> tuple[str, ...]:
        order = {g: i for i, g in enumerate(keys.GENERIC_ORDER)}
        mods = sorted(self.mods, key=lambda g: order[g])
        if not self.main and len(mods) == 1:
            return (mods[0],)
        return tuple(mods + self.main)

    def _emit(self, final: bool = False) -> None:
        self.on_change(self.chord(), final)

    def _mod_toggled(self, btn, g) -> None:
        if btn.get_active() and g not in self.mods:
            self.mods.append(g)
        elif not btn.get_active() and g in self.mods:
            self.mods.remove(g)
        self._emit()

    # -- list --------------------------------------------------------------

    def _build_rows(self) -> None:
        from ..keys import CATEGORIES, CATEGORY_TITLES_JA
        for cid, title, names in CATEGORIES:
            hdr = Gtk.ListBoxRow()
            hdr.set_activatable(False)
            hdr.set_selectable(False)
            lbl = Gtk.Label(label=CATEGORY_TITLES_JA[cid] if LANG == "ja" else title, xalign=0)
            lbl.add_css_class("picker-header")
            hdr.set_child(lbl)
            self.list.append(hdr)
            self._rows.append((hdr, None, cid))
            for n in names:
                row = Gtk.ListBoxRow()
                row.key_name = n
                b = Gtk.Box(spacing=8)
                a = Gtk.Label(label=keys.key_name(n, LANG), xalign=0)
                a.set_hexpand(True)
                b.append(a)
                other = keys.key_name(n, "en" if LANG == "ja" else "ja")
                if other != keys.key_name(n, LANG):
                    o = Gtk.Label(label=other, xalign=1)
                    o.add_css_class("dim")
                    o.add_css_class("caption")
                    b.append(o)
                hint = keys.key_hint(n, LANG)
                if hint:
                    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                    v.append(b)
                    hl = Gtk.Label(label=hint[0], xalign=0, wrap=True)
                    hl.add_css_class("caption")
                    hl.add_css_class("warning" if hint[1] else "dim")
                    v.append(hl)
                    row.set_child(v)
                else:
                    row.set_child(b)
                self.list.append(row)
                self._rows.append((row, n, cid))

    def _filter(self, row) -> bool:
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        info = next((r for r in self._rows if r[0] is row), None)
        if info is None:
            return True
        _, name, cid = info
        if name is None:
            # show a category header only when some of its keys match
            return any(self._matches(n, q) for _, n, c in self._rows if c == cid and n)
        return self._matches(name, q)

    @staticmethod
    def _matches(name: str, q: str) -> bool:
        hay = " ".join([name, keys.key_name(name, "en"), keys.key_name(name, "ja")]).lower()
        return q in hay

    def _row_activated(self, lb, row) -> None:
        n = getattr(row, "key_name", None)
        if not n:
            return
        g = keys.generic_of(keys.name_to_code(n))
        if g in self._mod_btns:                 # a modifier picked from the list toggles it
            self._mod_btns[g].set_active(not self._mod_btns[g].get_active())
            return
        self.main = [n]
        self._emit(True)

    # -- recording -----------------------------------------------------------

    def _set_rec_label(self, recording: bool, seq=None) -> None:
        if recording:
            txt = T("キーを押してください…", "Press the keys…")
            if seq:
                txt = " + ".join(keys.key_name(keys.code_to_name(c), LANG) for c in seq)
            self.rec_btn.set_label("⏺  " + txt)
        else:
            self.rec_btn.set_label("⏺  " + T("キーを押して指定", "Press keys to set"))

    def _toggle_record(self, *_) -> None:
        if self.win.recorder.active:
            self._stop_record()
            return
        self._set_rec_label(True)
        self.win.recorder.start(self._recorded, lambda seq: self._set_rec_label(True, seq))

    def _stop_record(self) -> None:
        self.win.recorder.cancel()
        self._set_rec_label(False)

    def _recorded(self, codes: list[int]) -> None:
        self._set_rec_label(False)
        if not codes:
            return
        out = output_from_codes(codes)
        self.mods, self.main = [], []
        self._load(out)
        for g, b in self._mod_btns.items():
            b.handler_block_by_func(self._mod_toggled)
            b.set_active(g in self.mods)
            b.handler_unblock_by_func(self._mod_toggled)
        self._emit(True)


class KeyChooser(Gtk.Popover):
    """A :class:`KeyChooserPanel` in a popover.  Calls *on_change(tuple_of_names)*."""

    def __init__(self, window, chord: tuple[str, ...], on_change: Callable[[tuple[str, ...]], None]):
        super().__init__()
        self.set_autohide(True)

        def changed(chord, final):
            on_change(chord)
            if final:
                self.popdown()

        self.panel = KeyChooserPanel(window, chord, changed)
        self.panel.set_margin_top(12)
        self.panel.set_margin_bottom(12)
        self.panel.set_margin_start(12)
        self.panel.set_margin_end(12)
        self.panel.set_size_request(340, -1)
        self.set_child(self.panel)


class ChordButton(Gtk.MenuButton):
    """Shows a key combination as chips; click to change it."""

    def __init__(self, window, chord: tuple[str, ...], on_change: Callable[[tuple[str, ...]], None],
                 empty_text: str | None = None, big: bool = True):
        super().__init__()
        self.win = window
        self.chord = tuple(chord)
        self._user_cb = on_change
        self.add_css_class("chord-button")
        self.set_tooltip_text(T("クリックして変更", "Click to change"))
        self._big = big
        self._empty = empty_text if empty_text is not None else T("キーを選択…", "Choose a key…")
        self._render()
        self._popover: KeyChooser | None = None
        self.set_create_popup_func(self._create_popup)

    def _render(self) -> None:
        inner = Gtk.Box(spacing=8)
        inner.append(chord_box(self.chord, accent=True, big=self._big, empty_text=self._empty))
        icon = Gtk.Image.new_from_icon_name("document-edit-symbolic")
        icon.add_css_class("dim")
        inner.append(icon)
        self.set_child(inner)

    def _create_popup(self, *_) -> None:
        pop = KeyChooser(self.win, self.chord, self._changed)
        self._popover = pop
        self.set_popover(pop)

    def _changed(self, chord) -> None:
        self.chord = tuple(chord)
        self._render()
        self._user_cb(self.chord)

    def open(self) -> None:
        self.popup()
