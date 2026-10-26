"""Randomised stress test: whatever the user does, outputs end balanced and never stick."""

import random


from helpers import Rig
from keyboard_remapper import keys

NAMES = ["LEFTCTRL", "RIGHTCTRL", "LEFTSHIFT", "LEFTALT", "LEFTMETA", "CAPSLOCK", "SPACE",
         "A", "B", "J", "K", "F13", "MUHENKAN"]

MAPS = [
    (("CTRL", "J"), ("DOWN",)),
    (("CTRL", "K"), ("UP",)),
    (("CTRL", "SHIFT", "J"), ("PAGEDOWN",)),
    (("META", "A"), ("LEFTCTRL", "T")),
    (("CAPSLOCK",), ("LEFTCTRL",)),
    (("MUHENKAN",), ("ESC",)),
    (("SPACE", "J"), ("ENTER",)),
    (("ALT", "B"), "disable"),
    (("F13",), ["Ctrl+C", "wait 30", "Ctrl+V"]),
    (("LEFTSHIFT", "LEFTCTRL"), ("CAPSLOCK",)),
    (("CTRL", "ALT"), ("F14",)),
]


def test_fuzz_outputs_stay_balanced():
    for seed in range(300):
        rnd = random.Random(seed)
        r = Rig(*rnd.sample(MAPS, rnd.randint(0, len(MAPS))))
        down = set()
        state = {}                          # output key -> pressed, from the emitted stream
        for _ in range(rnd.randint(5, 60)):
            if down and rnd.random() < 0.45:
                n = rnd.choice(sorted(down))
                down.discard(n)
                r.engine.handle(keys.name_to_code(n), 0)
            else:
                n = rnd.choice(NAMES)
                if n in down:
                    continue
                down.add(n)
                r.engine.handle(keys.name_to_code(n), 1)
            if rnd.random() < 0.2:
                r.sched.advance(rnd.choice([10, 30, 100]))
            for name, v in r.take():
                assert state.get(name, 0) != v, (seed, name, v, "duplicate press/release")
                state[name] = v
        for n in sorted(down):
            r.engine.handle(keys.name_to_code(n), 0)
        r.sched.advance(1000)
        for name, v in r.take():
            assert state.get(name, 0) != v, (seed, name, v)
            state[name] = v
        assert not r.out.pressed, (seed, r.out.pressed)
        assert not any(state.values()), (seed, {k: v for k, v in state.items() if v})


def test_guard_key_is_never_left_pressed():
    r = Rig((("META", "A"), ("B",)))
    r.down("LEFTMETA", "A")
    r.up("A", "LEFTMETA")
    state = {}
    for n, v in r.take():
        state[n] = v
    assert state.get("F24", 0) == 0
