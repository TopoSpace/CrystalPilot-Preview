"""Read-only audit of the round-4 publication deliverables."""

from pathlib import Path
import re

import gemmi


HERE = Path(__file__).resolve().parent
CIF = HERE / "final.cif"
RES = HERE / "final.res"

doc = gemmi.cif.read_file(str(CIF))
block = doc.sole_block()


def value(tag):
    out = block.find_value(tag)
    return None if out is None else str(out)


for tag in (
    "_chemical_formula_moiety",
    "_refine_ls_R_factor_gt",
    "_refine_ls_R_factor_all",
    "_refine_ls_wR_factor_ref",
    "_refine_ls_goodness_of_fit_ref",
    "_refine_ls_number_parameters",
    "_refine_ls_number_restraints",
    "_refine_diff_density_max",
    "_refine_diff_density_min",
):
    print(tag, value(tag))

st = gemmi.make_small_structure_from_block(block)
sites = list(st.sites)
hs = [site for site in sites if site.element.name == "H"]
print("cif_n_sites", len(sites))
print("cif_n_H_sites", len(hs))
print("cif_H_occ_sum", round(sum(float(site.occ) for site in hs), 5))

selected = {
    "C22", "C22B", "C36", "C36B", "C44", "C44B", "C28", "C28B",
    "N3", "C4", "C3", "N4",
}
for site in sites:
    if site.label in selected:
        print("site", site.label, site.element.name, "occ", round(float(site.occ), 5))

part = 0
part_h = []
fvar = []
atom_re = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s+(\d+)\s+[-+0-9.]", re.ASCII)
for raw in RES.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    fields = line.split()
    if fields and fields[0].upper() == "FVAR":
        fvar.extend(fields[1:])
    if fields and fields[0].upper() == "PART":
        try:
            part = int(float(fields[1]))
        except (IndexError, ValueError):
            part = 0
        continue
    match = atom_re.match(line)
    if match and match.group(1).upper().startswith("H") and part != 0:
        part_h.append((match.group(1), part))

print("res_FVAR", " ".join(fvar))
print("res_n_H_in_nonzero_PART", len(part_h))
print("res_PART_H_counts", {p: sum(q == p for _, q in part_h) for p in sorted({q for _, q in part_h})})
