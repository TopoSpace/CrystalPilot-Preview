"""Read-only CIF/RES consistency audit for the round-7 deliverables."""

from collections import Counter
from pathlib import Path
import re

import gemmi


HERE = Path(__file__).resolve().parent
CIF = HERE / "final.cif"
RES = HERE / "final.res"


def clean_number(value):
    if value is None:
        return None
    text = str(value).strip()
    return re.sub(r"\([^)]*\)$", "", text)


doc = gemmi.cif.read_file(str(CIF))
block = doc.sole_block()

for tag in (
    "_chemical_formula_moiety",
    "_refine_ls_R_factor_gt",
    "_refine_ls_R_factor_all",
    "_refine_ls_wR_factor_ref",
    "_refine_ls_goodness_of_fit_ref",
    "_refine_ls_number_parameters",
    "_refine_ls_number_restraints",
    "_refine_ls_shift/su_max",
    "_refine_diff_density_max",
    "_refine_diff_density_min",
):
    print(tag, block.find_value(tag))

st = gemmi.make_small_structure_from_block(block)
cif_sites = list(st.sites)
cif_labels = [site.label for site in cif_sites]
cif_h = [site for site in cif_sites if site.element.name == "H"]
print("cif_n_sites", len(cif_sites))
print("cif_n_H_sites", len(cif_h))
print("cif_H_occ_sum", round(sum(float(site.occ) for site in cif_h), 5))
print("cif_has_H0", "H0" in cif_labels)
print("cif_has_H16B", "H16B" in cif_labels)

selected = {"C22B", "C36B", "C44B", "C28B", "H0", "H16B"}
for site in cif_sites:
    if site.label in selected:
        print("cif_site", site.label, site.element.name, round(float(site.occ), 5))

lines = RES.read_text(encoding="utf-8").splitlines()
sfac = []
fvar = []
part = 0
res_atoms = []
part_h = []
for raw in lines:
    line = raw.strip()
    fields = line.split()
    if not fields:
        continue
    key = fields[0].upper()
    if key == "SFAC":
        sfac = fields[1:]
        continue
    if key == "FVAR":
        fvar.extend(fields[1:])
        continue
    if key == "PART":
        try:
            part = int(float(fields[1]))
        except (IndexError, ValueError):
            part = 0
        continue
    if len(fields) < 7 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", fields[0]):
        continue
    try:
        sfac_index = int(fields[1])
        float(fields[2]); float(fields[3]); float(fields[4]); float(fields[5]); float(fields[6])
    except (ValueError, IndexError):
        continue
    if not (1 <= sfac_index <= len(sfac)):
        continue
    label = fields[0]
    element = sfac[sfac_index - 1]
    res_atoms.append((label, element, part))
    if element.upper() == "H" and part != 0:
        part_h.append((label, part))

res_labels = [label for label, _, _ in res_atoms]
res_h_labels = [label for label, element, _ in res_atoms if element.upper() == "H"]
print("res_n_sites", len(res_atoms))
print("res_n_H_sites", len(res_h_labels))
print("res_has_H0", "H0" in res_labels)
print("res_has_H16B", "H16B" in res_labels)
print("res_FVAR", " ".join(fvar))
print("res_n_H_in_nonzero_PART", len(part_h))
print("res_PART_H_counts", dict(sorted(Counter(p for _, p in part_h).items())))
print("labels_only_in_CIF", sorted(set(cif_labels) - set(res_labels)))
print("labels_only_in_RES", sorted(set(res_labels) - set(cif_labels)))
print("duplicate_CIF_labels", sorted(label for label, n in Counter(cif_labels).items() if n > 1))
print("duplicate_RES_labels", sorted(label for label, n in Counter(res_labels).items() if n > 1))
