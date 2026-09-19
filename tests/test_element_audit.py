"""audit_element_assignment (r13 backflow): evidence, not verdicts.

The r13 grade differentiator was six C/N misassignments (lattice benzene
read as pyridine + five ligand sites). The audit tool must surface the
three evidence channels - idle typed-N/O environment, Ueq-vs-neighbour
direction, bond-length swap comparison - without ever mutating the model.
"""
import math
from types import SimpleNamespace

from cctbx import crystal, xray

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.refine.tools_chemaudit import AuditElementAssignment
from crystalpilot.tools.base import ToolContext


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _session(atoms):
    cs = crystal.symmetry(unit_cell=(15, 15, 15, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for label, el, cart, u in atoms:
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=u, occupancy=1.0))
    xs.scattering_type_registry(table="it1992")
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = cs
    return ses


def _ring(n_label="N1", n_u=0.05, c_u=0.05):
    """Regular 1.39-A hexagon at z=5: one N + five C, no hydrogens."""
    atoms = []
    for k in range(6):
        ang = math.radians(60 * k)
        cart = (5 + 1.39 * math.cos(ang), 5 + 1.39 * math.sin(ang), 5.0)
        if k == 0:
            atoms.append((n_label, "N", cart, n_u))
        else:
            atoms.append((f"C{k}", "C", cart, c_u))
    return atoms


def _run(ses, **params):
    tool = AuditElementAssignment(SimpleNamespace(session=ses))
    return tool.run(ToolContext(store=_Store(), session=ses), **params)


def test_idle_ring_nitrogen_flagged():
    # lattice "pyridine" whose N does nothing - the r13 benzene tell
    r = _run(_session(_ring()))
    assert r.ok
    assert "N1" in r.summary["idle_n_o"]
    row = next(a for a in r.summary["atoms"] if a["label"] == "N1")
    assert "苯" in row["environment_note"]
    # swap evidence rides along: aromatic 1.39 A fits C-C if N1 were C
    assert any("C-C" in f for b in row["bonds"] for f in b["if_swapped"])


def test_protonated_or_contacted_nitrogen_not_flagged():
    # N-H: the lone pair is spoken for
    atoms = _ring()
    n_cart = atoms[0][2]
    atoms.append(("H1", "H",
                  (n_cart[0] + 1.0, n_cart[1], n_cart[2]), 0.06))
    r = _run(_session(atoms))
    assert r.summary["idle_n_o"] == []

    # acceptor contact from a separate molecule at 2.9 A along +x
    atoms2 = _ring()
    n2 = atoms2[0][2]
    atoms2.append(("O99", "O", (n2[0] + 2.9, n2[1], n2[2]), 0.05))
    r2 = _run(_session(atoms2))
    assert "N1" not in r2.summary["idle_n_o"]
    # ...though the added O99 itself is now the idle one (no contact back
    # counted for it? it has the same 2.9 A contact) - it must NOT appear
    # either, the contact is symmetric
    assert "O99" not in r2.summary["idle_n_o"]


def test_intra_ring_meta_para_not_counted_as_contacts():
    # ring meta (2.4 A) and para (2.78 A) neighbours are torsion geometry;
    # without the <=3-bond exclusion every ring N would look "contacted"
    r = _run(_session(_ring()))
    row = next(a for a in r.summary["atoms"] if a["label"] == "N1")
    assert row["acceptor_contacts_le_3.3A"] == 0


def test_ueq_direction_notes():
    # chain C-C-C, middle atom's ADP inflated 3x -> typed-too-heavy note
    chain = [("C1", "C", (4.0, 5.0, 5.0), 0.03),
             ("N9", "N", (5.5, 5.0, 5.0), 0.09),
             ("C3", "C", (7.0, 5.0, 5.0), 0.03)]
    r = _run(_session(chain))
    assert "N9" in r.summary["ueq_high_vs_neighbours"]
    row = next(a for a in r.summary["atoms"] if a["label"] == "N9")
    assert "轻" in row["ueq_note"]

    chain2 = [("C1", "C", (4.0, 5.0, 5.0), 0.05),
              ("C2", "C", (5.5, 5.0, 5.0), 0.02),
              ("C3", "C", (7.0, 5.0, 5.0), 0.05)]
    r2 = _run(_session(chain2), elements=["C"])
    assert "C2" in r2.summary["ueq_low_vs_neighbours"]
    row2 = next(a for a in r2.summary["atoms"] if a["label"] == "C2")
    assert "重" in row2["ueq_note"]


def test_read_only_and_caveat():
    ses = _session(_ring())
    before = [(sc.label, sc.scattering_type, tuple(sc.site))
              for sc in ses.model.scatterers()]
    r = _run(ses)
    after = [(sc.label, sc.scattering_type, tuple(sc.site))
             for sc in ses.model.scatterers()]
    assert before == after
    assert "不能" in r.summary["caveat"]
