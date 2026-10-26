import os
import re
import subprocess
import sys

import keyboard_remapper
from keyboard_remapper import cli, daemon

ROOT = os.path.dirname(os.path.dirname(__file__))


def _run(*args):
    env = dict(os.environ, PYTHONPATH=ROOT)
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, env=env)


def test_version_is_1_0_0_and_semver():
    assert keyboard_remapper.__version__ == "1.0.0"
    assert re.fullmatch(r"\d+\.\d+\.\d+", keyboard_remapper.__version__)


def test_pyproject_takes_the_version_from_the_package():
    text = open(os.path.join(ROOT, "pyproject.toml")).read()
    assert 'dynamic = ["version"]' in text
    assert 'attr = "keyboard_remapper.__version__"' in text
    assert not re.search(r'^version\s*=\s*"', text, re.M)    # no second, driftable copy


def test_changelog_has_the_current_version():
    assert f"## {keyboard_remapper.__version__}" in open(os.path.join(ROOT, "CHANGELOG.md")).read()


def test_version_flags():
    for mod, prog in (("keyboard_remapper.daemon", "keyboard-remapperd"),
                      ("keyboard_remapper.cli", "keyboard-remapper-ctl")):
        r = _run("-m", mod, "--version")
        assert r.returncode == 0 and r.stdout.strip() == f"{prog} 1.0.0", (mod, r.stdout, r.stderr)


def test_daemon_reports_its_version_in_hello():
    import asyncio
    from keyboard_remapper.backend import FakeBackend

    async def go():
        d = daemon.Daemon(FakeBackend([]), state_path=None, socket_path=None, check_peer=False)
        await d.start()
        reply = d.dispatch(daemon.Client(None), {"cmd": "hello"})
        await d.stop()
        return reply

    assert asyncio.run(go())["version"] == "1.0.0"
    assert cli.__version__ == "1.0.0"
