"""Read and surgically edit the isolated codex config (codex-home/config.toml).

The file is hand-maintained "config as code" with comments that explain
each provider and guard rail, so writes are line-level edits that keep
everything else byte-for-byte: a top-level scalar is replaced in place (or
inserted before the first table header), a `[model_providers.<id>]` block
(with its `.auth` / `.http_headers` sub-tables) is replaced or appended as a
unit, and every write is parsed back with tomllib before it lands
(temp file + atomic replace, previous text kept as config.toml.bak).

TOML values written here are limited to what the settings UI needs: strings
(basic, escaped), integers, floats, booleans, string lists and one-level
inline tables of strings.
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

from .core import CODEX_HOME

CONFIG_PATH = CODEX_HOME / "config.toml"
_HEADER_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*(#.*)?$")
#: provider ids: bare TOML keys, lower-case, no dots (a dot would open a
#: sub-table); the three names codex reserves are refused too
PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
RESERVED_PROVIDER_IDS = ("openai", "ollama", "lmstudio")


class ConfigError(ValueError):
    pass


def config_path() -> Path:
    return CONFIG_PATH


def read_text() -> str:
    return CONFIG_PATH.read_text(encoding="utf-8")


def load() -> dict[str, Any]:
    with CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def config_mtime() -> float:
    try:
        return CONFIG_PATH.stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------- literals
def _escape(s: str) -> str:
    return (s.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\t", "\\t"))


def toml_value(v: Any) -> str:
    """Render a Python value as a TOML literal (the subset the UI writes)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        # literal strings keep Windows paths readable and need no escaping
        if "\\" in v and "'" not in v and "\n" not in v:
            return f"'{v}'"
        return f'"{_escape(v)}"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        items = ", ".join(f'"{_escape(str(k))}" = {toml_value(x)}' for k, x in v.items())
        return "{ " + items + " }"
    raise ConfigError(f"cannot write a {type(v).__name__} to config.toml")


# --------------------------------------------------------------- structure
def _lines(text: str) -> list[str]:
    return text.split("\n")


def _first_header_index(lines: list[str]) -> int:
    for i, ln in enumerate(lines):
        if _HEADER_RE.match(ln):
            return i
    return len(lines)


def _top_level_key_index(lines: list[str], key: str) -> int | None:
    """The line index of `key = ...` in the top-level scope (before the
    first table header), None when absent."""
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i in range(_first_header_index(lines)):
        if pat.match(lines[i]):
            return i
    return None


def _validate(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config.toml would become invalid: {e}") from e


def _write(text: str) -> None:
    _validate(text)
    tmp = CONFIG_PATH.with_suffix(".toml.tmp")
    bak = CONFIG_PATH.with_suffix(".toml.bak")
    try:
        bak.write_text(read_text(), encoding="utf-8")
    except OSError:
        pass
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)


# ------------------------------------------------------------ top-level keys
def get_top_level(key: str) -> Any:
    return load().get(key)


