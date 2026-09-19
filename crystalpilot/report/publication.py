"""Publication CIF assembly.

The backbone is SHELXL's own ACTA output (job.cif from a run_shelxl job):
~130 data items with esds, weighting details, geometry loops and the embedded
_refln loop. SHELXL leaves `?` in every slot it cannot know (instrument,
crystal description, absorption correction, computing history, special
details). This module fills those slots from what CrystalPilot *does* know -
the project's context.json `experiment` block, the solvent-mask record, and
its own provenance - strictly text-level so every esd SHELXL computed
survives untouched.

Honesty notes (surfaced to the caller for VALIDATION.md):
- SHELXL assumes 20 C (293 K) whenever no TEMP card was given - a harmless
  approximation for computing riding-H bond lengths/ADPs - and then prints
  that same 293(2) into _diffrn_ambient_temperature/_cell_measurement_
  temperature as if it were a measurement. It is not: when the experiment
  block carries no temperature_K we OVERRIDE both slots to '?' (never copy
  SHELXL's assumption forward as a fact) and report the override as a
  caveat. WP4 (2026-09-03): both slots used to be left at SHELXL's 293(2)
  untouched - an unmeasured temperature must never reach the CIF as a
  number.
- Slots that remain `?` are listed in the return value, never silently.
"""
from __future__ import annotations

import re
from typing import Any

# single-line `_tag           value` (value may be ? or a number/word)
_TAG_RE = "^({tag})(\\s+)(\\S.*)$"


def _set_tag(text: str, tag: str, value: str, only_if_placeholder: bool = True
             ) -> tuple[str, bool]:
    """Replace a single-line CIF item's value; returns (text, changed)."""
    pat = re.compile(_TAG_RE.format(tag=re.escape(tag)), re.MULTILINE)
    m = pat.search(text)
    if not m:
        return text, False
    if only_if_placeholder and m.group(3).strip() not in ("?", "'?'", "."):
        return text, False
    return pat.sub(lambda mm: f"{mm.group(1)}{mm.group(2)}{value}", text,
                   count=1), True


def _cif_str(v: str) -> str:
    v = str(v).strip()
    if re.search(r"\s", v) or v == "":
        return "'" + v.replace("'", " ") + "'"
    return v


#: Unicode → CIF 1.1 markup (IUCr conventions: Greek = backslash+Latin,
#: ring accent = \%letter, degree = \%). CIF is an ASCII format: journal
#: pipelines and iotbx's lexer both reject raw UTF-8 (r13: a 'Mo Kα' prior
#: carried into _diffrn_source crashed the grader's C++ CIF parser).
_CIF_TRANSLIT = {
    "α": r"\a", "β": r"\b", "γ": r"\g", "δ": r"\d", "ε": r"\e",
    "ζ": r"\z", "η": r"\h", "θ": r"\q", "κ": r"\k", "λ": r"\l",
    "μ": r"\m", "ν": r"\n", "ξ": r"\x", "π": r"\p", "ρ": r"\r",
    "σ": r"\s", "τ": r"\t", "φ": r"\f", "χ": r"\c", "ψ": r"\y",
    "ω": r"\w", "Δ": r"\D", "Σ": r"\S", "Ω": r"\W", "Θ": r"\Q",
    "Λ": r"\L", "Π": r"\P", "Å": r"\%A", "å": r"\%a", "°": r"\%",
    "±": "+-", "×": "x", "·": ".", "–": "-", "—": "-", "−": "-",
    "‘": " ", "’": " ", "“": " ", "”": " ",
}


