"""CIF dialect compatibility: normalize DDLm (CIF2-style, dotted
`_category.object`) tags to the DDL1 underscore names our readers and the
rest of the toolchain speak.

Why: gemmi/iotbx read DDLm files but our field lookups expect DDL1 names;
a DDLm `_cell.length_a` used to fall through every lookup and leave a
1 Angstrom P1 placeholder (caught since by the zero-atom hard failure,
but supporting the dialect is the real fix).

Rule: in DDLm every data name is `_category.object`; the DDL1 alias for
core-dictionary items is the same name with the dot(s) replaced by
underscores (that is how the COMCIFS alias tables are built). So the
transform is mechanical, plus a small exceptions map for names whose
DDL1 spelling differs beyond the separator.
"""
from __future__ import annotations

import re

#: names whose DDL1 alias is not the mechanical dot->underscore join
_EXCEPTIONS = {
    "_space_group.it_number": "_space_group_IT_number",
    "_symmetry.space_group_name_h-m": "_symmetry_space_group_name_H-M",
    "_space_group.name_h-m_alt": "_space_group_name_H-M_alt",
    "_space_group.name_h-m_full": "_space_group_name_H-M_full",
    "_space_group.name_hall": "_space_group_name_Hall",
}

_TAG = re.compile(r"(?m)^([ \t]*)(_[A-Za-z0-9_\-\[\]]+"
                  r"(?:\.[A-Za-z0-9_\-\[\]%/]+)+)")


def looks_like_ddlm(text: str) -> bool:
    """Any dotted data name at a tag position marks the DDLm dialect
    (DDL1 names never contain dots)."""
    return bool(_TAG.search(text))


def normalize_ddlm_tags(text: str) -> str:
    """Rewrite dotted DDLm tags to DDL1 names; DDL1 input passes through
    byte-identical. Only tag tokens at line starts are touched, so dots
    inside quoted values survive."""
    if not looks_like_ddlm(text):
        return text

    def _sub(m: re.Match) -> str:
        tag = m.group(2)
        exc = _EXCEPTIONS.get(tag.lower())
        return m.group(1) + (exc if exc else tag.replace(".", "_"))

    return _TAG.sub(_sub, text)