def set_top_level(key: str, value: Any) -> dict[str, Any]:
    """Set (or, with None, remove) a top-level scalar. Returns the parsed
    config after the write."""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        raise ConfigError(f"bad config key {key!r}")
    lines = _lines(read_text())
    idx = _top_level_key_index(lines, key)
    if value is None:
        if idx is not None:
            del lines[idx]
    else:
        rendered = f"{key} = {toml_value(value)}"
        if idx is not None:
            # keep a trailing comment on the same line
            m = re.match(r"^[^#]*?(\s+#.*)$", lines[idx])
            lines[idx] = rendered + (m.group(1) if m else "")
        else:
            # after the last top-level assignment, else before the first header
            last = None
            for i in range(_first_header_index(lines)):
                if re.match(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=", lines[i]):
                    last = i
            at = (last + 1) if last is not None else _first_header_index(lines)
            lines.insert(at, rendered)
    text = "\n".join(lines)
    _write(text)
    return _validate(text)


def set_top_level_many(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = load()
    for k, v in values.items():
        out = set_top_level(k, v)
    return out


# --------------------------------------------------------- provider blocks
def _provider_span(lines: list[str], pid: str,
                   with_comments: bool = True) -> tuple[int, int] | None:
    """(start, end) line indexes of the `[model_providers.<pid>]` block
    including its sub-tables and, with `with_comments`, the comment lines
    glued to its header (a replacement keeps them, a removal takes them);
    `end` is exclusive and excludes trailing blank lines."""
    start = None
    for i, ln in enumerate(lines):
        m = _HEADER_RE.match(ln)
        if m and m.group("name").strip() == f"model_providers.{pid}":
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = _HEADER_RE.match(lines[j])
        if m and not m.group("name").strip().startswith(f"model_providers.{pid}."):
            end = j
            break
    if with_comments:
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
    while end > start + 1 and lines[end - 1].strip() == "":
        end -= 1
    return start, end


def _insertion_index(lines: list[str]) -> int:
    """Where a new provider block goes: after the last provider block, else
    before [agents] / the first [projects.*] header, else at the end."""
    last_end = None
    i = 0
    while i < len(lines):
        m = _HEADER_RE.match(lines[i])
        if m and m.group("name").strip().startswith("model_providers."):
            pid = m.group("name").strip().split(".")[1]
            span = _provider_span(lines, pid)
            if span:
                last_end = span[1]
                i = span[1]
                continue
        i += 1
    if last_end is not None:
        return last_end
    for i, ln in enumerate(lines):
        m = _HEADER_RE.match(ln)
        if m and (m.group("name").strip() == "agents"
                  or m.group("name").strip().startswith("projects.")):
            # keep the comment paragraph glued to that header
            while i > 0 and lines[i - 1].lstrip().startswith("#"):
                i -= 1
            return i
    return len(lines)


def validate_provider_id(pid: str) -> str:
    p = (pid or "").strip()
    if not PROVIDER_ID_RE.match(p):
        raise ConfigError(
            "provider id must be 1-32 chars: lower-case letters, digits, '-' or "
            "'_', starting with a letter")
    if p in RESERVED_PROVIDER_IDS:
        raise ConfigError(f"provider id {p!r} is reserved by codex")
    return p


def render_provider_block(pid: str, table: dict[str, Any],
                          auth: dict[str, Any] | None = None,
                          comment: str | None = None) -> str:
    lines = []
    if comment:
        for c in comment.rstrip("\n").split("\n"):
            lines.append(f"# {c}" if c else "#")
    lines.append(f"[model_providers.{pid}]")
    for k, v in table.items():
        if v is None:
            continue
        lines.append(f"{k} = {toml_value(v)}")
    if auth:
        lines.append("")
        lines.append(f"[model_providers.{pid}.auth]")
        for k, v in auth.items():
            if v is None:
                continue
            lines.append(f"{k} = {toml_value(v)}")
    return "\n".join(lines)


def providers() -> dict[str, dict[str, Any]]:
    return dict(load().get("model_providers") or {})


def upsert_provider(pid: str, table: dict[str, Any],
                    auth: dict[str, Any] | None = None,
                    comment: str | None = None) -> dict[str, Any]:
    pid = validate_provider_id(pid)
    lines = _lines(read_text())
    span = _provider_span(lines, pid, with_comments=False)
    if span:
        # an existing block keeps the comment paragraph above its header
        # unless the caller supplies a new one
        s, e = span
        if comment and s > 0 and lines[s - 1].lstrip().startswith("#"):
            while s > 0 and lines[s - 1].lstrip().startswith("#"):
                s -= 1
        block = render_provider_block(pid, table, auth, comment)
        lines[s:e] = block.split("\n")
    else:
        block = render_provider_block(pid, table, auth, comment)
        at = _insertion_index(lines)
        chunk = block.split("\n")
        if at > 0 and lines[at - 1].strip() != "":
            chunk = [""] + chunk
        if at < len(lines) and lines[at].strip() != "":
            chunk = chunk + [""]
        lines[at:at] = chunk
    text = "\n".join(lines)
    _write(text)
    return _validate(text)["model_providers"][pid]


def remove_provider(pid: str) -> bool:
    pid = validate_provider_id(pid)
    lines = _lines(read_text())
    span = _provider_span(lines, pid)
    if not span:
        return False
    s, e = span
    del lines[s:e]
    # collapse the double blank line the removal leaves behind
    if 0 < s < len(lines) and lines[s].strip() == "" and lines[s - 1].strip() == "":
        del lines[s]
    _write("\n".join(lines))
    return True
