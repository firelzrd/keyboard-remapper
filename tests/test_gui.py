"""GUI tests: a real window on a virtual display talking to an in-process fake daemon.

Run with:  xvfb-run -a dbus-run-session -- python3.12 -m pytest tests/test_gui.py
"""

import asyncio
import json
import os
import threading
import time

import pytest

if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    pytest.skip("needs a display (use xvfb-run)", allow_module_level=True)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from keyboard_remapper import keys  # noqa: E402
from keyboard_remapper.backend import FakeBackend, fake_keyboard  # noqa: E402
from keyboard_remapper.config import Config  # noqa: E402
from keyboard_remapper.daemon import Daemon  # noqa: E402
from keyboard_remapper.gui.app import App  # noqa: E402
from keyboard_remapper.mapping import Action, Mapping  # noqa: E402


class DaemonThread:
    def __init__(self, tmp):
        self.sock = str(tmp / "s.sock")
        self.backend = FakeBackend(fake_keyboard(0))
        self.daemon = None
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(self.loop)
            self.daemon = Daemon(self.backend, state_path=str(tmp / "state.json"),
                                 socket_path=self.sock, check_peer=False)
            self.loop.run_until_complete(self.daemon.start())
            ready.set()
            self.loop.run_forever()

        self.t = threading.Thread(target=run, daemon=True)
        self.t.start()
        assert ready.wait(5)

    def call(self, fn):
        done = threading.Event()
        box = []

        def w():
            box.append(fn())
            done.set()

        self.loop.call_soon_threadsafe(w)
        assert done.wait(5)
        return box[0]

    def stop(self):
        fut = asyncio.run_coroutine_threadsafe(self.daemon.stop(), self.loop)
        fut.result(3)
        self.loop.call_soon_threadsafe(self.loop.stop)


def pump(seconds=0.3):
    ctx = GLib.MainContext.default()
    end = time.time() + seconds
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)


_APP = []


def _app():
    if not _APP:
        app = App("/nonexistent")
        app.register(None)
        _APP.append(app)
    return _APP[0]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    d = DaemonThread(tmp_path)
    app = _app()
    app.socket_path = d.sock
    app.win = None
    app.activate()
    pump(0.8)
    win = app.win
    yield win, d, tmp_path
    win.config.save()
    win.link.client.close()
    win.destroy()
    app.win = None
    pump(0.1)
    if d.loop.is_running():
        d.stop()


def test_device_listed_and_empty_editor(env):
    win, d, _ = env
    assert win.model == "1234:5678"
    assert win.stack.get_visible_child_name() == "main"
    assert win.banner.get_revealed() is False


def test_click_key_selects_and_layer_changes_trigger(env):
    win, d, _ = env
    win.on_key_clicked("J")
    assert win.trigger == ("J",)
    win.layer_btns["CTRL"].set_active(True)
    assert win.trigger == ("CTRL", "J")
    win.layer_btns["CTRL"].set_active(False)
    assert win.trigger == ("J",)


def test_create_mapping_autosaves_and_applies(env):
    win, d, tmp = env
    win.layer_btns["CTRL"].set_active(True)
    win.on_key_clicked("J")
    win.set_mapping(Mapping(("CTRL", "J"), Action("key", output=("DOWN",))))
    assert win.keyboard.assignments.get("J")           # shown on the keycap
    pump(0.8)
    # persisted
    assert os.path.exists(win.config.path)
    assert Config(win.config.path).devices["1234:5678"].preset.find(("CTRL", "J"))
    # applied in the daemon (and the keyboard grabbed)
    assert d.call(lambda: d.daemon.presets.get("1234:5678")) is not None
    pump(0.3)
    assert d.backend.inputs["/dev/input/fake0a"].grabbed
    # status pill
    assert win.status_pill.get_label() in ("適用中", "Active")
    # end-to-end: ctrl + J on the physical keyboard becomes Down
    h = d.backend.inputs["/dev/input/fake0a"]
    d.call(lambda: [h.inject(keys.name_to_code("LEFTCTRL"), 1), h.inject(keys.name_to_code("J"), 1)])
    out = d.call(lambda: [(keys.code_to_name(c), v) for c, v in d.backend.outputs[0].log])
    assert out == [("LEFTCTRL", 1), ("LEFTCTRL", 0), ("DOWN", 1)]


