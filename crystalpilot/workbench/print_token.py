"""Auth command for the Codex model provider: prints the bearer token to stdout.

Invoked by codex app-server on demand ([model_providers.*.auth] command). The
key therefore never sits in the app-server process environment and is never
inherited by agent shell commands.

SOFT caller gate (defense-in-depth, not a security boundary - the agent
shares the OS user): the legitimate chain is codex.exe -> venv python
launcher stub -> real python (so the DIRECT parent is python.exe - the
venv python.exe re-execs the base interpreter as a child). An agent shell
replaying the command arrives as codex.exe -> bash/cmd/pwsh -> python
stub -> python. Rule: walk ancestors, skip python layers, and judge the
first NON-python ancestor - allow codex, refuse shells/others. Detection
failure fails OPEN (model auth must never break on a psutil hiccup).
CRYSTALPILOT_CRED_FILE overrides the credential file path; a second
provider's hook passes `--cred <file>` instead (codex-home/config.toml
[model_providers.<id>.auth] args), so several providers can share this
one gate with one credential file each.
"""
import os
import re
import sys
from pathlib import Path

CRED_FILE = Path(os.environ.get("CRYSTALPILOT_CRED_FILE")
                 or Path(__file__).resolve().parents[2] / "testAPI.txt")

_ALLOWED = {"codex.exe", "codex"}
_PYTHON_LAYERS = {"python.exe", "python", "pythonw.exe", "py.exe"}


def parse_credential_text(text: str) -> str | None:
    """Parse the gateway's ``Key: ...`` note or a managed bare token."""
    m = re.search(r"Key[：:]\s*(\S+)", text)
    if m:
        return m.group(1)
    bare = text.strip()
    if not bare or any(ch.isspace() for ch in bare):
        return None
    return bare


def _caller_looks_legitimate() -> bool:
    try:
        import psutil
        p = psutil.Process(os.getpid())
        chain: list[str] = []
        for _ in range(6):
            p = p.parent()
            if p is None:
                break
            chain.append(p.name().lower())
        if os.environ.get("CRYSTALPILOT_TOKEN_TRACE") == "1":
            try:  # diagnostic breadcrumb: process names only, never secrets
                log = Path(__file__).resolve().parents[2] \
                    / "workdir" / "token_caller.log"
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(" <- ".join(chain) + "\n")
            except Exception:  # noqa: BLE001
                pass
        for name in chain:
            if name in _PYTHON_LAYERS or re.fullmatch(r"python\d+(?:\.\d+)?", name):
                continue          # venv launcher stub re-exec layer(s)
            return name in _ALLOWED
        return True               # all-python / empty chain: inconclusive
    except Exception:  # noqa: BLE001 - fail open: auth availability first
        return True


def credential_file(argv: list[str]) -> Path:
    """`--cred <file>` wins over the env / default location."""
    if "--cred" in argv:
        i = argv.index("--cred")
        if i + 1 < len(argv):
            return Path(argv[i + 1])
    return CRED_FILE


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not _caller_looks_legitimate():
        print("refused: this command only serves the codex app-server "
              "auth hook. Agents and shells must not read credentials "
              "(see AGENTS.md honesty rules).", file=sys.stderr)
        return 2
    cred = credential_file(argv)
    if not cred.is_file():
        print(f"credential file not found: {cred.name}", file=sys.stderr)
        return 1
    token = parse_credential_text(cred.read_text(encoding="utf-8"))
    if token is None:
        print("credentials not found", file=sys.stderr)
        return 1
    sys.stdout.write(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
