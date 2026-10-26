"""keyboard-remapper entry point."""

from __future__ import annotations

import argparse
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .. import APP_ID, __version__  # noqa: E402
from ..daemon import DEFAULT_SOCKET  # noqa: E402
from ..i18n import T  # noqa: E402
from .compat import HAS_ABOUT_DIALOG, load_css  # noqa: E402
from .style import CSS  # noqa: E402
from .window import MainWindow  # noqa: E402


class App(Adw.Application):
    def __init__(self, socket_path: str):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE
                         if socket_path != DEFAULT_SOCKET else Gio.ApplicationFlags.FLAGS_NONE)
        self.socket_path = socket_path
        self.win: MainWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        prov = Gtk.CssProvider()
        load_css(prov, CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.set_accels_for_action("win.quit", ["<Primary>q"])

    def do_activate(self) -> None:
        if self.win is None:
            self.win = MainWindow(self, self.socket_path)
        self.win.present()

    def _about(self, *_) -> None:
        comments = T("Linux 向けのキーボード割り当てツール。\n修飾キーとの組み合わせでも固まりません。",
                     "A keyboard remapper for Linux.\nNo stalls on modifier + key combos.")
        if HAS_ABOUT_DIALOG:                               # libadwaita >= 1.5
            d = Adw.AboutDialog()
            d.set_application_name("Keyboard Remapper")
            d.set_version(__version__)
            d.set_comments(comments)
            d.set_license_type(Gtk.License.GPL_3_0)
            d.present(self.win)
        elif hasattr(Adw, "AboutWindow"):                  # libadwaita >= 1.2
            d = Adw.AboutWindow(transient_for=self.win)
            d.set_application_name("Keyboard Remapper")
            d.set_version(__version__)
            d.set_comments(comments)
            d.set_license_type(Gtk.License.GPL_3_0)
            d.present()
        else:
            d = Gtk.AboutDialog(transient_for=self.win, modal=True, program_name="Keyboard Remapper",
                                version=__version__, comments=comments,
                                license_type=Gtk.License.GPL_3_0)
            d.present()


MIN_ADW = (1, 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="keyboard-remapper")
    ap.add_argument("--version", action="version", version=f"keyboard-remapper {__version__}")
    ap.add_argument("--socket", default=DEFAULT_SOCKET, help="daemon socket path")
    args, rest = ap.parse_known_args(argv)
    if (Adw.get_major_version(), Adw.get_minor_version()) < MIN_ADW:
        print(f"Keyboard Remapper needs libadwaita >= {MIN_ADW[0]}.{MIN_ADW[1]} (found "
              f"{Adw.get_major_version()}.{Adw.get_minor_version()}).\n"
              "Ubuntu 22.04 or newer provides it.", file=sys.stderr)
        return 1
    app = App(args.socket)
    return app.run([sys.argv[0]] + rest)


if __name__ == "__main__":
    sys.exit(main())