def test_delete_with_undo(env):
    win, d, _ = env
    win.on_key_clicked("A")
    win.set_mapping(Mapping(("A",), Action("key", output=("B",))))
    win.delete_mapping()
    assert win.cfg().preset.find(("A",)) is None
    win._undo_delete(Mapping(("A",), Action("key", output=("B",))))
    assert win.cfg().preset.find(("A",)) is not None


def test_physical_key_selects_via_daemon_monitor(env):
    win, d, _ = env
    win.present()
    pump(0.5)
    if not win.is_active():
        pytest.skip("window not active in this display (no window manager)")
    h = d.backend.inputs["/dev/input/fake0a"]
    d.call(lambda: h.inject(keys.name_to_code("K"), 1))
    pump(0.3)
    assert win.trigger == ("K",)
    d.call(lambda: h.inject(keys.name_to_code("K"), 0))


def test_record_trigger_through_daemon_capture(env):
    win, d, _ = env
    got = []
    win.recorder.start(lambda codes: got.append(codes))
    pump(0.4)
    assert d.call(lambda: d.daemon.groups["1234:5678@usb-fake-0"].capture)
    h = d.backend.inputs["/dev/input/fake0a"]
    c = keys.name_to_code
    d.call(lambda: [h.inject(c("LEFTCTRL"), 1), h.inject(c("C"), 1), h.inject(c("C"), 0)])
    pump(0.4)
    assert got == [[c("LEFTCTRL"), c("C")]]
    from keyboard_remapper.gui.widgets import trigger_from_codes, output_from_codes
    assert trigger_from_codes(got[0]) == ("CTRL", "C")
    assert output_from_codes(got[0]) == ("CTRL", "C")
    pump(0.3)
    assert not d.call(lambda: d.daemon.groups["1234:5678@usb-fake-0"].capture)


def test_banner_when_daemon_gone(env):
    win, d, _ = env
    d.stop()
    pump(1.0)
    assert win.banner.get_revealed()
    # the remembered keyboard stays editable while offline
    assert win.stack.get_visible_child_name() == "main"
    assert win.status_pill.get_label() in ("未接続", "Offline")
    win.on_key_clicked("A")
    win.set_mapping(Mapping(("A",), Action("key", output=("B",))))
    assert win.cfg().preset.find(("A",))


def test_assign_flow_draft_then_record_output(env):
    """Click key -> 'remap to a key' -> press the target combo: nothing saved before the pick."""
    win, d, _ = env
    win.on_key_clicked("A")
    assert win.editor.mapping is None
    win.editor._create(None, "key")
    pump(0.3)
    assert win.editor.draft and win.cfg().preset.find(("A",)) is None      # not saved yet
    # the chooser is shown inline, already open; use its record button
    assert win.editor.out_btn.get_active() and win.editor.chooser_rev.get_reveal_child()
    win.editor.panel._toggle_record()
    pump(0.4)
    h = d.backend.inputs["/dev/input/fake0a"]
    c = keys.name_to_code
    d.call(lambda: [h.inject(c("LEFTCTRL"), 1), h.inject(c("C"), 1), h.inject(c("C"), 0), h.inject(c("LEFTCTRL"), 0)])
    pump(0.5)
    m = win.cfg().preset.find(("A",))
    assert m is not None and m.action.output == ("CTRL", "C")
    assert not win.editor.draft and win.editor.del_btn.get_visible()
    assert win.keyboard.assignments["A"] == "Ctrl+C"
    assert not win.editor.out_btn.get_active()          # collapsed after a definite pick


def test_dismissed_chooser_leaves_no_mapping(env):
    win, d, _ = env
    win.on_key_clicked("B")
    win.editor._create(None, "key")
    pump(0.3)
    win.on_key_clicked("C")           # moves on without choosing
    assert win.cfg().preset.find(("B",)) is None
    assert not win.editor.draft


