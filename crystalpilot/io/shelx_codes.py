"""SHELX numeric parameter coding (free / fixed / free-variable references).

A SHELX atom card holds ten numbers (x y z sof U11 U22 U33 U23 U13 U12, or
one Uiso). Every reader decodes each as 10*m + p with m the NEAREST multiple
of ten (|p| <= 5): m = 0 a free parameter, m = 1 fixed at p, |m| >= 2 a
multiple of free variable m (p*fv_m, or p*(1-fv_m) when m < 0). The
corollary that bites: a free parameter can only be stored while |value| < 5.
A refinement that drives an ADP to U33 = 16.6 A^2 writes an atom card that
SHELXL, iotbx and Olex2 all decode as "-3.42 x free variable 2" - reg1-mof
cage n0152 (2026-09-04): the node was committed, then checkout/ghost_test
died with IndexError inside iotbx and the agent lost its best node. These
helpers keep the format honest on every side: the writer refuses such a
value, the loader names it, `refine` reverts it before the node is written.
"""
from __future__ import annotations

#: |value| below this an atom-card number reads back as a FREE parameter
FREE_LIMIT = 5.0

PARAM_NAMES_ANISO = ("x", "y", "z", "sof",
                     "U11", "U22", "U33", "U23", "U13", "U12")
PARAM_NAMES_ISO = ("x", "y", "z", "sof", "Uiso")


def code_of(value: float) -> tuple[int, float]:
    """(m, p) with value = 10*m + p and m the nearest multiple of ten
    (ties to even, as scitbx.math.divmod resolves them)."""
    v = float(value)
    m = int(round(v / 10.0))
    return m, v - 10.0 * m


def free_encodable(value: float) -> bool:
    """True when `value` on an atom card reads back as a free parameter."""
    return abs(float(value)) < FREE_LIMIT


def unencodable_free_params(site, u_iso=None, u_cif=None) -> list[tuple[str, float]]:
    """[(name, value)] of the free parameters the SHELX format cannot store.

    `u_cif` (U11 U22 U33 U23 U13 U12, CIF basis) for an anisotropic atom,
    else `u_iso`."""
    bad: list[tuple[str, float]] = []
    for name, v in zip(("x", "y", "z"), site):
        if not free_encodable(v):
            bad.append((name, float(v)))
    if u_cif is not None:
        for name, v in zip(PARAM_NAMES_ANISO[4:], u_cif):
            if not free_encodable(v):
                bad.append((name, float(v)))
    elif u_iso is not None and not free_encodable(u_iso):
        bad.append(("Uiso", float(u_iso)))
    return bad


def dangling_free_variable_refs(fields, n_free_variables: int
                                ) -> list[tuple[str, float, int]]:
    """[(name, value, m)] of the atom-card numbers that reference a free
    variable the FVAR card does not define.

    `fields` are the numbers after the element index (x y z sof U...);
    `n_free_variables` counts FVAR entries INCLUDING the scale (fv1)."""
    names = PARAM_NAMES_ANISO if len(fields) >= 10 else PARAM_NAMES_ISO
    out: list[tuple[str, float, int]] = []
    for name, v in zip(names, fields):
        m, _p = code_of(v)
        if abs(m) >= 2 and abs(m) > n_free_variables:
            out.append((name, float(v), m))
    return out


def wrap_card(line: str, width: int = 76) -> str:
    """Re-emit a long instruction with SHELX '=' continuation (any card may
    be continued that way; SHELXL reads 80 columns per physical line)."""
    if len(line) <= width:
        return line
    head = line[:width]
    cut = head.rfind(" ")
    if cut <= 0:
        return line
    return head[:cut] + " =\n " + wrap_card(line[cut:].strip(), width)
