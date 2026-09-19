"""The `run_shelxl(extra_cards=[...])` whitelist gate and the HTAB builder.

WHY THIS EXISTS (defect D11).  CrystalPilot never emitted HTAB or MPLA, so
the delivered CIF carried no `_geom_hbond_*` loop and no plane block - the
first thing a crystallographer looks for in a hydrogen-bonded structure was
simply absent, and the numbers our own interaction engine computes have no
esds.  SHELXL computes both WITH esds from the full covariance matrix.  The
fix is therefore NOT to compute `_geom_hbond_*` here: it is to hand SHELXL
the two-atom `HTAB D A` cards and let it do the measurement.  Verified
against vendor SHELXL-2019/3 (2026-09-04):

  * `HTAB D A` / `HTAB D A_$n` -> a `_geom_hbond_*` loop in the ACTA CIF,
    with esds, which `report/publication.py` carries through to final.cif
    untouched (it is a text-level assembler);
  * bare `HTAB` (search form) prints candidates in the .lst and appends
    suggested cards AFTER `END` in the .res - it puts NOTHING in the CIF;
  * `MPLA` / `RTAB` results reach the .lst ONLY.  SHELXL writes no plane or
    named-distance data item into the CIF, so an MPLA card buys the .lst
    table (and the covariance-matrix esds in it), not a CIF block.  The
    `_geom_special_details` text SHELXL always writes is boilerplate about
    how esds are estimated, not the plane itself.

WHAT THE GATE IS FOR.  `shelxl_command_block` passes instruction text into
the .ins verbatim, so an unchecked channel is a way to hand SHELXL a card
that aborts the job (unknown atom name, undefined `$n`, a line past the
80-column limit) after the model has already been serialized - the failure
surfaces as a bare "shelxl failed (exit 2)" with the reason buried in the
.lst.  Every rejection here names the offending card instead.

Checks that are NOT SHELXL's own: SHELXL applies an EQIV operator
literally, without asking whether it belongs to the space group - a typo
produces a plausible-looking distance and a wrong `_geom_hbond_site_
symmetry_A` code in the published CIF.  That one is checked here.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from ..io.shelx_codes import wrap_card
from ..io.shelx_model import EXTRA_CARD_KEYWORDS

__all__ = ["EXTRA_CARD_KEYWORDS", "CARD_FAMILIES", "MAX_EQIV_INDEX",
           "SHELX_LINE_LIMIT", "op_to_shelx", "validate_extra_cards",
           "htab_cards", "extra_cards_help"]

#: SHELXL reads 80 columns per physical line; longer cards must be split
#: with a trailing `=` and a continuation line that starts with a space.
SHELX_LINE_LIMIT = 80
#: `wrap_card` breaks at this column, leaving room for the " =" it appends.
_WRAP_WIDTH = 76
#: SHELX symmetry-code index range ($1..$99); vendor SHELXL-2019/3 accepts
#: $99 (probed 2026-09-04).
MAX_EQIV_INDEX = 99

#: identity operator as cctbx prints it - the rows that need no EQIV
IDENTITY_OP = "x,y,z"

#: accepted family -> its SHELX syntax and what it buys, kept SHORT: this
#: dict is the tool's parameter description (extra_cards_help).
CARD_FAMILIES: dict[str, str] = {
    "EQIV": "$n <symop>` defines the _$n code the others use",
    "HTAB": "D A` / `HTAB D A_$n` = the hydrogen bond -> _geom_hbond_* "
            "with esds in the CIF (never name the H)",
    "RTAB": "name a1 a2 [a3 [a4]]` named distance/angle/torsion (.lst)",
    "MPLA": "[na] atoms` least-squares plane + deviations (.lst)",
    "CONF": "[atoms [d_max ang_max]]` torsion angles",
    "BOND": "atoms` / `BOND $H` bond lengths",
    "EADP": "atoms` equal ADP",
    "EXYZ": "atoms` shared site",
    "SAME": "[s1 s2] atoms` same-geometry restraint",
    "SUMP": "c sigma c1 m1 ...` free-variable sum",
    "ACTA": "[2theta]` CIF switch (already emitted for l_s > 0)",
    "FREE": "a1 a2` remove a pair from the connectivity table (the CIF "
            "bond/angle loops follow it; write_outputs' bond_table_audit "
            "names the card)",
    "BIND": "a1 a2` add a pair to the connectivity table",
}

#: RTAB's first argument is a <=4-character NAME, not an atom.
_NAME_FIRST = frozenset({"RTAB"})
#: cards whose arguments are all numeric - an atom name there is a mistake.
_NUMERIC_ONLY = frozenset({"SUMP", "ACTA"})

_NUM_RE = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eEdD][-+]?\d+)?$")
#: NAME[_resi][_$n] - SHELX atom reference (`_*` = all residues).
_ATOM_REF_RE = re.compile(
    r"^(?P<name>[^_\s]+)"
    r"(?:_(?P<resi>\*|\d+|[A-Za-z][A-Za-z0-9]*))?"
    r"(?:_\$(?P<eqiv>\d+))?$")
_EQIV_DEF_RE = re.compile(r"^\$(\d+)$")


def extra_cards_help() -> str:
    """One flat sentence naming every accepted family - the tool's
    parameter description, so the agent never has to guess the whitelist."""
    return "; ".join(f"`{k} {v}" for k, v in CARD_FAMILIES.items())


def _is_number(tok: str) -> bool:
    return bool(_NUM_RE.match(tok))


# --------------------------------------------------------------------------
# symmetry operators: cctbx `x,y,z` string  ->  SHELX EQIV form
# --------------------------------------------------------------------------

def op_to_shelx(op: Any) -> str:
    """`-x,-y+1,-z` (cctbx) -> `-X, -Y+1, -Z` (SHELX EQIV/SYMM form).

    Exactly the emission `io/shelx_writer` uses for SYMM cards, so the two
    can never disagree: uppercase symbols, translations LAST and written as
    exact fractions (`Y+1/2`, never 0.5 rounded).  Vendor SHELXL-2019/3 was
    probed with all three spellings (`-X+1/2, Y+1/2, -Z+1/2`,
    `0.5-X, 0.5+Y, 0.5-Z`, lowercase) and returns the same distance for
    each; the fraction form is chosen because it is exact.

    Accepts an `sgtbx.rt_mx` or any string cctbx can parse.
    """
    from cctbx import sgtbx
    rt = op if isinstance(op, sgtbx.rt_mx) else sgtbx.rt_mx(str(op).strip())
    return rt.as_xyz(decimal=False, t_first=False, symbol_letters="XYZ",
                     separator=", ")


def _parse_op(text: str):
    """`sgtbx.rt_mx` from SHELX or cctbx spelling, or None."""
    from cctbx import sgtbx
    try:
        return sgtbx.rt_mx(text.replace(" ", ""))
    except Exception:                                    # noqa: BLE001
        return None


def _op_in_group(rt, space_group) -> bool:
    """Is `rt` an operator of `space_group` (integral lattice translations
    and centring included)?  `space_group.contains` answers exactly that."""
    try:
        return bool(space_group.contains(rt))
    except Exception:                                    # noqa: BLE001
        return True          # never reject on a cctbx quirk


# --------------------------------------------------------------------------
# the whitelist gate
# --------------------------------------------------------------------------

class _Gate:
    def __init__(self, labels: Iterable[str], rename: dict[str, str] | None,
                 elements: Iterable[str], space_group,
                 base_cards: Sequence[str]):
        rename = rename or {}
        # both spellings resolve: the session label an agent quotes from
        # inspect_model AND the (possibly sanitized) label the .ins carries
        self.by_upper: dict[str, str] = {}
        for lbl in labels:
            ins = rename.get(lbl, lbl.strip())
            self.by_upper.setdefault(lbl.strip().upper(), ins)
            self.by_upper.setdefault(ins.upper(), ins)
        self.elements = {str(e).upper() for e in elements}
        self.space_group = space_group
        self.base_keywords = {c.split()[0].upper() for c in base_cards
                              if c.split()}
        self.base_norm = {" ".join(c.upper().split()) for c in base_cards}
        self.ls_cycles: int | None = None
        for c in base_cards:                 # L.S. n / CGLS n
            t = c.split()
            if len(t) >= 2 and t[0].upper() in ("L.S.", "CGLS"):
                try:
                    self.ls_cycles = int(float(t[1]))
                except ValueError:
                    pass
        self.eqiv: dict[int, str] = {}       # $n -> SHELX operator text
        for c in base_cards:                 # EQIV already in the .ins
            t = c.split()
            if len(t) >= 3 and t[0].upper() == "EQIV":
                m = _EQIV_DEF_RE.match(t[1])
                if m:
                    self.eqiv[int(m.group(1))] = " ".join(t[2:])

    # -- one token ---------------------------------------------------------
    def token(self, tok: str, card: str) -> tuple[str | None, str | None]:
        """(rewritten token, error). Numbers / range operators / wildcards
        pass through; `$El` is checked against the model's element list;
        anything else is an atom reference."""
        if _is_number(tok) or tok in (">", "<", "*"):
            return tok, None
        if tok.startswith("$"):
            el = tok[1:].upper()
            if el and el in self.elements:
                return tok, None
            return None, (
                f"{card!r}: `{tok}` names all atoms of element "
                f"{tok[1:]!r}, which this model does not contain "
                f"(elements: {', '.join(sorted(self.elements))})")
        m = _ATOM_REF_RE.match(tok)
        if not m:
            return None, (f"{card!r}: {tok!r} is not a SHELX atom reference "
                          f"(NAME, NAME_resi, NAME_$n)")
        ins = self.by_upper.get(m.group("name").upper())
        if ins is None:
            return None, (
                f"{card!r}: no atom {m.group('name')!r} in the model - "
                f"use the labels inspect_model reports")
        n = m.group("eqiv")
        if n is not None and int(n) not in self.eqiv:
            return None, (
                f"{card!r}: symmetry code $" + n + " is not defined; add "
                f"`EQIV ${n} <symop>` to the same extra_cards list")
        out = ins
        if m.group("resi") is not None:
            out += "_" + m.group("resi")
        if n is not None:
            out += "_$" + n
        return out, None

    # -- one card ----------------------------------------------------------
    def card(self, raw: str) -> tuple[str | None, str | None]:
        """(card text with .ins labels, error)."""
        if not isinstance(raw, str):
            return None, f"extra_cards entries must be strings, got {raw!r}"
        if "\n" in raw or "\r" in raw:
            return None, (
                f"{raw!r}: give one instruction per list entry - the "
                f"80-column split is added here, not by you")
        toks = raw.split()
        if not toks:
            return None, "extra_cards contains an empty entry"
        head = toks[0].upper()
        kw = head.split("_")[0]              # SAME_2 -> SAME (residue form)
        if kw == "ANIS":
            return None, "ANIS is a model edit: use set_adp(atoms=[...], mode='anisotropic'), then run_shelxl; AFIX/TWIN are retained"
        if kw == "AFIX":
            return None, "AFIX is a scoped model constraint: use set_afix with ordered existing atoms and create/replace/remove"
        if kw not in EXTRA_CARD_KEYWORDS:
            return None, (
                f"{raw!r}: {kw} is not on the extra_cards whitelist "
                f"({', '.join(sorted(EXTRA_CARD_KEYWORDS))}). Restraints go "
                f"through set_restraints; refinement cards through the "
                f"run_shelxl parameters.")
        if kw == "EQIV":
            return self._eqiv(raw, toks)
        norm = " ".join(raw.upper().split())
        if kw == "ACTA" and "ACTA" in self.base_keywords:
            return None, (
                f"{raw!r}: ACTA is already emitted by run_shelxl whenever "
                f"it can be (l_s > 0), so a second one only risks a "
                f"duplicate-card abort; drop it")
        if kw == "ACTA" and self.ls_cycles == 0:
            return None, (
                f"{raw!r}: SHELXL refuses ACTA with L.S. 0 ('ACTA requires "
                f"least-squares') and aborts the job; a 0-cycle run cannot "
                f"produce a CIF at all - raise l_s")
        if norm in self.base_norm:
            return None, (
                f"{raw!r}: run_shelxl already writes this card into every "
                f".ins - a duplicate is not additive")
        args = toks[1:]
        if kw in _NUMERIC_ONLY:
            for t in args:
                if not _is_number(t):
                    return None, (f"{raw!r}: {kw} takes numbers only, "
                                  f"got {t!r}")
            return " ".join([head] + args), None
        out = [head]
        for i, t in enumerate(args):
            if i == 0 and kw in _NAME_FIRST:
                if len(t) > 4 or _is_number(t):
                    return None, (
                        f"{raw!r}: RTAB's first argument is the <=4 "
                        f"character NAME of the table, not an atom")
                out.append(t)
                continue
            new, err = self.token(t, raw)
            if err:
                return None, err
            out.append(new or t)
        return " ".join(out), None

    def _eqiv(self, raw: str, toks: list[str]) -> tuple[str | None,
                                                        str | None]:
        if len(toks) < 3:
            return None, f"{raw!r}: EQIV needs `$n` and a symmetry operator"
        m = _EQIV_DEF_RE.match(toks[1])
        if not m:
            return None, (f"{raw!r}: {toks[1]!r} is not a SHELX symmetry "
                          f"code - it must read $1 ... ${MAX_EQIV_INDEX}")
        n = int(m.group(1))
        if not 1 <= n <= MAX_EQIV_INDEX:
            return None, (f"{raw!r}: symmetry codes run $1..${MAX_EQIV_INDEX}")
        rt = _parse_op(" ".join(toks[2:]))
        if rt is None:
            return None, (f"{raw!r}: {' '.join(toks[2:])!r} is not a "
                          f"symmetry operator (expected `-X+1/2, Y+1/2, -Z`)")
        if self.space_group is not None and not _op_in_group(
                rt, self.space_group):
            return None, (
                f"{raw!r}: that operator is not in this space group. SHELXL "
                f"would apply it anyway and publish a wrong "
                f"_geom_hbond_site_symmetry_A - take the operator from the "
                f"`op` field of the interaction table, not by hand")
        text = op_to_shelx(rt)
        if n in self.eqiv and self.eqiv[n] != text:
            return None, (f"{raw!r}: $" + str(n) + " is already defined as "
                          f"`{self.eqiv[n]}` in this job")
        self.eqiv[n] = text
        return f"EQIV ${n} {text}", None


def validate_extra_cards(cards: Sequence[Any], *, labels: Iterable[str],
                         elements: Iterable[str] = (),
                         rename: dict[str, str] | None = None,
                         space_group: Any = None,
                         base_cards: Sequence[str] = (),
                         ) -> tuple[list[str], list[str], str | None]:
    """Gate agent-supplied SHELX instructions.

    Returns `(lines, applied, error)`.  `lines` are ready for the .ins
    (EQIV definitions first, then the rest in the order given, each already
    split with SHELX `=` continuation when it passes 80 columns); `applied`
    is the same set as single-line text for the tool summary; `error` is a
    ready-to-return failure message naming the offending card, and is the
    only thing a caller needs to look at to decide.

    `labels` are the model's atom labels and `rename` the writer's
    sanitization map, so an agent may quote either spelling; `elements` are
    the model's element symbols (for `$H`-style references); `space_group`
    is checked for EQIV membership when given; `base_cards` are the
    instructions run_shelxl already writes (duplicate detection).
    """
    if cards is None:
        return [], [], None
    if isinstance(cards, str) or not isinstance(cards, (list, tuple)):
        return [], [], (f"extra_cards must be a list of SHELX instruction "
                        f"strings, got {type(cards).__name__}")
    gate = _Gate(labels, rename, elements, space_group, base_cards)
    # EQIV first, so a card may reference $n before the list defines it
    order = sorted(range(len(cards)),
                   key=lambda i: (0 if (isinstance(cards[i], str)
                                        and cards[i].split()
                                        and cards[i].split()[0].upper()
                                        .split("_")[0] == "EQIV") else 1, i))
    eqiv: list[tuple[str, str]] = []          # (wrapped, flat)
    other: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i in order:
        text, err = gate.card(cards[i])
        if err:
            return [], [], err
        assert text is not None
        wrapped = wrap_card(text, _WRAP_WIDTH)
        too_long = [ln for ln in wrapped.split("\n")
                    if len(ln) > SHELX_LINE_LIMIT]
        if too_long:
            return [], [], (
                f"{cards[i]!r}: this card cannot be split inside SHELX's "
                f"{SHELX_LINE_LIMIT}-column limit (the longest piece is "
                f"{len(too_long[0])} characters with no break point); split "
                f"it into several cards")
        if text.upper() in seen:
            continue                          # exact duplicate: harmless
        seen.add(text.upper())
        (eqiv if text.upper().startswith("EQIV") else
         other).append((wrapped, text))
    pairs = eqiv + other
    return [w for w, _ in pairs], [t for _, t in pairs], None


# --------------------------------------------------------------------------
# HTAB builder (pure: takes the canonical hydrogen-bond table, gives cards)
# --------------------------------------------------------------------------

#: `chem/interactions.py` marks a hydrogen bond measured without hydrogen.
_NO_H_STATUS = "no_H_D···A_only"

_RIDING_NOTE = (
    "the H are riding, so SHELXL will report the D-H it imposed "
    "(~0.95-0.98 A, not the neutron ~1.09 A) and an angle the constraint "
    "fixed - the D...A distance is the measured quantity; say so wherever "
    "the table is quoted")


def htab_cards(rows: Sequence[dict], h_source: str | None, *,
               max_eqiv: int = 48) -> dict[str, Any]:
    """`EQIV`/`HTAB` cards for `run_shelxl(extra_cards=...)`.

    `rows` is `find_interactions(...)["unique"]["hbond"]` - the
    SYMMETRY-UNIQUE table, so the cards do not change when the viewer grows
    the picture.  Returns `{"cards": [...], "skipped": [...], "note": str}`.

    What it will not do:

    * `h_source == "absent"` -> no cards at all.  A hydrogen bond without a
      hydrogen is a D...A contact; SHELXL cannot measure D-H or the angle
      and would print `** No suitable H-bond found **` for every card.
      Place the H first (add_hydrogens) and re-run.
    * a row whose `status` is the hydrogen-free marker, or whose `passes` is
      false, is skipped with its reason rather than published.

    Rows are emitted shortest D...A first.  Every operator other than the
    identity gets one `EQIV $n`, reused for every row that shares it, and
    at most `max_eqiv` distinct operators are defined (SHELX codes run to
    $99; the remaining rows are reported in `skipped`, never dropped
    silently).  The H is deliberately NOT named on the card: SHELXL finds
    the hydrogen itself, which is what makes a donor carrying several H
    work.
    """
    skipped: list[dict[str, Any]] = []
    rows = list(rows or [])
    if h_source == "absent":
        return {"cards": [], "skipped": [
            {"d": r.get("d"), "a": r.get("a"), "op": r.get("op"),
             "reason": "no hydrogen in the model"} for r in rows],
            "note": ("no HTAB emitted: the model has no hydrogen atoms "
                     "(h_source='absent'), so SHELXL has nothing to "
                     "measure D-H or the D-H...A angle from. Place the H "
                     "(add_hydrogens) and build the cards again.")}

    usable: list[dict] = []
    for r in rows:
        if r.get("status") == _NO_H_STATUS:
            skipped.append({"d": r.get("d"), "a": r.get("a"),
                            "op": r.get("op"), "dist": r.get("dist"),
                            "reason": "measured without H "
                                      f"(status {_NO_H_STATUS!r})"})
            continue
        if not r.get("passes"):
            skipped.append({"d": r.get("d"), "a": r.get("a"),
                            "op": r.get("op"), "dist": r.get("dist"),
                            "angle": r.get("angle"),
                            "reason": "fails the distance/angle criterion"})
            continue
        if not (r.get("d") and r.get("a")):
            skipped.append({"d": r.get("d"), "a": r.get("a"),
                            "op": r.get("op"),
                            "reason": "row carries no donor/acceptor label"})
            continue
        usable.append(r)
    usable.sort(key=lambda r: (float(r.get("dist") or 0.0),
                               str(r.get("d")), str(r.get("a"))))

    eqiv_index: dict[str, int] = {}
    eqiv_cards: list[str] = []
    htab: list[str] = []
    seen: set[str] = set()
    for r in usable:
        op = str(r.get("op") or IDENTITY_OP)
        suffix = ""
        if op.replace(" ", "").lower() != IDENTITY_OP:
            if op not in eqiv_index:
                if len(eqiv_index) >= int(max_eqiv):
                    skipped.append({
                        "d": r["d"], "a": r["a"], "op": op,
                        "dist": r.get("dist"),
                        "reason": f"more than max_eqiv={int(max_eqiv)} "
                                  f"distinct symmetry operators"})
                    continue
                n = len(eqiv_index) + 1
                eqiv_index[op] = n
                eqiv_cards.append(f"EQIV ${n} {op_to_shelx(op)}")
            suffix = f"_${eqiv_index[op]}"
        card = f"HTAB {r['d']} {r['a']}{suffix}"
        if card.upper() in seen:
            continue
        seen.add(card.upper())
        htab.append(card)
    cards = eqiv_cards + htab

    if not cards:
        note = ("no HTAB emitted: none of the "
                f"{len(rows)} canonical hydrogen-bond rows passed the "
                f"distance/angle criterion with a hydrogen present")
    else:
        note = (f"{len(htab)} HTAB card(s) over {len(eqiv_cards)} symmetry "
                f"code(s); SHELXL - not CrystalPilot - measures D-H, H...A, "
                f"D...A and the angle, and writes them into the ACTA CIF as "
                f"_geom_hbond_* WITH esds")
    if h_source in ("riding", "mixed"):
        note += "; " + _RIDING_NOTE
    elif h_source in (None, "unknown"):
        note += ("; h_source is unknown - state whether the H were refined "
                 "or ridden before quoting D-H or the angle")
    n_cap = sum(1 for s in skipped if "max_eqiv" in str(s.get("reason")))
    if n_cap:
        note += (f"; {n_cap} row(s) left out at the {int(max_eqiv)}-operator "
                 f"cap - raise max_eqiv (SHELX codes run to "
                 f"${MAX_EQIV_INDEX}) or pick the rows you want")
    return {"cards": cards, "skipped": skipped, "note": note}


# --------------------------------------------------------------------------
# effective instruction cards (round-3 WP2)
# --------------------------------------------------------------------------
#: cards that change the refinement itself; the rest (HTAB/RTAB/MPLA/CONF/
#: BOND and the EQIV codes they reference) are measurements SHELXL makes on
#: the way out and do not move a single parameter
CONSTRAINT_CARD_KEYWORDS = frozenset({"EADP", "EXYZ", "SAME", "SUMP"})


def card_keyword(card: str) -> str:
    toks = str(card).split()
    return toks[0].upper().split("_")[0] if toks else ""


def canonical_card(card: str) -> str:
    return " ".join(str(card).split()).upper()


def instruction_cards_of(text: str) -> list[str]:
    """The instruction cards (EXTRA_CARD_KEYWORDS families, ACTA excluded)
    in a .res/.ins text: `=` continuations joined, canonicalised, in file
    order, up to the HKLF card. REM lines are not cards."""
    out: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.strip()
        if buf:
            line = buf + " " + line
            buf = ""
        if line.endswith("="):
            buf = line[:-1].rstrip()
            continue
        toks = line.split()
        if not toks:
            continue
        kw = toks[0].upper()
        if kw == "HKLF":
            break
        if kw in EXTRA_CARD_KEYWORDS and kw != "ACTA":
            out.append(canonical_card(line))
    return out


def card_coherence(res_text: str, ins_text: str) -> dict[str, Any]:
    """Can the delivered final.res be restarted as the job that produced
    the delivered numbers? The constraint cards decide (a missing EADP or
    SUMP means a restart refines a different model); missing measurement
    cards only mean the CIF's measured tables would not be reproduced."""
    res_cards = instruction_cards_of(res_text)
    job_cards = instruction_cards_of(ins_text)
    rs, js = set(res_cards), set(job_cards)
    missing = [c for c in job_cards if c not in rs]
    extra = [c for c in res_cards if c not in js]
    missing_c = [c for c in missing if card_keyword(c) in CONSTRAINT_CARD_KEYWORDS]
    missing_m = [c for c in missing if card_keyword(c) not in CONSTRAINT_CARD_KEYWORDS]
    extra_c = [c for c in extra if card_keyword(c) in CONSTRAINT_CARD_KEYWORDS]
    restartable = not missing_c and not extra_c
    if not restartable:
        note = ("final.res does not carry the constraint cards the paired "
                "SHELXL job refined with (missing: "
                + (", ".join(missing_c) or "none")
                + "; extra: " + (", ".join(extra_c) or "none")
                + ") - restarting SHELXL from final.res would refine a "
                  "different model than the one delivered")
    elif missing_m:
        note = ("final.res carries every constraint card of the paired job; "
                "the measurement cards (" + ", ".join(missing_m) + ") are "
                "not in it, so a restart reproduces the refinement but not "
                "the CIF's measured tables")
    else:
        note = "final.res carries every instruction card of the paired job"
    return {"restartable": restartable, "res_cards": res_cards,
            "job_cards": job_cards, "missing_constraints": missing_c,
            "missing_measurements": missing_m, "extra_in_res": extra,
            "note": note}


