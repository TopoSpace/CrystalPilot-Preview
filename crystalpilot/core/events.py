"""Run store: append-only event log making every solve reproducible and auditable.

Every tool invocation, agent decision, parameter set and result digest is an Event
persisted to ``runs/<run_id>/events.jsonl``. Nothing modifies a structure silently.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


def _now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class Event:
    """One auditable step in a run."""

    kind: str                      # e.g. tool_call, tool_result, agent_thought, agent_decision,
                                   # stage_start, stage_end, artifact, error, user_input
    payload: dict[str, Any]
    run_id: str
    trajectory_id: str = "main"
    event_id: str = field(default_factory=lambda: new_id("ev"))
    parent_id: str | None = None
    ts: float = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": self.event_id,
                "run_id": self.run_id,
                "trajectory_id": self.trajectory_id,
                "parent_id": self.parent_id,
                "ts": self.ts,
                "kind": self.kind,
                "payload": self.payload,
            },
            ensure_ascii=False,
            default=str,
        )


class RunStore:
    """Directory-backed store for a single run: events + artifacts + state."""

    def __init__(self, root: Path, run_id: str | None = None) -> None:
        self.run_id = run_id or new_id("run")
        self.dir = Path(root) / self.run_id
        self.artifacts_dir = self.dir / "artifacts"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(exist_ok=True)
        self._events_path = self.dir / "events.jsonl"

    # -- events ------------------------------------------------------------
    def emit(self, kind: str, payload: dict[str, Any], *, trajectory_id: str = "main",
             parent_id: str | None = None) -> Event:
        ev = Event(kind=kind, payload=payload, run_id=self.run_id,
                   trajectory_id=trajectory_id, parent_id=parent_id)
        with self._events_path.open("a", encoding="utf-8") as fh:
            fh.write(ev.to_json() + "\n")
        return ev

    def events(self) -> Iterator[dict[str, Any]]:
        if not self._events_path.exists():
            return
        with self._events_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    # -- artifacts ---------------------------------------------------------
    def artifact_path(self, name: str) -> Path:
        p = self.artifacts_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save_json(self, name: str, obj: Any) -> Path:
        p = self.artifact_path(name)
        p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                     encoding="utf-8")
        return p

    # -- state (resume support) -------------------------------------------
    def save_state(self, state: dict[str, Any]) -> None:
        (self.dir / "state.json").write_text(
            json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    def load_state(self) -> dict[str, Any] | None:
        p = self.dir / "state.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None
