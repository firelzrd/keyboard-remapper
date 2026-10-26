"""The keyboard drawing: realistic 3D keycaps, live press feedback, mapping overlay."""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import GObject, Gtk, Pango, PangoCairo  # noqa: E402

from .. import keys, layouts  # noqa: E402
from ..i18n import LANG, T  # noqa: E402

GAP = 0.055          # gap between caps, in key units
DEPTH = 0.075        # visible cap side height
MAX_UNIT = 50        # px per key unit; keeps compact keyboards from towering over the editor


def _rgb(h: str, a: float = 1.0):
    h = h.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a


def _mix(c1, c2, t):
    return tuple(c1[i] * (1 - t) + c2[i] * t for i in range(3)) + (c1[3] * (1 - t) + c2[3] * t,)


PALETTES = {
    "light": dict(
        plate=_rgb("#d5d9e0"), plate_edge=_rgb("#bfc5cf"),
        cap=_rgb("#fbfbfd"), cap_side=_rgb("#b4bac6"), mod=_rgb("#eceef3"),
        text=_rgb("#2b2f38"), text_dim=_rgb("#7d8493"),
        accent=_rgb("#3584e4"), accent_text=_rgb("#ffffff"),
    ),
    "dark": dict(
        plate=_rgb("#1f2228"), plate_edge=_rgb("#15171b"),
        cap=_rgb("#3c414b"), cap_side=_rgb("#171a1f"), mod=_rgb("#333842"),
        text=_rgb("#eef0f5"), text_dim=_rgb("#9aa1af"),
        accent=_rgb("#62a0ea"), accent_text=_rgb("#0b1a2e"),
    ),
}


