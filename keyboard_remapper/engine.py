"""Key translation engine.

The engine is pure logic: it consumes physical key events and drives a single
:class:`Output`.  All keyboards and all mappings feed the *same* output, which
in the daemon is one persistent uinput device.  That is what avoids the
desktop-shortcut re-registration stall input-remapper 2 suffers from (it emits
from two different virtual devices, so every modifier/normal key hand-over
makes the X server / compositor re-read the keymap).

Output model
------------
Every held physical key owns a *claim* on a set of output keys.  The keys that
are down on the virtual device are the union of all non-suppressed claims.  A
trigger's modifiers are not released on the spot when a mapping fires; their
claim is *suppressed* (so the application does not see ``Ctrl+Down`` for a
``Ctrl+J -> Down`` mapping) and restored lazily, only if the next key press
actually needs it.  Pressing ``Ctrl`` once and then ``J`` ten times therefore
produces ten ``Down`` taps and not a single extra modifier event.
"""

from __future__ import annotations

from typing import Callable, Hashable, Protocol

from . import keys
from .mapping import ACTION_DISABLE, ACTION_KEY, Mapping, Preset, is_chord_tap, parse_step


class Scheduler(Protocol):
    def call_later(self, delay_ms: int, fn: Callable[[], None]) -> object: ...


class Output:
    """Tracks which keys are down on the output device and emits the diff."""

    def __init__(self, emit: Callable[[int, int], None]):
        self._emit = emit
        self.claims: dict[Hashable, tuple[int, ...]] = {}
        self.suppressed: set[Hashable] = set()
        self.pressed: dict[int, None] = {}

    def claim(self, owner: Hashable, codes) -> None:
        self.claims[owner] = tuple(codes)

    def unclaim(self, owner: Hashable) -> None:
        self.claims.pop(owner, None)
        self.suppressed.discard(owner)

    def suppress(self, owner: Hashable) -> None:
        if owner in self.claims:
            self.suppressed.add(owner)

    def unsuppress(self, owner: Hashable) -> None:
        self.suppressed.discard(owner)

    def desired(self) -> list[int]:
        seen: dict[int, None] = {}
        for owner, codes in self.claims.items():
            if owner in self.suppressed:
                continue
            for c in codes:
                seen.setdefault(c, None)
        return list(seen)

    def sync(self) -> None:
        want = self.desired()
        want_set = set(want)
        # release plain keys first, modifiers last
        gone = [c for c in self.pressed if c not in want_set]
        gone.sort(key=keys.is_modifier)
        for c in gone:
            del self.pressed[c]
            self._emit(c, 0)
        new = [c for c in want if c not in self.pressed]
        new.sort(key=lambda c: not keys.is_modifier(c))  # stable: modifiers first
        for c in new:
            self.pressed[c] = None
            self._emit(c, 1)

    def tap_guard(self) -> None:
        """Slip in a harmless key so a following modifier release is not a 'tap'."""
        self._emit(keys.TAP_GUARD_KEY, 1)
        self._emit(keys.TAP_GUARD_KEY, 0)

    def release_all(self) -> None:
        self.claims.clear()
        self.suppressed.clear()
        self.sync()


class _Compiled:
    __slots__ = ("mapping", "held", "key_codes", "score")

    def __init__(self, mapping: Mapping):
        self.mapping = mapping
        self.held = [keys.spec_codes(n) for n in mapping.held]
        self.key_codes = keys.spec_codes(mapping.key)
        # specific (left/right) specs beat generic ones, more held keys beat fewer
        self.score = (len(self.held), sum(1 for h in self.held if len(h) == 1))


class _Chord:
    """A modifier-only trigger: fires when its keys are released together, untouched by other keys."""

    __slots__ = ("mapping", "specs", "score")

    def __init__(self, mapping: Mapping):
        self.mapping = mapping
        self.specs = [keys.spec_codes(n) for n in mapping.trigger]
        self.score = (len(self.specs), sum(1 for h in self.specs if len(h) == 1))


