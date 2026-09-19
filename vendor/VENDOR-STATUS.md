# 厂商/生态软件集成状态（2026-08-31）

授权边界（用户 2026-08-31）：只装 H 盘；免费+需注册的可装（注册步骤留给
用户）；明确付费的排除。vendor/ 目录 gitignore，二进制永不入库。

## 已安装（免登录免付费，开箱即用）

### Olex2 1.5（vendor/olex2/app/）
- 来源：https://secure.olexsys.org/olex2-distro/1.5/olex2-win64.zip
  （官方 CDS 分发，MD5 227ebf736b6b11b37be402180671d4db 校验通过；
  注意 olex2.org 域证书错配是别家的——绝不从那里下载）
- 许可：BSD 开源，任何人免费（含商用）
- 状态：绿色解压版，olex2.exe 可直接运行（GUI）。用途①：人工验收
  工具链——用课题组事实标准软件打开平台交付的 res/cif；用途②：
  第三方 mask/精修对照（GUI 操作）
- **headless 已解决（2026-09-01 实弹）**：`app/olex2c.dll` 就是
  console 版——CONSOLE 子系统 EXE 映像顶着 .dll 扩展名（更新器把非
  .exe 名当数据载荷；零图形库导入，天然不可见）。驱动要点：REPL 读
  控制台输入不读管道 → 必须 ConPTY（pywinpty）；嵌入 Python 3.8 要
  PYTHONHOME=app/Python + 剥离用户 PYTHON* 环境；refine 前须
  `user '<绝对目录>'` + 绝对路径 reap（相对路径令内部 cd 静默失败）。
  平台驱动器 crystalpilot/io/olex2c.py（Olex2Console/refine_job）。
  实测：52s 内 boot→reap→refine 4→file cif，olex2.refine（smtbx）
  R1_gt 0.0650 vs SHELXL 基线 0.0647（跨引擎 0.0003 内复现）。
  备选通道：内置 socket server（`server start -p=8899`）未启用

### Gavrog Systre 19.6.0（vendor/gavrog/Systre-19.6.0.jar）——已安装（2026-09-04）
- 来源：<https://github.com/odf/gavrog/releases/download/Systre-19.6.0/Systre-19.6.0.jar>
  （release tag `Systre-19.6.0`，"Systre update: Version 19.6.0 with RCSR
  data archive as of June 1, 2019"）
- 大小 1 650 068 B；**sha256 =
  0d272e98a1a21669bc67a809b95c014ba2a2fb39a6fd2147039201216ab0d48d**
- 许可：Apache-2.0（odf/gavrog）——可自由使用；按 vendor/ 规则**不入库**
  （`.gitignore` 里 `vendor/` 整目录已忽略，`git check-ignore` 已核）
- 运行环境：`java -version` = OpenJDK 17.0.17 LTS（Microsoft build），
  已在 PATH 上；调用方式
  `java -cp vendor/gavrog/*.jar org.gavrog.apps.systre.SystreCmdline net.cgd`
- 平台入口：`crystalpilot/chem/topology.py::systre_jar / run_systre`
  （`SYSTRE_JAR_GLOB = "vendor/gavrog/*.jar"`，缺 jar/缺 java 时如实报"未算"）
- 实弹复核（2026-09-04，benchmark/known_answers）：MOF-5 → **pcu**、
  HKUST-1 → **tbo**、ZIF-8 → **sod**、UiO-66 → **fcu**、NU-1000 → **csq**、
  双重互穿 MOF-5 → 两个分量都是 **pcu**。见
  `docs/VALIDATION-2026-09-topology-pores.md`

### superflip（vendor/superflip/superflip.exe）
- 来源：https://superflip.fzu.cz/download/superflip_win.zip
- 许可：非商用免费；发表须引用 Palatinus & Chapuis, J. Appl.
  Cryst. 40 (2007) 786-790；**不得再分发**（gitignore 已保证）
- 冒烟：r14a 真实数据（18200 反射，P2₁2₁2₁）397 轮收敛，
  R 42→17，空间群一致性因子 0.09——独立求解引擎完全可用
