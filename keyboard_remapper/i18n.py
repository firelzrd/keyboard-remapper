"""Tiny language switch: every UI string is written as a (ja, en) pair."""

import locale
import os


def _detect() -> str:
    forced = os.environ.get("KEYBOARD_REMAPPER_LANG")
    if forced:
        return "ja" if forced.lower().startswith("ja") else "en"
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(var)
        if v:
            return "ja" if v.lower().startswith("ja") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    return "ja" if loc.lower().startswith("ja") else "en"


LANG = _detect()


def T(ja: str, en: str) -> str:
    return ja if LANG == "ja" else en
