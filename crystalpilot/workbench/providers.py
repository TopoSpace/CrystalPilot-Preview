"""Safe editing and catalogue probes for Codex model providers.

Codex natively accepts only OpenAI Responses providers. Authentication is an
explicit managed key, environment variable, or none; unrecognized legacy
command/inline auth is preserved until the user deliberately replaces it.
Secrets are never returned, logged, or committed. Sensitive legacy map values
are masked and may be preserved but new constants are refused in favor of the
managed key or ``env_http_headers``.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import codex_config
from .core import ENGINE_ROOT
from .print_token import parse_credential_text
from ..runtime_paths import engine_python

SECRETS_DIR = ENGINE_ROOT / "secrets"
PRINT_TOKEN = ENGINE_ROOT / "crystalpilot" / "workbench" / "print_token.py"
ENGINE_PY = engine_python(ENGINE_ROOT)
DEFAULT_CRED_FILE = ENGINE_ROOT / "testAPI.txt"
#: provider kinds the model list knows how to ask
KIND_OPENROUTER = "openrouter"
KIND_OPENAI_COMPAT = "openai_compatible"
WIRE_API_RESPONSES = "responses"
AUTH_MANAGED = "managed_api_key"
AUTH_ENVIRONMENT = "environment"
AUTH_NONE = "none"
MASKED_VALUE = "********"
_UNSET = object()
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_NAME_RE = re.compile(
    r"(^|[-_])(authorization|proxy-authorization|auth|api[-_]?key|key|token|cookie|"
    r"secret|credential|signature|sig|password|passwd)([-_]|$)",
    re.IGNORECASE,
)


def _cred_file_of(table: dict[str, Any]) -> Path | None:
    auth = table.get("auth") or {}
    if not isinstance(auth, dict):
        return None
    args = auth.get("args") or []
    if isinstance(args, list) and "--cred" in args:
        i = args.index("--cred")
        if i + 1 < len(args):
            return Path(str(args[i + 1]))
    if auth.get("command"):
        env = os.environ.get("CRYSTALPILOT_CRED_FILE")
        return Path(env) if env else DEFAULT_CRED_FILE
    return None


def _auth_kind(table: dict[str, Any]) -> str:
    if table.get("auth"):
        return "command"
    if table.get("env_key"):
        return "env_key"
    if table.get("experimental_bearer_token"):
        return "inline"
    if table.get("aws") or table.get("requires_openai_auth"):
        return "other"
    return "none"


def _same_path(left: object, right: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
            os.path.abspath(str(right))
        )
    except (OSError, ValueError, TypeError):
        return False


def _is_managed_auth(table: dict[str, Any], cred: Path | None) -> bool:
    auth = table.get("auth") or {}
    if not isinstance(auth, dict):
        return False
    args = auth.get("args") or []
    if not isinstance(args, list) or not cred:
        return False
    if not _same_path(auth.get("command"), ENGINE_PY):
        return False
    if not args or not _same_path(args[0], PRINT_TOKEN):
        return False
    return cred == DEFAULT_CRED_FILE or cred.parent == SECRETS_DIR


def _auth_mode(table: dict[str, Any], managed: bool) -> str:
    kind = _auth_kind(table)
    if kind == "command" and managed:
        return AUTH_MANAGED
    if kind == "env_key":
        return AUTH_ENVIRONMENT
    if kind == "none":
        return AUTH_NONE
    return "legacy"


def _is_sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_NAME_RE.search(name))


def _masked_map(values: object) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {
        str(k): MASKED_VALUE if _is_sensitive_name(str(k)) else str(v)
        for k, v in values.items()
    }


def _clean_string_map(value: object, field: str, *, headers: bool = False,
                      env_values: bool = False) -> dict[str, str]:
    if not isinstance(value, dict):
        raise codex_config.ConfigError(f"{field} must be an object of string pairs")
    if len(value) > 64:
        raise codex_config.ConfigError(f"{field} may contain at most 64 entries")
    out: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            raise codex_config.ConfigError(f"{field} keys and values must be strings")
        key, item = raw_key.strip(), raw_value.strip()
        if not key or len(key) > 256 or len(item) > 8192:
            raise codex_config.ConfigError(f"{field} contains an empty or overlong entry")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in key + item):
            raise codex_config.ConfigError(f"{field} must not contain control characters")
        if headers and not _HEADER_NAME_RE.fullmatch(key):
            raise codex_config.ConfigError(f"invalid HTTP header name {key!r}")
        if env_values and not _ENV_NAME_RE.fullmatch(item):
            raise codex_config.ConfigError(f"invalid environment variable name {item!r}")
        if key in out:
            raise codex_config.ConfigError(f"{field} contains duplicate key {key!r}")
        out[key] = item
    return out


def _restore_masked_values(values: dict[str, str], existing: object,
                           field: str, *, allow_sensitive_new: bool = False) -> dict[str, str]:
    old = existing if isinstance(existing, dict) else {}
    out: dict[str, str] = {}
    for key, value in values.items():
        if value == MASKED_VALUE and _is_sensitive_name(key):
            if key not in old:
                raise codex_config.ConfigError(
                    f"{field}.{key} is masked but has no stored value to preserve"
                )
            out[key] = str(old[key])
        elif _is_sensitive_name(key) and not allow_sensitive_new:
            raise codex_config.ConfigError(
                f"{field}.{key} looks sensitive; use managed API-key auth or an environment header"
            )
        else:
            out[key] = value
    return out


def _optional_uint(value: object, field: str, maximum: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise codex_config.ConfigError(f"{field} must be an integer or null")
    if not 0 <= value <= maximum:
        raise codex_config.ConfigError(f"{field} must be between 0 and {maximum}")
    return value


def provider_kind(pid: str, table: dict[str, Any]) -> str:
    url = str(table.get("base_url") or "").lower()
    if "openrouter.ai" in url or pid == "openrouter":
        return KIND_OPENROUTER
    return KIND_OPENAI_COMPAT


def _key_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"has_key": False, "cred_file": None, "key_updated": None}
    try:
        st = path.stat()
        has = parse_credential_text(path.read_text(encoding="utf-8")) is not None
        updated = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)
        ) if has else None
        return {"has_key": has, "cred_file": str(path), "key_updated": updated}
    except (OSError, UnicodeError):
        return {"has_key": False, "cred_file": str(path), "key_updated": None}


def describe(pid: str, table: dict[str, Any], default_pid: str | None) -> dict[str, Any]:
    cred = _cred_file_of(table)
    kind = _auth_kind(table)
    managed = kind == "command" and _is_managed_auth(table, cred)
    wire_api = str(table.get("wire_api") or WIRE_API_RESPONSES)
    d = {"id": pid,
         "name": table.get("name") or pid,
         "base_url": table.get("base_url"),
         "wire_api": wire_api,
         "protocol_compatible": wire_api == WIRE_API_RESPONSES,
         "kind": provider_kind(pid, table),
         "is_default": pid == default_pid,
         "auth_kind": kind,
         "auth_mode": _auth_mode(table, managed),
         "env_key": table.get("env_key"),
         "http_headers": _masked_map(table.get("http_headers")),
         "env_http_headers": dict(table.get("env_http_headers") or {}),
         "query_params": _masked_map(table.get("query_params")),
         "request_max_retries": table.get("request_max_retries"),
         "stream_max_retries": table.get("stream_max_retries"),
         "stream_idle_timeout_ms": table.get("stream_idle_timeout_ms"),
         "managed": managed}
    if kind == "env_key":
        d.update({"has_key": bool(os.environ.get(str(table.get("env_key")))),
                  "cred_file": None, "key_updated": None})
    elif kind == "inline":
        d.update({"has_key": True, "cred_file": None, "key_updated": None})
    elif managed:
        d.update(_key_state(cred))
    else:
        # Do not inspect or expose paths belonging to an external auth command.
        d.update({"has_key": False, "cred_file": None, "key_updated": None})
    return d


def list_providers() -> list[dict[str, Any]]:
    cfg = codex_config.load()
    default_pid = cfg.get("model_provider")
    out = []
    for pid, table in (cfg.get("model_providers") or {}).items():
        if isinstance(table, dict):
            out.append(describe(pid, table, default_pid))
    # the default first, then the rest in file order
    out.sort(key=lambda d: (not d["is_default"]))
    return out


def get_provider(pid: str) -> dict[str, Any] | None:
    cfg = codex_config.load()
    table = (cfg.get("model_providers") or {}).get(pid)
    if not isinstance(table, dict):
        return None
    return describe(pid, table, cfg.get("model_provider"))


def read_key(pid: str) -> str | None:
    """INTERNAL: the bearer token for server-side probes only."""
    cfg = codex_config.load()
    table = (cfg.get("model_providers") or {}).get(pid) or {}
    if table.get("env_key"):
        return os.environ.get(str(table["env_key"])) or None
    if table.get("experimental_bearer_token"):
        return str(table["experimental_bearer_token"])
    cred = _cred_file_of(table)
    if cred is None or not _is_managed_auth(table, cred):
        return None
    try:
        text = cred.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    return parse_credential_text(text)


def _write_key(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(key.strip() + "\n", encoding="utf-8")
    os.replace(tmp, path)


def normalize_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if len(u) > 2048 or any(ord(ch) < 32 or ord(ch) == 127 for ch in u):
        raise codex_config.ConfigError(
            "base_url is empty, too long, or contains control characters"
        )
    try:
        parsed = urllib.parse.urlsplit(u)
    except ValueError as e:
        raise codex_config.ConfigError(f"invalid base_url: {e}") from e
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise codex_config.ConfigError("base_url must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password:
        raise codex_config.ConfigError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise codex_config.ConfigError("base_url must not contain a query string or fragment")
    return u


def upsert_provider(
    pid: str,
    name: str | None,
    base_url: str,
    api_key: str | None = None,
    http_headers: dict[str, str] | None | object = _UNSET,
    *,
    wire_api: str | object = _UNSET,
    auth_mode: str | None | object = _UNSET,
    env_key: str | None | object = _UNSET,
    remove_api_key: bool = False,
    query_params: dict[str, str] | None | object = _UNSET,
    env_http_headers: dict[str, str] | None | object = _UNSET,
    request_max_retries: int | None | object = _UNSET,
    stream_max_retries: int | None | object = _UNSET,
    stream_idle_timeout_ms: int | None | object = _UNSET,
) -> dict[str, Any]:
    """Create or update a Responses provider without exposing stored secrets.

    Omitted fields preserve existing config. A blank key also preserves it;
    removal requires ``remove_api_key=True``. Changing auth mode is explicit,
    so legacy command/inline auth survives ordinary name or URL edits.
    """
    pid = codex_config.validate_provider_id(pid)
    base = normalize_base_url(base_url)
    clean_name = (name or "").strip()
    if len(clean_name) > 160 or any(ord(ch) < 32 or ord(ch) == 127 for ch in clean_name):
        raise codex_config.ConfigError("provider name is too long or contains control characters")
    cfg = codex_config.load()
    existing = (cfg.get("model_providers") or {}).get(pid) or {}
    if not isinstance(existing, dict):
        existing = {}

    protocol = str(existing.get("wire_api") or WIRE_API_RESPONSES) if wire_api is _UNSET \
        else str(wire_api or "")
    if protocol != WIRE_API_RESPONSES:
        raise codex_config.ConfigError(
            "Codex only supports the OpenAI Responses protocol; Chat Completions, "
            "legacy Completions, and Anthropic Messages require a Responses-compatible gateway"
        )
    mode = (AUTH_MANAGED if not existing else None) if auth_mode is _UNSET else auth_mode
    if not existing and mode is None:
        mode = AUTH_MANAGED
    if mode not in (None, AUTH_MANAGED, AUTH_ENVIRONMENT, AUTH_NONE):
        raise codex_config.ConfigError("invalid authentication mode")
    if remove_api_key and api_key is not None and api_key.strip():
        raise codex_config.ConfigError("cannot set and remove an API key together")
    cleaned_key = api_key.strip() if api_key is not None else ""
    if cleaned_key and (any(ch.isspace() for ch in cleaned_key) or len(cleaned_key) > 4096):
        raise codex_config.ConfigError("that does not look like an API key")

    updates: dict[str, Any] = {}
    map_specs = (
        ("http_headers", http_headers, True, False),
        ("query_params", query_params, False, False),
        ("env_http_headers", env_http_headers, True, True),
    )
    for field, value, header_names, env_values in map_specs:
        if value is _UNSET:
            continue
        if value is None:
            continue
        cleaned = _clean_string_map(value, field, headers=header_names, env_values=env_values)
        if field != "env_http_headers":
            cleaned = _restore_masked_values(cleaned, existing.get(field), field)
        updates[field] = cleaned or None
    for field, value, maximum in (
        ("request_max_retries", request_max_retries, 100),
        ("stream_max_retries", stream_max_retries, 100),
        ("stream_idle_timeout_ms", stream_idle_timeout_ms, 86_400_000),
    ):
        if value is not _UNSET:
            updates[field] = _optional_uint(value, field, maximum)

    env_name = existing.get("env_key") if env_key is _UNSET else env_key
    if mode == AUTH_ENVIRONMENT:
        env_name = str(env_name or "").strip()
        if not _ENV_NAME_RE.fullmatch(env_name):
            raise codex_config.ConfigError(
                "environment-variable authentication needs a valid variable name"
            )

    existing_cred = _cred_file_of(existing) if existing else None
    existing_managed = _is_managed_auth(existing, existing_cred)
    cred = existing_cred if existing_managed else SECRETS_DIR / f"{pid}.txt"
    table: dict[str, Any] = {k: v for k, v in existing.items() if k != "auth"}
    table.update({"name": clean_name or existing.get("name") or pid,
                  "base_url": base, "wire_api": protocol})
    for field, value in updates.items():
        if value is None:
            table.pop(field, None)
        else:
            table[field] = value

    auth = existing.get("auth") if isinstance(existing.get("auth"), dict) else None
    if mode == AUTH_MANAGED:
        table.pop("env_key", None)
        table.pop("experimental_bearer_token", None)
        table.pop("aws", None)
        table.pop("requires_openai_auth", None)
        args = [str(PRINT_TOKEN)]
        if cred != DEFAULT_CRED_FILE:
            args += ["--cred", str(cred)]
        auth = {"command": str(ENGINE_PY), "args": args}
    elif mode == AUTH_ENVIRONMENT:
        table.pop("experimental_bearer_token", None)
        table.pop("aws", None)
        table.pop("requires_openai_auth", None)
        table["env_key"] = env_name
        auth = None
    elif mode == AUTH_NONE:
        table.pop("env_key", None)
        table.pop("experimental_bearer_token", None)
        table.pop("aws", None)
        table.pop("requires_openai_auth", None)
        auth = None

    comment = None if existing else (
        f"Added from the settings dialog on {time.strftime('%Y-%m-%d')}: "
        "OpenAI Responses-compatible endpoint; managed keys live in the git-ignored "
        "secrets directory and reach codex only through print_token.py."
    )
    # Render once before touching a credential so unknown preserved values
    # cannot make config serialization fail after the key has changed.
    codex_config.render_provider_block(pid, table, auth, comment)

    # All fields are validated before either the credential or config changes.
    if cleaned_key:
        if mode != AUTH_MANAGED and not (mode is None and existing_managed):
            raise codex_config.ConfigError("an API key can only be saved in managed API-key mode")
        _write_key(cred, cleaned_key)
    elif remove_api_key:
        if not existing_managed and mode != AUTH_MANAGED:
            raise codex_config.ConfigError("there is no managed API key to remove")
        try:
            if cred.exists():
                cred.unlink()
        except OSError as e:
            raise codex_config.ConfigError(f"could not remove the managed API key: {e}") from e

    codex_config.upsert_provider(pid, table, auth, comment)
    out = get_provider(pid)
    assert out is not None
    return out


def remove_provider(pid: str) -> dict[str, Any]:
    pid = codex_config.validate_provider_id(pid)
    cfg = codex_config.load()
    if cfg.get("model_provider") == pid:
        raise codex_config.ConfigError(
            "cannot remove the default provider; pick another default first"
        )
    table = (cfg.get("model_providers") or {}).get(pid)
    if not isinstance(table, dict):
        raise KeyError(pid)
    cred = _cred_file_of(table)
    removed = codex_config.remove_provider(pid)
    parked = None
    if cred is not None and cred.parent == SECRETS_DIR and cred.exists():
        # the key is parked, not destroyed (still git-ignored)
        parked = cred.with_name(f"{cred.name}.removed-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            os.replace(cred, parked)
        except OSError:
            parked = None
    return {"removed": removed, "id": pid, "key_parked": str(parked) if parked else None}


def set_default_provider(pid: str) -> dict[str, Any]:
    pid = codex_config.validate_provider_id(pid)
    if pid not in (codex_config.load().get("model_providers") or {}):
        raise KeyError(pid)
    codex_config.set_top_level("model_provider", pid)
    return {"model_provider": pid}


# ---------------------------------------------------------------- probing
def _get_json(url: str, headers: dict[str, str], timeout: float = 20.0) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body[:500]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def _safe_error(value: object, secrets: list[str]) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            for representation in (secret, urllib.parse.quote(secret, safe=""),
                                   urllib.parse.quote_plus(secret)):
                text = text.replace(representation, "[redacted]")
    return text[:300]


def test_connection(pid: str | None = None, base_url: str | None = None,
                    api_key: str | None = None,
                    http_headers: dict[str, str] | None = None,
                    query_params: dict[str, str] | None = None) -> dict[str, Any]:
    """Check only whether ``GET <base_url>/models`` is reachable.

    No billable model invocation is made, so this never claims Responses
    invocation compatibility. Secrets are used only server-side and redacted
    from every returned error.
    """
    table: dict[str, Any] = {}
    if pid:
        table = (codex_config.load().get("model_providers") or {}).get(pid) or {}
    base = normalize_base_url(base_url or str(table.get("base_url") or ""))
    key = api_key.strip() if api_key and api_key.strip() else (read_key(pid) if pid else None)
    raw_headers = (table.get("http_headers") or {}) if http_headers is None else http_headers
    cleaned_headers = _clean_string_map(raw_headers, "http_headers", headers=True)
    if http_headers is not None:
        cleaned_headers = _restore_masked_values(
            cleaned_headers, table.get("http_headers"), "http_headers",
            allow_sensitive_new=True,
        )
    raw_query = (table.get("query_params") or {}) if query_params is None else query_params
    cleaned_query = _clean_string_map(raw_query, "query_params")
    if query_params is not None:
        cleaned_query = _restore_masked_values(
            cleaned_query, table.get("query_params"), "query_params",
            allow_sensitive_new=True,
        )
    headers = {"Accept": "application/json", "User-Agent": "CrystalPilot/settings"}
    headers.update(cleaned_headers)
    for header, variable in _clean_string_map(
        table.get("env_http_headers") or {}, "env_http_headers", headers=True, env_values=True
    ).items():
        value = os.environ.get(variable)
        if value:
            headers[header] = value
    suffix = urllib.parse.urlencode(cleaned_query)
    models_url = base + "/models" + (f"?{suffix}" if suffix else "")
    if key:
        headers.setdefault("Authorization", f"Bearer {key}")
    secrets = [key or ""] + [v for k, v in headers.items() if _is_sensitive_name(k)] + [
        v for k, v in cleaned_query.items() if _is_sensitive_name(k)
    ]
    t0 = time.time()
    out: dict[str, Any] = {
        "ok": False,
        "check": "model_catalogue",
        "protocol_compatible": None,
        "base_url": base,
        "used_stored_key": bool(key) and not bool(api_key and api_key.strip()),
        "has_key": bool(key),
    }
    try:
        status, body = _get_json(models_url, headers)
    except (urllib.error.URLError, OSError, ValueError) as e:
        out.update({"status": None, "error": _safe_error(f"{type(e).__name__}: {e}", secrets)})
        out["latency_ms"] = int((time.time() - t0) * 1000)
        return out
    out["latency_ms"] = int((time.time() - t0) * 1000)
    out["status"] = status
    ids: list[str] = []
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            ids = [str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id")]
        err = body.get("error")
        if err and status >= 400:
            detail = err.get("message") if isinstance(err, dict) else err
            out["error"] = _safe_error(detail, secrets)
    elif isinstance(body, str) and status >= 400:
        out["error"] = _safe_error(body, secrets)
    if 200 <= status < 300:
        out["ok"] = True
        out["n_models"] = len(ids)
        out["sample"] = ids[:40]
        out["ids"] = ids
    elif status in (401, 403):
        out.setdefault("error", "the model catalogue endpoint rejected the credentials")
    elif status == 404:
        out.setdefault(
            "error",
            "no /models route; this check does not determine Responses invocation compatibility",
        )
    # OpenRouter: the key endpoint names the key label and its usage caps
    if provider_kind(pid or "", {"base_url": base}) == KIND_OPENROUTER and key:
        try:
            # A proxy may use a proxy-specific credential. Keep it at the
            # configured endpoint rather than forwarding it to another host.
            key_url = base + "/key" + (f"?{suffix}" if suffix else "")
            st2, body2 = _get_json(key_url, headers)
            if st2 == 200 and isinstance(body2, dict) and isinstance(body2.get("data"), dict):
                d = body2["data"]
                out["key_info"] = {
                    k: (_safe_error(d.get(k), secrets) if isinstance(d.get(k), str) else d.get(k))
                    for k in ("label", "usage", "limit", "limit_remaining", "is_free_tier")
                    if k in d
                }
                # Key metadata complements the catalogue check; it does not
                # turn a failed /models request into a successful catalogue.
            elif st2 in (401, 403):
                out["ok"] = False
                out["error"] = "OpenRouter rejected the credentials"
        except (urllib.error.URLError, OSError, ValueError):
            pass
    return out