def prune_cards_for_deleted(cards: Iterable[str],
                            deleted: Iterable[str]) -> tuple[list[str], list[str]]:
    """Same-fate hygiene: a card naming a deleted atom aborts every later
    SHELXL job. Returns (kept, dropped)."""
    dl = {str(x).upper() for x in deleted}
    kept: list[str] = []
    dropped: list[str] = []
    for c in cards:
        names = [t.upper().split("_")[0] for t in str(c).split()[1:]]
        (dropped if any(n in dl for n in names) else kept).append(c)
    return kept, dropped


def rename_cards(cards: Iterable[str], rename: dict[str, str]) -> list[str]:
    """Apply a label rename map to the atom references of every card
    (NAME, NAME_$n and NAME_resi spellings keep their suffix)."""
    ren = {str(k).upper(): str(v) for k, v in (rename or {}).items()}
    out: list[str] = []
    for c in cards:
        toks = str(c).split()
        if not toks:
            continue
        new = [toks[0]]
        for t in toks[1:]:
            base, sep, suf = t.partition("_")
            nb = ren.get(base.upper())
            new.append((nb + sep + suf) if nb else t)
        out.append(" ".join(new))
    return out


def effective_cards_from_lines(lines: Iterable[str], xs
                               ) -> tuple[list[str], list[str]]:
    """Constraint cards an imported .res carries (EADP/EXYZ/SAME/SUMP):
    the ones that fit the model become effective cards; the rest are
    reported instead of being dropped as "kept as text"."""
    cands = [str(ln).strip() for ln in lines
             if card_keyword(ln) in CONSTRAINT_CARD_KEYWORDS]
    if not cands:
        return [], []
    from ..io.shelx_writer import element_of, sanitize_labels
    scs = list(xs.scatterers())
    labels = [sc.label for sc in scs]
    applied: list[str] = []
    warns: list[str] = []
    for c in cands:
        _lines, ok, err = validate_extra_cards(
            [c], labels=labels,
            elements={element_of(sc.scattering_type) for sc in scs},
            rename=sanitize_labels(labels), space_group=xs.space_group())
        if err:
            warns.append(f"{c!r} not carried as an effective card: {err}")
        else:
            applied.extend(ok)
    return applied, warns