- 输入格式要点（试错实录）：终止符是 `endf` 不是 fend；
  `outputfile` 与显式 `symmetry ... endsymmetry` 块是必填；
  `dataformat intensity` 行格式 `h k l I sig`
- 集成价值：①求解失败阶梯的"换引擎"一级（独立于 cctbx 的电荷翻转
  实现）②对称一致性因子=密度空间的空间群独立判据（比消光统计直接）

## 需用户注册后可装（免费）——登录指引

### CrysAlisPro 171.44.85 ——已安装（2026-08-31）
- 用户注册论坛下载 CrysAlisPro171.44.85.exe（NSIS 安装器），经
  `/S /D=H:\CrystalPilot\vendor\crysalispro\app` 静默安装
  （344MB 全部在 H 盘）
- **注意**：安装器按 Oxford Diffraction 历史惯例在 C 盘自建了
  `C:\Xcalibur\`（仅 4KB：指回 H 的符号链接 + 空 INI 骨架——程序
  本体与数据都不在 C）。这是其硬编码行为；暂保持原样，如需严格
  清理可把 C:\Xcalibur 整体做成指向 H 的 junction
- 驱动级钩子侦察：主程序 `app\pro.exe`（CrysAlisPro 本体，带
  script/宏命令行自动化通道）；另有 ewald3d.exe、odhkl.exe 等组件。
  下一步：pro.exe 脚本模式冒烟（帧→还原产物），产物回接
  ingest_vendor_data

### Jana2020（捷克科学院物理所）——已安装（2026-08-31）
- 用户注册下载 Jana2020Inst.msi 后，经 `msiexec /a`（管理性解包）
  绿色落位 vendor/jana2020/app/（197MB；不写注册表不碰 C 盘）
- 布局：Jana2020.exe（GUI 主程序）+ SUPERFLIP/（自带 superflip.exe
  与 **EDMA.exe**——Palatinus 的电子密度图解析器，密度判读潜在可用）
  + FORMFAC/BONDVAL/CIF 等数据组件
- 首次启动可能有激活/初始化对话框（JanaActivatePatch.exe 在列）——
  留给用户 GUI 首启；命令行驱动能力待探（Jana 有 batch 模式文档线索）
- 用途定位：调制结构/复杂孪晶精修的第三方对照；EDMA 密度解析对照

### SHELX 家族补齐（Sheldrick，学术免注册即有但需邮件获取密码）
现有 vendor/shelx/ 已含 shelxl/shelxt（核心够用）。如需补
shelxd/shelxe/anode 等：https://shelx.uni-goettingen.de/ 按页面
说明邮件登记获取下载密码。优先级低。

## 排除（明确付费/不适用）

- Bruker APEX5（付费许可）；SADABS/TWINABS/XPREP 独立版随 APEX
- Stoe X-Area（付费）
- HKL-2000/3000（授权文件制）
- CCDC CSD/ConQuest（订阅）；Mercury 免费版需 CCDC 账号且功能受限
  （可视化我们已有查看器，暂不需要）
- XDS：免费但无 Windows 原生版（WSL 复杂度暂缓）
- PLATON：已有本地版在用（run_checkcif）
- DIALS：已有（帧路线主引擎）

## 集成状态更新（2026-09-01）

- **CrysAlisPro 171.44.85 已驱动级集成**：LISTEN MODE 文件通道
  （C:\Xcalibur\tmp\listen_mode_offline，客户端
  crystalpilot/io/crysalis_listen.py，命令驱动器
  workdir/cap_probe/cap_drive.py 带隐藏看门狗）。已实战：ph snogui
  峰搜 / selectexpnogui 切实验 / dc imgtoxds 格式转换。CAP 以常驻
  隐藏守护进程运行；机器重启后需一次引导（实验浏览对话框是模态的，
  必须真开一个实验后才能敲 xx listenmode on；对话框 X=退出应用）。
- **dials env 新增诊断依赖 fabio**（pip，ESRF 图像 IO 库）：用于独立
  交叉验证帧格式解析；dxtbx 插件本体不依赖它。
- **dxtbx 插件 0.2.0**：三格式（Bruker sfrm / Rigaku HyPix miniCBF /
  OD SAPPHIRE 3.0 legacy IMG）。