def test_sequence_editing(env):
    win, d, _ = env
    win.on_key_clicked("F13")
    win.editor._create(None, "sequence")
    pump(0.2)
    win.editor._step_added("Ctrl+C")
    win.editor._step_added("wait 40")
    m = win.cfg().preset.find(("F13",))
    assert m.action.steps == ("Ctrl+C", "wait 40")
    win.editor._step_removed(0)
    assert win.cfg().preset.find(("F13",)).action.steps == ("wait 40",)


def test_search_filters_key_list(env):
    win, d, _ = env
    from keyboard_remapper.gui.widgets import KeyChooserPanel
    pop = KeyChooserPanel(win, (), lambda c, f: None)
    pop.search.set_text("音量")
    visible = [n for r, n, c in pop._rows if n and pop._filter(r)]
    assert set(visible) == {"VOLUMEDOWN", "VOLUMEUP"}
    pop.search.set_text("enter")
    assert "ENTER" in [n for r, n, c in pop._rows if n and pop._filter(r)]


def test_daemon_updates_do_not_disturb_open_editor(env):
    """Saving pushes to the daemon, which broadcasts a device update: the editor must survive it."""
    win, d, _ = env
    win.on_key_clicked("A")
    win.editor._create(None, "key")
    pump(0.3)
    panel = win.editor.panel
    pump(0.2)
    panel._mod_btns["CTRL"].set_active(True)          # first pick -> mapping saved, push scheduled
    pump(1.0)                                         # save + daemon broadcast + GUI handling
    assert win.editor.panel is panel                  # not rebuilt
    assert panel.get_mapped()


def test_large_preset_survives_ipc(env):
    win, d, _ = env
    from keyboard_remapper.ipc import Client
    big = {"name": "big", "mappings": [
        {"trigger": ["CTRL", "SHIFT", "F13"], "action": {"type": "sequence", "steps": ["A"] * 20000}}]}
    c = Client(win.link.client.path)
    assert c.connect()
    assert c.request("apply", model="1234:5678", preset=big)["ok"]
    c.close()


def test_typing_in_chooser_does_not_select_keys_behind_it(env):
    win, d, _ = env
    win.present()
    pump(0.5)
    win.on_key_clicked("A")
    win.editor._create(None, "key")
    pump(0.3)
    panel = win.editor.panel
    pump(0.3)
    h = d.backend.inputs["/dev/input/fake0a"]
    d.call(lambda: [h.inject(keys.name_to_code("V"), 1), h.inject(keys.name_to_code("V"), 0)])
    pump(0.4)
    assert win.trigger == ("A",)                      # untouched
    assert win.editor.panel is panel                  # editor not rebuilt


def test_apple_keyboard_gets_apple_layout_and_extras_strip(env):
    win, d, _ = env
    dev = {"model": "004c:0267", "name": "Apple Inc. Magic Keyboard", "vendor": 0x4C}
    cfg = win._ensure_config(dev)
    assert cfg.size == "apple"
    win.keyboard.set_layout(__import__("keyboard_remapper.layouts", fromlist=["x"]).build("ansi", "apple"))
    assert win.layer_btns["FN"] is not None
    # a key the layout does not have gets its own strip once it is pressed
    win.extra_seen.add("PROG1")
    win._refresh_keyboard()
    assert "PROG1" in win.keyboard.extras
    assert win.keyboard._extra_shapes()[0]
    assert win.layer_btns["FN"].get_visible()


def test_fn_layer_selects_fn_trigger(env):
    win, d, _ = env
    win.layer_btns["FN"].set_active(True)
    win.on_key_clicked("H")
    assert win.trigger == ("FN", "H")