class KeyboardView(Gtk.DrawingArea):
    """Draws a layout.  The owner feeds it state; it reports clicks.

    ``assignments``  maps key name -> short text of what the *current layer* does there.
    ``other_layers`` is a set of key names that have mappings in some other layer.
    """

    __gsignals__ = {
        "key-clicked": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self.layout = layouts.build("ansi", "full")
        self.selected: str | None = None
        self.layer: set[str] = set()            # generic modifier names shown as active
        self.pressed: set[int] = set()          # physical codes currently down
        self.assignments: dict[str, str] = {}
        self.other_layers: set[str] = set()
        self.extras: list[str] = []             # keys the layout lacks but the user uses / pressed
        self.hover: str | None = None
        self.pulse: dict[str, float] = {}       # key -> animation progress 0..1 (just changed)
        self._hit: list[tuple[str, tuple[float, float, float, float]]] = []
        self._dark = False
        self._pulse_tick = 0
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.set_draw_func(self._draw)
        self.add_css_class("keyboard-view")

        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)
        self.set_focusable(False)

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        """Height follows width so the keyboard always keeps its proportions.

        Minimum == natural so a tall page scrolls instead of squashing the keyboard.
        """
        a = self.aspect()
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 360, 1000, -1, -1
        w = for_size if for_size > 0 else 900
        h = int(min(w, (self.layout.width + 1.2) * MAX_UNIT) / a)
        return h, h, -1, -1

    # -- state setters -----------------------------------------------------

    EXTRA_TITLE_H = 0.55
    EXTRA_PER_ROW = 12

    def _extra_shapes(self) -> tuple[list[layouts.KeyShape], float]:
        """Keys that are not on the drawn layout, in a strip below it, and the strip's height."""
        names = [n for n in self.extras if n not in self.layout.by_name()]
        if not names:
            return [], 0.0
        top = self.layout.height + 0.3 + self.EXTRA_TITLE_H
        shapes = []
        for i, n in enumerate(names):
            r, c = divmod(i, self.EXTRA_PER_ROW)
            shapes.append(layouts.KeyShape(n, ((c * 1.3, top + r * 1.1, 1.3, 1.0),)))
        rows = (len(names) + self.EXTRA_PER_ROW - 1) // self.EXTRA_PER_ROW
        return shapes, 0.3 + self.EXTRA_TITLE_H + rows * 1.1

    def _total_height(self) -> float:
        return self.layout.height + self._extra_shapes()[1]

    def aspect(self) -> float:
        """Width / height that fits the layout including the plate."""
        return (self.layout.width + 0.9 + 0.3) / (self._total_height() + 0.9 + 0.3)

    def set_layout(self, layout: layouts.Layout) -> None:
        self.layout = layout
        self.queue_resize()
        self.queue_draw()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.queue_draw()

    def set_state(self, *, selected="__keep__", layer=None, assignments=None, other_layers=None,
                  extras=None) -> None:
        if extras is not None and extras != self.extras:
            self.extras = list(extras)
            self.queue_resize()
        if selected != "__keep__":
            self.selected = selected
        if layer is not None:
            self.layer = set(layer)
        if assignments is not None:
            self.assignments = assignments
        if other_layers is not None:
            self.other_layers = other_layers
        self.queue_draw()

    def set_pressed(self, pressed: set[int]) -> None:
        if pressed != self.pressed:
            self.pressed = set(pressed)
            self.queue_draw()

    # -- geometry ----------------------------------------------------------

    def _metrics(self, w: float, h: float):
        pad = 12
        L = self.layout
        # the plate extends 0.45u beyond the keys on every side
        u = min((w - 2 * pad) / (L.width + 0.9), (h - 2 * pad) / (self._total_height() + 0.9),
                MAX_UNIT)
        ox = (w - L.width * u) / 2
        oy = (h - self._total_height() * u) / 2
        return u, ox, oy

    def _key_at(self, x: float, y: float) -> str | None:
        for name, (rx, ry, rw, rh) in reversed(self._hit):
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return name
        return None

    def _on_click(self, gesture, n, x, y) -> None:
        name = self._key_at(x, y)
        if name:
            self.emit("key-clicked", name)

    def _on_motion(self, ctl, x, y) -> None:
        name = self._key_at(x, y)
        if name != self.hover:
            self.hover = name
            self.set_cursor_from_name("pointer" if name else None)
            if name:
                tip = keys.key_name(name, LANG)
                a = self.assignments.get(name)
                self.set_tooltip_text(f"{tip}  →  {a}" if a else tip)
            else:
                self.set_tooltip_text(None)
            self.queue_draw()

    def _on_leave(self, ctl) -> None:
        if self.hover:
            self.hover = None
            self.set_cursor_from_name(None)
            self.set_tooltip_text(None)
            self.queue_draw()

    # -- drawing -----------------------------------------------------------

    def _accent(self, p):
        ctx = self.get_style_context()
        ok, rgba = ctx.lookup_color("accent_bg_color")
        if ok:
            return (rgba.red, rgba.green, rgba.blue, 1.0)
        return p["accent"]

    def _draw(self, area, cr, w, h) -> None:
        p = PALETTES["dark" if self._dark else "light"]
        accent = self._accent(p)
        u, ox, oy = self._metrics(w, h)
        self._hit = []

        # plate
        pad = 0.45 * u
        self._round_rect(cr, ox - pad, oy - pad, self.layout.width * u + 2 * pad,
                         self._total_height() * u + 2 * pad, 0.35 * u)
        cr.set_source_rgba(*p["plate"])
        cr.fill_preserve()
        cr.set_source_rgba(*p["plate_edge"])
        cr.set_line_width(1.2)
        cr.stroke()

        for shape in self.layout.keys:
            self._draw_key(cr, shape, u, ox, oy, p, accent)
        extra, _h = self._extra_shapes()
        if extra:
            self._text(cr, T("その他のキー", "Other keys"), ox + 0.1 * u,
                       oy + (self.layout.height + 0.3) * u, 4 * u, 0.3 * u, p["text_dim"])
            for shape in extra:
                self._draw_key(cr, shape, u, ox, oy, p, accent)

    def _draw_key(self, cr, shape, u, ox, oy, p, accent) -> None:
        name = shape.name
        code = keys.name_to_code(name)
        pressed = code in self.pressed
        selected = name == self.selected
        generic = keys.generic_of(code) if code is not None else None
        in_layer = generic in self.layer if generic else False
        assigned = self.assignments.get(name)
        hovered = name == self.hover
        is_mod = generic is not None

        base = p["mod"] if (is_mod or name in ("ENTER", "TAB", "BACKSPACE", "CAPSLOCK", "ESC",
                                                 "SPACE", "COMPOSE", "ZENKAKUHANKAKU")) else p["cap"]
        top = base
        text = p["text"]
        if assigned:
            top = _mix(base, accent, 0.30 if not self._dark else 0.42)
        if in_layer or pressed:
            top = _mix(base, accent, 0.85)
            text = p["accent_text"] if not self._dark else (1, 1, 1, 1)
        elif hovered:
            top = _mix(top, (1, 1, 1, 1) if self._dark else accent, 0.10)
        side = _mix(p["cap_side"], accent, 0.35) if (assigned or in_layer or pressed) else p["cap_side"]

        dy = DEPTH * u if pressed else 0
        if shape.poly:
            pts = self._inset_poly(shape.poly, GAP, ox, oy, u)
            depth = DEPTH * u
            self._hit.append((name, tuple(self._poly_bbox(pts))))
            self._round_poly(cr, [(x, y + depth) for x, y in pts], 0.13 * u)
            cr.set_source_rgba(*side)
            cr.fill()
            self._round_poly(cr, [(x, y + dy) for x, y in pts], 0.13 * u)
            cr.set_source_rgba(*top)
            cr.fill_preserve()
            if selected:
                cr.set_source_rgba(*accent)
                cr.set_line_width(max(2.2, 0.075 * u))
            else:
                cr.set_source_rgba(0, 0, 0, 0.10 if not self._dark else 0.35)
                cr.set_line_width(0.8)
            cr.stroke()
        first = True
        for (kx, ky, kw, kh) in (shape.rects if not shape.poly else ()):
            x = ox + (kx + GAP) * u
            y = oy + (ky + GAP) * u
            w = (kw - 2 * GAP) * u
            h = (kh - 2 * GAP) * u
            if first:
                self._hit.append((name, (x, y, w, h)))
            r = 0.13 * u
            depth = DEPTH * u
            # side / shadow
            self._round_rect(cr, x, y + depth, w, h, r)
            cr.set_source_rgba(*side)
            cr.fill()
            # top face
            self._round_rect(cr, x, y + dy, w, h - (depth if not pressed else 0) * 0, r)
            cr.set_source_rgba(*top)
            cr.fill_preserve()
            if selected:
                cr.set_source_rgba(*accent)
                cr.set_line_width(max(2.2, 0.075 * u))
                cr.stroke()
            else:
                cr.set_source_rgba(0, 0, 0, 0.10 if not self._dark else 0.35)
                cr.set_line_width(0.8)
                cr.stroke()
            first = False

        # legends on the first rect (ENTER: on the upper part)
        kx, ky, kw, kh = shape.rects[0]
        x = ox + (kx + GAP) * u
        y = oy + (ky + GAP) * u + dy
        w = (kw - 2 * GAP) * u
        h = (kh - 2 * GAP) * u
        self._legends(cr, name, x, y, w, h, u, text, p, accent, assigned, bool(in_layer or pressed))

        if name in self.other_layers and not assigned:
            cr.arc(x + w - 0.16 * u, y + 0.16 * u, 0.065 * u, 0, 2 * math.pi)
            cr.set_source_rgba(*accent)
            cr.fill()

    def _legends(self, cr, name, x, y, w, h, u, text, p, accent, assigned, active) -> None:
        top_txt, main_txt = keys.cap_legend(name, self.layout.family, LANG)
        if assigned:
            # show what it does, big; the original legend becomes the small one
            self._text(cr, main_txt or top_txt, x + 0.1 * u, y + 0.07 * u, w - 0.2 * u, 0.24 * u,
                       p["text_dim"] if not active else text, align="left", bold=False)
            self._text(cr, "→ " + assigned, x + 0.06 * u, y + h - 0.50 * u, w - 0.12 * u, 0.30 * u,
                       accent if not active else text, align="center", bold=True, anchor_bottom=h)
            return
        multi_row = bool(top_txt)
        if multi_row and top_txt != main_txt:
            self._text(cr, top_txt, x + 0.1 * u, y + 0.08 * u, w - 0.2 * u, 0.27 * u,
                       p["text_dim"] if not active else text, align="left")
            self._text(cr, main_txt, x + 0.1 * u, y + h - 0.50 * u, w - 0.2 * u, 0.32 * u,
                       text, align="left", bold=False)
            return
        size = 0.34 * u
        if len(main_txt) > 4:
            size = 0.25 * u
        if len(main_txt) > 7:
            size = 0.22 * u
        single = len(main_txt) <= 1 and name not in ("SPACE",)
        if single:
            self._text(cr, main_txt, x, y, w, h - 0.02 * u, text, size=0.40 * u, align="center",
                       vcenter=True, bold=False)
        else:
            self._text(cr, main_txt, x + 0.08 * u, y + 0.08 * u, w - 0.16 * u, size,
                       text, size=size, align="left" if len(main_txt) > 3 else "center")

    def _text(self, cr, s, x, y, w, size_or_h, color=None, size=None, align="left", bold=False,
              vcenter=False, anchor_bottom=None) -> None:
        if not s:
            return
        if isinstance(color, (int, float)):       # (cr, s, x, y, w, size, color...) misuse guard
            return
        # The widget's own Pango context: the system UI font (and its rendering settings), so the
        # keycaps look like the rest of the window.  Only size and weight are ours.
        layout = self.create_pango_layout(None)
        fsize = size if size is not None else size_or_h
        desc = self.get_pango_context().get_font_description().copy()
        desc.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
        desc.set_absolute_size(max(7.0, fsize) * Pango.SCALE)
        layout.set_font_description(desc)
        layout.set_text(s, -1)
        cur = max(7.0, fsize)
        for _ in range(6):                           # shrink to fit instead of eliding
            nat, _h = layout.get_pixel_size()
            if nat <= w * 0.96 or cur <= 6.0:
                break
            cur = max(6.0, cur * w * 0.93 / nat)
            desc.set_absolute_size(cur * Pango.SCALE)
            layout.set_font_description(desc)
        layout.set_width(int(w * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout.set_alignment({"left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER,
                              "right": Pango.Alignment.RIGHT}[align])
        layout.set_text(s, -1)
        _, lh = layout.get_pixel_size()
        yy = y
        if vcenter:
            yy = y + (size_or_h - lh) / 2
        cr.set_source_rgba(*(color or (0, 0, 0, 1)))
        cr.move_to(x, yy)
        PangoCairo.show_layout(cr, layout)

    @staticmethod
    def _poly_bbox(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    @staticmethod
    def _inset_poly(poly, gap, ox, oy, u):
        """Shrink an axis-aligned polygon by *gap* on every side."""
        n = len(poly)
        area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
        sign = 1 if area > 0 else -1
        out = []
        for i in range(n):
            px, py = poly[i]
            ax, ay = poly[i - 1]
            bx, by = poly[(i + 1) % n]
            d1 = ((px - ax), (py - ay))
            d2 = ((bx - px), (by - py))
            l1 = abs(d1[0]) + abs(d1[1])
            l2 = abs(d2[0]) + abs(d2[1])
            n1 = (-sign * d1[1] / l1, sign * d1[0] / l1)    # inward normals (y points down)
            n2 = (-sign * d2[1] / l2, sign * d2[0] / l2)
            out.append((ox + (px + (n1[0] + n2[0]) * gap) * u, oy + (py + (n1[1] + n2[1]) * gap) * u))
        return out

    @staticmethod
    def _round_poly(cr, pts, r) -> None:
        n = len(pts)
        cr.new_sub_path()
        for i in range(n):
            p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
            d1 = (p1[0] - p0[0], p1[1] - p0[1])
            d2 = (p2[0] - p1[0], p2[1] - p1[1])
            l1 = math.hypot(*d1) or 1
            l2 = math.hypot(*d2) or 1
            rr = min(r, l1 / 2, l2 / 2)
            a = (p1[0] - d1[0] / l1 * rr, p1[1] - d1[1] / l1 * rr)
            b = (p1[0] + d2[0] / l2 * rr, p1[1] + d2[1] / l2 * rr)
            if i == 0:
                cr.move_to(*a)
            else:
                cr.line_to(*a)
            cr.curve_to(p1[0], p1[1], p1[0], p1[1], b[0], b[1])
        cr.close_path()

    @staticmethod
    def _round_rect(cr, x, y, w, h, r) -> None:
        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
