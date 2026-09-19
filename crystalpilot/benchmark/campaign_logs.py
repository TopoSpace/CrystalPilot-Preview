"""Complete per-case log capture for agent campaigns.

The campaign runner used to keep three numbers from a run - a tool-event
count, a token total, and the last 8 kB of the agent's final message. That
is enough to score a delivery and useless for asking WHY a run went the
way it did: which tool returned an error, what the agent was thinking when
it changed approach, whether it spent forty minutes retrying one call.
Every such question needed the raw material, and the raw material was
being discarded.

What gets captured, and why each source is separately necessary:

  sse.jsonl        every event on the workbench SSE channel - exactly what
                   a human watching the UI would have seen.
  rollout.jsonl    the codex rollout for the thread, which is what the UI
                   does NOT show: the agent's private reasoning, full tool
                   arguments, full tool results, raw shell commands. The
                   thread id is embedded in the filename, so this is a
                   direct lookup rather than a search.
  engine-events/   the engine's own per-session event log, one directory
                   per refinement session.
  nodes.json       the refinement tree as committed, so model evolution can
                   be replayed without re-reading the project.
  results/         the delivered products plus the workbench transcript.
  MANIFEST.json    what was collected, how big, and its sha256 - a log
                   bundle that cannot prove its own completeness is not
                   evidence.

MANIFEST.json also records how many campaign lanes were running while the
case executed and how much memory was free. Wall-clock times from a batch
run on a shared machine are not comparable to each other unless you know
that, and pretending otherwise would put a spurious number in a report.

Capture never raises. A case that finished must not be lost because a log
file was locked; failures land in MANIFEST["errors"] and the run goes on.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CODEX_SESSIONS = REPO / "codex-home" / "sessions"

#: cap on any single copied artefact. A campaign can leave a multi-GB map
#: behind; the point of the bundle is the decision trail, not the density.
MAX_COPY_BYTES = 256 * 1024 * 1024


class CaseLogger:
    """Log bundle for one campaign case. Reused across resumes: sse.jsonl
    is appended to, everything else is re-collected at the end."""

    def __init__(self, out_dir: Path, project_dir: Path, case_name: str):
        self.dir = Path(out_dir) / "logs"
        self.project_dir = Path(project_dir)
        self.case_name = case_name
        self.errors: list[str] = []
        self._lock = threading.Lock()
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:  # pragma: no cover - unwritable workdir
            self.errors.append(f"mkdir: {e}")

    # -- live -------------------------------------------------------------
    def sse(self, seq: int, ev: dict[str, Any]) -> None:
        """Append one SSE event. Called from the turn-following loop, so it
        is on the hot path: one locked binary append, no re-encode of the
        file, no read-back.

        Binary rather than text on purpose. The workbench's own transcript
        writer learned this the hard way - a TextIOWrapper append can split
        a long line mid-multibyte-character when two writers interleave,
        which produced five genuinely corrupt transcripts before
        crystalpilot/workbench/core.py:256 switched to a locked binary
        append. This is the same shape of writer.
        """
        try:
            line = json.dumps({"seq": seq, "ev": ev},
                              ensure_ascii=False, default=str)
            data = (line + "\n").encode("utf-8", errors="replace")
            with self._lock, (self.dir / "sse.jsonl").open("ab") as fh:
                fh.write(data)
        except (OSError, TypeError, ValueError) as e:
            self._note(f"sse: {type(e).__name__}: {e}")

    def _note(self, msg: str) -> None:
        # bounded: a failing sink must not turn into a million-line list
        if len(self.errors) < 200 and msg not in self.errors:
            self.errors.append(msg)

    # -- collection -------------------------------------------------------
    def collect(self, thread_id: str | None, *,
                lanes_busy: int | None = None,
                free_mem_mb: float | None = None,
                extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Gather everything else and write MANIFEST.json. Safe to re-run."""
        self._copy_rollout(thread_id)
        self._copy_engine_events()
        self._copy_mcp_startup_log()
        self._dump_nodes()
        self._copy_results()
        return self._manifest(thread_id, lanes_busy, free_mem_mb, extra)

    def _copy_rollout(self, thread_id: str | None) -> None:
        if not thread_id:
            self._note("rollout: no thread id")
            return
        try:
            hits = sorted(CODEX_SESSIONS.rglob(f"rollout-*-{thread_id}.jsonl"))
        except OSError as e:
            self._note(f"rollout glob: {e}")
            return
        if not hits:
            # a turn that never started leaves no rollout; so does a
            # CODEX_HOME that was rotated between the run and the collect
            self._note(f"rollout: none found for thread {thread_id}")
            return
        # newest wins if a thread id somehow appears twice
        src = max(hits, key=lambda p: p.stat().st_mtime)
        self._copy(src, self.dir / "rollout.jsonl", "rollout")

    def _copy_mcp_startup_log(self) -> None:
        """<project>/.crystalpilot/mcp_server.jsonl: one line per MCP
        process start (pid, knowledge_mode, spec-cache hit, tool count).
        The only evidence of which tool surface the case's MCP actually
        served - the ka1 arm label in state.json is a request, this is
        what ran."""
        src = self.project_dir / ".crystalpilot" / "mcp_server.jsonl"
        if src.is_file():
            self._copy(src, self.dir / "mcp_server.jsonl", "mcp-server")

    def _copy_engine_events(self) -> None:
        runs = self.project_dir / ".crystalpilot" / "refine" / "runs"
        if not runs.is_dir():
            return
        dest = self.dir / "engine-events"
        for sess in sorted(runs.iterdir()):
            ev = sess / "events.jsonl"
            if ev.is_file():
                self._copy(ev, dest / f"{sess.name}.jsonl", "engine-events")

    def _dump_nodes(self) -> None:
        nodes_dir = self.project_dir / ".crystalpilot" / "refine" / "nodes"
        if not nodes_dir.is_dir():
            return
        out: dict[str, Any] = {}
        for nd in sorted(nodes_dir.iterdir()):
            f = nd / "node.json"
            if not f.is_file():
                continue
            try:
                out[nd.name] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                self._note(f"node {nd.name}: {type(e).__name__}: {e}")
        self._write_json(self.dir / "nodes.json", out, "nodes")

    def _copy_results(self) -> None:
        root = self.project_dir / "CrystalPilot Results"
        if not root.is_dir():
            return
        for task in sorted(root.iterdir()):
            if not task.is_dir():
                continue
            for src in sorted(task.rglob("*")):
                if src.is_file():
                    rel = src.relative_to(root)
                    self._copy(src, self.dir / "results" / rel, "results")

    # -- primitives -------------------------------------------------------
    def _copy(self, src: Path, dest: Path, label: str) -> None:
        try:
            size = src.stat().st_size
            if size > MAX_COPY_BYTES:
                self._note(f"{label}: {src.name} skipped ({size} bytes)")
                return
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        except OSError as e:
            self._note(f"{label} {src.name}: {type(e).__name__}: {e}")

    def _write_json(self, path: Path, obj: Any, label: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        except (OSError, TypeError, ValueError) as e:
            self._note(f"{label}: {type(e).__name__}: {e}")

    def _manifest(self, thread_id: str | None, lanes_busy: int | None,
                  free_mem_mb: float | None,
                  extra: dict[str, Any] | None) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        for p in sorted(self.dir.rglob("*")):
            if not p.is_file() or p.name == "MANIFEST.json":
                continue
            try:
                h = hashlib.sha256()
                with p.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                files.append({"path": p.relative_to(self.dir).as_posix(),
                              "bytes": p.stat().st_size,
                              "sha256": h.hexdigest()})
            except OSError as e:
                self._note(f"hash {p.name}: {e}")
        man = {
            "case": self.case_name,
            "thread_id": thread_id,
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "project_dir": str(self.project_dir),
            # wall-clock in a parallel batch means nothing without these
            "lanes_busy": lanes_busy,
            "free_mem_mb": (round(free_mem_mb, 1)
                            if free_mem_mb is not None else None),
            "cpu_cores_env": os.environ.get("CRYSTALPILOT_CPU_CORES"),
            "files": files,
            "total_bytes": sum(f["bytes"] for f in files),
            "errors": self.errors,
            **(extra or {}),
        }
        self._write_json(self.dir / "MANIFEST.json", man, "manifest")
        return man


def free_memory_mb() -> float | None:
    """Free physical memory, or None where it cannot be read cheaply."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        ms = _MS()
        ms.dwLength = ctypes.sizeof(_MS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return None
        return ms.ullAvailPhys / (1024 * 1024)
    except Exception:  # noqa: BLE001 - a telemetry field is never fatal
        return None
