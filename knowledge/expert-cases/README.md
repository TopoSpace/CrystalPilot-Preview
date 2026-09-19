# 案例卡（case cards）

从 Tokyo 文章提炼的结构化专家经验，每卡一个可复用决策单元。
命名：`<系列缩写>-<编号或关键词>.md`。frontmatter 供 CrystalPilot 检索，
正文供 agent 阅读引用。**规则**：卡内指标必须来自原文（不臆造数字）；
每卡必须带出处链接；与 AGENTS.md 铁律冲突时以铁律为准并在卡内标注。

```markdown
---
symptom: 一句话症状（agent 检索的主键）
alerts: [PLAT097]        # 涉及的 CheckCIF 警报（可空）
tools: [SHEL, OMIT, XPREP]  # 涉及的指令/软件
tags: [分辨率截断, 残余峰]
source: https://www.matstr.com/... （+公众号链接）
---

## 症状
## 诊断
## 处理（操作序列，含参数）
## 前后指标（原文数值）
## 提炼规则（可进 AGENTS/工具逻辑的一般化结论）
```
