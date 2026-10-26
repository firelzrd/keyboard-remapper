"""Main window."""

from __future__ import annotations

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from .. import __version__, keys, layouts  # noqa: E402
from ..config import Config, system_standard  # noqa: E402
from ..i18n import LANG, T  # noqa: E402
from ..mapping import ACTION_DISABLE, ACTION_KEY, Mapping, Preset  # noqa: E402
from .editor import Editor  # noqa: E402
from .keyboard import KeyboardView  # noqa: E402
from .compat import Layout, ask, choose_file, make_banner, set_placeholder  # noqa: E402
from .link import DaemonLink  # noqa: E402
from .widgets import Recorder, chord_box, short_chord  # noqa: E402

GENERIC = keys.GENERIC_ORDER


def _generic_of_name(n: str) -> str | None:
    if n in keys.GENERIC_MODIFIERS:
        return n
    c = keys.name_to_code(n)
    return keys.generic_of(c) if c is not None else None


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, socket_path: str, config: Config | None = None):
        super().__init__(application=app, title="Keyboard Remapper")
        self.set_default_size(1360, 820)
        self.set_size_request(380, 420)
        self.config = config or Config()
        self.link = DaemonLink(socket_path)
        self.recorder = Recorder(self)
        self.recording = False
        self.modal_open = 0          # open key-chooser popovers: physical keys must not select behind them
        self.model: str = ""
        self.devs: list[dict] = []
        self.sticky: set[str] = set()
        self.trigger: tuple[str, ...] = ()
        self.held: set[int] = set()
        self.extra_seen: set[str] = set()      # pressed keys that are not on the drawn layout
        self._mod_candidate: int | None = None
        self._peak_mods: list[int] = []        # modifiers pressed in this clean hold, in order
        self._pushed: dict[str, str] = {}
        self._save_timer = 0
        self._updating = False

        self.link.on_connection.append(self._on_connection)
        self.link.on_devices.append(self._on_devices)
        self.link.on_hello.append(self._check_daemon_version)
        self.link.on_key.append(self._on_daemon_key)
        self.link.on_capture_ended.append(lambda m: self.recorder.cancel(notify=True))

        self._deleted: list[Mapping] = []          # batch the "Undo" toast would restore
        self._undo_toast = None
        self._shown: list[Mapping] = []            # mappings in the order the sidebar shows them
        self._deleted: list[Mapping] = []          # what the current "Undo" toast would restore
        self._undo_toast = None
        self._build()
        self._on_connection(self.link.connected)

        sm = Adw.StyleManager.get_default()
        sm.connect("notify::dark", lambda *_: self.keyboard.set_dark(sm.get_dark()))
        self.keyboard.set_dark(sm.get_dark())
        self.connect("notify::is-active", self._on_active)
        self.connect("close-request", self._on_close)

    # ------------------------------------------------------------------ UI

    def _build(self) -> None:
        self.toasts = Adw.ToastOverlay()
        view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)     # header, banner, page
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        # header
        header = Adw.HeaderBar()
        self.dev_model = Gtk.StringList()
        self.dev_drop = Gtk.DropDown(model=self.dev_model)
        self.dev_drop.set_tooltip_text(T("設定するキーボード", "Keyboard to configure"))
        self.dev_drop.connect("notify::selected", self._on_dev_selected)
        header.set_title_widget(self.dev_drop)

        self.sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-show-right-symbolic")
        self.sidebar_btn.set_tooltip_text(T("割り当て一覧", "Mappings"))
        self.sidebar_btn.set_visible(False)
        header.pack_end(self.sidebar_btn)

        menu = Gio.Menu()
        io = Gio.Menu()
        io.append(T("割り当てを書き出す…", "Export mappings…"), "win.export")
        io.append(T("割り当てを読み込む…", "Import mappings…"), "win.import")
        menu.append_section(None, io)
        menu.append(T("Keyboard Remapper について", "About Keyboard Remapper"), "win.about")
        menu.append(T("終了", "Quit"), "win.quit")
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(mb)

        sw_box = Gtk.Box(spacing=8)
        self.status_pill = Gtk.Label()
        self.status_pill.add_css_class("status-pill")
        sw_box.append(self.status_pill)
        self.enable_switch = Gtk.Switch()
        self.enable_switch.set_valign(Gtk.Align.CENTER)
        self.enable_switch.set_tooltip_text(T("このキーボードに割り当てを適用する", "Apply the mappings to this keyboard"))
        self.enable_switch.connect("notify::active", self._on_enable_toggled)
        sw_box.append(self.enable_switch)
        header.pack_end(sw_box)
        view.append(header)

        self.banner = make_banner(T("バックグラウンドサービス (keyboard-remapperd) に接続できません",
                                    "Cannot reach the background service (keyboard-remapperd)"))
        self.banner.set_button_label(T("起動する", "Start"))
        self.banner.connect("button-clicked", self._start_service)
        view.append(self.banner)

        # stack: main / empty
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        view.append(self.stack)

        self.empty = Adw.StatusPage(icon_name="input-keyboard-symbolic")
        self.empty_btn = Gtk.Button(label=T("サービスを起動", "Start service"))
        self.empty_btn.add_css_class("suggested-action")
        self.empty_btn.add_css_class("pill")
        self.empty_btn.set_halign(Gtk.Align.CENTER)
        self.empty_btn.connect("clicked", self._start_service)
        self.empty.set_child(self.empty_btn)
        self.stack.add_named(self.empty, "empty")

        self.split = Layout(self, self.sidebar_btn)
        self.stack.add_named(self.split.widget, "main")

        # --- content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for side in ("start", "end"):
            getattr(content, f"set_margin_{side}")(18)
        content.set_margin_top(12)
        content.set_margin_bottom(18)
        scroller = Gtk.ScrolledWindow()
        self.scroller = scroller
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(content)
        self.split.set_content(scroller)

        # layer bar
        bar = Gtk.Box(spacing=10)
        bar.add_css_class("layer-bar")
        lab = Gtk.Label(label=T("組み合わせる修飾キー", "Modifiers"))
        lab.add_css_class("caption-heading")
        bar.append(lab)
        self.layer_btns: dict[str, Gtk.ToggleButton] = {}
        seg = Gtk.Box()
        seg.add_css_class("linked")
        for g, label in (("CTRL", "Ctrl"), ("SHIFT", "Shift"), ("ALT", "Alt"), ("META", "Super"),
                         ("FN", "Fn")):
            b = Gtk.ToggleButton(label=label)
            b.connect("toggled", self._on_layer_toggled, g)
            self.layer_btns[g] = b
            seg.append(b)
        self.layer_btns["FN"].set_visible(False)       # shown for Apple layouts / when in use
        bar.append(seg)
        hint = Gtk.Label(label=T("← 組み合わせの割り当てを表示", "← show shortcuts using these"))
        hint.add_css_class("dim")
        hint.add_css_class("caption")
        hint.set_hexpand(True)
        hint.set_xalign(0)
        hint.set_ellipsize(3)
        bar.append(hint)

        self.std_drop = Gtk.DropDown.new_from_strings(
            [layouts.TITLES[s][0 if LANG == "en" else 1] for s in layouts.STANDARDS])
        self.std_drop.set_tooltip_text(T("キーボードの配列", "Keyboard layout"))
        self.std_drop.connect("notify::selected", self._on_layout_changed)
        self.size_drop = Gtk.DropDown.new_from_strings(
            [layouts.SIZES[s][0 if LANG == "en" else 1] for s in layouts.SIZE_IDS])
        self.size_drop.connect("notify::selected", self._on_layout_changed)
        bar.append(self.std_drop)
        bar.append(self.size_drop)
        content.append(bar)

        self.keyboard = KeyboardView()
        self.keyboard.connect("key-clicked", lambda _w, n: self.on_key_clicked(n))
        content.append(self.keyboard)

        self.editor = Editor(self, self.set_mapping, self.delete_mapping)
        content.append(self.editor)

        tryrow = Gtk.Box(spacing=10)
        tl = Gtk.Label(label=T("動作テスト", "Try it"))
        tl.add_css_class("dim")
        tryrow.append(tl)
        self.try_entry = Gtk.Entry()
        self.try_entry.set_hexpand(True)
        self.try_entry.set_placeholder_text(T("ここに入力すると、適用中の割り当てを実際に試せます",
                                              "Type here to try the active mappings"))
        tryrow.append(self.try_entry)
        content.append(tryrow)

        # --- sidebar
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.add_css_class("background")
        head = Gtk.Box(spacing=8)
        head.set_margin_top(14)
        head.set_margin_start(14)
        head.set_margin_end(14)
        head.set_margin_bottom(8)
        self.side_title = Gtk.Label(xalign=0)
        self.side_title.add_css_class("heading")
        self.side_title.set_hexpand(True)
        head.append(self.side_title)
        self.clear_btn = Gtk.Button(icon_name="user-trash-symbolic")
        self.clear_btn.add_css_class("flat")
        self.clear_btn.set_tooltip_text(T("すべての割り当てを削除", "Remove all mappings"))
        self.clear_btn.connect("clicked", lambda *_: self.clear_all())
        head.append(self.clear_btn)
        side_menu = Gio.Menu()
        sort_sec = Gio.Menu()
        sort_sec.append(T("手動 (ドラッグで並べ替え)", "Manual (drag to reorder)"), "win.sort::manual")
        sort_sec.append(T("キーボードの並び順", "Keyboard order"), "win.sort::keyboard")
        side_menu.append_submenu(T("並べ替え", "Sort by"), sort_sec)
        io_sec = Gio.Menu()
        io_sec.append(T("書き出す…", "Export…"), "win.export")
        io_sec.append(T("読み込む…", "Import…"), "win.import")
        side_menu.append_section(None, io_sec)
        side_menu.append(T("すべて削除", "Remove all"), "win.clear-all")
        mbtn = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=side_menu)
        mbtn.add_css_class("flat")
        mbtn.set_tooltip_text(T("並べ替え・書き出し・読み込み", "Sort, export, import"))
        self._trigger_group = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)
        head.append(mbtn)
        side.append(head)

        sort_act = Gio.SimpleAction.new_stateful("sort", GLib.VariantType.new("s"),
                                                 GLib.Variant.new_string(self.config.sort))
        sort_act.connect("activate", self._on_sort_action)
        self.add_action(sort_act)
        self._sort_action = sort_act
        # About / Quit live here too (not as "app." actions): the window-level actions are the ones that
        # are always reachable from this menu, whatever the GTK / libadwaita version.
        for name, cb in (("about", lambda *_: self.get_application()._about()),
                         ("quit", lambda *_: self.get_application().quit()),
                         ("export", lambda *_: self.export_dialog()),
                         ("import", lambda *_: self.import_dialog()),
                         ("clear-all", lambda *_: self.clear_all())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
        self.search = Gtk.SearchEntry()
        set_placeholder(self.search, T("割り当てを検索", "Filter mappings"))
        self.search.set_margin_start(12)
        self.search.set_margin_end(12)
        self.search.set_margin_bottom(8)
        self.search.connect("search-changed", lambda *_: self.mlist.invalidate_filter())
        side.append(self.search)
        # column headers: click to sort ascending / descending / back to the manual order
        hdr = Gtk.Box(spacing=8)
        hdr.set_margin_start(12)
        hdr.set_margin_end(12)
        self._head_btns: dict[str, Gtk.Button] = {}
        for col, label in (("trigger", T("キー", "Key")), ("action", T("割り当て", "Mapped to"))):
            b = Gtk.Button()
            b.add_css_class("flat")
            b.add_css_class("sort-header")
            b.set_halign(Gtk.Align.START)
            b.set_tooltip_text(T("クリックで昇順 → 降順 → 手動順", "Click: ascending → descending → manual"))
            b.connect("clicked", self._on_sort_header, col)
            self._head_btns[col] = b
            hdr.append(b)
        self._trigger_group.add_widget(self._head_btns["trigger"])
        self.sort_head = hdr
        side.append(hdr)
        self.mlist = Gtk.ListBox()
        self.mlist.add_css_class("navigation-sidebar")
        self.mlist.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.mlist.set_filter_func(self._filter_row)
        self.mlist.connect("row-activated", self._on_row_activated)
        self.mlist_empty = Gtk.Label(label=T("割り当てはまだありません。\nキーを選んで作成しましょう。",
                                             "No mappings yet.\nPick a key to create one."))
        self.mlist_empty.add_css_class("dim")
        self.mlist_empty.set_justify(Gtk.Justification.CENTER)
        self.mlist_empty.set_margin_top(30)
        sc = Gtk.ScrolledWindow()
        sc.set_vexpand(True)
        sc.set_child(self.mlist)
        side.append(self.mlist_empty)
        side.append(sc)
        self.split.set_sidebar(side)

        # key controller (window-level; used for key press selection when the daemon is absent)
        kc = Gtk.EventControllerKey()
        kc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        kc.connect("key-pressed", self._on_gtk_key, 1)
        kc.connect("key-released", self._on_gtk_key_release)
        self.add_controller(kc)

    def scroll_to_end(self) -> None:
        """Bring the (just expanded) editor into view once the layout has settled."""
        def go():
            adj = self.scroller.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False
        GLib.timeout_add(260, go)

    # ------------------------------------------------------------- devices

    def _current_devices(self) -> list[dict]:
        """Connected keyboards, or - while offline - the ones remembered in the config."""
        if self.link.connected:
            return self.link.devices
        return [{"id": m, "model": m, "name": c.name, "applied": False, "offline": True}
                for m, c in self.config.devices.items() if c.name]

    def _check_daemon_version(self, version: str | None) -> None:
        """After an upgrade the old daemon keeps running until it is restarted: say so."""
        if version is None or version == __version__:
            return
        toast = Adw.Toast.new(T(
            f"バックグラウンドサービスが古いバージョン ({version}) のままです。再起動してください",
            f"The background service is still version {version} (app: {__version__}). Restart it."))
        toast.set_button_label(T("再起動", "Restart"))
        toast.set_timeout(0)
        toast.connect("button-clicked", lambda *_: self._start_service(verb="restart"))
        self.toasts.add_toast(toast)

    def _on_connection(self, ok: bool) -> None:
        self.banner.set_revealed(not ok)
        if ok:
            self._pushed.clear()
            self.link.monitor(self.is_active())
        if self.recorder.active:
            self.recorder.cancel(notify=True)
        self._on_devices(self._current_devices())

    def _on_devices(self, devs: list[dict]) -> None:
        if not self.link.connected:
            devs = self._current_devices()
        same = [(d["model"], d["name"]) for d in devs] == [(d["model"], d["name"]) for d in self.devs]
        self.devs = devs
        if same and (self.model or not devs):
            # only status flags changed (e.g. "applied"): never rebuild what the user is editing
            self._update_status()
        else:
            self._rebuild_device_list(devs)
        for d in devs:
            self._ensure_config(d)
            self._push(d["model"])

    def _rebuild_device_list(self, devs: list[dict]) -> None:
        prev = self.model
        self._updating = True
        self.dev_model.splice(0, self.dev_model.get_n_items(), [d["name"] for d in devs])
        idx = next((i for i, d in enumerate(devs) if d["model"] == prev), None)
        if idx is None:
            idx = next((i for i, d in enumerate(devs) if d["model"] == self.config.last_model), 0)
        if devs:
            self.dev_drop.set_selected(idx)
        self._updating = False
        if devs:
            self._select_device(devs[idx])
        else:
            self.model = ""
        self.dev_drop.set_sensitive(len(devs) > 1)
        self._update_empty()
        self._update_status()

    def _ensure_config(self, d: dict):
        new = d["model"] not in self.config.devices
        cfg = self.config.device(d["model"], d["name"], system_standard())
        if new and self._is_apple(d):
            cfg.size = layouts.APPLE_PRODUCT_SIZE.get(
                d.get("product"), "apple-num" if "numeric" in d["name"].lower() else "apple")
            if d.get("layout_hint") == "jis":
                cfg.standard = "jis"
        return cfg

    @staticmethod
    def _is_apple(d: dict) -> bool:
        return d.get("vendor") in layouts.APPLE_VENDORS or "apple" in d["name"].lower() \
            or "magic keyboard" in d["name"].lower()

    def _update_empty(self) -> None:
        if self.devs:
            self.stack.set_visible_child_name("main")
            return
        self.stack.set_visible_child_name("empty")
        if self.link.connected:
            self.empty.set_title(T("キーボードが見つかりません", "No keyboard found"))
            self.empty.set_description(T("キーボードを接続すると、ここに表示されます。", "Connect a keyboard and it will appear here."))
            self.empty_btn.set_visible(False)
        else:
            self.empty.set_title(T("サービスが起動していません", "The service is not running"))
            self.empty.set_description(T(
                "キーを入れ替えるには、バックグラウンドで動作する keyboard-remapperd が必要です。\n"
                "手動で起動する場合: sudo systemctl enable --now keyboard-remapperd",
                "Remapping needs keyboard-remapperd running in the background.\n"
                "To start it manually: sudo systemctl enable --now keyboard-remapperd"))
            self.empty_btn.set_visible(True)

    def _on_dev_selected(self, *_) -> None:
        if self._updating:
            return
        i = self.dev_drop.get_selected()
        if 0 <= i < len(self.devs):
            self._select_device(self.devs[i])

    def _select_device(self, d: dict) -> None:
        if d["model"] != self.model and self.recorder.active:
            self.recorder.cancel(notify=True)
        changed = d["model"] != self.model
        self.model = d["model"]
        self.config.last_model = self.model
        cfg = self._ensure_config(d)
        self._updating = True
        self.enable_switch.set_active(cfg.enabled)
        self.std_drop.set_selected(layouts.STANDARDS.index(cfg.standard))
        self.size_drop.set_selected(layouts.SIZE_IDS.index(cfg.size))
        self._updating = False
        self.keyboard.set_layout(layouts.build(cfg.standard, cfg.size))
        if changed:
            self.trigger = ()
            self.sticky = set()
            self.extra_seen = set()
        self._refresh_all()

    def cfg(self):
        return self.config.devices[self.model]

    # --------------------------------------------------------------- state

    def _layer(self) -> set[str]:
        held = {keys.generic_of(c) for c in self.held if keys.generic_of(c)}
        return set(self.sticky) | held

    def _mapping_layer(self, m: Mapping) -> set[str] | None:
        """Modifier set of a mapping's held keys, or None when it has non-modifier held keys."""
        s = set()
        for n in m.held:
            g = _generic_of_name(n)
            if g is None:
                return None
            s.add(g)
        return s

    def _short_action(self, m: Mapping) -> str:
        a = m.action
        if a.type == ACTION_KEY:
            return short_chord(a.output)
        if a.type == ACTION_DISABLE:
            return "✕"
        return T("連続", "Seq")

    def _key_names_for(self, spec: str) -> list[str]:
        n = keys.normalize_name(spec)
        if n is None:
            return []
        if n in keys.GENERIC_MODIFIERS:
            return [keys.code_to_name(c) for c in keys.GENERIC_MODIFIERS[n]]
        return [n]

    def _refresh_keyboard(self) -> None:
        if not self.model:
            return
        layer = self._layer()
        shapes = self.keyboard.layout.by_name()

        def shape_of(name: str) -> str:
            # Some JIS keyboards report Hankaku/Zenkaku as KEY_ZENKAKUHANKAKU, most as KEY_GRAVE:
            # both live on the same drawn key.
            alias = keys.DISPLAY_ALIASES.get(name)
            return alias if name not in shapes and alias in shapes else name

        assigns: dict[str, str] = {}
        others: set[str] = set()
        for m in self.cfg().preset.mappings:
            ml = self._mapping_layer(m)
            for kn in map(shape_of, self._key_names_for(m.key)):
                if ml is not None and ml == layer:
                    assigns[kn] = self._short_action(m)
                else:
                    others.add(kn)
        sel = self.trigger[-1] if self.trigger else None
        if sel in keys.GENERIC_MODIFIERS:
            sel = self._key_names_for(sel)[0]
        if sel:
            sel = shape_of(sel)
        # keys the drawn layout lacks (Fn, Eject, odd media keys ...) get their own strip
        wanted = [n for n in list(assigns) + sorted(others) + ([sel] if sel else [])
                  + sorted(shape_of(n) for n in self.extra_seen)]
        extras = list(dict.fromkeys(n for n in wanted if n and n not in shapes))
        fn_used = self.keyboard.layout.apple or "FN" in layer or any(
            "FN" in m.trigger for m in self.cfg().preset.mappings)
        self.layer_btns["FN"].set_visible(fn_used)
        self._updating = True
        for g, b in self.layer_btns.items():
            b.set_active(g in self._layer())
        self._updating = False
        self.keyboard.set_state(selected=sel, layer=layer, assignments=assigns, other_layers=others,
                                extras=extras)
        pressed = set(self.held)
        for name, alias in keys.DISPLAY_ALIASES.items():
            c = keys.name_to_code(name)
            if c in pressed and name not in shapes and alias in shapes:
                pressed.add(keys.name_to_code(alias))
        self.keyboard.set_pressed(pressed)

    def _refresh_sidebar(self) -> None:
        while (r := self.mlist.get_first_child()) is not None:
            self.mlist.remove(r)
        ms = self._sorted_mappings() if self.model else []
        self._shown = ms
        self._update_sort_headers()
        self.sort_head.set_visible(len(ms) > 1)
        n = len(ms)
        self.side_title.set_label(T(f"割り当て一覧 ({n})", f"Mappings ({n})"))
        self.mlist_empty.set_visible(n == 0)
        self.clear_btn.set_sensitive(n > 0)
        selected_row = None
        for idx, m in enumerate(ms):
            row = Gtk.ListBoxRow()
            row.mapping = m
            box = Gtk.Box(spacing=8)
            box.add_css_class("mapping-row")
            trig = chord_box(m.trigger)
            trig.set_halign(Gtk.Align.START)
            self._trigger_group.add_widget(trig)
            box.append(trig)
            arrow = Gtk.Label(label="→")
            arrow.add_css_class("mapping-arrow")
            box.append(arrow)
            desc = Gtk.Label(label=m.action.describe(LANG), xalign=0)
            desc.set_ellipsize(3)
            desc.set_hexpand(True)
            box.append(desc)
            if m.action.type == ACTION_KEY:
                box.remove(desc)
                oc = chord_box(m.action.output, accent=True)
                oc.set_hexpand(True)
                oc.set_halign(Gtk.Align.START)
                box.append(oc)
            row.set_child(box)
            click = Gtk.GestureClick(button=3)                    # right click: remove
            click.connect("pressed", self._on_row_right_click, row)
            row.add_controller(click)
            self._attach_drag(row, idx)
            self.mlist.append(row)
            if self.trigger and m.trigger_id() == Mapping(self.trigger, m.action).trigger_id():
                selected_row = row
        if selected_row is not None:
            self.mlist.select_row(selected_row)

    # -------------------------------------------------- list order / delete / io

    def _sorted_mappings(self) -> list[Mapping]:
        ms = list(self.cfg().preset.mappings)
        mode = self.config.sort
        if mode == "manual":
            return ms
        if mode.startswith("trigger-"):
            ms.sort(key=lambda m: (keys.chord_name(m.trigger, LANG).lower(), len(m.trigger)),
                    reverse=mode.endswith("desc"))
            return ms
        if mode.startswith("action-"):
            ms.sort(key=lambda m: (m.action.describe(LANG).lower(), keys.chord_name(m.trigger, LANG).lower()),
                    reverse=mode.endswith("desc"))
            return ms
        shapes = self.keyboard.layout.by_name()

        def kb_key(m: Mapping):
            # modifiers first (Ctrl, Shift ...), then the key's position on the drawn keyboard
            layer = tuple(GENERIC.index(g) if (g := _generic_of_name(n)) else 9 for n in m.held)
            last = keys.normalize_name(m.key) or m.key
            if last in keys.GENERIC_MODIFIERS:
                last = keys.code_to_name(keys.GENERIC_MODIFIERS[last][0])
            sh = shapes.get(last)
            if sh is not None:
                x, y, _w, _h = sh.bounds
                return (layer, 0, round(y, 2), round(x, 2), "")
            return (layer, 1, 0, keys.name_to_code(last) or 0, last)

        return sorted(ms, key=kb_key)

    def _set_sort(self, mode: str) -> None:
        self.config.sort = mode
        self._sort_action.set_state(GLib.Variant.new_string(mode))
        self._save_soon()
        if self.model:
            self._refresh_sidebar()

    def _on_sort_action(self, action, value) -> None:
        self._set_sort(value.get_string())

    def _on_sort_header(self, _btn, col: str) -> None:
        cur = self.config.sort
        if cur == f"{col}-asc":
            self._set_sort(f"{col}-desc")
        elif cur == f"{col}-desc":
            self._set_sort("manual")
        else:
            self._set_sort(f"{col}-asc")

    def _update_sort_headers(self) -> None:
        for col, label in (("trigger", T("キー", "Key")), ("action", T("割り当て", "Mapped to"))):
            mode = self.config.sort
            arrow = " ▲" if mode == f"{col}-asc" else " ▼" if mode == f"{col}-desc" else ""
            self._head_btns[col].set_label(label + arrow)

    # ---- drag to reorder

    def _attach_drag(self, row: Gtk.ListBoxRow, index: int) -> None:
        src = Gtk.DragSource()
        src.set_actions(Gdk.DragAction.MOVE)
        val = GObject.Value()
        val.init(GObject.TYPE_STRING)
        val.set_string(str(index))
        src.connect("prepare", lambda s, x, y: Gdk.ContentProvider.new_for_value(val))
        src.connect("drag-begin", lambda s, drag: s.set_icon(Gtk.WidgetPaintable.new(row), 0, 0))
        row.add_controller(src)

        tgt = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)

        def where(y: float) -> bool:                       # True: below the row's middle
            return y > row.get_height() / 2

        def motion(t, x, y):
            row.remove_css_class("drop-before")
            row.remove_css_class("drop-after")
            row.add_css_class("drop-after" if where(y) else "drop-before")
            return Gdk.DragAction.MOVE

        def leave(t):
            row.remove_css_class("drop-before")
            row.remove_css_class("drop-after")

        def drop(t, value, x, y):
            leave(t)
            try:
                self.move_mapping(int(value), index, where(y))
            except ValueError:
                return False
            return True

        tgt.connect("motion", motion)
        tgt.connect("leave", leave)
        tgt.connect("drop", drop)
        row.add_controller(tgt)

    def move_mapping(self, src: int, dst: int, after: bool) -> None:
        """Move the shown mapping *src* next to *dst*; the shown order becomes the manual order."""
        shown = list(self._shown)
        if not (0 <= src < len(shown) and 0 <= dst < len(shown)) or src == dst:
            return
        item = shown.pop(src)
        dst_item = self._shown[dst]
        pos = shown.index(dst_item) + (1 if after else 0)
        shown.insert(pos, item)
        self.cfg().preset.mappings = shown
        self._set_sort("manual")
        self._save_soon()

    def _on_row_right_click(self, gesture, n_press, x, y, row) -> None:
        pop = Gtk.Popover()
        pop.set_parent(row)
        pop.set_has_arrow(False)
        pop.set_pointing_to(Gdk.Rectangle(int(x), int(y), 1, 1))
        btn = Gtk.Button(label=T("この割り当てを削除", "Remove this mapping"))
        btn.add_css_class("flat")
        btn.get_child().add_css_class("error")

        def remove(*_):
            pop.popdown()
            self.remove_mappings([row.mapping])

        btn.connect("clicked", remove)
        pop.set_child(btn)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def remove_mappings(self, ms: list[Mapping]) -> None:
        """Delete without asking; the toast offers Undo (and merges consecutive deletions)."""
        preset = self.cfg().preset
        removed = [r for m in ms if (r := preset.remove(m.trigger)) is not None]
        if not removed:
            return
        self._after_edit(True)
        self._announce_removed(removed)

    def clear_all(self) -> None:
        if self.model:
            self.remove_mappings(list(self.cfg().preset.mappings))

    def _announce_removed(self, removed: list[Mapping]) -> None:
        batch = (self._deleted if self._undo_toast is not None else []) + removed
        old = self._undo_toast
        n = len(batch)
        toast = Adw.Toast.new(T(f"{n} 件の割り当てを削除しました", f"Removed {n} mapping" + ("s" if n > 1 else "")))
        toast.set_button_label(T("元に戻す", "Undo"))
        toast.set_timeout(6)
        toast.connect("button-clicked", lambda *_: self._undo_removed(batch))
        toast.connect("dismissed", self._toast_dismissed)
        self._deleted, self._undo_toast = batch, toast
        if old is not None:
            old.dismiss()                    # its "dismissed" is ignored: it is no longer the current toast
        self.toasts.add_toast(toast)

    def _toast_dismissed(self, toast) -> None:
        if toast is self._undo_toast:
            self._undo_toast = None
            self._deleted = []

    def _undo_removed(self, batch: list[Mapping]) -> None:
        if not self.model:
            return
        for m in batch:
            self.cfg().preset.set(m)
        self._after_edit(True)

    # ---- export / import

    def _suggest_filename(self) -> str:
        name = next((d["name"] for d in self.devs if d["model"] == self.model), "keyboard")
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "keyboard"
        return f"keyboard-remapper-{safe}.json"

    def export_dialog(self) -> None:
        if not self.model:
            return
        choose_file(self, True, T("割り当てを書き出す", "Export mappings"), self._suggest_filename(),
                    self.export_to)

    def export_to(self, path: str) -> bool:
        name = next((d["name"] for d in self.devs if d["model"] == self.model), "")
        data = self.cfg().preset.to_dict()
        data["keyboard"] = name
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError as ex:
            self.toasts.add_toast(Adw.Toast.new(T(f"書き出せませんでした: {ex.strerror}", f"Could not export: {ex.strerror}")))
            return False
        n = len(self.cfg().preset.mappings)
        self.toasts.add_toast(Adw.Toast.new(T(f"{n} 件の割り当てを書き出しました", f"Exported {n} mappings")))
        return True

    def import_dialog(self) -> None:
        if not self.model:
            return
        choose_file(self, False, T("割り当てを読み込む", "Import mappings"), "", self.import_from)

    def import_from(self, path: str, mode: str | None = None) -> bool:
        """Read a preset file.  *mode*: "replace" / "merge", or None to ask when mappings already exist."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("mappings"), list):
                raise ValueError("not a Keyboard Remapper mapping file")
        except (OSError, ValueError):
            self.toasts.add_toast(Adw.Toast.new(T(
                "このファイルは読み込めません (Keyboard Remapper の割り当てファイルではありません)",
                "Cannot import this file (not a Keyboard Remapper mappings file)")))
            return False
        imported = Preset.from_dict(data)
        skipped = len(data["mappings"]) - len(imported.mappings)
        if not imported.mappings:
            self.toasts.add_toast(Adw.Toast.new(T("読み込める割り当てがありません", "No usable mappings in this file")))
            return False
        current = self.cfg().preset
        if mode is None and current.mappings:
            n_new, n_old = len(imported.mappings), len(current.mappings)
            ask(self, T("割り当てを読み込みます", "Import mappings"),
                T(f"ファイルに {n_new} 件、今の設定に {n_old} 件あります。どうしますか?",
                  f"The file has {n_new} mappings, you currently have {n_old}. What should happen?"),
                [("merge", T("追加する (同じキーはファイル側を優先)", "Add (file wins on conflicts)"), "suggested"),
                 ("replace", T("置き換える", "Replace everything"), "destructive")],
                lambda choice: choice in ("merge", "replace") and self._apply_import(imported, choice, skipped))
            return True
        self._apply_import(imported, mode or "replace", skipped)
        return True

    def _apply_import(self, imported: Preset, mode: str, skipped: int) -> None:
        before = self.cfg().preset.copy()
        if mode == "replace":
            self.cfg().preset.mappings = list(imported.mappings)
        else:
            for m in imported.mappings:
                self.cfg().preset.set(m)
        self.trigger = ()
        self._after_edit(True)
        n = len(imported.mappings)
        msg = T(f"{n} 件の割り当てを読み込みました", f"Imported {n} mappings")
        if skipped:
            msg += T(f" ({skipped} 件は無効なため除外)", f" ({skipped} skipped as invalid)")
        toast = Adw.Toast.new(msg)
        toast.set_button_label(T("元に戻す", "Undo"))
        toast.set_timeout(8)

        def undo(*_):
            self.cfg().preset.mappings = list(before.mappings)
            self.trigger = ()
            self._after_edit(True)

        toast.connect("button-clicked", undo)
        self.toasts.add_toast(toast)

    def _filter_row(self, row) -> bool:
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        m = getattr(row, "mapping", None)
        if m is None:
            return True
        hay = (keys.chord_name(m.trigger, "ja") + keys.chord_name(m.trigger, "en") +
               m.action.describe("ja") + m.action.describe("en")).lower()
        return q in hay

    def _on_row_activated(self, lb, row) -> None:
        m = getattr(row, "mapping", None)
        if m is not None:
            self.select_trigger(m.trigger)

    def _refresh_editor(self) -> None:
        mapping = self.cfg().preset.find(self.trigger) if (self.model and self.trigger) else None
        self.editor.show_trigger(self.trigger if self.model else (), mapping)

    def _refresh_all(self) -> None:
        if not self.model:
            return
        self._refresh_keyboard()
        self._refresh_sidebar()
        self._refresh_editor()
        self._update_status()

    def _update_status(self) -> None:
        d = next((x for x in self.devs if x["model"] == self.model), None)
        pill = self.status_pill
        for c in ("on", "off"):
            pill.remove_css_class(c)
        if not self.link.connected:
            pill.set_label(T("未接続", "Offline"))
            pill.add_css_class("off")
        elif d and d.get("applied"):
            pill.set_label(T("適用中", "Active"))
            pill.add_css_class("on")
        elif self.model in self.config.devices and not self.cfg().preset.mappings:
            pill.set_label(T("割り当てなし", "No mappings"))
            pill.add_css_class("off")
        else:
            pill.set_label(T("停止中", "Inactive"))
            pill.add_css_class("off")

    # ---------------------------------------------------------- selection

    def select_trigger(self, trigger: tuple[str, ...]) -> None:
        self.trigger = tuple(trigger)
        # show the matching layer on the keyboard
        mods = {g for g in (_generic_of_name(n) for n in trigger[:-1]) if g}
        self.sticky = mods
        self._refresh_all()

    def on_key_clicked(self, name: str) -> None:
        if not self.model:
            return
        if keys.generic_of(keys.name_to_code(name) or -1):
            self.sticky = set()
            self.trigger = (name,)
        else:
            mods = [g for g in GENERIC if g in self._layer()]
            self.trigger = tuple(mods + [name])
        self._refresh_all()

    def _on_layer_toggled(self, btn, g: str) -> None:
        if self._updating:
            return
        if btn.get_active():
            self.sticky.add(g)
        else:
            self.sticky.discard(g)
            # physically held modifiers stay on until released
        if self.trigger:
            last = self.trigger[-1]
            if not keys.generic_of(keys.name_to_code(last) or -1):
                mods = [x for x in GENERIC if x in self._layer()]
                self.trigger = tuple(mods + [last])
        self._refresh_all()

    # ------------------------------------------------------------ editing

    def set_mapping(self, mapping: Mapping, rebuild: bool = True) -> None:
        self.cfg().preset.set(mapping)
        self.trigger = mapping.trigger
        self._after_edit(rebuild)

    def _after_edit(self, rebuild: bool) -> None:
        self._save_soon()
        self._update_status()
        self._refresh_keyboard()
        self._refresh_sidebar()
        if rebuild:
            self._refresh_editor()
        else:
            m = self.cfg().preset.find(self.trigger)
            self.editor.mapping = m
            self.editor.refresh_summary()

    def delete_mapping(self) -> None:
        """Remove the mapping being edited (editor button)."""
        m = self.cfg().preset.find(self.trigger) if self.trigger else None
        if m is not None:
            self.remove_mappings([m])

    def _undo_delete(self, m: Mapping) -> None:
        self._undo_removed([m])

    def _on_enable_toggled(self, *_) -> None:
        if self._updating or not self.model:
            return
        self.cfg().enabled = self.enable_switch.get_active()
        self._save_soon()

    def _on_layout_changed(self, *_) -> None:
        if self._updating or not self.model:
            return
        cfg = self.cfg()
        cfg.standard = layouts.STANDARDS[self.std_drop.get_selected()]
        cfg.size = layouts.SIZE_IDS[self.size_drop.get_selected()]
        self.keyboard.set_layout(layouts.build(cfg.standard, cfg.size))
        self._refresh_keyboard()
        self._refresh_sidebar()
        self._save_soon()

    # ---------------------------------------------------- save and push

    def _save_soon(self) -> None:
        if self._save_timer:
            GLib.source_remove(self._save_timer)
        self._save_timer = GLib.timeout_add(250, self._flush)

    def _flush(self) -> bool:
        self._save_timer = 0
        self.config.save()
        if self.model:
            self._push(self.model)
        return False

    def _push(self, model: str) -> None:
        cfg = self.config.devices.get(model)
        if cfg is None or not self.link.connected:
            return
        if cfg.preset.mappings:
            payload = json.dumps([cfg.preset.to_dict(), cfg.enabled], sort_keys=True)
            if self._pushed.get(model) == payload:
                return
            self._pushed[model] = payload
            self.link.apply(model, cfg.preset.to_dict(), cfg.enabled)
        else:
            if self._pushed.get(model) == "forget":
                return
            self._pushed[model] = "forget"
            self.link.forget(model)

    def _on_close(self, *_) -> bool:
        if self._save_timer:
            GLib.source_remove(self._save_timer)
            self._flush()
        self.config.save()
        return False

    # ------------------------------------------------------------ key input

    def capture_keys(self, on: bool) -> None:
        self.recording = on
        if self.link.connected and self.model:
            self.link.capture(self.model, on)
        self.link.monitor(on or self.is_active())

    def _on_active(self, *_) -> None:
        if self.link.connected:
            self.link.monitor(self.is_active() or self.recording)
        if not self.is_active() and self.held:
            self.held.clear()
            self._refresh_keyboard()

    def _on_daemon_key(self, msg: dict) -> None:
        if msg.get("model") != self.model:
            return
        if not (self.is_active() or self.recording):
            return
        if not self.recording and (self.modal_open or isinstance(self.get_focus(), Gtk.Editable)):
            # typing in a search box: don't hijack
            self._track_held(msg["code"], msg["value"], select=False)
            return
        self._feed(msg["code"], msg["value"])

    def _on_gtk_key(self, ctl, keyval, keycode, state, _v=1) -> bool:
        code = keycode - 8
        if self.link.connected and self.model:
            return self.recording            # daemon delivers the physical events instead
        if not self.recording and (self.modal_open or isinstance(self.get_focus(), Gtk.Editable)):
            return False
        if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and not self.recording:
            return False
        self._feed(code, 1)
        return True

    def _on_gtk_key_release(self, ctl, keyval, keycode, state) -> None:
        if self.link.connected and self.model:
            return
        if self.recording or self.held:
            self._feed(keycode - 8, 0)

    def _feed(self, code: int, value: int) -> None:
        if self.recorder.active:
            self.recorder.feed(code, value)
            return
        self._track_held(code, value, select=True)

    def _track_held(self, code: int, value: int, select: bool) -> None:
        if value == 2:
            return
        is_mod = keys.generic_of(code) is not None
        if value == 1:
            if not self.held:
                self._mod_candidate = code if is_mod else None
                self._peak_mods = [code] if is_mod else []
            elif not is_mod:
                self._mod_candidate = None
                self._peak_mods = []
            elif self._mod_candidate is not None:
                self._peak_mods.append(code)
            self.held.add(code)
            nm = keys.code_to_name(code)
            if nm not in self.keyboard.layout.by_name() and not is_mod:
                self.extra_seen.add(nm)
            if select and not is_mod and self.model:
                mods = [g for g in GENERIC if g in self._layer()]
                self.trigger = tuple(mods + [keys.code_to_name(code)])
                self.sticky = set(mods)      # keep that layer on screen after the keys are released
                self._refresh_all()
                return
        else:
            self.held.discard(code)
            if select and is_mod and self._mod_candidate is not None and self.model \
                    and (self._mod_candidate == code or len(self._peak_mods) >= 2):
                # a modifier tapped alone, or several modifiers pressed and released together
                names = [keys.code_to_name(c) for c in self._peak_mods] if len(self._peak_mods) >= 2 \
                    else [keys.code_to_name(code)]
                self.sticky = set()
                self.trigger = tuple(names)
                self._mod_candidate = None
                self._peak_mods = []
                self._refresh_all()
                return
        self._refresh_keyboard()

    # ---------------------------------------------------------- service

    def _start_service(self, *_, verb: str = "start") -> None:
        try:
            p = Gio.Subprocess.new(["pkexec", "systemctl", verb, "keyboard-remapperd.service"],
                                   Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            self.toasts.add_toast(Adw.Toast.new(T("pkexec を起動できませんでした", "Could not run pkexec")))
            return

        def done(proc, res):
            try:
                proc.wait_finish(res)
            except GLib.Error:
                pass
            if not proc.get_successful():
                self.toasts.add_toast(Adw.Toast.new(T(
                    "起動に失敗しました。keyboard-remapperd.service がインストールされているか確認してください",
                    "Could not start it. Is keyboard-remapperd.service installed?")))

        p.wait_async(None, done)