def _fix_bare_tags(text: str) -> tuple[str, list[str]]:
    """Give '?' to data tags that carry no value at all.

    Valid follow-ups for a lone tag line are a semicolon text field or
    (inside a loop header) more tags then data; outside loops, a tag line
    directly followed by another tag/loop_/data_/EOF has simply lost its
    value. Loop headers are skipped by tracking loop_ blocks."""
    lines = text.splitlines()
    fixed: list[str] = []
    in_loop_header = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == "loop_":
            in_loop_header = True
            continue
        if in_loop_header:
            if not s.startswith("_"):
                in_loop_header = False  # first data row of the loop
            continue
        if re.fullmatch(r"_\S+", s):
            nxt = ""
            for j in range(i + 1, len(lines)):
                if lines[j].strip() != "":
                    nxt = lines[j].lstrip()
                    break
            # a value on the NEXT line (quoted string, bare token, or a
            # semicolon text field) is legal CIF - only a tag directly
            # followed by another tag / loop_ / data_ / EOF lost its value
            if not (nxt == "" or nxt.startswith("_")
                    or nxt.startswith("loop_") or nxt.startswith("data_")):
                continue
            lines[i] = ln.rstrip() + "    ?"
            fixed.append(s)
    return ("\n".join(lines) + ("\n" if text.endswith("\n") else ""),
            fixed)


def _asciify_cif(text: str) -> tuple[str, list[str]]:
    """Transliterate non-ASCII to CIF markup; unknowns become '?'.
    Returns (ascii_text, sorted list of distinct chars that were replaced)."""
    if all(ord(c) < 127 for c in text):
        return text, []
    seen: set[str] = set()
    out: list[str] = []
    for c in text:
        if ord(c) < 127:
            out.append(c)
            continue
        seen.add(c)
        out.append(_CIF_TRANSLIT.get(c, "?"))
    return "".join(out), sorted(seen)


def _semitext(v: str) -> str:
    """A multi-line CIF text field."""
    body = str(v).strip()
    return "\n;\n " + body.replace("\n", "\n ") + "\n;"


#: The '?' slots a journal CIF cannot ship with, mapped to the checkCIF
#: alert they raise and the set_experiment key (or tool argument) that
#: fills them. pa1: 27/27 deliveries carried 183/184/185_A (cell
#: measurement), 24/27 699_A (crystal description), 16/27 660_A
#: (radiation type) - every one a metadata slot the agent could have
#: filled or asked the user about, but the assembler only listed the tags
#: in a caveat string without saying which alert each one costs.
KEY_METADATA_SLOTS: dict[str, tuple[str | None, str]] = {
    "_cell_measurement_reflns_used": ("183_A", "cell_measurement.reflns_used"),
    "_cell_measurement_theta_min": ("184_A", "cell_measurement.theta_min"),
    "_cell_measurement_theta_max": ("185_A", "cell_measurement.theta_max"),
    "_exptl_crystal_description": ("699_A", "crystal.description"),
    "_exptl_crystal_colour": (None, "crystal.colour"),
    "_exptl_crystal_size_max": ("055_C", "crystal.size_mm"),
    "_exptl_crystal_size_mid": ("054_C", "crystal.size_mm"),
    "_exptl_crystal_size_min": ("053_C", "crystal.size_mm"),
    "_exptl_absorpt_correction_type": ("052_C", "absorption.type"),
    "_exptl_absorpt_correction_T_min": ("052_C", "absorption.t_min"),
    "_exptl_absorpt_correction_T_max": ("052_C", "absorption.t_max"),
    "_diffrn_radiation_type": ("660_A", "instrument.source ('synchrotron "
                                        "...' or the tube, e.g. 'Mo Ka')"),
    "_diffrn_source": (None, "instrument.source"),
    "_diffrn_measurement_device_type": (None, "instrument.diffractometer"),
    "_diffrn_measurement_method": (None, "instrument.method"),
    "_computing_data_collection": (None, "computing.data_collection"),
    "_computing_cell_refinement": (None, "computing.cell_refinement"),
    "_computing_data_reduction": (None, "computing.data_reduction"),
    "_chemical_formula_moiety": ("048_C", "write_outputs(formula_moiety=)"),
    # written as '?' only when the refinement stands in a setting no
    # tabulated H-M symbol names (an origin-shifted SHELXT solution). The
    # honest fix is upstream, not a name the operator loop contradicts.
    "_space_group_name_H-M_alt": (
        "122_A", "no tabulated Hermann-Mauguin symbol names this setting - "
                 "re-solve / transform the model onto the ITA reference "
                 "origin (see setting_change.cb_op) and refine again"),
    "_computing_structure_solution": (None, "solver lineage (run_shelxt / "
                                            "solve_* node) - unknown for an "
                                            "imported start model"),
}

