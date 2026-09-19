"""Smoke test: run_checkcif tool on the finished MVP project (active node)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.refine.project import RefineProject  # noqa: E402


def main() -> int:
    proj = RefineProject(REPO / "workbench" / "mvp-sjtu9")
    proj.open()
    res = proj.invoke_tool("run_checkcif", {})
    print(json.dumps({"ok": res.ok, "summary": res.summary,
                      "error": res.error}, indent=2, ensure_ascii=False,
                     default=str))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