def test_chooser_is_visible_right_after_choosing_remap(env):
    """Regression: the key list/search must appear straight away, not only after a detour."""
    win, d, _ = env
    win.on_key_clicked("W")
    win.editor._create(None, "key")
    pump(0.5)
    assert win.editor.panel.get_mapped() and win.editor.panel.search.get_mapped()
    win.editor.panel.search.set_text("volume")
    visible = [n for r, n, c in win.editor.panel._rows if n and win.editor.panel._filter(r)]
    assert set(visible) == {"VOLUMEDOWN", "VOLUMEUP"}
    # pick one from the list: saved, chooser collapses
    row = next(r for r, n, c in win.editor.panel._rows if n == "VOLUMEUP")
    win.editor.panel.list.emit("row-activated", row)
    pump(0.3)
    assert win.cfg().preset.find(("W",)).action.output == ("VOLUMEUP",)
    assert not win.editor.chooser_rev.get_reveal_child()


def test_modifier_chord_selected_by_pressing_and_saved(env):
    """Left Shift + Left Ctrl pressed together and released selects that chord as the trigger."""
    win, d, _ = env
    win.present()
    pump(0.5)
    h = d.backend.inputs["/dev/input/fake0a"]
    c = keys.name_to_code
    d.call(lambda: [h.inject(c("LEFTSHIFT"), 1), h.inject(c("LEFTCTRL"), 1),
                    h.inject(c("LEFTCTRL"), 0), h.inject(c("LEFTSHIFT"), 0)])
    pump(0.5)
    assert win.trigger == ("LEFTSHIFT", "LEFTCTRL")
    win.editor._create(None, "key")
    pump(0.2)
    win.editor.panel.list.emit("row-activated", next(r for r, n, cat in win.editor.panel._rows if n == "CAPSLOCK"))
    pump(0.3)
    m = win.cfg().preset.find(("LEFTSHIFT", "LEFTCTRL"))
    assert m is not None and m.action.output == ("CAPSLOCK",)
    assert "離す" in win.editor.summary.get_label() or "released" in win.editor.summary.get_label()


def _fill(win, specs):
    for trig, out in specs:
        win.cfg().preset.set(Mapping(trig, Action("key", output=out)))
    win._refresh_all()


def _order(win):
    return [r.mapping.trigger for r in _rows(win)]


def _rows(win):
    rows, r = [], win.mlist.get_first_child()
    while r is not None:
        rows.append(r)
        r = r.get_next_sibling()
    return rows


def test_list_is_sorted_by_keyboard_position(env):
    win, d, _ = env
    _fill(win, [(("CTRL", "K"), ("UP",)), (("Z",), ("A",)), (("Q",), ("B",)), (("CTRL", "H"), ("LEFT",)),
                (("F1",), ("MUTE",))])
    # keyboard order: no-modifier mappings first, top row to bottom row, left to right; then the Ctrl layer
    assert _order(win) == [("F1",), ("Q",), ("Z",), ("CTRL", "H"), ("CTRL", "K")]


def test_header_click_cycles_ascending_descending_manual(env):
    win, d, _ = env
    _fill(win, [(("CTRL", "K"), ("UP",)), (("Z",), ("A",)), (("Q",), ("B",)), (("F1",), ("MUTE",))])
    stored = [m.trigger for m in win.cfg().preset.mappings]
    win._on_sort_header(None, "trigger")
    asc = [keys.chord_name(t, "en").lower() for t in _order(win)]
    assert asc == sorted(asc) and "▲" in win._head_btns["trigger"].get_label()
    win._on_sort_header(None, "trigger")
    desc = [keys.chord_name(t, "en").lower() for t in _order(win)]
    assert desc == sorted(desc, reverse=True) and "▼" in win._head_btns["trigger"].get_label()
    win._on_sort_header(None, "trigger")                      # third click: back to the manual order
    assert win.config.sort == "manual" and _order(win) == stored
    assert "▲" not in win._head_btns["trigger"].get_label()
    # the other column sorts by what the key does
    win._on_sort_header(None, "action")
    outs = [win.cfg().preset.find(t).action.describe("en").lower() for t in _order(win)]
    assert outs == sorted(outs) and win.config.sort == "action-asc"


