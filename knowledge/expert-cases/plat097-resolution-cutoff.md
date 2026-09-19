---
symptom: 高分辨率数据出现 B 级 PLAT097 残余峰警报，需判定残余峰来源并以壳层证据决定分辨率截断
alerts: [PLAT097]
tools: [estimate_resolution, scale_and_export, run_shelxl]  # SHEL/OMIT/XPREP 为外部指令/程序，当前平台不可执行，见正文标注
tags: [分辨率截断, 残余峰, CheckCIF]
source: https://www.matstr.com/forum.php?mod=viewthread&tid=2035
refs:
  - CheckCIF-PLAT097: https://mp.weixin.qq.com/s/p0FKsQtbjUF3BYXHqnQCxw
  - SHELXL指令之SHEL: https://mp.weixin.qq.com/s/GGoO3DyiFvPfiXBYbqBQvQ
  - SHELXL指令之OMIT: https://mp.weixin.qq.com/s/QvRwCRJG0TH2CXbN1o80xA
  - 晶体数据审稿意见-分辨率应在何时截断: https://mp.weixin.qq.com/s/xD3PHA72lgp1SEOzs2rwzA
---

## 症状

分辨率 0.48 Å 的数据，精修后 Max Peak = 1.0 e/Å³，CheckCIF 报 B 级
PLAT097（残余电子密度峰过高）。

## 诊断

极高分辨率壳层往往信噪比差；高角弱数据引入的噪声在差值图上表现为
残余峰。峰不对应真实原子（无化学意义、不在成键位置）时，属于数据
质量问题而非模型缺失。

## 处理（原文操作序列：外部软件案例记录，非平台流程）

> 外部能力标注：SHEL/OMIT 是 SHELXL 指令、XPREP 是独立程序，当前
> 平台 run_shelxl 不暴露对应参数，MCP 工具无法执行本节操作。此节仅
> 作案例证据保留；分辨率决定流程见"提炼规则"。

1. SHELXL `SHEL 999 0.65` 截断至 0.65 Å（或 `OMIT` 高角反射，
   或 XPREP 截断后生成新 hkl）。
2. 复查 Max Peak 与警报级别；原帖不足则继续小步截断（该"以警报
   降级为目标"的闭环本卡不采纳，理由见提炼规则）。

## 前后指标（原文数值）

| 分辨率截断 | Max Peak (e/Å³) | PLAT097 |
|---|---|---|
| 0.48 Å（原始） | 1.0 | B 级 |
| 0.65 Å | 0.90 | B 级（仍在） |
| 0.70 Å | 0.80 | C 级（降级） |

## 提炼规则

- 残余峰无化学解释（不在成键位置、无配位/构象意义）时，备择解释至少
  四类：高角噪声壳层、吸收校正残差、孪晶重影、傅里叶截断波纹。先用
  独立证据区分（壳层统计、吸收校正质量与 Tmin/Tmax、孪晶排查），不
  默认归因高角噪声，更不许加原子"吸收"残峰（与师兄铁律一致：宁可
  R 高，不可化学错）。
- 分辨率截断是**数据质量决定，不是消警报手段**。依据是壳层证据：
  CC1/2、I/σ、Rmeas/Rint、完整度随分辨率的变化；`estimate_resolution`
  的建议值为 advisory only。多项证据同向指认外壳已成噪声时，截到噪声
  起点并用 `scale_and_export(resolution=...)` 重导出，对照截前后合并
  统计与精修指标；证据不支持时保留数据，残余峰按其他机制解释或如实
  披露。
- 禁止以"PLAT 警报降级/R 值下降"为目标反复试截。截与不截都要记录：
  截断位置、壳层证据、截前后对照与理由，PLAT097 的变化只是随附
  观察，不是裁决标准，也不是第二信号源。
- 本案原文 SHEL/OMIT/XPREP 序列属外部软件操作（见"处理"节标注）；
  仅有成品 hkl、无帧可重导出时，精修端截断需人工执行并在 VALIDATION
  记录证据与理由。
