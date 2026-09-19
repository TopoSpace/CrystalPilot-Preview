<!-- crystalpilot-repo-root-pointer: 本文件不是智能体指令 -->
CrystalPilot 仓库根目录不放智能体指令。工作台项目目录里的 AGENTS.md 由 `crystalpilot/workbench/agents_md.py` 按项目设置 knowledge_mode 生成（版本标记在文件首行）。战役与用户项目目录一律放在仓库外（例如 `H:\CrystalPilot-campaigns\<战役名>\`）：Codex 会把 git 根到项目目录之间的每一个 AGENTS.md 都注入上下文，仓库内的项目会同时吃到本文件与模板。开发约定见 `ARCHITECTURE.md`。
