"""Disorder (PART/FVAR) + twin (TWIN/BASF) tests: writer/parser round-trip,
flag plumbing, and a real-SHELXL integration pass on the committed demo
project."""
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.io.shelx_model import load_res_model
from crystalpilot.io.shelx_writer import ShelxModel, write_res
from crystalpilot.refine.nodes import (disorder_from_parsed,
                                       serialization_extras)

DEMO = REPO / "workbench" / "demo-live-sjtu9"
SHELXL = REPO / "vendor" / "shelx" / "shelxl.exe"


def _toy_disordered():
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=(10, 11, 12, 90, 95, 90),
                          space_group_symbol="P 21/c")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site, occ in (
            ("CU1", "Cu", (0.25, 0.25, 0.25), 1.0),
            ("O1A", "O", (0.40, 0.30, 0.20), 0.6),
            ("O1B", "O", (0.44, 0.34, 0.22), 0.4)):
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                        occupancy=occ, scattering_type=el))
    return xs


class TestRoundTrip:
    def test_part_fvar_twin_roundtrip(self, tmp_path):
        m = ShelxModel(
            xray_structure=_toy_disordered(), wavelength=0.71073, z=4,
            fvars=[0.6],
            sof_codes={"O1A": 21.0, "O1B": -21.0},
            parts={"O1A": 1, "O1B": 2},
            twin={"matrix": [-1, 0, 0, 0, -1, 0, 0, 0, -1], "n": 2,
                  "basf": [0.35]})
        write_res(m, tmp_path / "t.res")
        parsed = load_res_model(tmp_path / "t.res")
        assert parsed.parts == {"O1A": 1, "O1B": 2}
        assert parsed.sof_codes == {"O1A": 21.0, "O1B": -21.0}
        assert parsed.twin["matrix"][:3] == [-1.0, 0.0, 0.0]
        assert parsed.basf == [0.35]
        assert parsed.fvar_extra == [0.6]
        occ = {sc.label: round(sc.occupancy, 3)
               for sc in parsed.structure.scatterers()}
        # iotbx applied the FVAR coding to effective occupancies
        assert occ["O1A"] == 0.6 and occ["O1B"] == 0.4

    def test_flags_to_extras_to_parsed_inverse(self, tmp_path):
        flags = {"disorder_groups": [
            {"fvar_index": 2, "value": 0.6, "members": [
                {"label": "O1A", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "O1B", "part": 2, "sign": -1, "mult": 1.0}]}],
            "twin": {"matrix": [-1, 0, 0, 0, -1, 0, 0, 0, -1], "n": 2,
                     "basf": [0.35]}}
        extras = serialization_extras(flags)
        assert extras["fvars"] == [0.6]
        assert extras["sof_codes"] == {"O1A": 21.0, "O1B": -21.0}
        m = ShelxModel(xray_structure=_toy_disordered(), z=4, **extras)
        write_res(m, tmp_path / "t.res")
        dg, twin = disorder_from_parsed(load_res_model(tmp_path / "t.res"))
        assert len(dg) == 1 and dg[0]["fvar_index"] == 2
        assert dg[0]["value"] == pytest.approx(0.6)
        members = {m["label"]: m for m in dg[0]["members"]}
        assert members["O1A"]["sign"] == 1 and members["O1A"]["part"] == 1
        assert members["O1B"]["sign"] == -1 and members["O1B"]["part"] == 2
        assert twin["basf"] == [0.35]


@pytest.fixture(scope="module")
def demo_copy(tmp_path_factory):
    if not (DEMO / "start.res").exists():
        pytest.skip("demo project not present")
    d = tmp_path_factory.mktemp("disorder-proj") / "proj"
    shutil.copytree(DEMO, d, ignore=shutil.ignore_patterns(
        "uploads", "scene-cache", "checkcif", "runs", "specialists",
        "CrystalPilot Results"))
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(d)
    p.open()
    # the committed demo predates data revisions: its nodes carry no
    # data_revision and every reflection tool refuses them until the HKL
    # is bound explicitly (2026-09-08) - bind it the way a user would
    from helpers_binding import bind_legacy_project
    bind_legacy_project(p)
    return p


