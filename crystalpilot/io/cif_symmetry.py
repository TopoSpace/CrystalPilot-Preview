"""Symmetry names that are TRUE for the operators standing beside them.

reg1-ext2 case hsl (org_hsl_cod2241460) was solved by SHELXT on a shifted
origin: the model's group is `P 21 21 21 (a+1/4,b,c-1/4)`, but every writer
in the chain printed the REFERENCE-setting name `P 21 21 21` next to the
SHIFTED operator loop.  Consequences, all measured on the delivered file:

  * `iotbx.cif.reader(...).build_crystal_structures()` raises
    `CifBuilderError: Inconsistent symmetry information found` - so the
    grader fell through to its gemmi fallback, which reads the H-M SYMBOL
    and therefore paired the standard operators with shifted coordinates:
    emma matched 4/13 at rms 0.64 A and the run was graded
    "framework not reproduced".  The structure was in fact perfect
    (13/13, rms 0.001 A) once the operator loop was believed.
  * PLATON raised `120_G  Reported P212121 Inconsistent with Explicit
    P212121` and `125_C  No _symmetry_space_group_name_Hall Given`.

Decision - (b) "keep the setting, name it truthfully" - and why not (a):

  (a) would transform the delivered model into the reference setting at
  write time.  The delivery cannot carry that.  final.cif is SHELXL's own
  ACTA output (coordinates WITH esds, aniso U_ij, geometry loops whose
  `n_klm` codes index the operator list, the embedded _shelx_res_file and
  the _refln loop); final.fcf and final.fab are byte copies of the same
  job's files, and final.fab holds mask coefficients A+iB that an origin
  shift multiplies by exp(2*pi*i*h.t).  Rebasing all of that at text level
  would manufacture numbers no program computed, and it would break
  grade._reproduce_refinement, which re-runs the EMBEDDED res+hkl to prove
  the delivered R1.  Only a re-refinement can honestly produce a delivery
  in another basis, and write_outputs must never refine.

  (b) costs nothing but the truth: the operator loop is left exactly as
  refined (SHELXL's own _shelx_space_group_comment says that loop is the
  authoritative source), and every name written beside it is verified by
  round-trip against that loop.  A setting with no tabulated H-M symbol
  gets '?' plus the Hall symbol that does carry the origin; PLATON then
  raises 122_A "No _symmetry_space_group_name_H-M Given" INSTEAD of 120_G,
  which is the honest alert - the delivery really is not in a tabulated
  setting, and the agent is told so via write_outputs' `setting_change`.

Generalization: nothing here knows about P2(1)2(1)2(1) or about any
crystal.  Candidate symbols are generated from cctbx and then ACCEPTED
ONLY IF they parse back to exactly the group they are meant to name, so
the same code serves origin shifts, axis permutations (P21/n vs P21/c),
centred groups, rhombohedral settings and both origin choices of Fd-3m.
"""
from __future__ import annotations

import re
from typing import Any

#: operator-loop tags, new and deprecated spelling
SYMOP_TAGS = ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz")
#: Hermann-Mauguin name tags, new and deprecated spelling
HM_TAGS = ("_space_group_name_H-M_alt", "_symmetry_space_group_name_H-M")
#: Hall name tags, new and deprecated spelling
HALL_TAGS = ("_space_group_name_Hall", "_symmetry_space_group_name_Hall")
#: IT number tags, new and deprecated spelling
NUMBER_TAGS = ("_space_group_IT_number", "_symmetry_Int_Tables_number")
#: crystal-system tags, new and deprecated spelling
SYSTEM_TAGS = ("_space_group_crystal_system", "_symmetry_cell_setting")

#: marker so a re-written file is not annotated twice
_COMMENT_MARK = "# CrystalPilot symmetry:"


def _sgtbx():
    from cctbx import sgtbx
    return sgtbx


