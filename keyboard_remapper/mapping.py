"""Preset / mapping data model and (de)serialisation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import keys

ACTION_KEY = "key"
ACTION_SEQUENCE = "sequence"
ACTION_DISABLE = "disable"
ACTION_TYPES = (ACTION_KEY, ACTION_SEQUENCE, ACTION_DISABLE)

MAX_WAIT_MS = 10000


class MappingError(ValueError):
    pass


def _norm_chord(names) -> tuple[str, ...]:
    out = []
    for n in names:
        c = keys.normalize_name(str(n))
        if c is None:
            raise MappingError(f"unknown key: {n!r}")
        out.append(c)
    return tuple(out)


def parse_step(step: str) -> tuple[str, object]:
    """Parse one sequence step: ``"Ctrl+C"`` -> ("tap", names) / ``"wait 50"`` -> ("wait", 50)."""
    s = step.strip()
    m = re.fullmatch(r"(?i)wait\s*[: ]?\s*(\d+)\s*(ms)?", s)
    if m:
        return "wait", min(int(m.group(1)), MAX_WAIT_MS)
    parts = [p for p in re.split(r"\s*\+\s*", s) if p]
    if not parts:
        raise MappingError("empty step")
    return "tap", _norm_chord(parts)


def is_chord_tap(trigger) -> bool:
    """A trigger made only of modifier keys (e.g. Left Shift + Left Ctrl).

    Such a trigger fires when the keys are released together without any other key in between;
    firing on press would break ordinary shortcuts like Ctrl+Shift+T.
    """
    if len(trigger) < 2:
        return False
    for n in trigger:
        name = keys.normalize_name(n)
        if name is None:
            return False
        if name in keys.GENERIC_MODIFIERS:
            continue
        if keys.name_to_code(name) not in keys.MODIFIER_CODES:
            return False
    return True


@dataclass(frozen=True)
class Action:
    type: str = ACTION_KEY
    output: tuple[str, ...] = ()       # key action: keys pressed together
    steps: tuple[str, ...] = ()        # sequence action

    def validate(self) -> None:
        if self.type not in ACTION_TYPES:
            raise MappingError(f"unknown action type: {self.type!r}")
        if self.type == ACTION_KEY:
            if not self.output:
                raise MappingError("key action needs an output")
            for n in self.output:
                if n in keys.GENERIC_MODIFIERS:
                    continue
                if keys.name_to_code(n) is None:
                    raise MappingError(f"unknown key: {n!r}")
        elif self.type == ACTION_SEQUENCE:
            if not self.steps:
                raise MappingError("sequence needs at least one step")
            for s in self.steps:
                parse_step(s)

    def output_codes(self) -> list[int]:
        """Codes for a key action; generic modifiers become their left key."""
        codes = []
        for n in self.output:
            if n in keys.GENERIC_MODIFIERS:
                codes.append(keys.GENERIC_MODIFIERS[n][0])
            else:
                c = keys.name_to_code(n)
                if c is not None:
                    codes.append(c)
        return codes

    def to_dict(self) -> dict:
        if self.type == ACTION_KEY:
            return {"type": self.type, "output": list(self.output)}
        if self.type == ACTION_SEQUENCE:
            return {"type": self.type, "steps": list(self.steps)}
        return {"type": self.type}

    @staticmethod
    def from_dict(d: dict) -> "Action":
        t = d.get("type", ACTION_KEY)
        if t == ACTION_KEY:
            out = _norm_chord(d.get("output", []))
            return Action(t, output=out)
        if t == ACTION_SEQUENCE:
            return Action(t, steps=tuple(str(s) for s in d.get("steps", [])))
        return Action(t)

    def describe(self, lang: str = "ja") -> str:
        if self.type == ACTION_KEY:
            return keys.chord_name(self.output, lang)
        if self.type == ACTION_DISABLE:
            return "無効" if lang == "ja" else "Disabled"
        n = len(self.steps)
        return f"連続入力 ({n})" if lang == "ja" else f"Sequence ({n})"


@dataclass
class Mapping:
    """``trigger``: keys held down plus, last, the key whose press fires it."""

    trigger: tuple[str, ...]
    action: Action

    def validate(self) -> None:
        if not self.trigger:
            raise MappingError("empty trigger")
        self.action.validate()

    @property
    def held(self) -> tuple[str, ...]:
        return self.trigger[:-1]

    @property
    def key(self) -> str:
        return self.trigger[-1]

    def trigger_id(self) -> tuple:
        """Order-insensitive identity of the trigger (held keys are unordered)."""
        return (tuple(sorted(self.held)), self.key)

    def to_dict(self) -> dict:
        return {"trigger": list(self.trigger), "action": self.action.to_dict()}

    @staticmethod
    def from_dict(d: dict) -> "Mapping":
        m = Mapping(_norm_chord(d.get("trigger", [])), Action.from_dict(d.get("action", {})))
        m.validate()
        return m


@dataclass
class Preset:
    name: str = "Default"
    mappings: list[Mapping] = field(default_factory=list)

    def find(self, trigger: tuple[str, ...]) -> Mapping | None:
        tid = Mapping(trigger, Action()).trigger_id()
        for m in self.mappings:
            if m.trigger_id() == tid:
                return m
        return None

    def set(self, mapping: Mapping) -> None:
        """Add or replace the mapping with the same trigger."""
        mapping.validate()
        for i, m in enumerate(self.mappings):
            if m.trigger_id() == mapping.trigger_id():
                self.mappings[i] = mapping
                return
        self.mappings.append(mapping)

    def remove(self, trigger: tuple[str, ...]) -> Mapping | None:
        m = self.find(trigger)
        if m is not None:
            self.mappings.remove(m)
        return m

    def to_dict(self) -> dict:
        return {"version": 1, "name": self.name, "mappings": [m.to_dict() for m in self.mappings]}

    @staticmethod
    def from_dict(d: dict, strict: bool = False) -> "Preset":
        p = Preset(name=str(d.get("name", "Default")))
        for md in d.get("mappings", []):
            try:
                p.set(Mapping.from_dict(md))
            except MappingError:
                if strict:
                    raise
        return p

    def copy(self) -> "Preset":
        return Preset.from_dict(self.to_dict())