class TestModelDisorder:
    def test_split_commit_and_shelxl(self, demo_copy):
        p = demo_copy
        ses = p.session
        target = next((sc.label for sc in ses.model.scatterers()
                       if sc.flags.use_u_aniso()
                       and sc.weight_without_occupancy() >= 0.999
                       and sc.scattering_type.strip().upper() != "H"), None)
        assert target, "demo model must have a general-position aniso atom"
        n_before = ses.model.scatterers().size()
        r = p.invoke_tool("model_disorder", {"atoms": [target],
                                             "separation": 0.5})
        assert r.ok, r.error
        assert ses.model.scatterers().size() == n_before + 1
        node = r.summary["node"]
        res_text = (p.nodes.node_dir(node) / "model.res").read_text()
        assert "PART 1" in res_text and "PART 2" in res_text
        assert " 21.00000" in res_text and "-21.00000" in res_text
        # FVAR carries scale + the disorder variable
        fvar_line = next(ln for ln in res_text.splitlines()
                         if ln.startswith("FVAR"))
        assert len(fvar_line.split()) == 3

        # checkout the node again: linkage must survive the round-trip
        chk = p.invoke_tool("checkout", {"node": node})
        assert chk.ok
        dg = p.session.flags.get("disorder_groups")
        assert dg and dg[0]["fvar_index"] == 2

        # smtbx refine still runs (occupancies held)
        rr = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1})
        assert rr.ok, rr.error

        if not SHELXL.exists():
            pytest.skip("vendor shelxl not present")
        rs = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 2})
        assert rs.ok, rs.error
        assert rs.summary.get("disorder_occupancies"), \
            "adopt must report refined FVAR occupancies"


def _cccm_session(o5_aniso: str | None = None, o5_occ: float = 1.0,
                  n3_occ: float = 1.0):
    """The pa1 cu shape: Cccm, a Cu on a general position and the axial
    ligand atom O5 on the z=1/2 mirror (multiplicity factor 0.5) with a
    second mirror atom N3 1.2 A away in-plane. o5_aniso='normal' puts the
    ADP major axis perpendicular to the mirror, 'in_plane' along a."""
    from types import SimpleNamespace

    from cctbx import adptbx, crystal, xray
    cs = crystal.symmetry(unit_cell=(18.0, 26.0, 14.0, 90, 90, 90),
                          space_group_symbol="C c c m")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    xs.add_scatterer(xray.scatterer(label="CU1", site=(0.10, 0.20, 0.30),
                                    u=0.02, scattering_type="Cu"))
    xs.add_scatterer(xray.scatterer(label="O5", site=(0.05, 0.29, 0.5),
                                    u=0.05, occupancy=o5_occ,
                                    scattering_type="O"))
    xs.add_scatterer(xray.scatterer(label="N3", site=(0.11, 0.31, 0.5),
                                    u=0.05, occupancy=n3_occ,
                                    scattering_type="N"))
    if o5_aniso:
        sc = xs.scatterers()[1]
        u = ((0.03, 0.03, 0.09, 0, 0, 0) if o5_aniso == "normal"
             else (0.09, 0.03, 0.03, 0, 0, 0))
        sc.u_star = adptbx.u_cart_as_u_star(uc, u)
        sc.flags.set_use_u_aniso(True)
    return SimpleNamespace(model=xs, flags={}, dataset=None)


def _run_disorder(ses, **params):
    from types import SimpleNamespace

    from crystalpilot.refine.tools_disorder import ModelDisorder
    return ModelDisorder(None).run(SimpleNamespace(session=ses), **params)


def _res_text(ses) -> str:
    from crystalpilot.io.shelx_writer import write_res_text
    m = ShelxModel(xray_structure=ses.model, wavelength=0.71073, z=8,
                   **serialization_extras(ses.flags))
    return write_res_text(m)[0]


