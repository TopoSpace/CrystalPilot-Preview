"""Headless Olex2 console driver (olex2c over ConPTY).

The win64 Olex2 distribution DOES ship the console build - as
``app/olex2c.dll``, a CONSOLE-subsystem EXE image with a .dll extension
(the updater treats non-.exe names as data payloads; macOS uses
``olex2c_exe``). It imports no OpenGL/GDI/wxWidgets, so nothing can
appear on the desktop. Recon + live smoke 2026-09-01.

Hard-won runtime facts (do not "simplify"):

* The REPL reads CONSOLE input, not pipes: with plain Popen(stdin=PIPE)
  it boots fully and then ignores every command (v1 smoke hung 900 s).
  It must be driven through a pseudoconsole - pywinpty. ConPTY windows
  are invisible by nature.
* pywinpty's ``PtyProcess.read()`` BLOCKS (a dead child hangs the
  caller forever) - reads live on a daemon thread feeding a queue.
* The embedded CPython 3.8 needs ``PYTHONHOME=<app>/Python`` (stdlib
  lives in Python/{DLLs,Lib}) and the parent's PYTHON* variables
  scrubbed - a user-level PYTHONPATH (ChemOffice etc.) kills startup
  with ``ModuleNotFoundError: encodings``.
* ``refine`` internally runs ``user filepath()``; after a RELATIVE
  ``reap`` that cd fails ("could not change current folder") and the
  refinement silently does not run. Always ``user '<absdir>'`` then
  ``reap '<abs>/job.res'`` with forward slashes.
* Boot takes ~15 s; a 4-cycle olex2.refine on a 517-parameter
  structure ~10 s. Prompt is ``>>``.
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

APP_DEFAULT = Path(r"H:/CrystalPilot/vendor/olex2/app")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\r")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def build_env(app: Path, datadir: Path) -> dict[str, str]:
    """Isolated environment for the embedded Olex2 python."""
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("PYTHON")}
    env.update(
        OLEX2_DIR=str(app),
        OLEX2_CCTBX_DIR=str(app / "cctbx"),
        PYTHONHOME=str(app / "Python"),
        OLEX2_DATADIR=str(datadir),
    )
    return env


@dataclass
class CommandResult:
    command: str
    output: str
    elapsed_s: float
    eof: bool = False

    @property
    def clean(self) -> str:
        return strip_ansi(self.output)


@dataclass
class Olex2Console:
    """One hidden olex2c process driven over ConPTY.

    Usage::

        with Olex2Console(workdir) as ol:
            ol.command(f"user '{ol.fwd(workdir)}'")
            ol.command(f"reap '{ol.fwd(workdir / 'job.res')}'")
            r = ol.command("refine 8", max_s=600)
            ol.command("file job.cif")
    """
    workdir: Path
    app: Path = APP_DEFAULT
    boot_timeout_s: float = 300.0
    transcript: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        from winpty import PtyProcess   # lazy: repo venv dep

        self.workdir = Path(self.workdir)
        self._q: queue.Queue[str | None] = queue.Queue()
        self._eof = False
        self.proc = PtyProcess.spawn(
            [str(self.app / "olex2c.dll")], cwd=str(self.workdir),
            env=build_env(self.app, self.workdir / "olex2data"),
            dimensions=(60, 400))
        threading.Thread(target=self._reader, daemon=True).start()
        # first-ever boot unpacks the datadir and can sit SILENT well past
        # 10 s (observed live: quiet_s=10 aborted a boot that a blocking
        # read completed in 7.6 s under load; the next two attempts took
        # ~24 s end-to-end) - keep the quiet window generous here
        banner = self._pump(self.boot_timeout_s, quiet_s=45.0)
        if self._eof or ">>" not in banner:
            raise RuntimeError(
                "olex2c did not reach its prompt; tail: "
                + strip_ansi(banner)[-400:])

    @staticmethod
    def fwd(p: Path | str) -> str:
        return str(p).replace("\\", "/")

    # -- plumbing ------------------------------------------------------
    def _reader(self) -> None:
        while True:
            try:
                chunk = self.proc.read(4096)
            except (EOFError, ConnectionError, OSError):
                self._q.put(None)
                return
            if chunk:
                self._q.put(chunk)
            else:
                time.sleep(0.1)

    def _pump(self, max_s: float, quiet_s: float) -> str:
        got: list[str] = []
        end = time.time() + max_s
        last = time.time()
        while time.time() < end:
            try:
                chunk = self._q.get(timeout=0.3)
            except queue.Empty:
                if not self.proc.isalive():
                    self._eof = True
                    break
                if time.time() - last > quiet_s:
                    break
                continue
            if chunk is None:
                self._eof = True
                break
            got.append(chunk)
            last = time.time()
        text = "".join(got)
        self.transcript.append(text)
        return text

    # -- API -----------------------------------------------------------
    def command(self, cmd: str, max_s: float = 120.0,
                quiet_s: float = 8.0) -> CommandResult:
        if self._eof:
            return CommandResult(cmd, "", 0.0, eof=True)
        t0 = time.time()
        self.proc.write(cmd + "\r\n")
        out = self._pump(max_s, quiet_s)
        return CommandResult(cmd, out, time.time() - t0, self._eof)

    def close(self) -> None:
        try:
            if not self._eof and self.proc.isalive():
                self.proc.write("quit\r\n")
                self._pump(20.0, quiet_s=4.0)
        finally:
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001 - already gone
                pass

    def __enter__(self) -> "Olex2Console":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def refine_job(workdir: Path | str, res_name: str = "job.res",
               cycles: int = 8, app: Path = APP_DEFAULT,
               refine_timeout_s: float = 900.0) -> dict:
    """One-shot: load <workdir>/<res_name> (+ matching .hkl), run
    olex2.refine, write the refined res/cif back. Returns a summary."""
    wd = Path(workdir)
    with Olex2Console(wd, app=app) as ol:
        steps = [
            ol.command(f"user '{ol.fwd(wd)}'"),
            ol.command(f"reap '{ol.fwd(wd / res_name)}'"),
            ol.command(f"refine {int(cycles)}", max_s=refine_timeout_s,
                       quiet_s=10.0),
            ol.command(f"file {Path(res_name).stem}.cif"),
        ]
    joined = strip_ansi("".join(s.output for s in steps))
    ok = "Refinement finished" in joined and "Error" not in joined[:0]
    m = re.search(r"R1\s*=\s*([\d.]+)", joined)
    return {
        "ok": ok and not steps[-1].eof,
        "refinement_finished": "Refinement finished" in joined,
        "r1_console": (float(m.group(1)) if m else None),
        "cif": str(wd / (Path(res_name).stem + ".cif")),
        "elapsed_s": round(sum(s.elapsed_s for s in steps), 1),
        "console_tail": joined[-1200:],
    }
