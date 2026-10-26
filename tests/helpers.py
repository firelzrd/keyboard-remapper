
from keyboard_remapper import keys
from keyboard_remapper.engine import Engine, Output
from keyboard_remapper.mapping import Action, Mapping, Preset


class ManualScheduler:
    def __init__(self):
        self.now = 0
        self.queue = []

    class Handle:
        def __init__(self, s, item):
            self.s, self.item = s, item

        def cancel(self):
            if self.item in self.s.queue:
                self.s.queue.remove(self.item)

    def call_later(self, ms, fn):
        item = (self.now + ms, fn)
        self.queue.append(item)
        return self.Handle(self, item)

    def advance(self, ms):
        self.now += ms
        while True:
            due = sorted((q for q in self.queue if q[0] <= self.now), key=lambda q: q[0])
            if not due:
                return
            self.queue.remove(due[0])
            due[0][1]()


class Rig:
    """Engine + recording output."""

    def __init__(self, *mappings):
        self.log = []
        self.sched = ManualScheduler()
        self.out = Output(lambda c, v: self.log.append((keys.code_to_name(c), v)))
        self.engine = Engine(self.out, self.sched)
        self.set(*mappings)

    def set(self, *mappings):
        self.engine.set_preset(Preset("t", [m(x) for x in mappings]) if mappings else Preset())

    def down(self, *names):
        for n in names:
            self.engine.handle(keys.name_to_code(n), 1)

    def up(self, *names):
        for n in names:
            self.engine.handle(keys.name_to_code(n), 0)

    def tap(self, *names):
        self.down(*names)
        self.up(*reversed(names))

    def take(self):
        log, self.log = self.log, []
        return log


def m(spec):
    """("CTRL","J") -> ("DOWN",)   |   (trigger, action-dict)"""
    trig, act = spec
    if isinstance(act, tuple):
        act = Action("key", output=act)
    elif isinstance(act, list):
        act = Action("sequence", steps=tuple(act))
    elif act == "disable":
        act = Action("disable")
    return Mapping(tuple(trig), act)