class TestSpecialPositionDisorder:
    """pa1 batch: all 9 cu runs asked model_disorder to split the
    paddlewheel axial atom on the Cccm mirror and were refused ("sits on a
    special position ... edit_atoms(action='move') first"); 8/9 passed a
    second site on the same mirror, one passed an existing atom's site
    (cu-l2-r1 N2 -> N3), one used the ADP axis (cu-l1-r2). None followed
    the hint, two faked it with set_occupancy 0.5 (no PART, no FVAR)."""

    def test_in_plane_second_site_keeps_multiplicity_and_conserves_count(
            self, tmp_path):
        ses = _cccm_session()
        r = _run_disorder(ses, atoms=["O5"],
                          second_sites={"O5": [0.02, 0.27, 0.5]})
        assert r.ok, r.error
        split = r.summary["split"][0]
        assert split["mode"] == "two_site" and split["b"] == "O5B"
        assert split["part"] == {"a": 1, "b": 2}
        assert split["total_sof"] == pytest.approx(0.5)
        assert "20.50000" in split["sof_written"]["a"]
        assert "-20.50000" in split["sof_written"]["b"]
        scs = {sc.label: sc for sc in ses.model.scatterers()}
        # both components stay on the mirror: chemical occupancy 0.5 each,
        # weights 0.25 + 0.25 = the original mirror atom's 0.5
        assert scs["O5"].weight_without_occupancy() == pytest.approx(0.5)
        assert scs["O5B"].weight_without_occupancy() == pytest.approx(0.5)
        assert scs["O5"].weight() + scs["O5B"].weight() == pytest.approx(0.5)
        members = {m["label"]: m for m in
                   ses.flags["disorder_groups"][0]["members"]}
        assert members["O5"]["mult"] == pytest.approx(0.5)
        assert members["O5B"]["mult"] == pytest.approx(0.5)
        txt = _res_text(ses)
        assert " 20.50000" in txt and "-20.50000" in txt
        assert "PART 1" in txt and "PART 2" in txt
        # the message states what was written - nothing to hand-edit
        msg = r.summary["message"]
        assert "multiplicity factor 0.5" in msg and "sof 20.50000" in msg
        assert "PART 1" in msg and "PART 2" in msg
        # SHELX round trip: iotbx re-derives the chemical occupancies
        (tmp_path / "t.res").write_text(txt)
        parsed = load_res_model(tmp_path / "t.res")
        occ = {sc.label: round(sc.occupancy, 4)
               for sc in parsed.structure.scatterers()}
        assert occ["O5"] == 0.5 and occ["O5B"] == 0.5
        dg, _ = disorder_from_parsed(parsed)
        assert {m["label"]: m["mult"] for m in dg[0]["members"]} == {
            "O5": 0.5, "O5B": 0.5}

    def test_existing_atom_at_second_site_is_linked_as_part_b(self):
        # cu-l2-r1: second_sites[N2] was N3's exact site (PLAT374 pair)
        ses = _cccm_session()
        r = _run_disorder(ses, atoms=["O5"],
                          second_sites={"O5": [0.11, 0.31, 0.5]})
        assert r.ok, r.error
        assert ses.model.scatterers().size() == 3      # nothing added
        split = r.summary["split"][0]
        assert split["b"] == "N3" and split["b_is_existing_atom"]
        assert "existing atom linked" in r.summary["message"]
        members = {m["label"]: m for m in
                   ses.flags["disorder_groups"][0]["members"]}
        assert members["N3"]["part"] == 2 and members["N3"]["sign"] == -1
        scs = {sc.label: sc for sc in ses.model.scatterers()}
        # the pair holds ONE atom's budget (O5's sof 0.5); N3's own full
        # occupancy is replaced by its share and the message says so
        assert scs["O5"].weight() + scs["N3"].weight() == pytest.approx(0.5)
        assert "N3's own occupancy 1 is replaced" in r.summary["message"]

    def test_two_partial_partners_sum_their_budget(self):
        # cu-l3-r2 workaround state: set_occupancy 0.5 on both first
        ses = _cccm_session(o5_occ=0.5, n3_occ=0.5)
        r = _run_disorder(ses, atoms=["O5"],
                          second_sites={"O5": [0.11, 0.31, 0.5]})
        assert r.ok, r.error
        assert r.summary["split"][0]["total_sof"] == pytest.approx(0.5)
        assert "both already partial" in r.summary["split"][0]["total_from"]
        scs = {sc.label: sc for sc in ses.model.scatterers()}
        assert scs["O5"].weight() + scs["N3"].weight() == pytest.approx(0.5)

    def test_off_mirror_site_becomes_symmetry_image_single_atom(self):
        ses = _cccm_session()
        r = _run_disorder(ses, atoms=["O5"], occupancy=0.6,
                          second_sites={"O5": [0.05, 0.29, 0.5 + 0.35 / 14]})
        assert r.ok, r.error
        split = r.summary["split"][0]
        assert split["mode"] == "symmetry_image" and split["b"] is None
        assert ses.model.scatterers().size() == 3      # image is not an atom
        assert r.summary["fvar_index"] is None
        assert not ses.flags.get("disorder_groups")
        assert ses.flags["parts_extra"] == {"O5": -1}
        assert split["part"] == {"a": -1}
        assert split["n_components"] == 2
        assert "10.50000" in split["sof_written"]["a"]
        assert "occupancy=0.6 ignored" in split["note"]
        sc = ses.model.scatterers()[1]
        # site symmetry re-derived: general position, occupancy 0.5 fixed,
        # weight 0.5 = the original mirror atom
        assert sc.weight_without_occupancy() == pytest.approx(1.0)
        assert sc.occupancy == pytest.approx(0.5)
        assert not ses.model.site_symmetry_table().is_special_position(1)
        assert ses.model.site_symmetry_table().indices().size() == 3
        txt = _res_text(ses)
        assert "PART -1" in txt and " 10.50000" in txt
        assert "FVAR 1.00000\n" in txt                  # no free variable
        msg = r.summary["message"]
        assert "symmetry image" in msg and "PART -1" in msg
        assert "0.35 A off" in msg

    def test_image_mode_refuses_sites_that_would_merge_back(self):
        ses = _cccm_session()
        before = [(sc.label, tuple(sc.site), sc.occupancy,
                   sc.weight_without_occupancy())
                  for sc in ses.model.scatterers()]
        # 0.22 A off the mirror: image 0.44 A away < 0.5 A merge distance
        r = _run_disorder(ses, atoms=["O5"],
                          second_sites={"O5": [0.05, 0.29, 0.5 + 0.22 / 14]})
        assert not r.ok
        assert "symmetry image" in r.error and "snapped back" in r.error
        after = [(sc.label, tuple(sc.site), sc.occupancy,
                  sc.weight_without_occupancy())
                 for sc in ses.model.scatterers()]
        assert before == after and not ses.flags

    def test_special_atom_too_close_site_names_the_special_position(self):
        ses = _cccm_session()
        r = _run_disorder(ses, atoms=["O5"],
                          second_sites={"O5": [0.05, 0.29, 0.5 + 0.15 / 14]})
        assert not r.ok
        assert "special position x,y,1/2" in r.error
        assert "image becomes the partner" in r.error

    def test_isotropic_special_atom_message_explains_both_routes(self):
        ses = _cccm_session()
        r = _run_disorder(ses, atoms=["O5"])
        assert not r.ok
        assert "isotropic" in r.error and "site symmetry m" in r.error
        assert "in-plane two-site split" in r.error
        assert "symmetry image becomes the partner" in r.error

    def test_adp_axis_normal_to_mirror_gives_image_mode(self):
        ses = _cccm_session(o5_aniso="normal")
        r = _run_disorder(ses, atoms=["O5"], separation=0.65)
        assert r.ok, r.error
        split = r.summary["split"][0]
        assert split["mode"] == "symmetry_image"
        assert split["d_ab"] == pytest.approx(0.65, abs=0.01)
        assert ses.flags["parts_extra"] == {"O5": -1}
        assert ses.model.scatterers()[1].weight() == pytest.approx(0.5)

    def test_adp_axis_in_plane_gives_two_mirror_sites(self):
        ses = _cccm_session(o5_aniso="in_plane")
        r = _run_disorder(ses, atoms=["O5"], separation=0.65)
        assert r.ok, r.error
        split = r.summary["split"][0]
        assert split["mode"] == "two_site" and split["part"] == {"a": 1,
                                                                  "b": 2}
        assert split["d_ab"] == pytest.approx(0.65, abs=0.01)
        scs = {sc.label: sc for sc in ses.model.scatterers()}
        for lb in ("O5", "O5B"):
            assert scs[lb].site[2] == pytest.approx(0.5)     # still on m
            assert scs[lb].weight_without_occupancy() == pytest.approx(0.5)
        assert " 20.50000" in _res_text(ses)

    def test_image_atom_cannot_be_split_again(self):
        ses = _cccm_session(o5_aniso="normal")
        assert _run_disorder(ses, atoms=["O5"]).ok
        r = _run_disorder(ses, atoms=["O5"])
        assert not r.ok and "already in PART -1" in r.error

    def test_image_part_number_avoids_existing_group_parts(self):
        ses = _cccm_session(o5_aniso="normal")
        ses.flags["disorder_groups"] = [{"fvar_index": 2, "value": 0.5,
                                         "members": [
            {"label": "X1", "part": 1, "sign": 1, "mult": 1.0},
            {"label": "X1B", "part": 2, "sign": -1, "mult": 1.0}]}]
        r = _run_disorder(ses, atoms=["O5"])
        assert r.ok, r.error
        # same |n| as a PART 1/2 group would bond across the groups
        assert ses.flags["parts_extra"] == {"O5": -3}
        assert "PART -3" in r.summary["message"]

    def test_general_atom_split_conserves_partial_occupancy(self):
        ses = _cccm_session()
        ses.model.scatterers()[0].occupancy = 0.8
        r = _run_disorder(ses, atoms=["CU1"],
                          second_sites={"CU1": [0.10, 0.20, 0.30 + 0.6 / 14]})
        assert r.ok, r.error
        split = r.summary["split"][0]
        assert split["total_sof"] == pytest.approx(0.8)
        assert split["part"] == {"a": 1, "b": 2}
        assert serialization_extras(ses.flags)["sof_codes"] == {
            "CU1": pytest.approx(20.8), "CU1B": pytest.approx(-20.8)}
        scs = {sc.label: sc for sc in ses.model.scatterers()}
        assert scs["CU1"].weight() + scs["CU1B"].weight() == pytest.approx(0.8)

    def test_general_component_near_its_own_image_gets_negative_part(self):
        from cctbx import xray
        ses = _cccm_session()
        # C7 at a general position 0.9 A off the mirror (image 1.8 A away)
        ses.model.add_scatterer(xray.scatterer(
            label="C7", site=(0.30, 0.10, 0.5 + 0.9 / 14), u=0.04,
            scattering_type="C"))
        r = _run_disorder(ses, atoms=["C7"],
                          second_sites={"C7": [0.30, 0.10, 0.5 + 1.5 / 14]})
        assert r.ok, r.error
        split = r.summary["split"][0]
        assert split["part"] == {"a": -1, "b": 2}
        assert split["total_sof"] == pytest.approx(1.0)
        assert split["sof_written"]["b"].startswith("-21.00000")
        txt = _res_text(ses)
        assert "PART -1" in txt and " 21.00000" in txt and "-21.00000" in txt


