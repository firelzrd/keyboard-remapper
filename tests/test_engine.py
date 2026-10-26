from helpers import Rig


def test_passthrough_is_immediate_and_symmetric():
    r = Rig()
    r.down("LEFTCTRL", "C")
    r.up("C", "LEFTCTRL")
    assert r.take() == [("LEFTCTRL", 1), ("C", 1), ("C", 0), ("LEFTCTRL", 0)]


def test_simple_remap():
    r = Rig((("CAPSLOCK",), ("LEFTCTRL",)))
    r.down("CAPSLOCK", "C")
    r.up("C", "CAPSLOCK")
    assert r.take() == [("LEFTCTRL", 1), ("C", 1), ("C", 0), ("LEFTCTRL", 0)]


def test_modifier_then_key_hides_modifier():
    r = Rig((("CTRL", "J"), ("DOWN",)))
    r.down("LEFTCTRL")
    assert r.take() == [("LEFTCTRL", 1)]
    r.down("J")
    # guard not needed for Ctrl; Ctrl released, Down pressed
    assert r.take() == [("LEFTCTRL", 0), ("DOWN", 1)]
    r.up("J")
    assert r.take() == [("DOWN", 0)]
    r.up("LEFTCTRL")
    assert r.take() == []        # nothing: Ctrl was already up


def test_repeated_trigger_has_no_modifier_flicker():
    r = Rig((("CTRL", "J"), ("DOWN",)))
    r.down("LEFTCTRL")
    r.take()
    for _ in range(5):
        r.tap("J")
    log = r.take()
    assert log == [("LEFTCTRL", 0)] + [("DOWN", 1), ("DOWN", 0)] * 5


def test_modifier_restored_lazily_for_other_key():
    r = Rig((("CTRL", "J"), ("DOWN",)))
    r.down("LEFTCTRL")
    r.tap("J")
    r.take()
    r.down("C")
    assert r.take() == [("LEFTCTRL", 1), ("C", 1)]   # Ctrl+C reaches the app
    r.up("C", "LEFTCTRL")
    assert r.take() == [("C", 0), ("LEFTCTRL", 0)]


def test_extra_modifier_passes_through():
    r = Rig((("CTRL", "J"), ("DOWN",)))
    r.down("LEFTSHIFT", "LEFTCTRL", "J")
    log = r.take()
    assert log == [("LEFTSHIFT", 1), ("LEFTCTRL", 1), ("LEFTCTRL", 0), ("DOWN", 1)]
    from keyboard_remapper import keys
    assert set(r.out.pressed) == {keys.name_to_code("LEFTSHIFT"), keys.name_to_code("DOWN")}


def test_side_specific_beats_generic():
    r = Rig((("CTRL", "J"), ("DOWN",)), (("RIGHTCTRL", "J"), ("UP",)))
    r.down("RIGHTCTRL", "J")
    assert ("UP", 1) in r.take()
    r.up("J", "RIGHTCTRL")
    r.down("LEFTCTRL", "J")
    assert ("DOWN", 1) in r.take()


def test_more_specific_chord_wins():
    r = Rig((("CTRL", "J"), ("DOWN",)), (("CTRL", "SHIFT", "J"), ("PAGEDOWN",)))
    r.down("LEFTCTRL", "LEFTSHIFT", "J")
    assert ("PAGEDOWN", 1) in r.take()


def test_key_then_modifier_order_does_not_fire():
    r = Rig((("CTRL", "J"), ("DOWN",)))
    r.down("J")
    r.down("LEFTCTRL")
    assert r.take() == [("J", 1), ("LEFTCTRL", 1)]


def test_release_order_independent():
    r = Rig((("CTRL", "J"), ("DOWN",)))
    r.down("LEFTCTRL", "J")
    r.take()
    r.up("LEFTCTRL")          # modifier first
    assert r.take() == []
    r.up("J")
    assert r.take() == [("DOWN", 0)]