#: what the CIF says about HOW the structure was solved, per solver node
#: in the delivered node's ancestry. SHELXL's ACTA default claims
#: 'SHELXT 2018/2' and the old assembler forced 'charge flipping' - pa1
#: hex-l0-r1 shipped the latter while its lineage says run_shelxt.
#: _atom_sites_solution_primary enumeration (core CIF): dual = dual-space
#: (SHELXT), iterative = charge flipping (smtbx / SUPERFLIP).
SOLVER_PROVENANCE: dict[str, tuple[str, str]] = {
    "run_shelxt": ("SHELXT (Sheldrick, 2015)", "dual"),
    "solve_charge_flipping": ("CrystalPilot (charge flipping, smtbx/cctbx)",
                              "iterative"),
    "solve_superflip": ("SUPERFLIP (Palatinus & Chapuis, 2007)",
                        "iterative"),
    "interpret_peaks": ("charge flipping (CrystalPilot smtbx/cctbx or "
                        "SUPERFLIP)", "iterative"),
}


def missing_metadata(text: str) -> list[dict[str, Any]]:
    """Key slots still '?' in a CIF, each with the checkCIF alert it raises
    and the set_experiment key that fills it (machine-readable so the
    agent can ask the user for exactly these facts, or record them)."""
    remaining = set(re.findall(r"^(_[A-Za-z0-9_/.\[\]-]+)\s+\?\s*$",
                               text, re.MULTILINE))
    out: list[dict[str, Any]] = []
    for tag, (alert, key) in KEY_METADATA_SLOTS.items():
        if tag in remaining:
            entry: dict[str, Any] = {"tag": tag, "fill_via": key}
            if alert:
                entry["checkcif_alert"] = alert
            out.append(entry)
    return out


