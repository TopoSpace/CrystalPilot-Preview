"""Robust full-model .ins/.res reader for real-world (Olex2/SHELXL) files.

iotbx's SHELX parser crashes on instruction soup that Olex2 leaves in .res
files (`list 4`, `MORE -1`, `ABIN`, lowercase commands, ...): any unrecognized
token is lexed as a scatterer and short lines IndexError. This module
sanitizes the file down to the cards the parser needs, feeds it to
xray.structure.from_shelx, and separately extracts the refinement metadata a
workbench session needs: FVAR scale, WGHT, wavelength, Z, restraint cards,
and AFIX riding-hydrogen groups (so a model can be re-serialized faithfully
by crystalpilot.io.shelx_writer).
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .shelx_codes import dangling_free_variable_refs, wrap_card

# Cards the iotbx parser needs to build the crystal + model.
_KEEP = {"TITL", "CELL", "ZERR", "LATT", "SYMM", "SFAC", "UNIT", "FVAR",
         "AFIX", "PART", "HKLF", "END", "DISP", "RESI"}
# Restraint/constraint cards we surface to the session (not fed to the parser).
RESTRAINT_KINDS = {"DFIX", "DANG", "SADI", "FLAT", "SIMU", "DELU", "RIGU",
                   "ISOR", "SAME", "EADP", "EXYZ", "CHIV", "BUMP"}
#: The ONLY instructions an agent may hand to run_shelxl(extra_cards=[...]).
#: Defined here, next to _KNOWN, so the gate and the reader can never drift
#: apart: `_KNOWN` below folds this set in, therefore every card the gate
#: accepts is also a card load_res_model recognizes when SHELXL echoes it
#: back into the .res. Validation of the ARGUMENTS lives in
#: crystalpilot/refine/shelx_cards.py, which imports this name.
#: Each family is a measurement SHELXL can make WITH esds and we cannot:
#: HTAB hydrogen bonds (-> _geom_hbond_* in the ACTA CIF), RTAB named
#: distances/angles/torsions, MPLA least-squares planes, CONF torsion
#: angles, BOND bond lengths, EQIV the symmetry code the others reference;
#: EADP/EXYZ/SAME/SUMP are the constraint cards a disorder model needs and
#: ACTA is the CIF switch itself.
EXTRA_CARD_KEYWORDS = frozenset({
    "HTAB", "RTAB", "MPLA", "CONF", "EADP", "EXYZ", "SAME", "SUMP",
    "EQIV", "BOND", "ACTA",
    # connectivity-table corrections: SHELXL lists bonds by a fixed radius
    # table and the CIF's _geom_bond loop follows it; FREE removes a pair
    # that is not a bond (usertest test3-1: Zn02-C21 2.52 A drawn as a
    # seventh ligand), BIND adds one it missed. Both name two atoms.
    "FREE", "BIND",
})
# Full set of instructions we recognize (and drop unless in _KEEP).
_KNOWN = _KEEP | RESTRAINT_KINDS | EXTRA_CARD_KEYWORDS | {
    "L.S.", "CGLS", "ACTA", "BOND", "CONF", "FMAP", "PLAN", "LIST", "MORE",
    "ABIN", "ANIS", "TEMP", "SIZE", "OMIT", "SHEL", "TWIN", "BASF", "EXTI",
    "SWAT", "MERG", "GRID", "HTAB", "EQIV", "SUMP", "STIR", "SPEC", "MOVE",
    "MPLA", "RTAB", "WPDB", "REM", "BIND", "FREE", "FRAG", "FEND", "DAMP",
    "BLOC", "STOP", "TIME", "HFIX", "WGHT", "LAUE", "ANSC", "ANSR", "NEUT",
    "PRIG", "XNPD", "WIGL", "SLIM", "TANG", "FLAT", "DELF", "HOPE", "MOLE",
}

AFIX_KIND_BY_CODE_C = {43: "aromatic_CH", 23: "CH2", 13: "tertiary_CH",
                       137: "CH3", 127: "CH3", 93: "vinyl_CH2",
                       163: "linear_CH", 147: "OH", 83: "OH", 33: "NH2_planar"}
AFIX_KIND_BY_CODE_N = {43: "NH_planar", 13: "tertiary_NH", 93: "NH2_planar"}


def duplicate_atom_labels(lines: list[str], n_sfac: int) -> list[str]:
    """Atom labels that occur more than once in sanitized SHELX lines.

    An atom line is `LABEL sfac x y z ...` with sfac an integer in
    1..n_sfac and at least five numeric fields; everything else (cards,
    REM) is skipped. Used before handing the text to iotbx, whose own
    duplicate check crashes with an unrelated TypeError."""
    seen: dict[str, int] = {}
    for ln in lines:
        t = ln.split()
        if len(t) < 6 or t[0].upper() in _KNOWN:
            continue
        try:
            slot = int(t[1])
            float(t[2]); float(t[3]); float(t[4])
        except ValueError:
            continue
        if not 1 <= slot <= max(n_sfac, 1):
            continue
        key = t[0].upper()
        seen[key] = seen.get(key, 0) + 1
    return [k for k, n in seen.items() if n > 1]


@dataclass
class ParsedShelxModel:
    structure: Any                    # cctbx xray.structure (may include H)
    path: str
    title: str = ""
    wavelength: float = 0.71073
    z: int | None = None
    cell: tuple | None = None
    scale: float | None = None        # FVAR overall scale factor
    fvar_extra: list[float] = field(default_factory=list)
    weights: tuple[float, float] = (0.1, 0.0)
    sfac: list[str] = field(default_factory=list)
    restraint_lines: list[str] = field(default_factory=list)
    h_riding: list[dict] = field(default_factory=list)
    #: Non-H AFIX blocks, e.g. AFIX 66 aromatic rigid groups. Atom order and
    #: optional AFIX parameters matter and must survive every serialization.
    afix_groups: list[dict] = field(default_factory=list)
    rem_r1: float | None = None       # R1 quoted in REM lines, if any
    dropped_lines: list[str] = field(default_factory=list)
    temperature_K: float | None = None   # from TEMP card (Celsius on the card)
    crystal_size: tuple[float, float, float] | None = None  # SIZE card, mm
    cell_esd: tuple | None = None        # ZERR esds (a b c alpha beta gamma)
    parts: dict[str, int] = field(default_factory=dict)      # label -> PART n
    #: label -> raw sof for non-plain occupancies (free or FVAR-coded);
    #: effective occupancies are already applied by the iotbx reader
    sof_codes: dict[str, float] = field(default_factory=dict)
    twin: dict | None = None             # {"matrix": [9], "n": int}
    basf: list[float] = field(default_factory=list)
    hklf: int = 4                        # HKLF code (5 = twin-batch data)
    #: verbatim data-processing cards (SHEL/OMIT/MERG/EXTI/SWAT): they
    #: change WHICH reflections/Fc enter R and must round-trip to SHELX
    #: jobs; the in-process engine currently ignores them (disclosed).
    data_cards: list[str] = field(default_factory=list)
    #: the deposit refined WITH a solvent mask (ABIN card); the .fab is
    #: normally not deposited - R is meaningless until a mask is recomputed
    uses_abin: bool = False
    #: element -> the 14 numbers of a long-form SFAC card. Custom scattering
    #: factors: the refinement used THESE, our engines use the built-in
    #: X-ray tables. Nearly always electron diffraction (see is_electron).
    custom_sfac: dict[str, list[float]] = field(default_factory=dict)
    #: element -> (f', f'') from DISP cards: the anomalous terms the
    #: refinement actually used. shelx_writer regenerates them from the
    #: CELL wavelength; this is for audits and round-trip tests.
    disp: dict[str, tuple[float, float]] = field(default_factory=dict)

    @property
    def is_electron_diffraction(self) -> bool:
        """Electron wavelengths are ~0.02-0.05 A; X-ray sources are >0.5 A."""
        return self.wavelength < 0.1


def _strip_inline_comment(line: str) -> str:
    """SHELX treats '!' (and ' =' trailing handled separately) as start of an
    inline comment. Published deposits use it heavily on restraint cards
    ('SIMU ... !alternative list'); keeping the tail turns comments into
    phantom atom names (live failure: WRONG NUMBER OF ATOM NAMES on a
    CD-MOF deposit). TITL/REM lines are free text - left untouched."""
    head = line.split(maxsplit=1)
    if head and head[0].upper()[:4] in ("TITL", "REM"):
        return line
    cut = line.find("!")
    return line if cut < 0 else line[:cut].rstrip()


def _logical_lines(text: str) -> list[str]:
    """Join SHELX '=' continuations into single logical lines; stop at END.
    Inline '!' comments are stripped BEFORE continuation handling, matching
    SHELXL ('... = ! note' still continues)."""
    out: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = _strip_inline_comment(raw.rstrip())
        if pending:
            line = pending + " " + line.strip()
            pending = ""
        if line.endswith("="):
            pending = line[:-1].rstrip()
            continue
        out.append(line)
        if line.split(maxsplit=1) and line.split()[0].upper() == "END":
            break
    if pending:
        out.append(pending)
    return out


def _is_atom_card(tokens: list[str]) -> bool:
    if len(tokens) < 6 or len(tokens[0]) > 4:
        return False
    try:
        int(tokens[1])
        for t in tokens[2:6]:
            float(t)
    except ValueError:
        return False
    return True


_wrap_card = wrap_card          # shared with the writer (io.shelx_codes)


def load_res_model(path: str | Path) -> ParsedShelxModel:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = _logical_lines(text)

    kept: list[str] = []
    meta = ParsedShelxModel(structure=None, path=str(p))
    afix_code = 0
    last_carrier: str | None = None
    group: dict | None = None
    afix_block: dict | None = None
    capture_afix_atoms = True

    def close_afix_block():
        nonlocal afix_block
        if afix_block and afix_block.pop("has_heavy", False):
            meta.afix_groups.append(afix_block)
        afix_block = None

    seen_hklf = False
    current_part = 0
    sfac_slot: int | None = None       # where the collapsed SFAC card goes
    fv_refs: list[tuple] = []          # (label, param, value, m) with |m| >= 2

    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        t0 = tokens[0].upper()
        if t0.startswith("REM"):
            m = re.search(r"R1\s*=\s*([0-9.]+)", line)
            if m and meta.rem_r1 is None:
                meta.rem_r1 = float(m.group(1))
            continue
        known = t0 in _KNOWN
        if known and t0 in RESTRAINT_KINDS:
            meta.restraint_lines.append(line.strip())
            continue
        if known and t0 == "ABIN":
            meta.uses_abin = True
        if known and t0 in ("SHEL", "OMIT", "MERG", "EXTI", "SWAT") \
                and not seen_hklf:
            meta.data_cards.append(line.strip())
            # fall through: TEMP/SIZE-style metadata handling not needed
        if known and t0 not in _KEEP:
            if t0 == "WGHT" and not seen_hklf:
                try:
                    a = float(tokens[1]) if len(tokens) > 1 else 0.1
                    b = float(tokens[2]) if len(tokens) > 2 else 0.0
                    meta.weights = (a, b)
                except ValueError:
                    pass
            elif t0 == "TEMP" and len(tokens) > 1:
                try:  # SHELX TEMP is in Celsius
                    meta.temperature_K = round(float(tokens[1]) + 273.15, 2)
                except ValueError:
                    pass
            elif t0 == "SIZE" and len(tokens) >= 4:
                try:
                    dims = sorted((float(tokens[1]), float(tokens[2]),
                                   float(tokens[3])), reverse=True)
                    meta.crystal_size = tuple(dims)
                except ValueError:
                    pass
            elif t0 == "TWIN":
                try:
                    vals = [float(x) for x in tokens[1:]]
                    if len(vals) >= 9:
                        meta.twin = {"matrix": vals[:9],
                                     "n": int(vals[9]) if len(vals) > 9 else 2}
                except ValueError:
                    pass
            elif t0 == "BASF":
                try:
                    meta.basf = [float(x) for x in tokens[1:]]
                except ValueError:
                    pass
            continue
        if known:  # in _KEEP
            if t0 == "TITL":
                meta.title = line[4:].strip()
            elif t0 == "CELL" and len(tokens) >= 8:
                meta.wavelength = float(tokens[1])
                meta.cell = tuple(float(x) for x in tokens[2:8])
            elif t0 == "ZERR" and len(tokens) >= 2:
                try:
                    meta.z = int(float(tokens[1]))
                except ValueError:
                    pass
                if len(tokens) >= 8:
                    try:
                        esd = tuple(float(x) for x in tokens[2:8])
                        if any(e > 0 for e in esd):
                            meta.cell_esd = esd
                    except ValueError:
                        pass
            elif t0 == "SFAC":
                # element-list form only (long form has numbers at position 2)
                if len(tokens) > 2 and re.fullmatch(r"[-+0-9.Ee]+", tokens[2]):
                    # long form: one element + its scattering-factor
                    # coefficients. iotbx's parser raises NotImplementedError
                    # on these, so they are collapsed into a single
                    # element-list card below (SFAC ORDER IS THE ATOM TYPE
                    # INDEX - it must be preserved exactly).
                    meta.sfac.append(tokens[1])
                    try:
                        meta.custom_sfac[tokens[1]] = [float(x) for x
                                                       in tokens[2:]]
                    except ValueError:
                        meta.custom_sfac[tokens[1]] = []
                    if sfac_slot is None:
                        sfac_slot = len(kept)
                        kept.append("")          # patched after the scan
                    continue
                meta.sfac.extend(tokens[1:])
            elif t0 == "DISP" and len(tokens) >= 4:
                # `DISP $El f' f'' [mu]` (shelx_writer.disp_cards, Olex2).
                # The card stays in `kept` for iotbx, whose lexer reads
                # $El as an element token and whose parsers ignore DISP.
                try:
                    el = tokens[1].lstrip("$")
                    meta.disp[el[:1].upper() + el[1:].lower()] = (
                        float(tokens[2]), float(tokens[3]))
                except ValueError:
                    pass
            elif t0 == "FVAR":
                vals = [float(x) for x in tokens[1:]]
                if vals:
                    if meta.scale is None:
                        meta.scale = vals[0]
                        meta.fvar_extra = vals[1:]
                    else:
                        meta.fvar_extra.extend(vals)
            elif t0 == "AFIX":
                try:
                    afix_code = int(float(tokens[1])) if len(tokens) > 1 else 0
                except ValueError:
                    afix_code = 0
                # ANY new AFIX card ends the current H run (not only AFIX 0:
                # e.g. `AFIX 43 / H / AFIX 6 / O30 / H30A H30B / AFIX 0`
                # is two groups - merging them corrupts the round-trip)
                if group and group["h"]:
                    meta.h_riding.append(group)
                group = None
                # n=5 resumes the previous n=6/9 rigid group after a nested
                # riding-H block; m=6 fits the next six NON-hydrogen atoms.
                if afix_block and afix_code % 10 in (3, 4, 7, 8):
                    capture_afix_atoms = False
                elif afix_block and afix_code % 10 == 5:
                    capture_afix_atoms = True
                else:
                    close_afix_block()
                    capture_afix_atoms = True
                if afix_code and afix_block is None:
                    afix_block = {"afix": afix_code, "card": line.strip(), "atoms": [],
                                  "has_heavy": False}
            elif t0 == "PART":
                try:
                    current_part = int(float(tokens[1])) if len(tokens) > 1 \
                        else 0
                except ValueError:
                    current_part = 0
            elif t0 == "HKLF":
                close_afix_block()
                seen_hklf = True
                try:
                    meta.hklf = int(float(tokens[1])) if len(tokens) > 1 \
                        else 4
                except ValueError:
                    meta.hklf = 4
            kept.append(line)
            continue
        if not seen_hklf and _is_atom_card(tokens):
            kept.append(_wrap_card(line))
            label = tokens[0]
            try:
                nums = [float(t) for t in tokens[2:12]]
            except ValueError:
                nums = []
            for name, val, m in dangling_free_variable_refs(nums, 1):
                fv_refs.append((label, name, val, m))
            if current_part:
                meta.parts[label] = current_part
            try:
                sof_raw = float(tokens[5])
                # anything other than the plain fixed form (10+occ) needs
                # round-trip metadata: free (<5) or FVAR-coded (>=15 or <0)
                if not (5.0 < sof_raw < 15.0):
                    meta.sof_codes[label] = sof_raw
            except (ValueError, IndexError):
                pass
            try:
                elem = meta.sfac[int(tokens[1]) - 1] if meta.sfac else ""
            except (ValueError, IndexError):
                elem = ""
            elem = elem[:1].upper() + elem[1:].lower()
            if afix_block is not None and capture_afix_atoms:
                afix_block["atoms"].append(label)
                afix_block["has_heavy"] |= elem != "H"
            if afix_code > 4 and elem == "H" and last_carrier:
                if group is None:
                    kind_map = (AFIX_KIND_BY_CODE_N if last_carrier[:1].upper() == "N"
                                else AFIX_KIND_BY_CODE_C)
                    group = {"carrier": last_carrier,
                             "kind": kind_map.get(afix_code),
                             "afix": afix_code, "h": []}
                    # deposit's Uiso multiplier (H U field of -1.5 / -1.2)
                    try:
                        uval = float(tokens[6])
                        if uval < 0:
                            group["u_mult"] = -uval
                    except (IndexError, ValueError):
                        pass
                group["h"].append(label)
            elif elem != "H":
                # a non-H atom ends the current H run (next carrier)
                if group and group["h"]:
                    meta.h_riding.append(group)
                    group = None
                last_carrier = label
            continue
        meta.dropped_lines.append(line.strip())

    if group and group["h"]:
        meta.h_riding.append(group)
    close_afix_block()
    rigid_members = {a for g in meta.afix_groups for a in g["atoms"]}
    meta.h_riding = [g for g in meta.h_riding
                    if not any(h in rigid_members for h in g["h"])]
    if sfac_slot is not None:
        kept[sfac_slot] = "SFAC " + " ".join(meta.sfac)
    if not any(ln.split() and ln.split()[0].upper() == "END" for ln in kept):
        kept.append("END")

    n_fv = max(1, (1 if meta.scale is not None else 0) + len(meta.fvar_extra))
    dangling = [r for r in fv_refs if abs(r[3]) > n_fv]
    if dangling:
        # iotbx dies on these with a bare IndexError (free_variable[m]);
        # SHELXL and Olex2 misread them just as silently. Name the atom and
        # the number so the agent can act on the parent node instead
        label, name, val, m = dangling[0]
        kind = ("ADP" if name.startswith("U") else
                "occupancy" if name == "sof" else "coordinate")
        others = sorted({r[0] for r in dangling} - {label})
        raise ValueError(
            f"{p.name}: {label} {name} = {val:.5f} references free variable "
            f"{abs(m)} but FVAR defines {n_fv}"
            + (f" (also {', '.join(others[:6])})" if others else "")
            + f" - a number with |p| >= 5 is not a plain SHELX parameter, "
            f"so this {kind} diverged when the model was refined and no "
            f"SHELX reader can take the file. Check out the parent node and "
            f"repair {label} (isotropic ADP, restraints, or delete it) "
            f"before refining again")
    dups = duplicate_atom_labels(kept, len(meta.sfac))
    if dups:
        # iotbx's parser dies on a duplicate with a TypeError from its own
        # error formatting ("%i format ... NoneType") - pa2 cage-l0-r2
        # lost every checkout/ghost_test of two nodes to that message
        raise ValueError(
            f"{path.name if hasattr(path, 'name') else path} carries "
            f"duplicate atom labels {sorted(dups)} - a SHELX model must "
            "name every atom once (the node was committed with a label "
            "collision, usually riding H re-derived next to the job's own "
            "H); rename_atoms(mode='canonical') on the parent node or "
            "re-run add_hydrogens after run_shelxl(adopt)")
    sanitized = "\n".join(kept) + "\n"
    from cctbx import xray  # deferred: cctbx import is heavy
    with tempfile.NamedTemporaryFile("w", suffix=".res", delete=False,
                                     encoding="ascii", errors="replace") as fh:
        fh.write(sanitized)
        tmp = fh.name
    try:
        meta.structure = xray.structure.from_shelx(filename=tmp,
                                                   strictly_shelxl=False)
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
    return meta
