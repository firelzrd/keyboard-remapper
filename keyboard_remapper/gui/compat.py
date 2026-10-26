"""Fallbacks so the GUI also runs on older libadwaita / GTK (e.g. Ubuntu 22.04).

Set ``KEYBOARD_REMAPPER_COMPAT=1`` to force the legacy code paths (used by the tests).
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk  # noqa: E402

FORCE_LEGACY = bool(os.environ.get("KEYBOARD_REMAPPER_COMPAT"))
HAS_SPLIT = hasattr(Adw, "OverlaySplitView") and hasattr(Adw, "Breakpoint") and not FORCE_LEGACY
HAS_BANNER = hasattr(Adw, "Banner") and not FORCE_LEGACY
HAS_ABOUT_DIALOG = hasattr(Adw, "AboutDialog") and not FORCE_LEGACY


def set_placeholder(entry: Gtk.Widget, text: str) -> None:
    """``Gtk.SearchEntry`` only gained a placeholder in GTK 4.10."""
    try:
        entry.set_placeholder_text(text)
    except (AttributeError, TypeError):
        pass


def load_css(provider: Gtk.CssProvider, css: str) -> None:
    try:
        provider.load_from_string(css)               # GTK >= 4.12
    except AttributeError:
        try:
            provider.load_from_data(css.encode(), -1)    # GTK < 4.9
        except TypeError:
            provider.load_from_data(css.encode())


class LegacyBanner(Gtk.Revealer):
    """Minimal stand-in for ``Adw.Banner`` (libadwaita < 1.3)."""

    __gsignals__ = {"button-clicked": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, title: str):
        super().__init__()
        box = Gtk.Box(spacing=12)
        box.add_css_class("legacy-banner")
        self._label = Gtk.Label(label=title, xalign=0, hexpand=True, wrap=True)
        self._button = Gtk.Button(label="")
        self._button.add_css_class("suggested-action")
        self._button.connect("clicked", lambda *_: self.emit("button-clicked"))
        box.append(self._label)
        box.append(self._button)
        self.set_child(box)
        self.set_reveal_child(False)

    def set_button_label(self, label: str) -> None:
        self._button.set_label(label)

    def set_revealed(self, on: bool) -> None:
        self.set_reveal_child(on)

    def get_revealed(self) -> bool:
        return self.get_reveal_child()


def make_banner(title: str):
    if HAS_BANNER:
        return Adw.Banner(title=title)
    return LegacyBanner(title)


class Layout:
    """Content + collapsible sidebar on the right.

    ``Adw.OverlaySplitView`` + breakpoint where available, ``Adw.Flap`` otherwise.
    ``toggle`` is the header button that shows the sidebar when it is collapsed.
    """

    def __init__(self, window, toggle: Gtk.ToggleButton):
        self.toggle = toggle
        if HAS_SPLIT:
            self.widget = Adw.OverlaySplitView()
            self.widget.set_sidebar_position(Gtk.PackType.END)
            self.widget.set_min_sidebar_width(260)
            self.widget.set_max_sidebar_width(340)
            self.widget.set_sidebar_width_fraction(0.28)
            toggle.bind_property("active", self.widget, "show-sidebar",
                                 GObject.BindingFlags.BIDIRECTIONAL)
            bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 900sp"))
            bp.add_setter(self.widget, "collapsed", True)
            bp.add_setter(toggle, "visible", True)
            window.add_breakpoint(bp)
        else:
            self.widget = Adw.Flap()
            self.widget.set_flap_position(Gtk.PackType.END)
            self.widget.set_fold_policy(Adw.FlapFoldPolicy.AUTO)
            self.widget.set_transition_type(Adw.FlapTransitionType.OVER)
            self.widget.set_swipe_to_open(False)
            self.widget.set_swipe_to_close(False)
            self.widget.set_separator(Gtk.Separator())
            toggle.bind_property("active", self.widget, "reveal-flap",
                                 GObject.BindingFlags.BIDIRECTIONAL)
            self.widget.connect("notify::folded", self._folded)
            self._folded()

    def _folded(self, *_) -> None:
        folded = self.widget.get_folded()
        self.toggle.set_visible(folded)
        self.toggle.set_active(not folded)       # wide: sidebar always shown; narrow: starts hidden

    def set_content(self, w: Gtk.Widget) -> None:
        self.widget.set_content(w)

    def set_sidebar(self, w: Gtk.Widget) -> None:
        if HAS_SPLIT:
            self.widget.set_sidebar(w)
        else:
            clamp = Adw.Clamp(maximum_size=320, tightening_threshold=320)   # Flap uses the natural width
            clamp.set_size_request(300, -1)
            clamp.set_hexpand(False)         # an expanding child (search entry) would grab half the window
            clamp.set_child(w)
            self.widget.set_flap(clamp)


def ask(window, heading: str, body: str, choices: list[tuple[str, str, str]], callback) -> None:
    """Ask a question: choices are (id, label, style) with style 'suggested'/'destructive'/''.

    ``callback(choice_id)`` gets the chosen id, or ``"cancel"``.  Uses Adw.MessageDialog (>= 1.2),
    otherwise Gtk.MessageDialog.
    """
    if hasattr(Adw, "MessageDialog"):
        d = Adw.MessageDialog.new(window, heading, body)
        d.add_response("cancel", T_CANCEL())
        for cid, label, style in choices:
            d.add_response(cid, label)
            if style == "suggested":
                d.set_response_appearance(cid, Adw.ResponseAppearance.SUGGESTED)
            elif style == "destructive":
                d.set_response_appearance(cid, Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response(choices[0][0])
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: callback(r))
        d.present()
        return
    d = Gtk.MessageDialog(transient_for=window, modal=True, message_type=Gtk.MessageType.QUESTION,
                          text=heading, secondary_text=body)
    ids = {}
    d.add_button(T_CANCEL(), Gtk.ResponseType.CANCEL)
    for i, (cid, label, _style) in enumerate(choices, start=1):
        d.add_button(label, i)
        ids[i] = cid

    def on_response(dlg, resp):
        dlg.destroy()
        callback(ids.get(resp, "cancel"))

    d.connect("response", on_response)
    d.present()


def T_CANCEL() -> str:
    from ..i18n import T
    return T("キャンセル", "Cancel")


_KEEP = []     # keeps native dialogs alive until they answer


def choose_file(window, save: bool, title: str, filename: str, callback) -> None:
    """Open/save a JSON file.  ``callback(path)`` is called only when the user picked one."""
    from gi.repository import Gio, GLib
    from ..i18n import T
    flt = Gtk.FileFilter()
    flt.set_name("JSON")
    flt.add_pattern("*.json")
    if hasattr(Gtk, "FileDialog"):                      # GTK >= 4.10
        d = Gtk.FileDialog()
        d.set_title(title)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(flt)
        d.set_filters(filters)
        if save:
            d.set_initial_name(filename)

        def done(dlg, res):
            try:
                f = dlg.save_finish(res) if save else dlg.open_finish(res)
            except GLib.Error:
                return
            if f is not None and f.get_path():
                callback(f.get_path())

        (d.save if save else d.open)(window, None, done)
        return
    action = Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN
    n = Gtk.FileChooserNative.new(title, window, action, T("保存", "Save") if save else T("開く", "Open"),
                                  T("キャンセル", "Cancel"))
    n.add_filter(flt)
    if save:
        n.set_current_name(filename)
    _KEEP.append(n)

    def resp(dlg, r):
        if r == Gtk.ResponseType.ACCEPT and dlg.get_file() and dlg.get_file().get_path():
            callback(dlg.get_file().get_path())
        dlg.destroy()
        if dlg in _KEEP:
            _KEEP.remove(dlg)

    n.connect("response", resp)
    n.show()
