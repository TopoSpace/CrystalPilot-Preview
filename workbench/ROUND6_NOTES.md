# Round 6 working notes

## Security boundary (server/app.py, f2121e6)

Reviewer item #1 confirmed real: wildcard CORS + no auth = any webpage can
drive the local API. Fix = loopback **Host check** (kills DNS rebinding:
Host: evil.com resolving to 127.0.0.1) + **Origin allowlist** (kills
cross-site calls incl. CORS-exempt simple POSTs) + CORS allowlist replacing
"*". Verified live with 4-way curl matrix (good/bad host x good/bad origin).

## Frames-dir reference import (30ce7e6)

Thousands of raw frames never fit the ≤50 MB upload path. New
`GET /api/wb/projects/frames_probe` (read-only dir stat: ext counts, MB,
sample) + composer "+" menu 引用原始帧目录 → inserts a structured line
handing the path to import_frames. Probed live: 3324 frames / 887.9 MB.

## FE deliverable links + polish (committed with above)

- ReactMarkdown empties unknown URL schemes ("H:" parses as a scheme)
  BEFORE components see them → rewrite must happen in `urlTransform`
  (ui/src/lib/mdLink.tsx); remark already percent-encodes → decode-first
  or %20 double-encodes to %2520.
- ContextMeter token fallback when contextWindow unknown; CrystalViewer
  initial-fit retries + ResizeObserver (letterboxed-small render fixed);
  thread polling 10s→30s + visibility-gated.

## ADDSYM correctness ladder (6a4203e) — 3 discoveries

1. **Match targets must be group-expanded**: a candidate op maps atoms onto
   symmetry MATES (the inversion partner of a P2₁ atom is the screw image
   of its glide mate). Round-5 "C22 unmatched 3.5 Å" was this matcher
   artifact, not a real mismatch.
2. Expanded targets make current-group ops match trivially → numeric coset
   filter `_in_cur_group` + pre-seeded rotations (textual op forms differ
   across bases; string comparison missed variants).
3. **apply_shift standardization is unsound**: declared ops stay at the
   origin while content moves = a different crystal. v1 centro-trial
   (nodes n0014/n0015) shifted a (¼,·,¼) pseudo-centre to the origin,
   closed to P2₁/m, and refinement collapsed exactly as a wrong group
   should (negative Ueq, BAD Ueq DEPENDENCE, debye_waller arg_limit) —
   informative failure, kept as documented dead end.
   Sound design: snap fitted translations to /12 in the ORIGINAL frame,
   let sgtbx close the group → symbol carries a parenthesised origin
   annotation. Residuals off the /12 grid live along the current group's
   **polar directions** (common fixed space of all rotations = the
   floating-origin freedom) where shifting IS sound:
   t → t + (I−R)s least-squared toward 0 (`_polar_shift_for`).

## change_space_group tool (6a4203e + 558401a)

Same-cell re-declaration, both directions (supergroup merge / subgroup
descent via expand_to_p1 with correct ADP transforms). Honesty gates:
strict verification of added ops (fit + /12 snap + polar retry) — refuses
unobeyed symmetry; closure must match the requested group TYPE; borderline
(0.9–0.975) adoption needs explicit min_match_fraction + justification.
Rebuild strips H (riding constraints reference scatterer order), merges
P1 copies, isotropizes merged ADPs (old ADPs in old parameterization +
special-position snapping → non-positive-definite crashes).

Two integration bugs found by the real-data run, both fixed in 558401a:
- SHELX LATT convention requires −1 AT the origin → centric closures are
  re-based by a pure origin translation applied to group AND content
  together (cell + hkl indices unchanged — unlike the unsound
  content-only shift this breaks nothing).
- The DATA side must follow: re-merge raw observations under the new
  group before swapping the model (`ses.set_symmetry`); stale P2₁ miller
  arrays crashed the first refine. New r_int reported as the data-side
  verdict. Also prune `h_constraints` (separate key from h_riding_meta!)
  and twin flags.

## Centro-trial v2 on r5-onitwin (evidence)

Driver: workdir/onitwin_centro_trial.py, branch centro-v2 from n0013.