def hm_symbol_for(space_group) -> str | None:
    """A TABULATED Hermann-Mauguin symbol naming exactly `space_group`.

    None when the setting is not tabulated (e.g. an arbitrary origin
    shift): a name that does not reproduce the operators is worse than no
    name at all."""
    sgtbx = _sgtbx()
    try:
        lookup = space_group.info().type().lookup_symbol().strip()
    except Exception:  # noqa: BLE001 - an unnameable group is simply unnamed
        return None
    if not lookup or "(" in lookup:
        # cctbx appends the change of basis for a non-tabulated setting
        # ('P 21 21 21 (a+1/4,b,c-1/4)') - not an H-M symbol
        return None
    try:
        if sgtbx.space_group_info(symbol=lookup).group() == space_group:
            return lookup
    except Exception:  # noqa: BLE001
        pass
    return None


def _origin_shift_hall(space_group) -> list[str]:
    """`<reference Hall> (v1 v2 v3)` candidates, v in twelfths.

    This is the origin-shift form the Hall definition itself provides, so
    it travels to parsers that do not know cctbx's `(x,y,z)` extension.
    Only expressible when the change of basis is a pure origin shift whose
    translation is a whole number of twelfths."""
    info = space_group.info()
    cb = info.change_of_basis_op_to_reference_setting()
    if not cb.c().r().is_unit_mx():
        return []
    t = cb.c().t()
    den = t.den()
    vals = []
    for n in t.num():
        if (n * 12) % den:
            return []
        vals.append(n * 12 // den)
    ref_hall = info.reference_setting().type().hall_symbol().strip()
    plus = f"{ref_hall} ({vals[0]} {vals[1]} {vals[2]})"
    minus = f"{ref_hall} ({-vals[0]} {-vals[1]} {-vals[2]})"
    return [plus, minus]


def hall_symbol_for(space_group) -> str | None:
    """A Hall symbol that parses back to exactly `space_group`.

    Unlike the H-M symbol a Hall symbol CAN carry the origin, so this is
    the tag that makes a non-reference setting unambiguous.  Candidates,
    most portable first: the tabulated Hall of a tabulated H-M symbol, the
    Hall origin-shift form, then cctbx's change-of-basis extension."""
    sgtbx = _sgtbx()
    candidates: list[str] = []
    hm = hm_symbol_for(space_group)
    if hm:
        try:
            candidates.append(sgtbx.space_group_symbols(hm).hall().strip())
        except Exception:  # noqa: BLE001
            pass
    candidates += _origin_shift_hall(space_group)
    try:
        candidates.append(space_group.info().type().hall_symbol().strip())
    except Exception:  # noqa: BLE001
        pass
    for cand in candidates:
        if not cand:
            continue
        try:
            if sgtbx.space_group(cand) == space_group:
                return cand
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
    return None


def describe(space_group) -> dict[str, Any]:
    """Everything a CIF/report needs to say about the setting of a group.

    `cb_op` is the change of basis that WOULD take this model to the ITA
    reference setting; it is reported, never applied (see the module
    docstring).  `hkl_reindexed` says whether that change of basis would
    also reindex the reflections - false for a pure origin shift."""
    info = space_group.info()
    sg_type = info.type()
    cb = info.change_of_basis_op_to_reference_setting()
    pure_shift = bool(cb.c().r().is_unit_mx())
    hm = hm_symbol_for(space_group)
    out: dict[str, Any] = {
        "setting": str(info),
        "reference_setting": str(info.reference_setting()),
        "is_reference_setting": bool(info.is_reference_setting()),
        "it_number": int(sg_type.number()),
        "crystal_system": str(space_group.crystal_system()).lower(),
        "hm": hm,
        "hall": hall_symbol_for(space_group),
        "cb_op": cb.as_xyz(),
        "hkl_reindexed": not pure_shift,
    }
    if not out["is_reference_setting"]:
        out["note"] = (
            f"non-reference setting {out['setting']}; change of basis to the "
            f"reference setting is {out['cb_op']} "
            + ("(pure origin shift - hkl unchanged)" if pure_shift
               else "(reindexes hkl)"))
    if hm is None:
        out["hm_note"] = (
            "no tabulated Hermann-Mauguin symbol names this setting - "
            "_space_group_name_H-M_alt is written as '?' (checkCIF 122_A) "
            "rather than a symbol the operator loop contradicts")
    return out


# --------------------------------------------------------------------------- #
# reading the operator loop out of CIF text
# --------------------------------------------------------------------------- #

_OP_TOKEN = re.compile(r"^[-+0-9xyzXYZ/,.\s]+$")


def _ops_via_iotbx(text: str) -> list[str]:
    try:
        import iotbx.cif
        model = iotbx.cif.reader(input_string=text).model()
    except Exception:  # noqa: BLE001 - fall back to the text scan
        return []
    for block in model.values():
        for tag in SYMOP_TAGS:
            v = block.get(tag)
            if v is None:
                continue
            return [str(x) for x in ([v] if isinstance(v, str) else list(v))]
    return []


def _ops_via_scan(text: str) -> list[str]:
    """Regex fallback: a CIF too broken for the parser still has a loop."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if not any(ln.strip().startswith(t) for t in SYMOP_TAGS):
            continue
        ops: list[str] = []
        for row in lines[i + 1:]:
            s = row.strip()
            if not s or s.startswith(("_", "loop_", "data_", "#", ";")):
                break
            s = re.sub(r"^\d+\s+", "", s).strip().strip("'\"").strip()
            if "," in s and _OP_TOKEN.match(s):
                ops.append(s)
            else:
                break
        if ops:
            return ops
    return []


def space_group_from_cif_text(text: str):
    """The space group the CIF's OWN operator loop defines, or None.

    SHELXL says it best in its `_shelx_space_group_comment`: the loop
    "should always be used as a source of symmetry information in
    preference to the above space-group names"."""
    sgtbx = _sgtbx()
    ops = _ops_via_iotbx(text) or _ops_via_scan(text)
    if not ops:
        return None
    sg = sgtbx.space_group()
    try:
        for op in ops:
            sg.expand_smx(sgtbx.rt_mx(str(op)))
    except Exception:  # noqa: BLE001 - an unparseable operator is not a group
        return None
    return sg


def _tag_value(text: str, tag: str) -> str | None:
    m = re.search(r"^" + re.escape(tag) + r"[ \t]+(\S.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def cif_unquote(raw: str | None) -> str | None:
    """The value of a CIF token: only a MATCHING outer quote pair is
    removed, never a quote character that belongs to the value.

    2026-09-08 usertest test3-2 (P3(2)21): SHELXL writes the Hall symbol as
    `'P 32 2"'` - the trailing double quote IS the symbol (the 2" axis
    direction; 12 tabulated Hall symbols end that way: P321, P3121, P3221,
    R32, P3m1, P3c1, R3m, R3c, P-3m1, P-3c1, R-3m, R-3c). `strip("'\"")`
    ate it, the remainder `P 32 2` names P3(2)12, and finalize_delivery
    refused every delivery of that crystal three times over as a fatal
    symmetry conflict that did not exist."""
    if raw is None:
        return None
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1].strip()
    return s


def _set_tag(text: str, tag: str, value: str) -> tuple[str, str | None]:
    """Force `tag` to `value`; returns (text, previous value or None)."""
    pat = re.compile(r"^(" + re.escape(tag) + r")([ \t]+)(\S.*)$", re.MULTILINE)
    m = pat.search(text)
    if not m:
        return text, None
    old = m.group(3).strip()
    if old == value:
        return text, None
    return pat.sub(lambda mm: f"{mm.group(1)}{mm.group(2)}{value}", text,
                   count=1), old


def _quote(value: str | None) -> str:
    """A CIF string token. A value carrying a single quote is wrapped in
    double quotes rather than mutilated (no tabulated Hall symbol carries
    one today, but the writer must not depend on that); a value with both
    kinds cannot be a CIF 1.1 token and loses its single quotes."""
    if value is None:
        return "?"
    s = str(value)
    if "'" in s and '"' not in s:
        return '"' + s + '"'
    return "'" + s.replace("'", " ") + "'"


def _comment(body: str, width: int = 78) -> list[str]:
    """Wrap a note into `# ` lines - PLATON alert 802 counts CIF records
    longer than 80 characters, comments included."""
    out: list[str] = []
    line = "#"
    for word in str(body).split():
        if len(line) + 1 + len(word) > width and line != "#":
            out.append(line)
            line = "#"
        line += " " + word
    if line != "#":
        out.append(line)
    return out


def check_cif_symmetry(text: str) -> dict[str, Any]:
    """Do the CIF's symmetry NAMES agree with its operator loop?

    Returns {checked, consistent, ops_setting, conflicting: [{tag, value,
    names}]}.  `consistent=None` means there was nothing to compare."""
    sgtbx = _sgtbx()
    ops_sg = space_group_from_cif_text(text)
    out: dict[str, Any] = {"checked": ops_sg is not None}
    if ops_sg is None:
        out["consistent"] = None
        out["note"] = "no symmetry operator loop in this CIF"
        return out
    out["ops_setting"] = str(ops_sg.info())
    conflicts: list[dict[str, str]] = []
    for tag in HM_TAGS + HALL_TAGS + NUMBER_TAGS:
        val = cif_unquote(_tag_value(text, tag))
        if val is None or val in ("?", ".", ""):
            continue
        try:
            if tag in NUMBER_TAGS:
                # an IT number names the space-group TYPE, which every
                # setting of that group shares - only a different type is
                # a conflict
                same = (int(val) == ops_sg.info().type().number())
                if not same:
                    conflicts.append(
                        {"tag": tag, "value": val,
                         "names": str(sgtbx.space_group_info(
                             number=int(val)).group().info())})
                continue
            if tag in HALL_TAGS:
                named = sgtbx.space_group(val)
            else:
                named = sgtbx.space_group_info(symbol=val).group()
        except Exception:  # noqa: BLE001 - unreadable is not a conflict
            continue
        if named != ops_sg:
            conflicts.append({"tag": tag, "value": val,
                              "names": str(named.info())})
    out["consistent"] = not conflicts
    if conflicts:
        out["conflicting"] = conflicts
    return out


def _tag_is_true(tag: str, raw: str | None, ops_sg, desc) -> bool | None:
    """True/False when `raw` can be judged against the operator group,
    None when the slot is empty (nothing to judge, something to fill)."""
    val = cif_unquote(raw)
    if val is None or val in ("?", ".", ""):
        return None
    sgtbx = _sgtbx()
    try:
        if tag in NUMBER_TAGS:
            # an IT number names the space-group TYPE, true in every setting
            return int(val) == desc["it_number"]
        if tag in SYSTEM_TAGS:
            return val.lower() == desc["crystal_system"]
        if tag in HALL_TAGS:
            return sgtbx.space_group(val) == ops_sg
        return sgtbx.space_group_info(symbol=val).group() == ops_sg
    except Exception:  # noqa: BLE001 - unreadable is not true
        return False


def conflict_summary(sym: dict[str, Any]) -> str:
    """One line naming the untrue tags and the group they DO name.

    The two strings can look identical ('P 21 21 21' names P 21 21 21 while
    the loop is P 21 21 21 (a+1/4,b,c-1/4)), so the setting is spelled out
    on both sides."""
    conflicts = sym.get("conflicting") or []
    tags = ", ".join(f"{c['tag']}={c['value']}" for c in conflicts[:3])
    named = ", ".join(sorted({c["names"] for c in conflicts}))
    return (f"the operator loop defines {sym.get('ops_setting')}, but "
            f"{tags} name a different set of operators ({named})")


def rewrite_symmetry_tags(text: str) -> tuple[str, dict[str, Any]]:
    """Make every symmetry NAME in `text` true for its own operator loop.

    Coordinates, cell and operators are never touched - only the names
    that describe them, and only when they are UNTRUE or empty: a CIF
    that already names its setting correctly comes back byte-identical
    (a Hall symbol is still filled in when the slot is '?', which is what
    checkCIF 125 asks for).  Idempotent.  Returns (text, info) with
    `setting_change` (the describe() dict), `corrected` (names that were
    untrue) and `filled` (empty slots given a value)."""
    ops_sg = space_group_from_cif_text(text)
    info: dict[str, Any] = {"checked": ops_sg is not None,
                            "corrected": [], "filled": [], "changed": []}
    if ops_sg is None:
        info["note"] = "no symmetry operator loop found; names left untouched"
        return text, info
    desc = describe(ops_sg)
    info["setting_change"] = desc
    corrected: list[str] = []
    filled: list[str] = []
    truth = {**{t: _quote(desc["hm"]) for t in HM_TAGS},
             **{t: _quote(desc["hall"]) for t in HALL_TAGS},
             **{t: str(desc["it_number"]) for t in NUMBER_TAGS},
             **{t: desc["crystal_system"] for t in SYSTEM_TAGS}}
    for tag, value in truth.items():
        raw = _tag_value(text, tag)
        ok = _tag_is_true(tag, raw, ops_sg, desc)
        if ok is True:
            continue                     # already true: leave the wording be
        if ok is None and value == "?":
            continue                     # nothing known, nothing to fill
        text, old = _set_tag(text, tag, value)
        if old is None:
            continue
        (filled if ok is None else corrected).append(
            f"{tag}: {old} -> {value}")

    # cctbx's CIF builder ranks IT number < Hall < H-M: with the H-M
    # symbol withheld, only a Hall symbol can outrank an IT number that
    # names the reference setting.  Insert one when the file has none.
    if desc["hall"] and not any(_tag_value(text, t) for t in HALL_TAGS):
        anchor = None
        for tag in NUMBER_TAGS + HM_TAGS + SYSTEM_TAGS:
            m = re.search(r"^" + re.escape(tag) + r"[ \t]+\S.*$", text,
                          re.MULTILINE)
            if m:
                anchor = m
                break
        line = f"_space_group_name_Hall{' ' * 8}{_quote(desc['hall'])}"
        if anchor is not None:
            text = text[:anchor.end()] + "\n" + line + text[anchor.end():]
        else:
            text = line + "\n" + text
        filled.append(f"_space_group_name_Hall inserted: {desc['hall']}")

    changed = corrected + filled
    if corrected and _COMMENT_MARK not in text:
        note = _comment(f"{_COMMENT_MARK[2:]} names corrected to match the "
                        "operator loop below (the authoritative symmetry).")
        for key in ("note", "hm_note"):
            if desc.get(key):
                note += _comment(desc[key])
        m = re.search(r"^(" + "|".join(re.escape(t) for t in
                                       NUMBER_TAGS + HM_TAGS + HALL_TAGS +
                                       SYSTEM_TAGS) + r")[ \t]+\S.*$",
                      text, re.MULTILINE)
        if m:
            text = text[:m.start()] + "\n".join(note) + "\n" + text[m.start():]
    info["corrected"], info["filled"], info["changed"] = (corrected, filled,
                                                          changed)
    return text, info


def cif_symmetry_block(space_group) -> tuple[list[str], dict[str, Any]]:
    """The symmetry lines of a CIF we write ourselves, plus describe()."""
    desc = describe(space_group)
    lines = [f"_space_group_crystal_system   {desc['crystal_system']}",
             f"_space_group_IT_number        {desc['it_number']}"]
    if not desc["is_reference_setting"]:
        lines += _comment(f"{_COMMENT_MARK[2:]} {desc['note']}")
    if desc.get("hm_note"):
        lines += _comment(desc["hm_note"])
    lines.append(f"_space_group_name_H-M_alt     {_quote(desc['hm'])}")
    lines.append(f"_space_group_name_Hall        {_quote(desc['hall'])}")
    return lines, desc