class TestSpecialPositionDemoProject:
    """Full plumbing on the committed demo (I41/amd, four atoms on special
    positions): node commit, checkout, smtbx refine and SHELXL adopt must
    all carry the multiplicity-scaled codes / negative PART through."""

    @staticmethod
    def _free_special_atom(p):
        ses = p.session
        taken = {m["label"].upper() for g in
                 (ses.flags.get("disorder_groups") or [])
                 for m in g.get("members", ())}
        taken |= {str(k).upper() for k in (ses.flags.get("parts_extra")
                                           or {})}
        return next((sc for sc in ses.model.scatterers()
                     if sc.weight_without_occupancy() < 0.999
                     and sc.scattering_type.strip().upper() != "H"
                     and sc.label.upper() not in taken), None)

    @staticmethod
    def _shifted_sites(xs, sc, shift_a):
        uc = xs.unit_cell()
        for axis in range(3):
            cart = [0.0, 0.0, 0.0]
            cart[axis] = shift_a
            d = uc.fractionalize(tuple(cart))
            yield tuple(sc.site[k] + d[k] for k in range(3))

    def test_in_plane_split_commits_checkouts_and_adopts(self, demo_copy):
        p = demo_copy
        ses = p.session
        xs = ses.model
        sc = self._free_special_atom(p)
        assert sc is not None, "demo model must have a special-position atom"
        label, mult = sc.label, sc.multiplicity()
        # a second site on the SAME special position, clear of other atoms
        site_b = None
        for cand in self._shifted_sites(xs, sc, 0.7):
            ss = xs.site_symmetry(cand)
            if ss.multiplicity() != mult:
                continue
            if min(xs.unit_cell().distance(ss.exact_site(), tuple(o.site))
                   for o in xs.scatterers() if o.label != label) < 0.5:
                continue
            site_b = ss.exact_site()
            break
        assert site_b is not None
        n_before = xs.scatterers().size()
        r = p.invoke_tool("model_disorder", {
            "atoms": [label], "second_sites": {label: list(site_b)}})
        assert r.ok, r.error
        assert r.summary["split"][0]["mode"] == "two_site"
        assert ses.model.scatterers().size() == n_before + 1
        k = r.summary["fvar_index"]
        w = 1.0 * mult / xs.space_group().order_z()
        code = f"{10 * k + w:.5f}"
        node = r.summary["node"]
        res_text = (p.nodes.node_dir(node) / "model.res").read_text()
        assert f" {code}" in res_text and f"-{code}" in res_text
        assert "PART 1" in res_text and "PART 2" in res_text

        chk = p.invoke_tool("checkout", {"node": node})
        assert chk.ok, chk.error
        grp = next(g for g in p.session.flags["disorder_groups"]
                   if g["fvar_index"] == k)
        assert all(m["mult"] == pytest.approx(w) for m in grp["members"])
        rr = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1})
        assert rr.ok, rr.error

        if not SHELXL.exists():
            pytest.skip("vendor shelxl not present")
        rs = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 2})
        assert rs.ok, rs.error
        assert f"fvar{k}" in rs.summary["disorder_occupancies"]
        grp = next(g for g in p.session.flags["disorder_groups"]
                   if g["fvar_index"] == k)
        # SHELXL wrote the multiplicity-scaled codes back unchanged
        assert all(m["mult"] == pytest.approx(w) for m in grp["members"])

    def test_off_special_site_commits_single_atom_negative_part(
            self, demo_copy):
        p = demo_copy
        ses = p.session
        xs = ses.model
        sc = self._free_special_atom(p)
        assert sc is not None
        label, mult = sc.label, sc.multiplicity()
        sg = xs.space_group()
        site_b = None
        for cand in self._shifted_sites(xs, sc, 0.4):
            ss = xs.site_symmetry(cand)
            if ss.multiplicity() <= mult:
                continue
            d_img = min(xs.unit_cell().distance(cand, tuple(
                (sg(i) * cand)[j] - round((sg(i) * cand)[j] - cand[j])
                for j in range(3))) for i in range(1, sg.order_z()))
            if d_img > 0.6:
                site_b = cand
                break
        assert site_b is not None
        n_before = xs.scatterers().size()
        r = p.invoke_tool("model_disorder", {
            "atoms": [label], "second_sites": {label: list(site_b)}})
        assert r.ok, r.error
        split = r.summary["split"][0]
        assert split["mode"] == "symmetry_image"
        assert ses.model.scatterers().size() == n_before
        part = split["part"]["a"]
        assert part < 0
        total = split["total_sof"]
        node = r.summary["node"]
        res_text = (p.nodes.node_dir(node) / "model.res").read_text()
        assert f"PART {part}" in res_text
        assert f" {10 + total:.5f}" in res_text

        chk = p.invoke_tool("checkout", {"node": node})
        assert chk.ok, chk.error
        assert p.session.flags["parts_extra"].get(label.upper(),
                                                  p.session.flags[
                                                      "parts_extra"].get(
                                                      label)) == part
        moved = next(s for s in p.session.model.scatterers()
                     if s.label == label)
        assert moved.weight_without_occupancy() == pytest.approx(1.0)
        assert moved.weight() == pytest.approx(total)
        rr = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1})
        assert rr.ok, rr.error

        if not SHELXL.exists():
            pytest.skip("vendor shelxl not present")
        rs = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 2})
        assert rs.ok, rs.error
        # the loose negative PART survives the SHELXL round trip
        pe = p.session.flags.get("parts_extra") or {}
        assert pe.get(label.upper(), pe.get(label)) == part


