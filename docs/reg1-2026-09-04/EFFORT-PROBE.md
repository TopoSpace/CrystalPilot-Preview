# 推理档位探针（R0，2026-09-05 20:25–20:35）

> 目的：回答"当前 Codex 内核 + 网关下，gpt-6-astra 是否支持 `xhigh` 以上的档位"，以决定第三轮子代理分档（计划 §3 R0/R7）。两个探针都只用仓库内隔离的 `CODEX_HOME=H:\CrystalPilot\codex-home`，不碰用户自用 Codex。

## 1. app-server 目录（`model/list`，`workdir/r3-probe/effort_probe.py` → `effort_probe.json`）

codex-cli 0.147.0 的内置模型目录（`includeHidden=true`）：

| 模型 | 支持档位 | 默认 |
|---|---|---|
| gpt-5.6-sol（目录默认） | low / medium / high / xhigh / **max / ultra** | low |
| gpt-5.6-terra | low / medium / high / xhigh / **max / ultra** | medium |
| gpt-5.6-luna | low / medium / high / xhigh / **max** | medium |
| gpt-5.5 / gpt-5.4 / gpt-5.4-mini / gpt-5.2 / codex-auto-review | low / medium / high / xhigh | medium |

**gpt-6-astra 不在目录里**（passthrough 模型 id：SDK 不做档位校验，请求原样发往网关），所以目录不能回答 Astra 的问题。

## 2. 真实小回合（`workdir/r3-probe/max_probe.py` → `max_probe.json`）

对 gpt-6-astra 各发一个 ephemeral 线程、一条"只回复两个字：就绪"的回合，不带工具：

| effort | 结果 | 回复 | 推理 token | 用时 |
|---|---|---|---|---|
| `max` | 接受 | 就绪 | 38 | 54.9 s（含 app-server 冷启动） |
| `ultra` | 接受 | 就绪 | 34 | 4.7 s |
| `xhigh` | 接受 | 就绪 | 0 | 5.2 s |

网关没有对 `max`/`ultra` 返回 400（2026-06 的 codex issue #30585 里"backend rejects max"已不再成立）。这只证明档位被接受并产生推理 token，**不证明**更高档位对晶体学任务更好，那是 R7 A/B 的事。

## 3. 落地（R0）

- `crystalpilot/workbench/service.py`：`EFFORT_CHOICES = ("low","medium","high","xhigh","max","ultra")`；委派层级改为"xhigh 及以上"（`TOP_TIER_EFFORTS`），保持现有 `top_tier` 策略在 xhigh 的行为不变，max/ultra 同样激活；`aggressive` 策略留到 R7。
- `ui/src/lib/zh.ts::formatEffort`：`max → 最高`、`ultra → 超高`；设置面板的档位下拉自动读 `effort_choices`。
- `codex-home/config.toml` 的默认 `model_reasoning_effort` 仍是 `xhigh`；更高档位由项目设置 `effort_override` 或战役清单 `effort_override` 选用。

## 4. 未验证

- `max`/`ultra` 在长任务上的耗时与成本（本探针只有几十 token）。
- 子代理线程的 `default_subagent_reasoning_effort = "medium"`（`[agents]`）是否应随主档位提升，R7 A/B 决定。
