"""Semantic diff of the app-server protocol between two codex builds.

    <old codex.exe> app-server generate-json-schema --out OLD_DIR
    <new codex.exe> app-server generate-json-schema --out NEW_DIR
    python scripts/diff_codex_schema.py OLD_DIR NEW_DIR

Reports added / removed / changed protocol definitions (with the properties
that differ) and the client-request, server-notification and server-request
method inventories. "removed: []" on all three is what makes a kernel bump
safe for CrystalPilot's normalize_notification / approval handling; anything
removed must be checked against crystalpilot/workbench/core.py first.
"""
import json
import sys
from pathlib import Path

old_dir, new_dir = Path(sys.argv[1]), Path(sys.argv[2])
COMBINED = "codex_app_server_protocol.v2.schemas.json"


def load(d: Path) -> dict:
    return json.loads((d / COMBINED).read_text(encoding="utf-8"))


def defs(s: dict) -> dict:
    return s.get("definitions") or s.get("$defs") or {k: v for k, v in s.items() if isinstance(v, dict)}


def props(d: dict) -> dict:
    out = dict(d.get("properties") or {})
    for alt in d.get("oneOf") or d.get("anyOf") or []:
        if isinstance(alt, dict):
            for k, v in (alt.get("properties") or {}).items():
                out.setdefault(k, v)
    return out


def methods(s: dict) -> set[str]:
    out: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            m = x.get("properties", {}).get("method")
            if isinstance(m, dict):
                if "const" in m:
                    out.add(m["const"])
                out.update(m.get("enum") or [])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(s)
    return out


od, nd = defs(load(old_dir)), defs(load(new_dir))
print("definitions:", len(od), "->", len(nd))
print("added:", sorted(set(nd) - set(od)))
print("removed:", sorted(set(od) - set(nd)))
changed = sorted(k for k in set(od) & set(nd) if od[k] != nd[k])
print("changed:", len(changed))
for k in changed:
    op, np_ = props(od[k]), props(nd[k])
    req_o, req_n = set(od[k].get("required") or []), set(nd[k].get("required") or [])
    detail = []
    if set(np_) - set(op):
        detail.append(f"+props {sorted(set(np_) - set(op))}")
    if set(op) - set(np_):
        detail.append(f"-props {sorted(set(op) - set(np_))}")
    pc = sorted(p for p in set(op) & set(np_) if op[p] != np_[p])
    if pc:
        detail.append(f"~props {pc}")
    if req_n - req_o:
        detail.append(f"+required {sorted(req_n - req_o)}")
    if req_o - req_n:
        detail.append(f"-required {sorted(req_o - req_n)}")
    oe, ne = od[k].get("enum"), nd[k].get("enum")
    if oe != ne and (oe or ne):
        detail.append(f"enum +{sorted(set(ne or []) - set(oe or []))} -{sorted(set(oe or []) - set(ne or []))}")
    print(f"  {k}: {'; '.join(detail) or 'nested change only'}")

for fname in ("ClientRequest.json", "ServerNotification.json", "ServerRequest.json"):
    try:
        ma = methods(json.loads((old_dir / fname).read_text(encoding="utf-8")))
        mb = methods(json.loads((new_dir / fname).read_text(encoding="utf-8")))
    except FileNotFoundError:
        continue
    print(f"{fname}: {len(ma)} -> {len(mb)} methods; added {sorted(mb - ma)}; removed {sorted(ma - mb)}")
