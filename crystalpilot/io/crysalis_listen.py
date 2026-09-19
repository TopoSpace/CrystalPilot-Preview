"""CrysAlisPro LISTEN MODE file-channel client.

CrysAlisPro (CAP) has no headless mode - every executable in the 171.44
install is a GUI-subsystem PE. The supported unattended hook is LISTEN
MODE: after a one-time interactive `xx listenmode on` inside a running
CAP, the program polls a folder for command files and executes them:

    <root>/command.in      <- we write: one CAP command line
    <root>/command.busy    <- CAP creates while executing
    <root>/command.done    <- CAP creates on success
    <root>/command.error   <- CAP creates on failure
    <root>/command.stop    <- we write: interrupt current command
    <root>/command.close   <- we write: shut CAP down

Default root depends on CAP's mode: the offline/RED instance polls
C:/Xcalibur/tmp/listen_mode_offline (verified live 2026-09-01), the
online/CCD instance C:/Xcalibur/tmp/listen_mode (string-table
"CMainFrame::pListenMode _offline" is the suffix mechanism). CAP cleans
its folder at startup - never store anything else there. Evidence for
the protocol: pro.exe string table (format strings above verbatim), see
vendor/VENDOR-STATUS.md recon notes 2026-08-31.

The channel executes ONE command at a time; wait for done/error before
sending the next. Useful command families (RED/offline mode):
    xx selectexpnogui <path>\\exp.par      open experiment, no dialog
    dc rrp / dc proffit / dc red / dc hkl  reduction chain steps
    dc fullautoanalyse                     the full automatic pipeline
    dc imgtoxds / xx imgtoesperanto        frame format conversion
    xx savetext <path>                     dump CAP text buffer (probe)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path("C:/Xcalibur/tmp/listen_mode")
OFFLINE_ROOT = Path("C:/Xcalibur/tmp/listen_mode_offline")


def detect_root() -> Path:
    """Prefer whichever mode's channel folder actually exists."""
    if OFFLINE_ROOT.is_dir():
        return OFFLINE_ROOT
    return DEFAULT_ROOT


@dataclass
class ListenResult:
    status: str          # done | error | timeout | channel_missing
    elapsed_s: float
    detail: str = ""


class ListenModeClient:
    """Minimal file-IO driver for a CAP instance in listen mode."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else detect_root()

    # -- channel state -------------------------------------------------
    def channel_alive(self) -> bool:
        """The folder exists and no stale .in/.busy is pending."""
        return self.root.is_dir()

    def _p(self, name: str) -> Path:
        return self.root / f"command.{name}"

    def _clear_markers(self) -> None:
        for n in ("in", "busy", "done", "error"):
            try:
                self._p(n).unlink(missing_ok=True)
            except OSError:
                pass

    # -- driving -------------------------------------------------------
    def send(self, command: str, timeout_s: float = 600.0,
             poll_s: float = 0.5) -> ListenResult:
        """Write one command, wait for CAP's done/error marker."""
        if not self.channel_alive():
            return ListenResult("channel_missing", 0.0,
                                f"{self.root} does not exist - is CAP "
                                "running with `xx listenmode on`?")
        self._clear_markers()
        t0 = time.monotonic()
        self._p("in").write_text(command.strip() + "\n", encoding="ascii")
        saw_busy = False
        while True:
            el = time.monotonic() - t0
            if self._p("done").exists():
                return ListenResult("done", el)
            if self._p("error").exists():
                return ListenResult("error", el,
                                    "CAP reported command failure")
            if self._p("busy").exists():
                saw_busy = True
            if el > timeout_s:
                return ListenResult(
                    "timeout", el,
                    "busy seen" if saw_busy else
                    "command.in never picked up - listen mode off?")
            time.sleep(poll_s)

    def interrupt(self) -> None:
        self._p("stop").write_text("\n", encoding="ascii")

    def close_cap(self) -> None:
        self._p("close").write_text("\n", encoding="ascii")
