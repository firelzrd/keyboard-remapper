"""The assignment editor card shown under the keyboard."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk  # noqa: E402

from .. import keys  # noqa: E402
from ..i18n import LANG, T  # noqa: E402
from ..mapping import (ACTION_DISABLE, ACTION_KEY, ACTION_SEQUENCE, Action, Mapping,  # noqa: E402
                       MappingError, is_chord_tap, parse_step)
from .widgets import ChordButton, KeyChooserPanel, chord_box, trigger_from_codes  # noqa: E402


class StepRow(Gtk.Box):
    """One step of a sequence: a key combination or a pause."""

    def __init__(self, window, step: str, on_change: Callable[[str], None], on_remove: Callable[[], None]):
        super().__init__(spacing=8)
        self.add_css_class("step-row")
        kind, arg = parse_step(step)
        if kind == "wait":
            l = Gtk.Label(label=T("待機", "Wait"))
            l.add_css_class("dim")
            l.set_width_chars(5)
            l.set_xalign(0)
            self.append(l)
            spin = Gtk.SpinButton.new_with_range(0, 10000, 10)
            spin.set_value(arg)
            spin.connect("value-changed", lambda s: on_change(f"wait {int(s.get_value())}"))
            self.append(spin)
            self.append(Gtk.Label(label="ms"))
        else:
            l = Gtk.Label(label=T("入力", "Press"))
            l.add_css_class("dim")
            l.set_width_chars(5)
            l.set_xalign(0)
            self.append(l)
            btn = ChordButton(window, arg, lambda c: on_change("+".join(c)), big=False)
            self.append(btn)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.append(spacer)
        rm = Gtk.Button(icon_name="edit-delete-symbolic")
        rm.add_css_class("flat")
        rm.set_tooltip_text(T("この手順を削除", "Remove this step"))
        rm.connect("clicked", lambda *_: on_remove())
        self.append(rm)


class Editor(Gtk.Box):
    def __init__(self, window, on_set: Callable[[Mapping], None], on_delete: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.win = window
        self.on_set = on_set
        self.on_delete = on_delete
        self.add_css_class("editor-card")
        self.trigger: tuple[str, ...] = ()
        self.mapping: Mapping | None = None
        self.draft = False          # key action chosen, output not picked yet (nothing saved)
        self._rebuild()

    # -- public ------------------------------------------------------------

    def show_trigger(self, trigger: tuple[str, ...], mapping: Mapping | None, keep_open: bool = False) -> None:
        self.trigger = tuple(trigger)
        self.mapping = mapping
        self.draft = False
        self._rebuild()

    # -- construction ------------------------------------------------------------

    def _clear(self) -> None:
        child = self.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.remove(child)
            child = nxt

    def _rebuild(self) -> None:
        self._clear()
        if not self.trigger:
            self._build_empty()
            return
        self._build_header()
        if self.mapping is None:
            self._build_unassigned()
        else:
            self._build_assigned()

    def _build_empty(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("empty-hint")
        box.set_halign(Gtk.Align.CENTER)
        t = Gtk.Label(label=T("割り当てるキーを選びましょう", "Pick a key to remap"))
        t.add_css_class("title-4")
        s = Gtk.Label(label=T("画面のキーをクリックするか、実際にキーを押してください。\n"
                              "Ctrl などを押したまま、または上の修飾キーを選ぶと、組み合わせを割り当てられます。",
                              "Click a key above, or press a key on your keyboard.\n"
                              "Hold Ctrl etc. (or pick a modifier above) to map a shortcut."))
        s.add_css_class("dim")
        s.set_justify(Gtk.Justification.CENTER)
        box.append(t)
        box.append(s)
        self.append(box)

    def _build_header(self) -> None:
        row = Gtk.Box(spacing=10)
        lbl = Gtk.Label(label=T("このキーを押すと", "When you press"))
        lbl.add_css_class("dim")
        row.append(lbl)
        row.append(chord_box(self.trigger, accent=False, big=True))
        sp = Gtk.Box()
        sp.set_hexpand(True)
        row.append(sp)
        self.rec_btn = Gtk.Button(label="⏺  " + T("キーを押して変更", "Change by pressing keys"))
        self.rec_btn.add_css_class("flat")
        self.rec_btn.connect("clicked", self._record_trigger)
        row.append(self.rec_btn)
        self.append(row)

    def _record_trigger(self, *_) -> None:
        rec = self.win.recorder
        if rec.active:
            rec.cancel(notify=True)
            return
        self.rec_btn.set_label("⏺  " + T("キーを押してください…", "Press the keys…"))
        self.rec_btn.add_css_class("recording")

        def prog(seq):
            self.rec_btn.set_label("⏺  " + " + ".join(keys.key_name(keys.code_to_name(c), LANG) for c in seq))

        def done(codes):
            self.rec_btn.remove_css_class("recording")
            self.rec_btn.set_label("⏺  " + T("キーを押して変更", "Change by pressing keys"))
            if codes:
                self.win.select_trigger(trigger_from_codes(codes))

        rec.start(done, prog)

    def _build_unassigned(self) -> None:
        msg = Gtk.Label(label=T("まだ割り当てていません。今は、そのままのキー入力になります。",
                                "Not remapped yet — the key currently types normally."), xalign=0)
        msg.add_css_class("dim")
        self.append(msg)
        row = Gtk.Box(spacing=8)
        for kind, label, icon in (
            (ACTION_KEY, T("別のキー/ショートカットにする", "Remap to a key / shortcut"), "input-keyboard-symbolic"),
            (ACTION_SEQUENCE, T("連続入力にする", "Run a sequence"), "view-list-symbolic"),
            (ACTION_DISABLE, T("無効にする", "Disable"), "action-unavailable-symbolic"),
        ):
            b = Gtk.Button()
            inner = Gtk.Box(spacing=6)
            inner.append(Gtk.Image.new_from_icon_name(icon))
            inner.append(Gtk.Label(label=label))
            b.set_child(inner)
            if kind == ACTION_KEY:
                b.add_css_class("suggested-action")
            b.connect("clicked", self._create, kind)
            row.append(b)
        self.append(row)

    def _create(self, _btn, kind: str) -> None:
        if kind == ACTION_KEY:
            # nothing is saved until the user actually picks an output
            self.draft = True
            self.mapping = Mapping(self.trigger, Action(ACTION_KEY, output=()))
            self._rebuild()
        elif kind == ACTION_SEQUENCE:
            self.on_set(Mapping(self.trigger, Action(ACTION_SEQUENCE, steps=("wait 0",))))
        else:
            self.on_set(Mapping(self.trigger, Action(ACTION_DISABLE)))

    def _build_assigned(self) -> None:
        m = self.mapping
        seg = Gtk.Box(spacing=0)
        seg.add_css_class("linked")
        seg.set_halign(Gtk.Align.START)
        first = None
        for kind, label in ((ACTION_KEY, T("キー/ショートカット", "Key / shortcut")),
                            (ACTION_SEQUENCE, T("連続入力", "Sequence")),
                            (ACTION_DISABLE, T("無効", "Disabled"))):
            b = Gtk.ToggleButton(label=label)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.set_active(m.action.type == kind)
            b.connect("toggled", self._type_toggled, kind)
            seg.append(b)
        self.append(seg)

        if m.action.type == ACTION_KEY:
            self._build_key_action(m)
        elif m.action.type == ACTION_SEQUENCE:
            self._build_sequence(m)
        else:
            t = Gtk.Label(label=T("このキーを押しても何も入力されません。", "Pressing this key does nothing."), xalign=0)
            t.add_css_class("dim")
            self.append(t)
        self.append(self._summary(m))
        self.summary.set_visible(not self.draft)

        foot = Gtk.Box(spacing=8)
        hint = Gtk.Label(label=T("変更は自動で保存され、すぐに反映されます。", "Changes are saved and applied automatically."),
                         xalign=0)
        hint.add_css_class("dim")
        hint.add_css_class("caption")
        hint.set_hexpand(True)
        foot.append(hint)
        d = Gtk.Button(label=T("割り当てを削除", "Remove mapping"))
        d.add_css_class("flat")
        d.get_child().add_css_class("error")
        d.connect("clicked", lambda *_: self.on_delete())
        d.set_visible(not self.draft)
        self.del_btn = d
        foot.append(d)
        self.append(foot)

    def _type_toggled(self, btn, kind: str) -> None:
        if not btn.get_active() or self.mapping is None or self.mapping.action.type == kind:
            return
        self.draft = False
        old = self.mapping.action
        if kind == ACTION_KEY:
            out = old.output or (self.trigger[-1],)
            act = Action(ACTION_KEY, output=out)
        elif kind == ACTION_SEQUENCE:
            steps = ("+".join(old.output),) if old.type == ACTION_KEY and old.output else ("wait 0",)
            act = Action(ACTION_SEQUENCE, steps=steps)
        else:
            act = Action(ACTION_DISABLE)
        self.on_set(Mapping(self.trigger, act))

    def _build_key_action(self, m: Mapping) -> None:
        row = Gtk.Box(spacing=10)
        lbl = Gtk.Label(label=T("入力されるキー", "Types"))
        lbl.add_css_class("dim")
        row.append(lbl)
        # the chip row doubles as the "change" toggle for the chooser panel below it
        self.out_btn = Gtk.ToggleButton()
        self.out_btn.add_css_class("chord-button")
        self.out_btn.set_tooltip_text(T("クリックして変更", "Click to change"))
        self._render_out(m.action.output)
        row.append(self.out_btn)
        self.append(row)

        self.warn = Gtk.Label(xalign=0, wrap=True)           # "this output key will not work" notes
        self.warn.add_css_class("warning")
        self.append(self.warn)
        self._update_warning(m.action.output)

        self.chooser_rev = Gtk.Revealer()
        self.chooser_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.panel = KeyChooserPanel(self.win, m.action.output, self._panel_changed)
        frame = Gtk.Frame()
        frame.set_child(self.panel)
        self.panel.set_margin_top(10)
        self.panel.set_margin_bottom(10)
        self.panel.set_margin_start(10)
        self.panel.set_margin_end(10)
        self.chooser_rev.set_child(frame)
        self.out_btn.bind_property("active", self.chooser_rev, "reveal-child",
                                   GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        # a new mapping has no output yet: show the chooser straight away
        self.out_btn.set_active(self.draft or not m.action.output)
        self.out_btn.connect("toggled", lambda b: b.get_active() and self.win.scroll_to_end())
        if self.out_btn.get_active():
            self.win.scroll_to_end()
        self.append(self.chooser_rev)

    def _render_out(self, chord) -> None:
        inner = Gtk.Box(spacing=8)
        inner.append(chord_box(chord, accent=True, big=True, empty_text=T("キーを選択…", "Choose a key…")))
        icon = Gtk.Image.new_from_icon_name("pan-down-symbolic")
        icon.add_css_class("dim")
        inner.append(icon)
        self.out_btn.set_child(inner)

    def _update_warning(self, chord) -> None:
        notes = [h[0] for n in chord if (h := keys.key_hint(n, LANG)) and h[1]]
        self.warn.set_label("⚠ " + notes[0] if notes else "")
        self.warn.set_visible(bool(notes))

    def _panel_changed(self, chord, final: bool) -> None:
        self._update_warning(chord)
        self._render_out(chord)
        self._output_changed(chord)
        if final:
            self.out_btn.set_active(False)

    def _output_changed(self, chord) -> None:
        if not chord:
            return
        if self.draft:
            self.draft = False
            self.summary.set_visible(True)
            self.del_btn.set_visible(True)
        self.on_set(Mapping(self.trigger, Action(ACTION_KEY, output=tuple(chord))), rebuild=False)

    def _build_sequence(self, m: Mapping) -> None:
        steps = list(m.action.steps)
        lbl = Gtk.Label(label=T("順番に実行する手順", "Steps, run in order"), xalign=0)
        lbl.add_css_class("dim")
        self.append(lbl)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for i, s in enumerate(steps):
            box.append(StepRow(self.win, s,
                               lambda new, i=i: self._step_changed(i, new),
                               lambda i=i: self._step_removed(i)))
        self.append(box)
        add = Gtk.Box(spacing=8)
        b1 = Gtk.Button(label="＋ " + T("キー入力を追加", "Add key press"))
        b1.connect("clicked", lambda *_: self._step_added("A"))
        b2 = Gtk.Button(label="＋ " + T("待機を追加", "Add pause"))
        b2.connect("clicked", lambda *_: self._step_added("wait 100"))
        add.append(b1)
        add.append(b2)
        self.append(add)

    def _set_steps(self, steps, rebuild=True) -> None:
        steps = [s for s in steps]
        if not steps:
            steps = ["wait 0"]
        try:
            for s in steps:
                parse_step(s)
        except MappingError:
            return
        self.on_set(Mapping(self.trigger, Action(ACTION_SEQUENCE, steps=tuple(steps))), rebuild=rebuild)

    def _step_changed(self, i: int, new: str) -> None:
        steps = list(self.mapping.action.steps)
        steps[i] = new
        self._set_steps(steps, rebuild=False)

    def _step_removed(self, i: int) -> None:
        steps = list(self.mapping.action.steps)
        del steps[i]
        self._set_steps(steps)

    def _step_added(self, step: str) -> None:
        steps = [s for s in self.mapping.action.steps if s != "wait 0"] + [step]
        self._set_steps(steps)

    def _summary(self, m: Mapping) -> Gtk.Widget:
        trig = keys.chord_name(m.trigger, LANG)
        if is_chord_tap(m.trigger):
            if m.action.type == ACTION_KEY:
                what = keys.chord_name(m.action.output, LANG)
                txt = T(f"→ {trig} を同時に押して、他のキーを押さずに離すと、{what} が入力されます。",
                        f"→ Pressing {trig} together and releasing them without any other key types {what}.")
            else:
                txt = T(f"→ {trig} を同時に押して、他のキーを押さずに離すと実行されます。",
                        f"→ Runs when {trig} are pressed together and released without any other key.")
        elif m.action.type == ACTION_KEY:
            what = keys.chord_name(m.action.output, LANG)
            txt = T(f"→ {trig} を押すと、{what} が入力されます。", f"→ Pressing {trig} types {what}.")
        elif m.action.type == ACTION_SEQUENCE:
            txt = T(f"→ {trig} を押すと、{len(m.action.steps)} 個の手順を順に実行します。",
                    f"→ Pressing {trig} runs {len(m.action.steps)} steps in order.")
        else:
            txt = T(f"→ {trig} は無効になります。", f"→ {trig} is disabled.")
        l = Gtk.Label(label=txt, xalign=0)
        l.add_css_class("summary-line")
        l.set_wrap(True)
        self.summary = l
        return l

    def refresh_summary(self) -> None:
        """Update only the sentence (keeps open popovers alive while editing)."""
        if self.mapping is not None and getattr(self, "summary", None) is not None:
            self.summary.set_label(self._summary(self.mapping).get_label())
