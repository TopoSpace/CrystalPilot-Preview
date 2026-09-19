"""The workbench server must not run on the Windows Proactor event loop.

Bitten 2026-09-07 (and unexplained on 2026-09-05 19:55): a single failed
overlapped accept - WinError 64, "the specified network name is no longer
available", raised when a client resets between AcceptEx and its completion -
makes asyncio close the *listening* socket:

    asyncio\\proactor_events.py, BaseProactorEventLoop._start_serving
        except OSError as exc:
            if sock.fileno() != -1:
                self.call_exception_handler({'message': 'Accept failed on a
                                             socket', ...})
                sock.close()

uvicorn's main_loop only watches should_exit, so the process stays alive with
the app fully started and nothing listening on 8010. There is no crash, no
exit code and no failing health check to find afterwards - only that traceback
in uvicorn_r13.err.log. The selector loop reports the same event as
ConnectionAbortedError and goes on serving, so scripts\\restart_server.ps1
pins the loop with `--loop asyncio:SelectorEventLoop`.

Two things have to keep holding for that to work, and both are cheap to check:
uvicorn must keep resolving an unrecognised --loop value as an import string
for the loop factory, and the script must keep passing the flag.
"""
import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SCRIPT = REPO / "scripts" / "restart_server.ps1"


def test_uvicorn_still_takes_a_custom_loop_factory_string():
    """Config.get_loop_factory falls through to import_from_string for a value
    it does not know. An upgrade that drops that branch would silently put us
    back on the Proactor loop."""
    from uvicorn.config import LOOP_FACTORIES, Config

    assert "asyncio:SelectorEventLoop" not in LOOP_FACTORIES, (
        "the flag would take the mapped branch instead of the import-string one"
    )
    factory = Config("server.app:app", loop="asyncio:SelectorEventLoop").get_loop_factory()
    assert factory is asyncio.SelectorEventLoop


@pytest.mark.skipif(sys.platform != "win32", reason="Proactor is a Windows loop")
def test_the_pinned_loop_is_not_the_proactor_one():
    loop = asyncio.SelectorEventLoop()
    try:
        assert not isinstance(loop, asyncio.ProactorEventLoop)
    finally:
        loop.close()


def test_restart_script_pins_the_selector_loop():
    text = SCRIPT.read_text(encoding="utf-8", errors="replace")
    launch = text.split("-ArgumentList", 1)[1].split("-WorkingDirectory", 1)[0]
    compact = "".join(launch.split())  # the argument list wraps across lines
    assert "'--loop','asyncio:SelectorEventLoop'" in compact, (
        "restart_server.ps1 no longer starts uvicorn on the selector loop; see "
        "the comment block at the top of that script for what that costs"
    )


def test_kill_pattern_still_matches_the_launch_command():
    """The script finds a running server by matching its command line. The
    --loop flag sits between the app and the port, so the pattern has to keep
    matching what the script itself launches."""
    import re

    text = SCRIPT.read_text(encoding="utf-8", errors="replace")
    pattern = re.search(r"\$pattern = '([^']+)'", text).group(1)
    port_expr = pattern.replace("' + $Port + '", "8010")
    launched = (
        '"H:\\CrystalPilot\\.venv\\Scripts\\python.exe" -X utf8 -m uvicorn '
        "server.app:app --loop asyncio:SelectorEventLoop --port 8010"
    )
    assert re.search(port_expr, launched), (
        f"pattern {port_expr!r} would not find the process the script starts"
    )