class _Held:
    __slots__ = ("kind", "owner")

    def __init__(self, kind: str, owner: Hashable):
        self.kind = kind          # "pass" | "map" | "swallow" | "seq"
        self.owner = owner


class Engine:
    def __init__(self, output: Output, scheduler: Scheduler | None = None, engine_id: Hashable = 0):
        self.output = output
        self.scheduler = scheduler
        self.id = engine_id
        self.preset = Preset()
        self._by_key: dict[int, list[_Compiled]] = {}
        self.held: dict[int, _Held] = {}
        self._chords: list[_Chord] = []
        self._alias_mods: set[int] = set()   # keys remapped to a single modifier (count as modifiers)
        self._session_dirty = False          # a non-modifier key was used since the first key went down
        self._session_keys: set[int] = set()  # every key pressed since the first one went down
        self._timers: list[object] = []
        self._seq_serial = 0
        self._generation = 0

    # -- configuration --------------------------------------------------

    def set_preset(self, preset: Preset | None) -> None:
        self.release_all()
        self.preset = preset or Preset()
        self._by_key = {}
        self._chords = []
        self._alias_mods = set()
        for m in self.preset.mappings:
            if is_chord_tap(m.trigger):
                self._chords.append(_Chord(m))
                continue
            c = _Compiled(m)
            for code in c.key_codes:
                self._by_key.setdefault(code, []).append(c)
            a = m.action
            if (not m.held and a.type == ACTION_KEY and len(a.output_codes()) == 1
                    and keys.is_modifier(a.output_codes()[0])):
                self._alias_mods.update(c.key_codes)

    # -- event entry points ----------------------------------------------

    def handle(self, code: int, value: int) -> None:
        if value == 1:
            if code not in self.held:
                self._press(code)
        elif value == 0:
            self._release(code)
        # value 2 (auto-repeat) is dropped: the desktop repeats held keys itself.

    def release_all(self) -> None:
        self._generation += 1
        for t in self._timers:
            cancel = getattr(t, "cancel", None)
            if cancel:
                cancel()
        self._timers.clear()
        for h in self.held.values():
            self.output.unclaim(h.owner)
        self.held.clear()
        self.output.sync()

    # -- internals --------------------------------------------------------

    def _match(self, c: _Compiled, down: list[int]) -> list[int] | None:
        """Assign a distinct held physical key to every held spec, or None."""
        used: list[int] = []
        order = sorted(range(len(c.held)), key=lambda i: len(c.held[i]))  # specific first
        for i in order:
            for code in c.held[i]:
                if code in down and code not in used:
                    used.append(code)
                    break
            else:
                return None
        return used

    def _candidates(self, code: int) -> dict[int, int]:
        """Keys that count as held for trigger matching: code -> physical key providing it.

        Physical keys count as themselves.  A held key remapped to a single key also counts as
        that key, so with ``CapsLock -> Ctrl`` the user can hold CapsLock for a ``Ctrl+J`` trigger.
        """
        cand: dict[int, int] = {}
        for k in self.held:
            if k != code:
                cand[k] = k
        for k, h in self.held.items():
            if h.kind == "map":
                claim = self.output.claims.get(h.owner, ())
                if len(claim) == 1:
                    cand.setdefault(claim[0], k)
        return cand

    def _modlike(self, code: int) -> bool:
        return keys.is_modifier(code) or code in self._alias_mods

    def _press(self, code: int) -> None:
        if not self.held:
            self._session_dirty = False
            self._session_keys = set()
        self._session_keys.add(code)
        if not self._modlike(code):
            self._session_dirty = True
        cand = self._candidates(code)
        down = list(cand)
        best: tuple[_Compiled, list[int]] | None = None
        for c in self._by_key.get(code, ()):
            used = self._match(c, down)
            if used is None:
                continue
            if best is None or c.score > best[0].score:
                best = (c, [cand[u] for u in dict.fromkeys(used)])

        owner = (self.id, code)
        if best is None:
            self._restore(keep=())
            self.held[code] = _Held("pass", owner)
            self.output.claim(owner, (code,))
            self.output.sync()
            return

        compiled, used = best
        action = compiled.mapping.action
        if action.type == ACTION_DISABLE:
            self.held[code] = _Held("swallow", owner)
            return

        if action.type == ACTION_KEY:
            out_codes = action.output_codes()
        else:
            out_codes = []
        self._consume(used, out_codes)
        if action.type == ACTION_KEY:
            self.held[code] = _Held("map", owner)
            self.output.claim(owner, out_codes)
            self.output.sync()
        else:
            self.held[code] = _Held("seq", owner)
            self.output.sync()
            self._run_sequence(action.steps)

    def _consume(self, used: list[int], out_codes: list[int]) -> None:
        """Hide the trigger's held keys from the output; restore the others."""
        out = self.output
        self._restore(keep=used)
        for k in used:
            h = self.held.get(k)
            if h is None or h.owner in out.suppressed:
                continue
            claim = out.claims.get(h.owner, ())
            if claim and all(c in out_codes for c in claim):
                continue
            if any(c in keys.TAP_SENSITIVE_CODES for c in claim):
                out.tap_guard()
            out.suppress(h.owner)

    def _restore(self, keep) -> None:
        """Un-suppress held keys that are not part of the current trigger."""
        for k, h in self.held.items():
            if k in keep:
                continue
            if h.owner in self.output.suppressed:
                self.output.unsuppress(h.owner)

    def _fire_chord(self) -> None:
        """The held modifiers are being released together: run a matching modifier-only mapping."""
        phys = list(self.held)
        cand = self._candidates(-1)
        best: tuple[_Chord, list[int]] | None = None
        for c in self._chords:
            used = self._match_all(c.specs, list(cand))
            if used is None:
                continue
            owners = {cand[u] for u in used}
            if owners != set(phys):                    # an extra key is down: not this chord
                continue
            if best is None or c.score > best[0].score:
                best = (c, list(owners))
        if best is None:
            return
        chord, owners = best
        self._session_dirty = True                     # fire once per hold
        action = chord.mapping.action
        if action.type == ACTION_DISABLE:
            return
        out_codes = action.output_codes() if action.type == ACTION_KEY else []
        self._consume(owners, out_codes)
        if action.type == ACTION_KEY:
            self._tap(tuple(action.output), None, None, codes=out_codes)
        else:
            self.output.sync()
            self._run_sequence(action.steps)

    @staticmethod
    def _match_all(specs, down: list[int]) -> list[int] | None:
        used: list[int] = []
        for i in sorted(range(len(specs)), key=lambda i: len(specs[i])):
            for code in specs[i]:
                if code in down and code not in used:
                    used.append(code)
                    break
            else:
                return None
        return used

    def _release(self, code: int) -> None:
        if (self._chords and not self._session_dirty and code in self.held and len(self.held) >= 2
                and set(self.held) == self._session_keys and all(self._modlike(k) for k in self.held)):
            self._fire_chord()
        h = self.held.pop(code, None)
        if h is None:
            return
        if h.kind in ("pass", "map"):
            self.output.unclaim(h.owner)
            self.output.sync()

    # -- sequences ----------------------------------------------------------

    def _run_sequence(self, steps) -> None:
        parsed = [parse_step(s) for s in steps]
        self._seq_serial += 1
        self._step(parsed, 0, self._generation, self._seq_serial)

    def _step(self, steps, i: int, gen: int, serial: int) -> None:
        while i < len(steps):
            if gen != self._generation:
                return
            kind, arg = steps[i]
            i += 1
            if kind == "wait":
                if self.scheduler is None or arg <= 0:
                    continue
                self._timers.append(self.scheduler.call_later(
                    arg, lambda i=i: self._step(steps, i, gen, serial)))
                return
            self._tap(arg, serial, i)

    def _tap(self, names, serial, i, codes: list[int] | None = None) -> None:
        owner = ("seq", self.id, serial, i)
        if codes is None:
            codes = []
            for n in names:
                for c in keys.spec_codes(n)[:1]:
                    codes.append(c)
        self.output.claim(owner, codes)
        self.output.sync()
        self.output.unclaim(owner)
        self.output.sync()