def test_super_tap_guard():
    r = Rig((("META", "E"), ("LEFTCTRL", "T")))
    r.down("LEFTMETA")
    r.take()
    r.down("E")
    log = r.take()
    # a guard key tap must precede the Super release
    assert log[:3] == [("F24", 1), ("F24", 0), ("LEFTMETA", 0)]
    assert log[3:] == [("LEFTCTRL", 1), ("T", 1)]


def test_output_includes_trigger_modifier_keeps_it():
    r = Rig((("CTRL", "J"), ("LEFTCTRL", "DOWN")))
    r.down("LEFTCTRL", "J")
    log = r.take()
    assert ("LEFTCTRL", 0) not in log
    assert log == [("LEFTCTRL", 1), ("DOWN", 1)]


def test_disable_swallows_only_the_key():
    r = Rig((("CTRL", "Q"), "disable"))
    r.down("LEFTCTRL", "Q")
    assert r.take() == [("LEFTCTRL", 1)]
    r.up("Q", "LEFTCTRL")
    assert r.take() == [("LEFTCTRL", 0)]


def test_autorepeat_ignored():
    r = Rig()
    r.down("A")
    r.engine.handle(30, 2)
    assert r.take() == [("A", 1)]


def test_sequence_with_wait():
    r = Rig((("F13",), ["Ctrl+C", "wait 50", "Ctrl+V"]))
    r.tap("F13")
    assert r.take() == [("LEFTCTRL", 1), ("C", 1), ("C", 0), ("LEFTCTRL", 0)]
    r.sched.advance(49)
    assert r.take() == []
    r.sched.advance(1)
    assert r.take() == [("LEFTCTRL", 1), ("V", 1), ("V", 0), ("LEFTCTRL", 0)]


def test_release_all_frees_everything_and_cancels_sequence():
    r = Rig((("F13",), ["A", "wait 50", "B"]), (("CTRL", "J"), ("DOWN",)))
    r.down("LEFTCTRL", "J", "F13")
    r.take()
    r.engine.release_all()
    log = r.take()
    assert ("DOWN", 0) in log
    r.sched.advance(100)
    assert r.take() == []
    assert not r.out.pressed


def test_two_keys_one_output_refcount():
    r = Rig((("CAPSLOCK",), ("LEFTCTRL",)))
    r.down("CAPSLOCK", "LEFTCTRL")
    assert r.take() == [("LEFTCTRL", 1)]
    r.up("CAPSLOCK")
    assert r.take() == []        # the other source still holds Ctrl
    r.up("LEFTCTRL")
    assert r.take() == [("LEFTCTRL", 0)]


def test_swap_keys():
    r = Rig((("LEFTALT",), ("LEFTMETA",)), (("LEFTMETA",), ("LEFTALT",)))
    r.tap("LEFTALT")
    assert r.take() == [("LEFTMETA", 1), ("LEFTMETA", 0)]


def test_non_modifier_held_key_combo():
    r = Rig((("SPACE", "J"), ("DOWN",)))
    r.down("SPACE", "J")
    assert r.take() == [("SPACE", 1), ("SPACE", 0), ("DOWN", 1)]


def test_remapped_modifier_counts_as_held_trigger_key():
    """CapsLock -> Ctrl, Ctrl+J -> Down: holding CapsLock then J must give Down."""
    r = Rig((("CAPSLOCK",), ("LEFTCTRL",)), (("CTRL", "J"), ("DOWN",)))
    r.down("CAPSLOCK")
    assert r.take() == [("LEFTCTRL", 1)]
    r.down("J")
    assert r.take() == [("LEFTCTRL", 0), ("DOWN", 1)]
    r.up("J")
    r.down("C")                                   # Ctrl comes back for a normal key
    assert r.take() == [("DOWN", 0), ("LEFTCTRL", 1), ("C", 1)]
    r.up("C", "CAPSLOCK")
    assert r.take() == [("C", 0), ("LEFTCTRL", 0)]