- check_symmetry: pseudo-inversion **fraction 1.0**, mean_dev 0.08 Å →
  suggested `P 1 21/c 1 (a,b-5/12,a+c+1/4)` (the round-5 "borderline
  0.94" was measured by the pre-fix matcher).
- change_space_group adopt: P2₁ 64 atoms → **P2₁/n 20 atoms** (origin
  standardized by x−1/4,y−5/12,z−1/4; c-glide picks up the (a+c)/2
  component in this basis = n-glide, crystallographically consistent).
- **Data-side verdict: r_int 0.0753 in P2₁/n vs 0.0727 in P2₁** — nearly
  flat, completeness 0.927→0.955. The data DO share the inversion.
- Chain: iso 0.1354 → aniso 0.1083 → +8H 0.0939 → weights (a=0.2 b=3.0,
  GooF 0.972) → SHELXL check **R1 0.0926 / wR2 0.3503 / GooF 1.001**,
  smtbx↔SHELXL Δ −0.0004.
- Verdict vs P2₁ Z′=2 (R1 0.0812 / wR2 0.3063, 360 params): centro gets
  R1 +0.011 with HALF the parameters and flat r_int — Marsh-case pattern
  (P2₁'s extra parameters absorb twin error). Neither single-lattice
  model is publishable (wR2 ≥ 0.30 both); the real answer stays the
  round-5 two-lattice HKLF5 (RDL R1 0.0465). Trial's purpose was tool
  validation: the check_symmetry → change_space_group → re-refine →
  compare chain now runs end to end on real data.

AGENTS.md v8: change_space_group documented; honesty rule updated from
"trust the given space group" to the explicit branch → change →
compare → disclose chain.

## MCP startup: shell-fallback root cause killed (spec cache + deadlock)

Round-5 evidence: loaded machine → cctbx imports blew the 90s codex
startup timeout → whole run degraded to shell (84 shell calls in the
L-cysteine case). Fix in two layers:

1. **Spec cache**: tools/list served from ~/.crystalpilot/tool_specs-
   <fingerprint>.json (fingerprint = package .py mtimes hash). Handshake
   completes in ms with zero heavy imports regardless of machine load;
   registry composition is uniform across projects (stage gating happens
   at invoke time) so the cache is a pure function of the code.
2. **Windows loader-lock deadlock** (faulthandler-proven): importing
   numpy._core._multiarray_umath while anyio's stdio worker threads
   exist hangs FOREVER in the loader lock (OpenBLAS DllMain thread-pool
   init waits on threads that wait on the lock). Bare anyio loop without
   worker threads imports fine - the constraint is threads-at-import,
   not which thread imports. Fix: `import numpy` (~0.2s) BEFORE
   anyio.run; the rest of the cctbx chain then imports fine in-loop.
   First heavy import stays in the loop (= main) thread, never a worker.

Measured: initialize 0.75s; cold tools/list 3.1s; warm handshake <1s;
first call after warm handshake 0.02s. startup_timeout_sec 90→180.
Regression test: tests/test_mcp_startup.py (pre-fix the cold path hung
infinitely).

Ops lesson (recurring): Popen with stderr=PIPE and no drain thread
wedges the child once the pipe buffer fills - stderr to a FILE for
debug probes; and `faulthandler.dump_traceback_later(N, exit=True)` is
the definitive hang-diagnosis tool (dumps ALL thread stacks).

## Model/effort wiring + print_token gate + turn-error surfacing

FE model/effort pill is now interactive (per-project overrides, applied
per turn). Three live-discovered traps, each verified by real turns on
the r5-onitwin thread:

1. **codex Threads remember effort/model**: omitting the kwarg means
   "keep the thread's previous value", NOT "config default" - clearing
   an override kept sending the old effort (gateway 400). _turn_kwargs
   now always passes effective values explicitly.
2. **Gateway effort menu ≠ SDK enum**: gpt-5.6-sol accepts
   none/low/medium/high/xhigh/max, REJECTS minimal; the SDK enum lacks
   max. EFFORT_CHOICES = low/medium/high/xhigh (probed via real 400).
3. **print_token soft gate**: venv python.exe is a LAUNCHER STUB that
   re-execs the base interpreter, so the auth command's direct parent is
   always python.exe - a naive parent-name check refused codex itself
   (every turn 401'd). Correct rule: walk ancestors, skip python
   launcher layers, judge the first non-python ancestor (codex.exe →
   allow; bash/cmd → refuse, exit 2, nothing printed). Fails OPEN on
   psutil errors. Verified: shell replay refused, codex turn succeeds.

turn/completed(failed) events now carry the provider error verbatim
(was: bare "failed" chip, diagnosis required digging codex rollout
files). Verified with a bad-model turn.

**操作事故（已入长期记忆）**: taskkill 按进程名清"孤儿" codex.exe 时误杀了
用户本机自用的 Codex 会话。规程改为：杀前必须沿 ParentProcessId 追溯到
CrystalPilot 自己的进程，追不到就不动；绝不批杀同名进程。

## 数据收集：RODIN 教学原始帧集（4 套已入库）

RODIN（Resource of Diffraction Images, Newcastle；CCDC 托管，
J. Chem. Educ. 101 (2024) 4276, doi:10.1021/acs.jchemed.4c00797）：
CC-BY-4.0 原始衍射帧 + CSD Teaching Subset 参考结构。下载至
**H:\CrystalPilotData\rodin**（仓库外，盲测卫生），含 MANIFEST.md 出处/
许可清单：W(CO)6(Mo, Rigaku .rodhypix 27MB)、TCNQ(110MB)、
NaOAc·3H2O(106MB)、dppf-PdCl2·DCM 溶剂化物(345MB)。Zenodo 上还有 6+ 套
（Bruker/STOE/Cu 波长/双多晶型）备用。

## W(CO)6 确定性三阶段验证（r6-wco6，已归档 CrystalPilotData/validation）

**机制层全通**（.rodhypix = dxtbx FormatROD_Arc 原生支持，无需自研格式）：
import 376 帧/5 扫（3 个 10 帧 pre_ 筛查扫被新逻辑排除并披露）→
find_spots 3195 → index 98.2%（6.36/11.24/11.74 Å 正交）→ integrate 5064
→ scale R_merge 0.058 / I/σ 21.6 / d_min 0.71 Å / 完备度 88.3% →
charge-flip 粗解 R1 0.241。

**科学层暴露真缺口（诚实记录）**：DIALS 建议 P2₁2₁2₁，文献 W(CO)6 为
**Pnma**；错误空间群下粗解把 ASU 塞进 4 个 W（对称拷贝当独立原子 =
ASU 过载，组成先验 1W/分子 完全对不上）；iso/aniso 精修 R1 卡 0.10-0.17，
optimize_weights 走到 b=162（异常大 b = 在掩盖模型错误的信号）；
run_shelxl 独立复核 R1 0.805 vs smtbx 0.099——**引擎剧烈分歧正是
错模型的哨兵**（挂起的对称拷贝在两套 scale/权重下表现完全不同）。
判据链完整：SG 存疑 → ASU/组成矛盾 → 权重异常 → 引擎分歧。

## W(CO)6 agent 发现式运行（85 分钟，26.5M tokens，交付成功）

干净项目 r6-wco6，仅给 chemistry 先验 + 帧目录。最终交付：**Pcmn
（No.62，Pnma 非标准设置，与文献一致）完整八面体 W(CO)₆**，全非氢各向
异性 0 NPD，SHELXL R1=0.0363 / R1(all)=0.0662 / wR2=0.2170 /
GooF=0.972，checkCIF 5A/14B/38C 逐条 VALIDATION.md，Tmin/Tmax/晶体
外观缺失如实拒绝编造。50 节点 8 分支完整审计链。

关键自主行为（全部无人指导）：
- **独立完成全空间群筛查**，与我并行开发的 sg_screen 模块结论一致到
  小数点（460 消光/14 违例/均值 0.43σ vs 我的 472/16/0.45；E 1.171 vs
  1.161→中心对称→Pcmn）——两条独立路径同一结论，互为验证。
- 识破"缩放在 Sohncke 群下做→Pcmn 等价类未共同去离群"的数据侧问题，
  按 Pcmn 重缩放：坏等价组 3.3%→1.6%，消光违例 14→5。
- 从残差图逐支重建 W+4CO（伪峰剥离、临时 DFIX 后撤除验证自由收敛）、
  发现 7 条 σ=0 占位记录致无权重 GooF=529 并用 select_good_intensities
  客观剔除、EXTI 试后拒用、W 旁 10 e/Å³ 残差正确归因吸收拒绝加原子。

**故障级联（重要教训）**：工具版 find_spots 无进度反馈且慢（真因见下）
→ agent 等三轮后用 PowerShell 查进程 → Force-Kill 匹配 'python' 的进程
**连 MCP 服务器一起杀掉** → codex 会话内不重生 MCP 服务器 → 余下全程
只能 PowerShell/py 垫片（它自建 RefineProject.invoke_tool 直调层保住了
节点审计）。用户观察到的"满屏 PowerShell"即此级联，不是工具偏好问题。

**慢的真因（A/B 实测）**：CONDA_PREFIX 假设被基准否定（87.3 vs 86.5s，
1.01x）；真凶是 **Windows 下 dials.find_spots 多进程病理**：nproc=1
11.6s / nproc=2 44.1s / nproc=4 86.5s（每 worker 重开 imageset 主导），
叠加当时我在并行跑测试套件的机器争用。agent 的 18.8s 手跑恰是 nproc=1。
已改默认（Windows find_spots nproc=1，参数可调）。

本轮平台修复（全部由该运行的故障驱动）：长阶段心跳、busy-lock 显式
报错、nproc 默认、spec-cache 启动、AGENTS v10（慢≠卡死/禁杀进程）、
sg_screen 工具化、screening 扫排除、CONDA_PREFIX 补全（无害保留）。

**下一轮工具缺口**（agent 用 .py 自补的能力）：数据清洗工具
（σ=0/select_good_intensities）、scale_and_export 按指定群重缩放
（space_group= 参数）、CIF 装配的晶胞测定统计自动化。
codex 侧限制记录：MCP 服务器死亡后会话内不重连。
