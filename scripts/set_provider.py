r"""Switch an OPEN workbench project to another model provider / model / effort.

Usage (venv python, from H:\CrystalPilot):
  python workdir/scratch/set_provider.py <project_dir> [provider] [model] [effort]

  provider: openrouter | crystalpilot | default   (default = clear the override,
            back to codex-home/config.toml: gateway gpt-6-astra @ xhigh)
  model / effort default to z-ai/glm-5.3 @ high for openrouter.

The project must be open in the browser (the server holds its session), and
the provider is fixed when a thread STARTS - so open a NEW thread after this.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010/api"


def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    project = argv[1]
    provider = argv[2] if len(argv) > 2 else "openrouter"
    if provider in ("default", "", "none"):
        settings = {"model_provider_override": None, "model_override": None, "effort_override": None}
    else:
        model = argv[3] if len(argv) > 3 else ("z-ai/glm-5.3" if provider == "openrouter" else None)
        effort = argv[4] if len(argv) > 4 else ("high" if provider == "openrouter" else None)
        settings = {"model_provider_override": provider, "model_override": model,
                    "effort_override": effort}
    try:
        s = post("/projects/settings", {"path": project, "settings": settings})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 404 or "project not open" in body:
            print("项目没有在服务器里打开：先在浏览器 8010 里「打开项目」，再运行本脚本。", body)
        else:
            print("HTTP", e.code, body)
        return 1
    print(json.dumps({"provider": s.get("model_provider"), "model": s.get("model"),
                      "effort": s.get("effort"), "effort_choices": s.get("effort_choices"),
                      "vision": s.get("vision"), "subagents": s.get("subagents"),
                      "permission_mode": s.get("permission_mode")}, ensure_ascii=False))
    print("已写入项目设置；对之后新建的对话生效（正在进行的对话不变）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
