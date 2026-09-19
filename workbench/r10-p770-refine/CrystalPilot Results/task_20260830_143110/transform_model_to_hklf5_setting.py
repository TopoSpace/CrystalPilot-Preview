from __future__ import annotations

from pathlib import Path

from cctbx import sgtbx
from iotbx import cif


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".crystalpilot" / "refine" / "nodes" / "n0012" / "model.cif"
OUTPUT = ROOT / "CrystalPilot Results" / "task_20260830_143110" / "hklf5_work" / "model_hklf5_setting.cif"

# From the direct reflection pairing:
#   (h5, k5, l5) = (-h4, -k4, h4+k4+l4)
# CCTBX's coordinate-form change-of-basis operator is the inverse transpose;
# this matrix is involutory, giving (x5,y5,z5)=(-x4+z4,-y4+z4,z4).
cb_op = sgtbx.change_of_basis_op("-x+z,-y+z,z")

structures = cif.reader(file_path=str(SOURCE)).build_crystal_structures()
source_structure = next(iter(structures.values()))
transformed = source_structure.change_basis(cb_op)

block = transformed.as_cif_block()
block["_audit_creation_method"] = (
    "CCTBX exact unimodular change of basis from HKLF4 to TWINABS HKLF5 setting; "
    "h5=-h4, k5=-k4, l5=h4+k4+l4"
)
# The importer uses the conventional CIF 1.1 tag spellings.  CCTBX emits
# DDLm dotted aliases for these scalar items, so include both representations.
a, b, c, alpha, beta, gamma = transformed.unit_cell().parameters()
block["_cell_length_a"] = f"{a:.6f}"
block["_cell_length_b"] = f"{b:.6f}"
block["_cell_length_c"] = f"{c:.6f}"
block["_cell_angle_alpha"] = f"{alpha:.6f}"
block["_cell_angle_beta"] = f"{beta:.6f}"
block["_cell_angle_gamma"] = f"{gamma:.6f}"
block["_symmetry_space_group_name_H-M"] = "P -1"
block["_symmetry_Int_Tables_number"] = "2"
document = cif.model.cif()
document["p770_hklf5_setting"] = block
with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
    document.show(out=stream)

print(f"source_cell={source_structure.unit_cell().parameters()}")
print(f"transformed_cell={transformed.unit_cell().parameters()}")
print(f"n_scatterers={len(transformed.scatterers())}")
print(f"space_group={transformed.space_group_info()}")
print(f"output={OUTPUT}")