def assemble_publication_cif(cif_text: str,
                             experiment: dict[str, Any] | None = None,
                             mask_info: dict[str, Any] | None = None,
                             solution_note: str | None = None,
                             refine_note: str | None = None,
                             moiety: str | None = None,
                             solution: dict[str, Any] | None = None,
                             mask_params: dict[str, Any] | None = None,
                             ) -> tuple[str, dict[str, Any]]:
    """Fill SHELXL ACTA `?` slots. Returns (cif_text, report) where report =
    {filled: [tags], remaining_placeholders: [tags], caveats: [str],
    missing_metadata: [{tag, checkcif_alert, fill_via}]}.

    `solution` = {"computing": str|None, "primary": str|None,
    "caveat": str|None} from the delivered node's solver lineage (see
    SOLVER_PROVENANCE); computing=None means the method is unknown and the
    slot is written as '?' instead of SHELXL's default SHELXT claim.
    `mask_params` = the solvent_mask parameters (probe radius goes into
    _platon_squeeze_void_probe_radius)."""
    exp = experiment or {}
    filled: list[str] = []
    caveats: list[str] = []
    text = cif_text

    def put(tag: str, value: str | None, quoted: bool = True,
            force: bool = False) -> None:
        nonlocal text
        if value is None or str(value).strip() == "":
            return
        v = _cif_str(value) if quoted else str(value)
        text, ok = _set_tag(text, tag, v, only_if_placeholder=not force)
        if ok:
            filled.append(tag)

    # ---- experiment block -------------------------------------------------
    cryst = exp.get("crystal") or {}
    put("_exptl_crystal_description", cryst.get("description"))
    put("_exptl_crystal_colour", cryst.get("colour"))
    size = cryst.get("size_mm")
    if size and len(size) == 3:
        # FORCED like the temperature: SHELXL copies the SIZE card of the
        # job into these slots, so a size corrected by set_experiment
        # after the job must still win - the delivery is the job's model
        # plus the session's metadata, and metadata never needs a rerun
        s = sorted((float(x) for x in size), reverse=True)
        put("_exptl_crystal_size_max", f"{s[0]:.3f}", quoted=False,
            force=True)
        put("_exptl_crystal_size_mid", f"{s[1]:.3f}", quoted=False,
            force=True)
        put("_exptl_crystal_size_min", f"{s[2]:.3f}", quoted=False,
            force=True)

    inst = exp.get("instrument") or {}
    put("_diffrn_source", inst.get("source"))
    put("_diffrn_measurement_device_type", inst.get("diffractometer"))
    put("_diffrn_measurement_method", inst.get("method"))
    # SHELXL names the radiation only for the laboratory lines it knows
    # (MoK\a, CuK\a, ...); any other wavelength leaves '?' = 660_A on every
    # synchrotron dataset (pa1 hex/cage, 0.68883 A: 16/27 deliveries). The
    # IUCr enumeration has 'synchrotron' for exactly that case - filled
    # only when the recorded source says so, never inferred from lambda.
    if "synchrotron" in str(inst.get("source") or "").lower():
        put("_diffrn_radiation_type", "synchrotron", quoted=False)

    absn = exp.get("absorption") or {}
    put("_exptl_absorpt_correction_type", absn.get("type"))
    if absn.get("t_min") is not None:
        put("_exptl_absorpt_correction_T_min", f"{float(absn['t_min']):.4f}",
            quoted=False)
    if absn.get("t_max") is not None:
        put("_exptl_absorpt_correction_T_max", f"{float(absn['t_max']):.4f}",
            quoted=False)
    put("_exptl_absorpt_process_details", absn.get("details"))

    # SHELXL estimates a T range from SIZE (_shelx_estimated_absorpt_T_*).
    # When a correction METHOD is on record but its T range is not, those
    # estimates are the honest fallback for _exptl_absorpt_correction_T_*;
    # with no correction on record they stay a caveat only - promoting them
    # would fabricate a correction that never happened.
    est = {}
    for k in ("min", "max"):
        m = re.search(rf"_shelx_estimated_absorpt_T_{k}\s+([\d.]+)", text)
        if m:
            est[k] = m.group(1)
    if est:
        if absn.get("type") and (absn.get("t_min") is None
                                 or absn.get("t_max") is None):
            for k in ("min", "max"):
                if k in est and absn.get(f"t_{k}") is None:
                    put(f"_exptl_absorpt_correction_T_{k}", est[k],
                        quoted=False)
            caveats.append(
                "吸收校正 T_min/T_max 取自 SHELXL 按 SIZE 的估算值"
                f"（_shelx_estimated_absorpt_T_*：{est.get('min', '?')}-"
                f"{est.get('max', '?')}），如有 SADABS/TWINABS .abs 实测"
                "范围请经 ingest 或 set_experiment 提供后重新输出。")
        elif not absn.get("type"):
            caveats.append(
                "无吸收校正记录（_exptl_absorpt_correction_type 空缺）；"
                f"SHELXL 由 SIZE 估算 T ≈ {est.get('min', '?')}-"
                f"{est.get('max', '?')} 仅供参考，未写入正式字段，"
                "请用 set_experiment 记录真实校正方法与 T 范围。")

    temp = exp.get("temperature_K")
    if temp is not None:
        tv = f"{float(temp):.0f}"
        put("_diffrn_ambient_temperature", tv, quoted=False, force=True)
        put("_cell_measurement_temperature", tv, quoted=False, force=True)
    else:
        # WP4: an unmeasured temperature must never reach the CIF as a
        # number. With no TEMP card, SHELXL silently assumes 20 C (293 K)
        # for riding-H bond-length/ADP calculations - a fine approximation
        # for GEOMETRY - and then prints that same 293(2) into these two
        # tags as if it had been measured. FORCE both to '?' regardless of
        # what SHELXL wrote (293(2) or anything else): copying the
        # assumption forward would publish a fact nobody measured. This
        # also overrides a bogus placeholder value that may have entered
        # the experiment block via import_cif_model from a third-party
        # deposit that made the same mistake (set_experiment(
        # temperature_K=None) is how an agent purges it going forward).
        had_default = "_diffrn_ambient_temperature       293(2)" in text
        put("_diffrn_ambient_temperature", "?", quoted=False, force=True)
        put("_cell_measurement_temperature", "?", quoted=False, force=True)
        if had_default:
            caveats.append(
                "温度未记录：SHELXL 按惯例假设 20°C 计算（如 riding-H 键长/ADP），"
                "并在其 ACTA 输出中写入 293(2)，两个温度字段已强制覆盖为 '?'，"
                "拒绝把 SHELXL 的假设当成实测值发表。如温度已知，请用 "
                "set_experiment(experiment={'temperature_K': ...}) 记录后 "
                "重新 write_outputs。")
        else:
            caveats.append(
                "温度未记录：_diffrn_ambient_temperature / "
                "_cell_measurement_temperature 已写为 '?'。如温度已知，请用 "
                "set_experiment(experiment={'temperature_K': ...}) 记录后 "
                "重新 write_outputs。")

    cellm = exp.get("cell_measurement") or {}
    if cellm.get("reflns_used") is not None:
        put("_cell_measurement_reflns_used", str(int(cellm["reflns_used"])),
            quoted=False)
    for k, tag in (("theta_min", "_cell_measurement_theta_min"),
                   ("theta_max", "_cell_measurement_theta_max")):
        if cellm.get(k) is not None:
            put(tag, f"{float(cellm[k]):.3f}", quoted=False)

    comp = exp.get("computing") or {}
    put("_computing_data_collection", comp.get("data_collection"))
    put("_computing_cell_refinement", comp.get("cell_refinement"))
    put("_computing_data_reduction", comp.get("data_reduction"))

    # ---- CrystalPilot provenance -----------------------------------------
    # SHELXL writes its SHELXT default into _computing_structure_solution
    # whatever solved the structure. With a lineage-derived `solution` the
    # slot says what the node store recorded (unknown -> '?', with a
    # caveat); the legacy `solution_note` / charge-flipping default only
    # applies when no lineage was supplied.
    if solution is not None:
        if solution.get("computing"):
            put("_computing_structure_solution", solution["computing"],
                force=True)
        else:
            put("_computing_structure_solution", "?", quoted=False,
                force=True)
        if solution.get("primary"):
            put("_atom_sites_solution_primary", solution["primary"],
                quoted=False, force=True)
        if solution.get("caveat"):
            caveats.append(str(solution["caveat"]))
    else:
        put("_computing_structure_solution",
            solution_note or "CrystalPilot (charge flipping, smtbx/cctbx)",
            force=True)
        put("_atom_sites_solution_primary", "iterative", quoted=False)
    if refine_note:
        put("_computing_structure_refinement", refine_note, force=True)
    put("_computing_molecular_graphics", "CrystalPilot workbench (3Dmol.js)")
    put("_computing_publication_material", "CrystalPilot")
    put("_atom_sites_solution_secondary", "difmap", quoted=False)
    put("_chemical_formula_moiety", moiety)

    # _refine_special_details: how this structure was refined
    details = ["Refined with the CrystalPilot autonomous refinement workbench:",
               "typed crystallographic tools (smtbx least squares) with",
               "SHELXL-2019 cross-validation; every model edit is recorded in",
               "an auditable node store."]
    if mask_info:
        details.append(
            "Disordered pore content was treated with a solvent mask computed "
            "by CrystalPilot (smtbx flood fill, PLATON/SQUEEZE-equivalent); "
            "its structure-factor contribution entered the refinement via a "
            ".fab file (ABIN).")
    pat = re.compile(r"^_refine_special_details\s+\?\s*$", re.MULTILINE)
    if pat.search(text):
        text = pat.sub("_refine_special_details" + _semitext(" ".join(details)),
                       text, count=1)
        filled.append("_refine_special_details")

    # ---- solvent mask documentation (_platon_squeeze_*) -------------------
    if mask_info and "_platon_squeeze_details" in text:
        # already documented (a re-assembled delivery CIF rather than a raw
        # SHELXL job.cif): a second block would be a CIF syntax error
        caveats.append("已有 _platon_squeeze 记录，保留原块未重复写入。")
    elif mask_info:
        detail = ("Solvent mask (smtbx flood fill; SQUEEZE-equivalent) "
                  "computed by CrystalPilot. Contributions were included in "
                  "the refinement via ABIN/.fab.")
        totals = []
        if mask_info.get("solvent_volume_A3"):
            totals.append(f"total solvent-accessible volume "
                          f"{mask_info['solvent_volume_A3']:.1f} A^3")
        if mask_info.get("total_solvent_electrons_per_cell"):
            totals.append(f"~{mask_info['total_solvent_electrons_per_cell']:.0f}"
                          " electrons per cell")
        if totals:
            detail += " " + "; ".join(totals) + "."
        if mask_info.get("solvent_mask_converged") is False:
            # the electron count is a lower bound / unsettled number
            # (mask_tools electron_count_note) - the CIF must say so too
            detail += (" The mask electron count did not converge and is "
                       "reported as a provisional estimate.")
        lines = ["", "_platon_squeeze_details" + _semitext(detail)]
        probe = (mask_params or {}).get("solvent_radius")
        if probe is not None:
            # the PLATON-SQUEEZE CIF carries the probe radius (dictionary
            # item _platon_squeeze_void_probe_radius); ours is the
            # solvent_mask solvent_radius that actually produced the voids
            lines.append(f"_platon_squeeze_void_probe_radius "
                         f"{float(probe):.2f}")
        if mask_info.get("voids"):
            # the full PLATON-SQUEEZE loop: checkCIF reads void_content
            # too (' ' = not assigned, PLATON's own convention); the
            # chemical assignment belongs in _chemical_formula_moiety
            lines += ["", "loop_", " _platon_squeeze_void_nr",
                      " _platon_squeeze_void_average_x",
                      " _platon_squeeze_void_average_y",
                      " _platon_squeeze_void_average_z",
                      " _platon_squeeze_void_volume",
                      " _platon_squeeze_void_count_electrons",
                      " _platon_squeeze_void_content"]
            for v in mask_info["voids"]:
                c = v.get("centre_frac") or [0, 0, 0]
                lines.append(f" {v.get('void', '?')} {c[0]:.3f} {c[1]:.3f} "
                             f"{c[2]:.3f} {v.get('volume_A3', 0):.1f} "
                             f"{v.get('electrons', 0):.1f} ' '")
        block = "\n".join(lines) + "\n"
        anchor = "\nloop_\n _atom_site_label"
        if anchor in text:
            text = text.replace(anchor, block + anchor, 1)
            filled.append("_platon_squeeze details"
                          + (" + void loop" if mask_info.get("voids") else ""))

    # ---- formula / Z bookkeeping ------------------------------------------
    # SHELXL prints _chemical_formula_sum = UNIT / ZERR-Z; fractional
    # counts mean Z is wrong (special position / Z' != 1) or partial
    # occupancies are undocumented - either way a guaranteed referee catch.
    mf = re.search(r"^_chemical_formula_sum\s+'?([^'\n]+?)'?\s*$",
                   text, re.MULTILINE)
    if mf and mf.group(1).strip() not in ("?", "."):
        frac = [t for t in re.findall(r"[A-Za-z]{1,2}(\d+\.\d+)", mf.group(1))
                if abs(float(t) - round(float(t))) > 0.05]
        if frac:
            caveats.append(
                f"化学式含非整数计数（_chemical_formula_sum: "
                f"{mf.group(1).strip()}）：UNIT/Z 不整，要么 ZERR 的 Z 不对"
                f"（分子居特殊位置或 Z′≠1），要么存在部分占有的物种。审稿人必查："
                f"用 inspect_model 的 formula 块核实 Z，或在 VALIDATION.md "
                f"说明部分占有的化学依据。")

    # ---- symmetry names vs the operator loop -------------------------------
    # SHELXL names the space group from its LATT/SYMM cards and prints the
    # REFERENCE-setting symbol even when the refinement stands on a shifted
    # origin (reg1-ext2 hsl: 'P 21 21 21' beside the operators of
    # P 21 21 21 (a+1/4,b,c-1/4)). cctbx then refuses the file outright and
    # PLATON raises 120. The operator loop is what SHELXL actually refined -
    # and its own _shelx_space_group_comment says so - therefore the NAMES
    # are corrected to the loop, never the other way round, and no
    # coordinate is touched (see crystalpilot/io/cif_symmetry).
    from ..io.cif_symmetry import rewrite_symmetry_tags
    text, sym_info = rewrite_symmetry_tags(text)
    setting = sym_info.get("setting_change") or {}
    if sym_info.get("corrected"):
        caveats.append("空间群名称与对称操作循环不符，已按操作循环订正"
                       "（操作循环才是权威）："
                       + "；".join(sym_info["corrected"][:4]))
    if setting and not setting.get("is_reference_setting", True):
        caveats.append(
            f"交付所用设置不是 ITA 标准设置（{setting.get('setting')}）："
            f"到标准设置的基变换为 {setting.get('cb_op')}"
            + ("（纯原点平移，hkl 不变）" if not setting.get("hkl_reindexed")
               else "（需要重新指标化 hkl）")
            + "。坐标未被改动，期刊/checkCIF 期望标准设置，若要标准设置请回"
              "到求解端按该基变换重做并重新精修。")

    # ---- what's still open ------------------------------------------------
    remaining = sorted(set(re.findall(r"^(_[A-Za-z0-9_/.\[\]-]+)\s+\?\s*$",
                                      text, re.MULTILINE)))
    if remaining:
        caveats.append("仍为 '?' 的 CIF 项：" + ", ".join(remaining[:20])
                       + ("…" if len(remaining) > 20 else ""))
    # final pass 1: valueless tags are invalid CIF 1.1. SHELXL-2018 copies
    # SADABS trailer metadata from the .hkl into ACTA output but loses the
    # ')'-delimited _exptl_absorpt_process_details text, leaving a bare tag
    # that strict parsers (iotbx, journal pipelines) reject while PLATON
    # forgives (r14b live-fire). Patch such tags to '?'.
    text, bare_fixed = _fix_bare_tags(text)
    if bare_fixed:
        caveats.append("无值 CIF 标签已补为 '?'（SHELXL 拷贝 .hkl 尾注元数据"
                       "时丢失文本值）：" + ", ".join(bare_fixed[:6]))
    # final pass 2: CIF 1.1 is ASCII-only: transliterate any Unicode that
    # rode in via experiment strings (Greek/Å → IUCr markup, unknowns → ?)
    text, replaced = _asciify_cif(text)
    if replaced:
        caveats.append("非 ASCII 字符已按 CIF 惯例转写："
                       + " ".join(replaced[:12])
                       + ("…" if len(replaced) > 12 else ""))
    return text, {"filled": filled, "remaining_placeholders": remaining,
                  "caveats": caveats,
                  "symmetry_names_corrected": sym_info.get("corrected") or [],
                  "symmetry_names_filled": sym_info.get("filled") or [],
                  "setting_change": setting or None,
                  "missing_metadata": missing_metadata(text)}
