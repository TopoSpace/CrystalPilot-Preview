# Linux 安装与运行

适用于 Linux x86_64、Python 3.11 和 Node.js 22。以下命令在源码仓库根目录运行，依赖安装在项目目录内；需要预先安装 `uv` 和 Node.js。

## 安装依赖

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-linux.lock
uv pip install --python .venv/bin/python --no-deps -e '.[server,workbench,refine,dev]'
bash scripts/update_codex_kernel.sh
.venv/bin/python scripts/setup_linux.py
cd ui
npm ci --no-audit --no-fund
npm run build
cd ..
```

`requirements-linux.lock` 固定 Python 依赖版本。Codex 内核安装到 `vendor/codex/`，Python SDK 版本在项目依赖中固定。`setup_linux.py` 将仓库配置中的 Windows 路径迁移到当前源码目录，清理历史 Windows 信任目录，并重新生成模型目录。迁移前的配置备份保存在被 Git 忽略的 `workdir/` 中。

CrystalPilot 使用自己的 `codex-home/`；不会读取或修改服务器个人 Codex 配置。模型提供方、接口地址、默认模型及密钥需要在工作台设置中填写。凭据只保存在本机的 `secrets/` 或明确配置的环境变量中，不随源码发布。本机对 `codex-home/config.toml` 的部署修改也应排除在代码提交之外。

## 晶体学程序

DIALS 使用独立 Conda 环境，不与主 Python 环境混装。安装 Conda 后运行：

```bash
conda create --prefix "$PWD/vendor/dials" --override-channels -c conda-forge \
  --solver libmamba -y python=3.11 dials pip
.venv/bin/python -c 'from crystalpilot.io.frames_dials import find_dials, ensure_format_plugins; print(ensure_format_plugins(find_dials()))'
```

程序自动发现 `vendor/dials`；其他位置可通过 `CRYSTALPILOT_DIALS_ENV` 指定。`ensure_format_plugins` 安装项目附带的衍射图像格式插件。

SHELXL/SHELXT 需自行取得官方授权的 Linux 安装文件，然后执行：

```bash
.venv/bin/python scripts/setup_vendor_shelx.py --source /path/to/licensed-shelx
```

脚本接受原生 `shelxl`、`shelxt` 文件名，并保留现有程序约定的 `*.exe` 目标名称；Linux 下目标内容仍为 ELF 程序。Windows PE 文件会被拒绝。也可设置 `CRYSTALPILOT_SHELXL`、`CRYSTALPILOT_SHELXT` 为已授权程序的绝对路径。

本地 checkCIF 需要可用的 Linux PLATON，可按项目原有发现规则安装到 `vendor/shelx/` 或提供对应程序路径。拓扑分析所需的 Systre 和 Java 安装要求见仓库现有说明。授权程序、安装包、下载凭据和安装日志不提交到 Git。

## 启动与访问

```bash
.venv/bin/python scripts/server_linux.py start
.venv/bin/python scripts/server_linux.py status
.venv/bin/python scripts/server_linux.py restart
.venv/bin/python scripts/server_linux.py stop
```

服务在后台运行，默认绑定 `127.0.0.1:8010`，限制为 4 个 CPU 核；可通过 `--port`、`--cores` 调整。脚本检查 PID、创建时间和源码路径，只管理当前副本启动的服务。日志位于 `workdir/server.stdout.log` 和 `workdir/server.stderr.log`。不安装系统服务或开机自启。

`start`/`restart` 前会检查 codex 内核自己的日志数据库 `codex-home/logs_2.sqlite`：超过 256 MB 且没有本仓库的 codex 进程在运行时删除它（内核会重建）。它三周能长到 1.6 GB，过大时内核启动会卡在 sqlite 上（2026-09-16 实测）。

远程访问可在本地电脑建立 SSH 隧道，替换自己的用户和服务器地址：

```bash
ssh -N -L 8010:127.0.0.1:8010 <user>@<server>
```

随后打开 <http://127.0.0.1:8010>。晶体项目放在源码仓库外，例如 `../projects/`，避免项目指令、实验数据和运行产物混入源码。

## 验证与发布边界

```bash
.venv/bin/python -m pytest tests/test_linux_runtime.py -q
cd ui
npm test
```

浏览器测试在 Linux 默认使用已安装的 Chrome；可通过 `CP_BROWSER_CHANNEL` 选择其他浏览器，使用 `CP_BASE_URL` 指定测试服务，并用 `CP_E2E_PROJECT` 和 `CP_SOL_THREAD` 指向独立测试副本。

pytest 临时目录在仓库外的 `../.crystalpilot-pytest`。真实模型测试使用 `gpt-5.6-luna`；需要本机已配置的模型服务，普通单元测试不应发起模型调用。

提交源码时排除本机凭据和配置、虚拟环境、第三方二进制、实验项目、衍射数据、截图、日志和构建产物。科学程序能运行不等于结构已经达到发表标准，仍需核对数据、精修指标和验证结果。
