"""Detached Linux server lifecycle with owned-PID checks and health polling.

Usage: .venv/bin/python scripts/server_linux.py [start|restart|stop|status]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "workdir"


def owned_process(record: Path, port: int) -> psutil.Process | None:
    if not record.exists():
        return None
    try:
        data = json.loads(record.read_text())
        proc = psutil.Process(data["pid"])
        args = proc.cmdline()
        if (abs(proc.create_time() - data["created"]) < 0.01
                and Path(proc.cwd()).resolve() == ROOT
                and "server.app:app" in args
                and args[args.index("--port") + 1] == str(port)):
            return proc
    except (psutil.Error, ValueError, KeyError, OSError):
        pass
    return None


def stop(proc: psutil.Process) -> None:
    children = proc.children(recursive=True)
    # Allow application shutdown first, then reap its remaining descendants.
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except psutil.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(children, timeout=5)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass


CODEX_LOG_DB_CAP = 256 * 1024 * 1024


def rotate_codex_log_db(codex_home: Path, cap: int = CODEX_LOG_DB_CAP) -> bool:
    """Remove codex's own log database when it has outgrown `cap` and no
    codex process of this checkout can hold it. codex 0.154 writes every
    log line into codex-home/logs_2.sqlite (1.6 GB after three weeks on
    Windows, ~15 MB/min while an engine runs); with a large write-ahead
    log a new app-server failed to start twice with "failed to initialize
    sqlite state runtime" (2026-09-16). codex recreates the file."""
    db = codex_home / "logs_2.sqlite"
    try:
        if not db.is_file() or db.stat().st_size <= cap:
            return False
    except OSError:
        return False
    vendor = str((ROOT / "vendor" / "codex").resolve())
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info["name"] and "codex" in proc.info["name"] and any(
                    vendor in part for part in (proc.info["cmdline"] or [])):
                print(f"codex log database is {db.stat().st_size >> 20} MB but PID {proc.pid} holds it; not rotated")
                return False
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    size = db.stat().st_size >> 20
    for suffix in ("", "-wal", "-shm"):
        try:
            (codex_home / f"logs_2.sqlite{suffix}").unlink()
        except FileNotFoundError:
            pass
    print(f"rotated codex log database ({size} MB) - codex recreates it on start")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("start", "restart", "stop", "status"), default="restart", nargs="?")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--cores", type=int, default=4)
    args = ap.parse_args()
    WORK.mkdir(exist_ok=True)
    record = WORK / f"server-{args.port}.json"
    with (WORK / f"server-{args.port}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        proc = owned_process(record, args.port)
        url = f"http://127.0.0.1:{args.port}"
        if args.action == "status":
            if proc is None:
                print("Server is stopped (no owned process).")
                return 1
            print(f"Server PID {proc.pid}: {url}")
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=5) as response:
                    print(response.read().decode())
            except OSError as exc:
                print(f"Health check failed: {exc}")
                return 1
            return 0
        if proc is not None and args.action == "start":
            print(f"Already running: PID {proc.pid}, {url}")
            return 0
        if proc is not None:
            stop(proc)
        record.unlink(missing_ok=True)
        if args.action == "stop":
            print("Server stopped.")
            return 0
        # Never terminate another checkout's server or an unrelated listener.
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", args.port))
            except OSError:
                print(f"Port {args.port} is occupied; no foreign process was stopped.")
                return 1
        rotate_codex_log_db(ROOT / "codex-home")
        env = dict(os.environ)
        env.update(PYTHONUTF8="1", CRYSTALPILOT_CPU_CORES=str(args.cores),
                   CRYSTALPILOT_CODEX_HOME=str(ROOT / "codex-home"),
                   OPENBLAS_NUM_THREADS=str(max(1, args.cores)),
                   OMP_NUM_THREADS=str(max(1, args.cores)))
        env.pop("CRYSTALPILOT_CODEX_BIN", None)  # prefer this checkout's vendor kernel
        # Descendant GitHub commands inherit the project's isolated entrypoints.
        project_bin = ROOT.parent / ".github-cli" / "bin"
        if project_bin.is_dir():
            env["PATH"] = str(project_bin) + os.pathsep + env.get("PATH", "")
        python = ROOT / ".venv/bin/python"
        with (WORK / "server.stdout.log").open("ab") as out, (WORK / "server.stderr.log").open("ab") as err:
            child = subprocess.Popen(
                [str(python), "-X", "utf8", "-m", "uvicorn", "server.app:app",
                 "--loop", "asyncio", "--host", "127.0.0.1", "--port", str(args.port)],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                start_new_session=True,
            )
        record.write_text(json.dumps({"pid": child.pid,
                                      "created": psutil.Process(child.pid).create_time(),
                                      "port": args.port}, indent=2) + "\n")
        if args.cores > 0:
            process = psutil.Process(child.pid)
            available = process.cpu_affinity()
            process.cpu_affinity(available[:args.cores])
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and child.poll() is None:
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=2) as response:
                    if response.status == 200:
                        print(f"Server ready: {url} (PID {child.pid})")
                        print(response.read().decode())
                        return 0
            except OSError:
                pass
            time.sleep(1)
        print(f"Server startup failed; see {WORK / 'server.stderr.log'}")
        failed = owned_process(record, args.port)
        if failed is not None:
            stop(failed)
        record.unlink(missing_ok=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
