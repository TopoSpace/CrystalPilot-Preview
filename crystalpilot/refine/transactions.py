"""Cooperating project processes share a permanent OS lock, never a stale sentinel.

Readers retain this lock too: this first stage provides a fixed read version by
serialization, not parallel immutable reflection-data snapshots. All writers must
run this implementation; external file edits and older binaries are not covered.
"""
from __future__ import annotations

import contextlib
import errno
import functools
import json
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_LOCK_TIMEOUT_S = 1800.0
POLL_S = 0.05
PING_S = 10.0
UNSET = object()


class TransactionError(RuntimeError):
    code = "transaction_failed"

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.details = details


class LockTimeout(TransactionError):
    code = "project_lock_timeout"


class TransactionCancelled(TransactionError):
    code = "cancelled"


class StateConflict(TransactionError):
    code = "state_conflict"


def check_cancelled(event) -> None:
    if event is not None and event.is_set():
        raise TransactionCancelled("Operation cancelled before publication")


@dataclass
class _Ownership:
    mutex: Any = field(default_factory=threading.RLock)
    depth: int = 0
    fd: int | None = None
    cancel_event: Any = None
    progress: Any = None
    commit_hooks: list = field(default_factory=list)

    def check_cancelled(self) -> None:
        check_cancelled(self.cancel_event)

    def committed(self) -> None:
        errors = []
        for hook in tuple(self.commit_hooks):
            try:
                hook()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]


_registry: dict[str, _Ownership] = {}
_registry_guard = threading.Lock()
_registry_pid = os.getpid()


def _entry(directory: Path) -> _Ownership:
    global _registry, _registry_guard, _registry_pid
    if _registry_pid != os.getpid():
        # Close inherited descriptors without unlocking the parent's flock.
        for entry in _registry.values():
            if entry.fd is not None:
                os.close(entry.fd)
        _registry = {}
        _registry_guard = threading.Lock()
        _registry_pid = os.getpid()
    key = os.path.normcase(str(directory.resolve()))
    with _registry_guard:
        return _registry.setdefault(key, _Ownership())


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise
        return False


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def _owner(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def project_transaction(project_dir: str | Path, *, operation: str = "project",
                        timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
                        cancel_event=None, progress=None):
    directory = Path(project_dir).resolve()
    root = directory / ".crystalpilot" / "refine"
    root.mkdir(parents=True, exist_ok=True)
    owner_path = root / "project.owner.json"
    entry = _entry(directory)
    deadline = time.monotonic() + max(0.0, timeout_s)
    next_ping = time.monotonic() + PING_S

    def waiting():
        nonlocal next_ping
        check_cancelled(cancel_event)
        now = time.monotonic()
        holder = _owner(owner_path)
        if now >= deadline:
            raise LockTimeout("Timed out waiting for the project lock; retry later. "
                              "Do not delete the lock or kill its owner.",
                              project=str(directory), owner=holder)
        if progress is not None and now >= next_ping:
            next_ping = now + PING_S
            try:
                progress(f"{operation}: waiting for project lock; owner={holder}")
            except Exception:
                pass
        time.sleep(min(POLL_S, max(0.0, deadline - now)))

    check_cancelled(cancel_event)
    while not entry.mutex.acquire(blocking=False):
        waiting()
    acquired = False
    previous_cancel, previous_progress = entry.cancel_event, entry.progress
    try:
        if entry.depth == 0:
            # Never truncate/unlink/replace this inode. Locking past EOF is
            # supported by msvcrt and avoids an unlocked initialization write.
            entry.fd = os.open(root / "project.lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                while not _try_lock(entry.fd):
                    waiting()
                acquired = True
                check_cancelled(cancel_event)
                owner = {"pid": os.getpid(), "host": socket.gethostname(),
                         "thread": threading.get_ident(), "operation": operation,
                         "started_at": time.time()}
                try:
                    owner_path.write_text(json.dumps(owner), encoding="utf-8")
                except OSError:
                    pass
            except BaseException:
                if acquired:
                    _unlock(entry.fd)
                os.close(entry.fd)
                entry.fd = None
                raise
        entry.depth += 1
        if cancel_event is not None:
            entry.cancel_event = cancel_event
        if progress is not None:
            entry.progress = progress
        try:
            yield entry
        finally:
            entry.cancel_event, entry.progress = previous_cancel, previous_progress
            entry.depth -= 1
            if entry.depth == 0:
                try:
                    _unlock(entry.fd)
                finally:
                    os.close(entry.fd)
                    entry.fd = None
    finally:
        entry.mutex.release()


def locked(method):
    """Lock a project/store method including its reads, not just its final write."""
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        directory = getattr(self, "dir", None) or self.project_dir
        with project_transaction(directory, operation=method.__name__):
            try:
                return method(self, *args, **kwargs)
            except BaseException:
                discard = getattr(self, "_discard_session", None)
                if discard is not None:
                    discard()
                raise
    return wrapped


def validate_expected(state: dict, *, expected_node=UNSET,
                      expected_project_revision=UNSET) -> None:
    expected = {}
    if expected_node is not UNSET:
        if expected_node is not None and not isinstance(expected_node, str):
            raise ValueError("expected_node must be a node id or null")
        expected["node"] = expected_node
    if expected_project_revision is not UNSET:
        if (type(expected_project_revision) is not int
                or expected_project_revision < 0):
            raise ValueError("expected_project_revision must be a nonnegative integer")
        expected["project_revision"] = expected_project_revision
    current = {"node": state.get("active_node"),
               "project_revision": state.get("project_revision", 0)}
    if any(current[key] != value for key, value in expected.items()):
        raise StateConflict("Project state changed; refresh and reapprove the operation. "
                            "The tool was not run.", expected=expected, current=current)