class TestSetTwin:
    def test_inversion_refused_in_centric_group(self, demo_copy):
        r = demo_copy.invoke_tool("set_twin", {"law": "inversion"})
        assert not r.ok and "centrosymmetric" in r.error

    def test_suggest_no_candidates_for_holohedral(self, demo_copy):
        r = demo_copy.invoke_tool("set_twin", {"law": "suggest"})
        assert r.ok
        assert r.summary["candidates"] == []

    def test_matrix_twin_blocks_refine_until_removed(self, demo_copy):
        p = demo_copy
        bad = p.invoke_tool("set_twin", {"law": "matrix",
                                         "matrix": [2, 0, 0, 0, 1, 0,
                                                    0, 0, 1]})
        assert not bad.ok and "det" in bad.error
        r = p.invoke_tool("set_twin", {
            "law": "matrix", "basf": 0.2,
            "matrix": [0, 1, 0, 1, 0, 0, 0, 0, -1]})
        assert r.ok, r.error
        node = r.summary["node"]
        res_text = (p.nodes.node_dir(node) / "model.res").read_text()
        assert "TWIN 0 1 0 1 0 0 0 0 -1 2" in res_text
        assert "BASF 0.20000" in res_text
        rr = p.invoke_tool("refine", {"mode": "isotropic"})
        assert not rr.ok and "run_shelxl" in rr.error
        rm = p.invoke_tool("set_twin", {"law": "remove"})
        assert rm.ok and rm.summary.get("removed")
        rr2 = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1})
        assert rr2.ok, rr2.error


