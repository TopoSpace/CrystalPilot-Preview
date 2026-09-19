import json
import numpy as np
from dxtbx.model.experiment_list import ExperimentList

el = ExperimentList.from_file(
    "H:/CrystalPilot/workdir/onitwin_2latt/indexed.expt", check_format=False)
uniq = list(dict.fromkeys(e.crystal for e in el))
print("n_experiments", len(el), "n_unique_crystals", len(uniq))
A1 = np.array(uniq[0].get_A()).reshape(3, 3)
U1 = np.array(uniq[0].get_U()).reshape(3, 3)
U2 = np.array(uniq[1].get_U()).reshape(3, 3)
R = U2 @ U1.T
T = np.linalg.inv(A1) @ R @ A1     # twin law in hkl space
np.set_printoptions(suppress=True, precision=4)
print("hkl-space twin law T = A1^-1 R A1 =\n", T)
Tr = np.round(T)
dev = float(np.abs(T - Tr).max())
print("nearest integer matrix:\n", Tr, "\nmax |T-round(T)| =", round(dev, 4))
print("det T =", round(float(np.linalg.det(T)), 4))
cell = uniq[0].get_unit_cell().parameters()
print("cell:", [round(x, 3) for x in cell])
json.dump({"cell_P1": [round(x, 4) for x in cell],
           "twin_law_hkl": [[round(x, 4) for x in r_] for r_ in T.tolist()],
           "nearest_integer": [[int(x) for x in r_] for r_ in Tr.tolist()],
           "max_dev_from_integer": round(dev, 4),
           "lab_rotation_deg": 179.992,
           "lab_axis": [0.919, 0.254, 0.301],
           "pct_indexed_two_lattices": "99.0-99.4 per sweep",
           "pct_indexed_one_lattice": 86.9},
          open("H:/CrystalPilot/workdir/onitwin_2latt/twin_law.json", "w"),
          indent=1)
print("saved twin_law.json")