def test_drag_reorder_makes_shown_order_manual(env):
    win, d, _ = env
    _fill(win, [(("A",), ("B",)), (("C",), ("D",)), (("E",), ("F",)), (("G",), ("H",))])
    win._set_sort("manual")
    assert _order(win) == [("A",), ("C",), ("E",), ("G",)]
    win.move_mapping(3, 0, False)                      # G before A
    assert _order(win) == [("G",), ("A",), ("C",), ("E",)]
    win.move_mapping(0, 2, True)                       # G after C
    assert _order(win) == [("A",), ("C",), ("G",), ("E",)]
    # reordering while a sort is active freezes the shown order as the manual one
    win._on_sort_header(None, "trigger")
    asc = _order(win)
    win.move_mapping(0, len(asc) - 1, True)
    assert win.config.sort == "manual"
    assert _order(win) == asc[1:] + asc[:1]
    assert [m.trigger for m in win.cfg().preset.mappings] == _order(win)     # saved in that order


def test_rows_are_draggable_and_accept_drops(env):
    win, d, _ = env
    _fill(win, [(("A",), ("B",)), (("C",), ("D",))])
    row = _rows(win)[0]
    ctl = [row.observe_controllers().get_item(i) for i in range(row.observe_controllers().get_n_items())]
    assert any(isinstance(c, Gtk.DragSource) for c in ctl) and any(isinstance(c, Gtk.DropTarget) for c in ctl)


def test_remove_via_menu_is_immediate_and_undo_merges_batches(env):
    win, d, _ = env
    _fill(win, [(("A",), ("B",)), (("C",), ("D",)), (("E",), ("F",))])
    win.remove_mappings([win.cfg().preset.find(("A",))])
    assert win.cfg().preset.find(("A",)) is None                 # no confirmation step
    win.remove_mappings([win.cfg().preset.find(("C",))])
    assert len(win._deleted) == 2                                # consecutive deletions share one undo
    win._undo_removed(win._deleted)
    assert win.cfg().preset.find(("A",)) and win.cfg().preset.find(("C",))


def test_clear_all_and_undo(env):
    win, d, _ = env
    _fill(win, [(("A",), ("B",)), (("C",), ("D",))])
    assert win.clear_btn.get_sensitive()
    win.clear_all()
    assert not win.cfg().preset.mappings and not win.clear_btn.get_sensitive()
    win._undo_removed(win._deleted)
    assert len(win.cfg().preset.mappings) == 2


def test_right_click_menu_exists_on_rows(env):
    win, d, _ = env
    _fill(win, [(("A",), ("B",))])
    row = _rows(win)[0]
    assert any(isinstance(c, Gtk.GestureClick) and c.get_button() == 3 for c in
               [row.observe_controllers().get_item(i) for i in range(row.observe_controllers().get_n_items())])
    win._on_row_right_click(None, 1, 5, 5, row)          # must not raise
    pump(0.2)


def test_export_import_roundtrip_replace_merge_and_undo(env, tmp_path):
    win, d, _ = env
    _fill(win, [(("CTRL", "J"), ("DOWN",)), (("CAPSLOCK",), ("LEFTCTRL",))])
    f = str(tmp_path / "out.json")
    assert win.export_to(f)
    data = json.load(open(f))
    assert data["mappings"] and "keyboard" in data
    win.clear_all()
    assert win.import_from(f, "replace")                          # empty -> no question needed
    assert win.cfg().preset.find(("CTRL", "J")) and win.cfg().preset.find(("CAPSLOCK",))
    # merge keeps what is there, file wins on conflicts
    win.cfg().preset.set(Mapping(("CTRL", "J"), Action("key", output=("UP",))))
    win.cfg().preset.set(Mapping(("X",), Action("key", output=("Y",))))
    win.import_from(f, "merge")
    assert win.cfg().preset.find(("CTRL", "J")).action.output == ("DOWN",)
    assert win.cfg().preset.find(("X",)) is not None
    # replace drops extras
    win.import_from(f, "replace")
    assert win.cfg().preset.find(("X",)) is None
    assert len(win.cfg().preset.mappings) == 2


