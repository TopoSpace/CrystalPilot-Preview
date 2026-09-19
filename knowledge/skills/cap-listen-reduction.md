---
name: cap-listen-reduction
description: CrysAlisPro LISTEN MODE 全自主数据还原链（实弹验证 2026-09-01）：ph snogui 峰搜→um twinttt 双域 Duisenberg 索引（污染峰表上 um f 全灭时的正解）→dc proffit auto 免框还原；向导类命令（proffittwin/rrptwin/xmlrrp）用 drive_wizard.ps1 BM_CLICK 链自动化；挂起判别=CPU 烧速法。禁令：xx savetext（弹图形保存框）、dc autoanalyse（采集钩子离线 no-op）。zn_dpnpp 实测我方还原 R1 0.0747 超作者/文献一切版本。
alerts: []
tools: []
tags: [CrysAlisPro, CAP, LISTEN, 数据还原, 孪晶, 索引, Duisenberg, 向导自动化]
source: workdir/cap_tune1/EXPERIMENTS.md（2026-09-01 专项，pg33/zn_dpnpp 帧实弹）；命令语法权威源=CAS2Help.chm 解包（hh -decompile，workdir/cap_tune1/chm/）+pro.exe 字符串表
confidence: high
created_by: mentor
---

# CAP LISTEN MODE 全自主还原链

## 命令链（全部实弹验证）

1. `xx selectexpnogui <abs>\exp.par`，开实验（~2s）。
2. `ph snogui`，峰搜（1102 帧 ~20s；表上限 99999 会撞满，属正常）。
   `ph snogui_pars <14 参数>` 的 lthreshold 提高**并不能**减峰（实测
   8000 依旧 99999，阈值语义存疑，别指望它做强峰筛选）。
3. **索引：`um twinttt`**（Duisenberg 直接空间法，依次找组件并剔兼容
   峰，UB 入 twin array）。40676 混合峰（双域+噪声）上 `um f`
   （Clegg 倒空间法）只给 0.8-8.8% 的垃圾三斜胞，twinttt 一发命中
   两个同型正交域（46%+8904 峰）。**污染峰表用 direct-space，别用
   um f**。`um i [tol]` 随后精修当前 UB。`um f2` 在 171.44 已被裁。
4. **还原：`dc proffit auto`**：免框直跑（1102 帧 ~4min），用当前
   UB+par 状态参数，产出 `<name>_autored.hkl` 等全套。
5. 向导类命令（`dc proffittwin` / `dc proffitrrptwin` / `dc xmlrrp`）
   **必弹向导**（auto 后缀不被接受）：用 drive_wizard.ps1
   （workdir/cap_tune1/，EnumChildWindows 找 Next/Finish 按 BM_CLICK
   0x00F5，每步抓控件文本留档）全默认走通 6 步。twin 选项等状态
   记在 par 里，向导默认值即沿用。

## 挂起判别法（CPU 烧速）

命令发出后 log 静默 ≠ 挂起。判别：`Get-CimInstance Win32_Process`
两次采样 KernelModeTime+UserModeTime，积分=满核烧（45s +50 CPU 秒），
挂对话框=近零（20s +0.2s）。挂起时用 listallwin.ps1 枚举**全部**
窗口（主窗隐藏时向导可能不可见也可能可见），WM_CLOSE 取消后通道
记 done。

## 禁令与陷阱

- **`xx savetext` 禁用**：是存图形命令，弹 bmp 保存框到用户桌面并
  模态挂死通道（2026-09-01 实弹翻车）。
- **`dc autoanalyse` 离线无用**：采集后钩子，"run list 未终结即等新
  数据"，334s no-op 零产物。
- `um help` 等 help 命令弹 CAS2Help 窗；语法权威源=CAS2Help.chm
  解包＋pro.exe 字符串表，别在 CAP 里查。
- 未在本轮 redLOG 验证过行为的命令不得裸发。

## zn_dpnpp 实测结论（重叠 97.8% 的近共格双域）

同一模型移植评估（SHEL 0.81+TWIN 反演）：**我方单 UB 常规还原
R1 0.0747 / Rint 0.088**（twinttt UB+171.44 proffit）＞HKLF5 解卷积
0.0977 ＞文献发表 0.0904 ＞作者常规 0.0811 ＞twin HKLF4 阈值版
0.11-0.14 ＞DIALS 0.1625。机制：高冗余（16.8）+Blessing 离群剔除把
重叠污染当离群清洗，胜过显式解卷积的分解噪声；DIALS 输在分域积分
拆薄冗余+剔除弱。**先跑单 UB 常规版拿基线，再考虑 twin 解卷积**。
