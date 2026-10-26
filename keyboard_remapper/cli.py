"""keyboard-remapper-ctl: talk to the daemon from a shell."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, keys
from .daemon import DEFAULT_SOCKET
from .ipc import Client
from .mapping import MappingError, Preset


def _connect(path: str) -> Client:
    c = Client(path)
    if not c.connect():
        print(f"cannot connect to {path} - is keyboard-remapperd running?\n"
              "  sudo systemctl enable --now keyboard-remapperd", file=sys.stderr)
        sys.exit(2)
    return c


def _model(c: Client, ident: str) -> str:
    """Accept a model id (vid:pid) or a part of the keyboard name."""
    devs = c.request("devices").get("devices", [])
    for d in devs:
        if ident in (d["model"], d["id"]):
            return d["model"]
    hits = [d for d in devs if ident.lower() in d["name"].lower()]
    if len(hits) == 1:
        return hits[0]["model"]
    if ":" in ident:
        return ident
    print(f"no unique keyboard matches {ident!r}", file=sys.stderr)
    sys.exit(1)


def cmd_list(c: Client, args) -> int:
    for d in c.request("devices").get("devices", []):
        state = "active" if d["applied"] else ("configured" if d["configured"] else "-")
        print(f"{d['model']}  {state:<10}  {d['name']}")
    return 0


def cmd_apply(c: Client, args) -> int:
    try:
        with open(args.preset, encoding="utf-8") as f:
            data = json.load(f)
        preset = Preset.from_dict(data, strict=True)
    except (OSError, ValueError, MappingError) as ex:
        print(f"invalid preset: {ex}", file=sys.stderr)
        return 1
    r = c.request("apply", model=_model(c, args.keyboard), preset=preset.to_dict())
    print("ok" if r.get("ok") else r.get("error"))
    return 0 if r.get("ok") else 1


def cmd_stop(c: Client, args) -> int:
    r = c.request("enable", model=_model(c, args.keyboard), enabled=False)
    return 0 if r.get("ok") else 1


def cmd_start(c: Client, args) -> int:
    r = c.request("enable", model=_model(c, args.keyboard), enabled=True)
    return 0 if r.get("ok") else 1


def cmd_monitor(c: Client, args) -> int:
    import time

    def show(m: dict) -> None:
        state = "down" if m["value"] else "up"
        if m.get("event") == "key":
            print(f"IN   {m['model']}  {keys.code_to_name(m['code']):<18} {state}", flush=True)
        elif m.get("event") == "out":
            print(f"OUT  {'':9}  {keys.code_to_name(m['code']):<18} {state}", flush=True)

    c.on_event = show
    c.request("monitor", on=True, output=args.output)
    try:
        while c.connected:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_doctor(c: Client | None, args) -> int:
    ok = True

    def check(label: str, good: bool, hint: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"[{'ok' if good else 'NG'}] {label}" + ("" if good else f"  -> {hint}"))

    check("/dev/uinput exists", os.path.exists("/dev/uinput"), "sudo modprobe uinput")
    check("/dev/input readable by root", os.access("/dev/input", os.R_OK))
    cl = Client(args.socket)
    reachable = cl.connect()
    check("daemon socket reachable", reachable, "sudo systemctl enable --now keyboard-remapperd")
    if reachable:
        info = cl.request("hello")
        theirs = info.get("version", "?")
        check(f"daemon version {theirs} matches this tool ({__version__})", theirs == __version__,
              "sudo systemctl restart keyboard-remapperd")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="keyboard-remapper-ctl", description=__doc__)
    ap.add_argument("--version", action="version", version=f"keyboard-remapper-ctl {__version__}")
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list keyboards")
    p = sub.add_parser("apply", help="apply a preset JSON file to a keyboard")
    p.add_argument("keyboard", help="vendor:product or part of the name")
    p.add_argument("preset")
    for name, h in (("stop", "stop remapping on a keyboard"), ("start", "resume remapping on a keyboard")):
        p = sub.add_parser(name, help=h)
        p.add_argument("keyboard")
    p = sub.add_parser("monitor", help="print physical key events (Ctrl+C to quit)")
    p.add_argument("--output", action="store_true",
                   help="also print the keys Keyboard Remapper sends (what the desktop receives)")
    sub.add_parser("doctor", help="check the system setup")
    args = ap.parse_args(argv)
    if args.cmd == "doctor":
        return cmd_doctor(None, args)
    c = _connect(args.socket)
    return {"list": cmd_list, "apply": cmd_apply, "stop": cmd_stop, "start": cmd_start,
            "monitor": cmd_monitor}[args.cmd](c, args)


if __name__ == "__main__":
    sys.exit(main())