def test_import_rejects_garbage_and_skips_invalid_entries(env, tmp_path):
    win, d, _ = env
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert not win.import_from(str(bad), "replace")
    other = tmp_path / "other.json"
    other.write_text('{"hello": 1}')
    assert not win.import_from(str(other), "replace")
    mixed = tmp_path / "mixed.json"
    mixed.write_text(json.dumps({"mappings": [
        {"trigger": ["A"], "action": {"type": "key", "output": ["B"]}},
        {"trigger": ["NOSUCHKEY"], "action": {"type": "key", "output": ["B"]}}]}))
    assert win.import_from(str(mixed), "replace")
    assert len(win.cfg().preset.mappings) == 1


def test_warning_for_output_key_that_cannot_work(env):
    win, d, _ = env
    win.on_key_clicked("W")
    win.editor._create(None, "key")
    pump(0.3)
    assert not win.editor.warn.get_visible()
    win.editor.panel.list.emit("row-activated", next(
        r for r, n, c in win.editor.panel._rows if n == "ZENKAKUHANKAKU"))
    pump(0.3)
    assert win.editor.warn.get_visible()
    assert "Grave" in win.editor.warn.get_label()


def test_jis_zenkaku_key_press_lights_the_grave_cap(env):
    """A keyboard that reports Hankaku/Zenkaku as KEY_ZENKAKUHANKAKU still maps onto the drawn key."""
    win, d, _ = env
    from keyboard_remapper import layouts
    win.keyboard.set_layout(layouts.build("jis", "full"))
    win.cfg().preset.set(Mapping(("ZENKAKUHANKAKU",), Action("key", output=("ESC",))))
    win.held.add(keys.name_to_code("ZENKAKUHANKAKU"))
    win.trigger = ("ZENKAKUHANKAKU",)
    win._refresh_keyboard()
    assert win.keyboard.selected == "GRAVE" and "GRAVE" in win.keyboard.assignments
    assert keys.name_to_code("GRAVE") in win.keyboard.pressed
    assert "ZENKAKUHANKAKU" not in win.keyboard.extras


def test_gui_flags_a_daemon_of_another_version(env):
    win, d, _ = env
    from keyboard_remapper import __version__
    win._check_daemon_version(__version__)          # same version: silent
    win._check_daemon_version(None)
    win._check_daemon_version("0.9.0")              # must not raise; shows a persistent toast
    pump(0.2)


def test_menu_actions_are_all_window_actions_and_enabled(env):
    """The header menu must only use actions that exist and are enabled (About/Quit were greyed out)."""
    win, d, _ = env
    for name in ("about", "quit", "export", "import", "clear-all", "sort"):
        act = win.lookup_action(name)
        assert act is not None and act.get_enabled(), name
    # every action the menus refer to is a window action
    def refs(model):
        out = []
        for i in range(model.get_n_items()):
            v = model.get_item_attribute_value(i, "action", None)
            if v is not None:
                out.append(v.get_string())
            for kind in ("section", "submenu"):
                sub = model.get_item_link(i, kind)
                if sub is not None:
                    out += refs(sub)
        return out
    menus = []
    stack = [win.get_first_child()]
    while stack:                                        # find the MenuButtons' models
        w = stack.pop()
        if w is None:
            continue
        if isinstance(w, Gtk.MenuButton) and w.get_menu_model() is not None:
            menus.append(w.get_menu_model())
        stack += [w.get_first_child(), w.get_next_sibling()]
    names = [n for m in menus for n in refs(m)]
    assert any(n == "win.about" for n in names) and any(n == "win.quit" for n in names)
    assert not [n for n in names if n.startswith("app.")]


def test_about_action_opens_without_error(env):
    win, d, _ = env
    win.lookup_action("about").activate(None)
    pump(0.4)


def test_keycap_text_uses_the_system_ui_font(env):
    """No hard-coded font family: the drawing must follow the user's UI font like the rest of the window."""
    import inspect
    from keyboard_remapper.gui import keyboard as kbmod
    src = inspect.getsource(kbmod)
    assert "set_family" not in src and "Noto Sans" not in src
    win, d, _ = env
    assert win.keyboard.get_pango_context().get_font_description().get_family()