def test_physical_key_trigger_still_wins_over_remapped_alias():
    r = Rig((("CAPSLOCK",), ("LEFTCTRL",)), (("CTRL", "J"), ("DOWN",)), (("CAPSLOCK", "J"), ("UP",)))
    r.down("CAPSLOCK", "J")
    assert ("UP", 1) in r.take()


def test_fn_as_layer_key():
    """Apple Fn: Fn+H -> Left, and Fn is hidden while the mapping is used."""
    r = Rig((("FN", "H"), ("LEFT",)))
    r.down("FN")
    assert r.take() == [("FN", 1)]
    r.down("H")
    assert r.take() == [("FN", 0), ("LEFT", 1)]
    r.up("H", "FN")
    assert r.take() == [("LEFT", 0)]


def test_fn_pressed_before_key_in_output():
    r = Rig((("CAPSLOCK",), ("FN", "A")))
    r.down("CAPSLOCK")
    assert r.take() == [("FN", 1), ("A", 1)]


def _chord_rig(*extra):
    return Rig((("LEFTSHIFT", "LEFTCTRL"), ("CAPSLOCK",)), *extra)


def test_modifier_chord_fires_on_release_either_order():
    for first, second in (("LEFTSHIFT", "LEFTCTRL"), ("LEFTCTRL", "LEFTSHIFT")):
        r = _chord_rig()
        r.down(first, second)
        assert r.take() == [(first, 1), (second, 1)]            # modifiers behave normally meanwhile
        r.up(second)
        log = r.take()
        assert log[-2:] == [("CAPSLOCK", 1), ("CAPSLOCK", 0)]
        assert not any(n in ("LEFTSHIFT", "LEFTCTRL") and v == 1 for n, v in log)
        r.up(first)
        assert r.take() == []                                     # fires once per hold


def test_modifier_chord_does_not_break_real_shortcuts():
    r = _chord_rig()
    r.down("LEFTSHIFT", "LEFTCTRL", "T")
    r.up("T", "LEFTCTRL", "LEFTSHIFT")
    names = [n for n, v in r.take()]
    assert "CAPSLOCK" not in names and "T" in names               # Ctrl+Shift+T is untouched


def test_modifier_chord_needs_exactly_those_modifiers():
    r = _chord_rig()
    r.down("LEFTSHIFT", "LEFTCTRL", "LEFTALT")
    r.up("LEFTALT", "LEFTCTRL", "LEFTSHIFT")
    assert "CAPSLOCK" not in [n for n, v in r.take()]


def test_modifier_chord_works_with_remapped_ctrl():
    """CapsLock is Ctrl; Shift + (Caps as Ctrl) released together still fires the chord."""
    r = Rig((("CAPSLOCK",), ("LEFTCTRL",)), (("LEFTSHIFT", "LEFTCTRL"), ("F",)))
    r.down("LEFTSHIFT", "CAPSLOCK")
    r.take()
    r.up("CAPSLOCK")
    assert r.take()[-2:] == [("F", 1), ("F", 0)]


def test_disabled_ctrl_still_works_as_trigger_modifier():
    """Ctrl alone is disabled, yet Ctrl+Space still fires (here: Zenkaku/Hankaku)."""
    r = Rig((("LEFTCTRL",), "disable"), (("CTRL", "SPACE"), ("ZENKAKUHANKAKU",)))
    r.tap("LEFTCTRL")
    assert r.take() == []                                   # Ctrl alone does nothing at all
    r.down("LEFTCTRL", "SPACE")
    assert r.take() == [("ZENKAKUHANKAKU", 1)]
    r.up("SPACE", "LEFTCTRL")
    assert r.take() == [("ZENKAKUHANKAKU", 0)]
    r.down("LEFTCTRL", "C")                                 # other Ctrl combos: Ctrl is gone
    assert r.take() == [("C", 1)]