class TestMultiAtomSplitAtomicity:
    """p770 audit: multi-atom splits died with 'cannot read element from'
    (flex proxies invalidated by add_scatterer reallocation) and left
    half-mutated models; agent needed a no-op move between every split."""

    def _session_4c(self):
        from types import SimpleNamespace

        from cctbx import adptbx, crystal, xray
        cs = crystal.symmetry(unit_cell=(14, 14, 14, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()
        for k in range(4):
            sc = xray.scatterer(label=f"C{k+1}",
                                site=(0.1 + 0.2 * k, 0.3, 0.3),
                                u=0.04, occupancy=1.0, scattering_type="C")
            xs.add_scatterer(sc)
        # anisotropic ADPs so the split direction is defined
        for sc in xs.scatterers():
            sc.u_star = adptbx.u_cart_as_u_star(
                uc, (0.08, 0.03, 0.03, 0.0, 0.0, 0.0))
            sc.flags.set_use_u_aniso(True)
        ses = SimpleNamespace(model=xs, flags={}, dataset=None)
        return ses

    def test_four_atoms_in_one_call(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import ModelDisorder
        ses = self._session_4c()
        ctx = SimpleNamespace(session=ses)
        r = ModelDisorder(None).run(
            ctx, atoms=["C1", "C2", "C3", "C4"], occupancy=0.6)
        assert r.ok, r.error
        assert len(r.summary["split"]) == 4
        scs = list(ses.model.scatterers())
        assert len(scs) == 8
        # every B copy kept its element (the proxy bug read '' here)
        for sc in scs:
            assert sc.scattering_type.strip() == "C", sc.label
        labels = {sc.label for sc in scs}
        assert {"C1B", "C2B", "C3B", "C4B"} <= labels
        members = ses.flags["disorder_groups"][0]["members"]
        assert len(members) == 8

    def test_validation_failure_leaves_model_untouched(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import ModelDisorder
        ses = self._session_4c()
        ctx = SimpleNamespace(session=ses)
        before = [(sc.label, tuple(sc.site), sc.occupancy)
                  for sc in ses.model.scatterers()]
        # C4 gets an implausible second site -> phase-1 validation fails
        r = ModelDisorder(None).run(
            ctx, atoms=["C1", "C2", "C3", "C4"], occupancy=0.6,
            second_sites={"C4": (0.9, 0.9, 0.9)})
        assert not r.ok
        after = [(sc.label, tuple(sc.site), sc.occupancy)
                 for sc in ses.model.scatterers()]
        assert before == after      # no half-mutated dirty state
        assert not ses.flags.get("disorder_groups")


class TestInvertStructure:
    """Flack x ~ 1 remedy: proper change-of-hand, enantiomorph swap,
    guard rails."""

    @staticmethod
    def _xs(sg, sites):
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(9, 10, 11, 90, 90, 90),
                              space_group_symbol=sg)
        xs = xray.structure(crystal_symmetry=cs)
        for i, site in enumerate(sites):
            xs.add_scatterer(xray.scatterer(
                label=f"C{i + 1}", site=site, u=0.03, occupancy=1.0,
                scattering_type="C"))
        return xs

    @staticmethod
    def _ses(xs):
        from types import SimpleNamespace
        return SimpleNamespace(model=xs, flags={},
                               symmetry=xs.crystal_symmetry(), fo_sq=None)

    def _run(self, ses):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import InvertStructure
        return InvertStructure(None).run(SimpleNamespace(session=ses))

    def test_p21_roundtrip_negates_sites(self):
        sites = [(0.12, 0.23, 0.34), (0.41, 0.15, 0.62)]
        ses = self._ses(self._xs("P 1 21 1", sites))
        r = self._run(ses)
        assert r.ok, r.error
        assert not r.summary["group_changed"]
        assert "P 1 21 1" in r.summary["space_group"]
        inv = [tuple(sc.site) for sc in ses.model.scatterers()]
        for (a, b, c), (x, y, z) in zip(inv, sites):
            assert (round((a + x) % 1.0, 6) % 1.0,
                    round((b + y) % 1.0, 6) % 1.0,
                    round((c + z) % 1.0, 6) % 1.0) == (0.0, 0.0, 0.0)
        # round trip restores the original coordinates (mod lattice)
        r2 = self._run(ses)
        assert r2.ok
        back = [tuple(round(v % 1.0, 6) for v in sc.site)
                for sc in ses.model.scatterers()]
        assert back == [tuple(round(v % 1.0, 6) for v in s) for s in sites]

    def test_enantiomorphic_pair_swaps_group(self):
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(9, 9, 11, 90, 90, 120),
                              space_group_symbol="P 31")
        xs = xray.structure(crystal_symmetry=cs)
        xs.add_scatterer(xray.scatterer(label="C1", site=(0.1, 0.2, 0.3),
                                        u=0.03, scattering_type="C"))
        ses = self._ses(xs)
        r = self._run(ses)
        assert r.ok, r.error
        assert r.summary["group_changed"]
        assert "P 32" in r.summary["space_group"].replace("(", "").replace(
            ")", "")
        # session symmetry followed the swap
        assert ses.symmetry.space_group() == ses.model.space_group()

    def test_centric_refused(self):
        ses = self._ses(self._xs("P 21/c", [(0.1, 0.2, 0.3)]))
        r = self._run(ses)
        assert not r.ok and "centrosymmetric" in r.error

    def test_twin_active_refused(self):
        ses = self._ses(self._xs("P 1 21 1", [(0.1, 0.2, 0.3)]))
        ses.flags["twin"] = {"matrix": [-1, 0, 0, 0, -1, 0, 0, 0, -1],
                             "n": 2, "basf": [0.3]}
        r = self._run(ses)
        assert not r.ok and "set_twin" in r.error


class TestSecondSiteSymmetryFolding:
    """Process-audit T13: difference-map peaks live in the ASU, not next
    to the target - r14a (16.66 A) and r19 (12.97 A) both had to fold the
    candidate by hand. The tool folds through symmetry + lattice
    translations before judging now."""

    @staticmethod
    def _session_p_1():
        from types import SimpleNamespace

        from cctbx import adptbx, crystal, xray
        cs = crystal.symmetry(unit_cell=(14, 14, 14, 90, 90, 90),
                              space_group_symbol="P -1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()
        sc = xray.scatterer(label="C1", site=(0.10, 0.10, 0.10),
                            u=0.04, occupancy=1.0, scattering_type="C")
        xs.add_scatterer(sc)
        for s in xs.scatterers():
            s.u_star = adptbx.u_cart_as_u_star(
                uc, (0.08, 0.03, 0.03, 0.0, 0.0, 0.0))
            s.flags.set_use_u_aniso(True)
        return SimpleNamespace(model=xs, flags={}, dataset=None)

    def test_inversion_image_folds_into_range(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import ModelDisorder
        ses = self._session_p_1()
        ctx = SimpleNamespace(session=ses)
        # candidate given as the INVERTED image (plus a lattice shift):
        # -x,-y,-z of (0.15, 0.12, 0.10) then +1 on x
        r = ModelDisorder(None).run(
            ctx, atoms=["C1"], occupancy=0.6,
            second_sites={"C1": (0.85, -0.12, -0.10)})
        assert r.ok, r.error
        split = r.summary["split"][0]
        assert 0.2 <= split["d_ab"] <= 2.0
        assert "folded" in split.get("note", "")

    def test_truly_far_site_still_refused_with_best_distance(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import ModelDisorder
        ses = self._session_p_1()
        ctx = SimpleNamespace(session=ses)
        r = ModelDisorder(None).run(
            ctx, atoms=["C1"], occupancy=0.6,
            second_sites={"C1": (0.5, 0.5, 0.5)})
        assert not r.ok
        assert "no symmetry image comes closer" in r.error


class TestPeakSecondSite:
    """reg4-dbu (2026-09-04): the agent split the right ring atoms with the
    default 0.6 A ADP-axis displacement while the last difference map had
    peaks at 0.9-1.0 A from them, was told the drawn separation was below
    d_min, and abandoned the split. The map knows where B is."""

    def _session(self, peaks):
        from types import SimpleNamespace

        from cctbx import adptbx, crystal, xray
        cs = crystal.symmetry(unit_cell=(14, 14, 14, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()
        for k in range(3):
            xs.add_scatterer(xray.scatterer(
                label=f"C{k + 1}", site=(0.1 + 0.2 * k, 0.3, 0.3),
                u=0.04, occupancy=1.0, scattering_type="C"))
        for sc in xs.scatterers():
            sc.u_star = adptbx.u_cart_as_u_star(
                uc, (0.08, 0.03, 0.03, 0.0, 0.0, 0.0))
            sc.flags.set_use_u_aniso(True)
        return SimpleNamespace(model=xs, flags={"diff_map_peaks": peaks},
                               dataset=None)

    def test_b_lands_on_the_peak_that_belongs_to_the_atom(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import ModelDisorder
        # a 0.9 A peak along y from C2 (site 0.3,0.3,0.3), and a stronger
        # peak that belongs to C3 (nearest atom C3 at 0.5 A)
        peaks = [{"site": [0.3, 0.3 + 0.9 / 14, 0.3], "height": 0.9,
                  "nearest_atom": "C2", "nearest_d": 0.9},
                 {"site": [0.5, 0.3 + 0.5 / 14, 0.3], "height": 1.5,
                  "nearest_atom": "C3", "nearest_d": 0.5}]
        ses = self._session(peaks)
        r = ModelDisorder(None).run(SimpleNamespace(session=ses),
                                    atoms=["C1", "C2"], occupancy=0.7)
        assert r.ok, r.error
        rows = {row["a"]: row for row in r.summary["split"]}
        assert rows["C2"]["d_ab"] == pytest.approx(0.9, abs=0.01)
        assert "difference-map peak 0.90" in rows["C2"]["second_site_from"]
        # C1 has no peak of its own: ADP-axis fallback, and it says so
        assert rows["C1"]["d_ab"] == pytest.approx(0.6, abs=0.01)
        assert rows["C1"]["second_site_from"].startswith("ADP major axis")
        assert "no difference peak" in rows["C1"]["second_site_from"]
        assert "B from difference-map peak" in r.summary["message"]
        ev = {e["a"]: e for e in r.summary["evidence"]}
        assert ev["C2"]["second_site_from"].startswith("difference-map peak")
        assert ev["C2"]["carrier_u_eq_over_model_median"] == pytest.approx(1.0, abs=0.05)
        assert ev["C2"]["carrier_adp_max_over_min"] == pytest.approx(2.7, abs=0.1)
        assert "nearest_modelled_H_to_B" not in ev["C2"]     # no H in the model
        assert "unresolved second position" in ev["C2"]["reading"]

    def test_explicit_second_site_still_wins(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import ModelDisorder
        peaks = [{"site": [0.3, 0.3 + 0.9 / 14, 0.3], "height": 0.9,
                  "nearest_atom": "C2", "nearest_d": 0.9}]
        ses = self._session(peaks)
        r = ModelDisorder(None).run(
            SimpleNamespace(session=ses), atoms=["C2"],
            second_sites={"C2": [0.3, 0.3, 0.3 + 0.7 / 14]})
        assert r.ok, r.error
        row = r.summary["split"][0]
        assert row["d_ab"] == pytest.approx(0.7, abs=0.01)
        assert row["second_site_from"] == "second_sites (given)"

    def test_isotropic_atom_with_a_peak_is_no_longer_refused(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import ModelDisorder
        peaks = [{"site": [0.3, 0.3 + 0.8 / 14, 0.3], "height": 0.6,
                  "nearest_atom": "C2", "nearest_d": 0.8}]
        ses = self._session(peaks)
        for sc in ses.model.scatterers():
            sc.flags.set_use_u_aniso(False)
            sc.u_iso = 0.04
        r = ModelDisorder(None).run(SimpleNamespace(session=ses),
                                    atoms=["C2"])
        assert r.ok, r.error
        assert r.summary["split"][0]["d_ab"] == pytest.approx(0.8, abs=0.01)
        # ...while an isotropic atom with no peak still needs a direction
        r2 = ModelDisorder(None).run(SimpleNamespace(session=ses),
                                     atoms=["C1"])
        assert not r2.ok and "no defined split direction" in r2.error

    def test_no_map_on_record_says_so(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_disorder import ModelDisorder
        ses = self._session(None)
        ses.flags = {}
        r = ModelDisorder(None).run(SimpleNamespace(session=ses),
                                    atoms=["C1"])
        assert r.ok, r.error
        assert "no difference map on record" in r.summary["split"][0]["second_site_from"]

