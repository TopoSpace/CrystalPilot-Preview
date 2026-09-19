"""P1-8a: delivery status (provisional / diagnostic / final), final.fab +
ABIN for masked deliveries, key CIF fields, and finalize_delivery.

pa1 evidence: 27/27 publication CIFs drew 995_B because PLATON was never
told where SHELXL lives; 17 masked final.res without ABIN and 11 masked
deliveries without any .fab; cage-l2-r1 delivered the I2/a model its own
SUMMARY.md rejected with nothing machine-readable saying so; hex-l2-r3
shipped without SUMMARY/VALIDATION; every delivery carried 183/184/185_A
and most 699_A / 660_A for '?' slots nobody was told how to fill."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.refine import tools_deliver as td  # noqa: E402

RES_3ATOMS = """TITL t
CELL 0.71073 10 10 10 90 90 90
ZERR 4 0 0 0 0 0 0
SFAC C H O
UNIT 4 8 4
FVAR 1.0
C1 1 0.1 0.1 0.1 11.0 0.03
O1 3 0.2 0.2 0.2 11.0 0.03
H1 2 0.3 0.3 0.3 11.0 0.04
HKLF 4
END
"""

ACTA_CIF = """\
data_job
_audit_creation_method            'SHELXL-2019/3'
_chemical_formula_sum
'C1 H1 O1'
_chemical_formula_moiety          ?
_cell_length_a                    10.0
_cell_formula_units_Z             4
_space_group_name_H-M_alt         'P 1'
_cell_measurement_reflns_used     ?
_cell_measurement_theta_min       ?
_cell_measurement_theta_max       ?
_exptl_crystal_description        ?
_exptl_crystal_colour             ?
_diffrn_radiation_wavelength      0.68883
_diffrn_radiation_type            ?
_diffrn_source                    ?
_computing_structure_solution     'SHELXT 2018/2 (Sheldrick, 2018)'
_atom_sites_solution_primary      ?
_refine_special_details           ?
_refine_ls_hydrogen_treatment     constr
_refine_ls_R_factor_gt            0.0400
_refine_ls_wR_factor_ref          0.1000
_refine_ls_goodness_of_fit_ref    1.05

loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
C1 C 0.1 0.1 0.1
O1 O 0.2 0.2 0.2
H1 H 0.3 0.3 0.3
"""

MASK_INFO = {"n_voids": 1, "n_voids_masked": 1,
             "voids": [{"void": 1, "volume_A3": 500.0, "electrons": 120.0,
                        "centre_frac": [0.0, 0.5, 0.5], "masked": True}],
             "total_solvent_electrons_per_cell": 120.0,
             "solvent_volume_A3": 500.0, "solvent_volume_pct_of_cell": 50.0,
             "solvent_mask_converged": True}
MASK_PARAMS = {"solvent_radius": 1.2, "shrink_truncation_radius": 1.2,
               "resolution_factor": 0.25, "d_min": None,
               "min_void_volume": 30.0, "max_cycles": 40}


class _Nodes:
    """Disk-backed stand-in for NodeStore: node.json chain + model files."""

    def __init__(self, root: Path, active: str):
        self.root = root / ".crystalpilot" / "refine" / "nodes"
        self.active = active

    def state(self):
        return {"active_node": self.active, "active_branch": "main",
                "branches": {"main": self.active}, "seq": 3}

    def node_dir(self, node_id):
        return self.root / node_id

    def node_meta(self, node_id):
        return json.loads((self.node_dir(node_id) / "node.json")
                          .read_text(encoding="utf-8"))

    def list_nodes(self, limit=50):
        rows = []
        for d in sorted(self.root.iterdir()):
            m = self.node_meta(d.name)
            rows.append({"id": m["id"], "parent": m.get("parent"),
                         "tool": m.get("tool")})
        return {"nodes": rows[-limit:], "active_node": self.active,
                "active_branch": "main", "branches": {"main": self.active}}


def _project(tmp_path, *, masked=False, with_job=True, job_fab=None,
             lineage=("import", "run_shelxt", "refine"), experiment=None,
             session=None, res_text=RES_3ATOMS, cif_text=ACTA_CIF,
             job_res_text=None, job_cif_text=None):
    """job_fab=None: the SHELXL job carries a job.fab exactly when the node
    is masked (what run_shelxl does); pass True/False to force a mismatch.
    res_text/cif_text: the node's model files; job_res_text/job_cif_text
    default to the same (a job that IS the node's) - pass different text
    to stage a job the model drifted away from."""
    if job_fab is None:
        job_fab = masked
    job_res_text = job_res_text or res_text
    job_cif_text = job_cif_text or cif_text
    nodes = _Nodes(tmp_path, "n%04d" % (len(lineage) - 1))
    parent = None
    for i, tool in enumerate(lineage):
        nid = "n%04d" % i
        d = nodes.node_dir(nid)
        d.mkdir(parents=True)
        meta = {"id": nid, "parent": parent, "tool": tool,
                "metrics": {"r1_strong": 0.04, "wr2": 0.10, "goof": 1.05},
                "metrics_current": True,
                "model": {"n_atoms": 3, "element_counts": {"C": 1, "O": 1,
                                                          "H": 1}},
                "restraints": [], "hydrogens": {"present": True},
                "mask": ({"params": MASK_PARAMS, "info": MASK_INFO}
                         if masked else None)}
        (d / "node.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "model.res").write_text(res_text, encoding="utf-8")
        (d / "model.cif").write_text(cif_text, encoding="utf-8")
        parent = nid
    if with_job:
        job = tmp_path / ".crystalpilot" / "refine" / "shelxl" / "job_1"
        job.mkdir(parents=True)
        (job / "job.cif").write_text(job_cif_text, encoding="utf-8")
        (job / "job.res").write_text(job_res_text, encoding="utf-8")
        (job / "job.fcf").write_text("fcf\n", encoding="utf-8")
        (job / ".ok").write_text("", encoding="ascii")
        if job_fab:
            (job / "job.fab").write_text("1 0 0 1.0000 0.0000\n"
                                         "0 0 0 0.0 0.0\n", encoding="ascii")
    exp = dict(experiment or {})
    # the observations the node is bound to (what final.hkl is made from);
    # three rows and NO terminator - the vendor-file shape usertest
    # test3-1 delivered by hand and Olex2 refused
    hkl = tmp_path / "crystal.hkl"
    if not hkl.exists():
        hkl.write_text("   1   0   0  100.00    2.00\n"
                       "   0   1   0   50.00    1.50\n"
                       "   1   1   0   25.00    1.00\n", encoding="ascii")
    return SimpleNamespace(dir=tmp_path, nodes=nodes, context={},
                           experiment=lambda: exp, session=session,
                           hkl_path=hkl)


def _ctx():
    return SimpleNamespace(session=None, progress=None)


def _write(proj, **kw):
    kw.setdefault("output_dir", "CrystalPilot Results/t1")
    return td.WriteOutputs(proj).run(_ctx(), **kw)


# ---------------------------------------------------------------------------
class TestStatusHeader:
    def test_roundtrip_preserves_cif_body_when_status_changes(self):
        body = "data_x\n_cell_length_a 10.0\n"
        prov = td.with_status_header(body, "provisional", "n0002", "now")
        assert prov.startswith("# CrystalPilot delivery status: provisional")
        assert td.read_status_header(prov) == "provisional"
        assert td.strip_status_header(prov) == body
        fin = td.with_status_header(prov, "final", "n0002", "later")
        assert td.read_status_header(fin) == "final"
        assert fin.count("# CrystalPilot delivery status:") == 1
        assert td.strip_status_header(fin) == body
        assert td.read_status_header(body) is None

    def test_header_is_legal_cif(self):
        import iotbx.cif
        text = td.with_status_header(ACTA_CIF, "provisional", "n0", "t")
        block = next(iter(iotbx.cif.reader(input_string=text).model()
                          .values()))
        assert str(block["_refine_ls_R_factor_gt"]) == "0.0400"


class TestResAbin:
    def test_abin_inserted_before_fvar_and_idempotent(self):
        text, added = td._res_with_abin(RES_3ATOMS)
        assert added
        lines = [ln.split()[0] for ln in text.splitlines() if ln.strip()]
        assert lines.index("ABIN") < lines.index("FVAR")
        assert lines.index("ABIN") > lines.index("UNIT")
        again, added2 = td._res_with_abin(text)
        assert not added2 and again == text
        # SHELXL aborts on any input line over 80 characters; the first
        # version of the provenance REM was 96 characters and made every
        # masked final.res unrunnable (grader transplant arm, pa3)
        assert all(len(ln) <= 80 for ln in text.splitlines())
        # the delivery audit still counts 3 atoms / Z=4
        from crystalpilot.refine.tools_shelxl import (_res_zerr_z,
                                                       _shelx_atom_stats)
        assert _shelx_atom_stats(text)[0] == 3 and _res_zerr_z(text) == 4


class TestKeyFacts:
    def test_same_line_and_next_line_values(self):
        facts = td.cif_key_facts(ACTA_CIF)
        assert facts["r1_gt"] == "0.0400" and facts["goof"] == "1.05"
        assert facts["formula_sum"] == "C1 H1 O1"       # next-line value
        assert facts["z"] == "4" and facts["space_group"] == "P 1"
        assert "radiation_type" not in facts               # '?' omitted
        assert "formula_moiety" not in facts


# ---------------------------------------------------------------------------
class TestWriteOutputsStatus:
    def test_default_provisional_in_cif_report_manifest(self, tmp_path):
        r = _write(_project(tmp_path))
        assert r.ok, r.error
        out = tmp_path / "CrystalPilot Results" / "t1"
        cif = (out / "final.cif").read_text(encoding="utf-8")
        assert td.read_status_header(cif) == "provisional"
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "provisional"
        assert rep["status_history"][0]["by"] == "write_outputs"
        man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        assert man["status"] == "provisional"
        assert r.summary["status"] == "provisional"
        assert "finalize_delivery" in r.summary["next"]
        # the header is a comment: the coherence audit still parses the CIF
        assert "coherence_issues" not in r.summary
        # key facts come back in the reply AND sit in REPORT.json
        assert r.summary["key_facts"]["r1_gt"] == "0.0400"
        assert rep["key_facts"]["z"] == "4"
        assert r.summary["publication_cif"] is True

    def test_final_is_downgraded_with_note(self, tmp_path):
        r = _write(_project(tmp_path), status="final")
        assert r.ok and r.summary["status"] == "provisional"
        assert "finalize_delivery" in r.summary["status_note"]
        rep = json.loads((tmp_path / "CrystalPilot Results" / "t1"
                          / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "provisional" and rep["status_note"]

    def test_diagnostic_is_recorded_everywhere(self, tmp_path):
        r = _write(_project(tmp_path), status="diagnostic")
        assert r.ok and r.summary["status"] == "diagnostic"
        out = tmp_path / "CrystalPilot Results" / "t1"
        assert td.read_status_header(
            (out / "final.cif").read_text(encoding="utf-8")) == "diagnostic"
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "diagnostic"
        assert "not a structure claim" in r.summary["next"]

    def test_unknown_status_refused(self, tmp_path):
        r = _write(_project(tmp_path), status="published")
        assert not r.ok and "provisional" in r.error

    def test_minimal_cif_path_also_carries_status(self, tmp_path):
        r = _write(_project(tmp_path, with_job=False))
        assert r.ok and r.summary["publication_cif"] is False
        cif = (tmp_path / "CrystalPilot Results" / "t1" / "final.cif"
               ).read_text(encoding="utf-8")
        assert td.read_status_header(cif) == "provisional"


class TestFinalFab:
    def test_job_fab_copied_and_abin_added(self, tmp_path):
        r = _write(_project(tmp_path, masked=True))
        assert r.ok, r.error
        out = tmp_path / "CrystalPilot Results" / "t1"
        assert (out / "final.fab").read_text() == (
            "1 0 0 1.0000 0.0000\n0 0 0 0.0 0.0\n")
        res = (out / "final.res").read_text(encoding="utf-8")
        assert "\nABIN\n" in res
        assert r.summary["final_fab"]["written"] is True
        assert "job_1" in r.summary["final_fab"]["source"]
        assert "final.fab" in r.summary["files"]
        man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        assert "final.fab" in man["files"]
        assert r.artifacts["final_fab"].endswith("final.fab")
        # the mask documentation is the full PLATON-SQUEEZE block
        cif = (out / "final.cif").read_text(encoding="utf-8")
        assert "_platon_squeeze_void_probe_radius 1.20" in cif
        assert "_platon_squeeze_void_content" in cif
        assert " 1 0.000 0.500 0.500 500.0 120.0 ' '" in cif
        # nothing masked -> nothing owed, no fab, no ABIN
        other = tmp_path / "unmasked"
        other.mkdir()
        r2 = _write(_project(other, masked=False),
                    output_dir="CrystalPilot Results/t2")
        assert r2.ok and "final_fab" not in r2.summary
        assert "ABIN" not in (other / "CrystalPilot Results" / "t2"
                              / "final.res").read_text(encoding="utf-8")

    def test_fab_from_node_snapshot_when_job_has_none(self, tmp_path):
        from cctbx import crystal, miller
        from cctbx.array_family import flex
        from libtbx import easy_pickle
        proj = _project(tmp_path, masked=True, with_job=False)
        cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                              space_group_symbol="P 1")
        ms = miller.set(cs, flex.miller_index([(1, 0, 0), (0, 1, 0)]),
                        anomalous_flag=False)
        fm = ms.array(data=flex.complex_double([1 + 2j, 3 + 4j]))
        easy_pickle.dump(str(proj.nodes.node_dir("n0002") / "f_mask.pkl"),
                         {"f_mask": fm, "info": MASK_INFO,
                          "params": MASK_PARAMS})
        r = _write(proj)
        assert r.ok, r.error
        assert r.summary["final_fab"]["written"] is True
        assert "snapshot" in r.summary["final_fab"]["source"]
        fab = (tmp_path / "CrystalPilot Results" / "t1" / "final.fab"
               ).read_text().splitlines()
        assert fab[-1] == "0 0 0 0.0 0.0"
        assert len(fab) == 5                    # 2 refl + Bijvoet mates
        assert "1 0 0 1.0000 2.0000" in fab and "-1 0 0 1.0000 -2.0000" in fab

    def test_masked_without_any_mask_source_is_reported_not_hidden(
            self, tmp_path):
        # the job refined WITHOUT ABIN while the node is masked: the job is
        # rejected on the mask leg (final.cif must not describe a different
        # model than final.res/REPORT), and with no f_mask snapshot either
        # the missing final.fab is said out loud, not hidden
        r = _write(_project(tmp_path, masked=True, with_job=True,
                            job_fab=False))
        assert r.ok
        assert r.summary["publication_cif"] is False
        rep = json.loads((tmp_path / "CrystalPilot Results" / "t1"
                          / "REPORT.json").read_text(encoding="utf-8"))
        assert any("mask: job without ABIN" in m
                   for m in rep["publication_cif"]["job_mismatches"])
        assert r.summary["final_fab"]["written"] is False
        assert "f_mask snapshot" in r.summary["final_fab"]["reason"]
        assert any("final.fab" in c for c in r.summary["cif_caveats"])
        assert "final.fab" not in r.summary["files"]

    def test_masked_job_rejected_for_unmasked_node(self, tmp_path):
        r = _write(_project(tmp_path, masked=False, job_fab=True))
        assert r.ok and r.summary["publication_cif"] is False
        rep = json.loads((tmp_path / "CrystalPilot Results" / "t1"
                          / "REPORT.json").read_text(encoding="utf-8"))
        assert any("mask: job with ABIN" in m
                   for m in rep["publication_cif"]["job_mismatches"])
        assert not (tmp_path / "CrystalPilot Results" / "t1"
                    / "final.fab").exists()


class TestKeyCifFields:
    def test_solver_lineage_replaces_shelxl_default_claim(self, tmp_path):
        r = _write(_project(tmp_path))          # import -> run_shelxt -> refine
        assert r.ok
        cif = (tmp_path / "CrystalPilot Results" / "t1" / "final.cif"
               ).read_text(encoding="utf-8")
        assert "_computing_structure_solution     'SHELXT (Sheldrick, 2015)'" \
            in cif
        assert "_atom_sites_solution_primary      dual" in cif
        rep = json.loads((tmp_path / "CrystalPilot Results" / "t1"
                          / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["solution"]["solver_node"] == "n0001"

    def test_imported_model_without_solver_is_unknown_not_shelxt(
            self, tmp_path):
        r = _write(_project(tmp_path, lineage=("import", "refine")))
        assert r.ok
        cif = (tmp_path / "CrystalPilot Results" / "t1" / "final.cif"
               ).read_text(encoding="utf-8")
        assert "_computing_structure_solution     ?" in cif
        assert "SHELXT" not in cif
        assert any("求解方法未知" in c for c in r.summary["cif_caveats"])
        assert any(m["tag"] == "_computing_structure_solution"
                   for m in r.summary["cif_missing_metadata"])

    def test_charge_flipping_lineage_uses_live_engine(self, tmp_path):
        ses = SimpleNamespace(flags={}, cf_info={"engine": "superflip"})
        r = _write(_project(tmp_path, lineage=("import", "interpret_peaks",
                                               "refine"), session=ses))
        cif = (tmp_path / "CrystalPilot Results" / "t1" / "final.cif"
               ).read_text(encoding="utf-8")
        assert "SUPERFLIP" in cif
        assert "_atom_sites_solution_primary      iterative" in cif

    def test_missing_metadata_names_alert_and_fill_key(self, tmp_path):
        r = _write(_project(tmp_path))
        miss = {m["tag"]: m for m in r.summary["cif_missing_metadata"]}
        assert miss["_cell_measurement_reflns_used"]["checkcif_alert"] == "183_A"
        assert miss["_cell_measurement_reflns_used"]["fill_via"] == \
            "cell_measurement.reflns_used"
        assert miss["_exptl_crystal_description"]["checkcif_alert"] == "699_A"
        assert miss["_diffrn_radiation_type"]["checkcif_alert"] == "660_A"
        assert "set_experiment" in r.summary["metadata_note"]

    def test_synchrotron_source_fills_radiation_type(self, tmp_path):
        exp = {"instrument": {"source": "synchrotron, beamline BL17B",
                              "diffractometer": "Pilatus 6M"},
               "crystal": {"description": "block"},
               "cell_measurement": {"reflns_used": 9917, "theta_min": 2.1,
                                    "theta_max": 20.2}}
        r = _write(_project(tmp_path, experiment=exp))
        cif = (tmp_path / "CrystalPilot Results" / "t1" / "final.cif"
               ).read_text(encoding="utf-8")
        assert "_diffrn_radiation_type            synchrotron" in cif
        assert "_exptl_crystal_description        block" in cif
        assert "_cell_measurement_reflns_used     9917" in cif
        tags = {m["tag"] for m in r.summary.get("cif_missing_metadata", [])}
        assert "_diffrn_radiation_type" not in tags
        assert "_cell_measurement_reflns_used" not in tags
        assert "_exptl_crystal_colour" in tags          # still unknown


# ---------------------------------------------------------------------------
def _complete(out: Path, alerts=(), unresolved=None, with_source=True):
    """Make a write_outputs directory finalizable: narrative files and a
    checkcif.json that saw THIS final.cif."""
    (out / "SUMMARY.md").write_text("# 总结\n", encoding="utf-8")
    (out / "VALIDATION.md").write_text("# checkCIF\n", encoding="utf-8")
    cc = {"target": "publication:final.cif",
          "counts": {lv: sum(1 for a in alerts if a[1] == lv) for lv in "ABCG"},
          "alerts": [{"code": c, "type": 1, "level": lv, "text": f"t{c}"}
                     for c, lv in alerts]}
    if with_source:
        cc["source"] = td.validation_source(out / "final.cif")
    (out / "checkcif.json").write_text(json.dumps(cc), encoding="utf-8")
    if unresolved is not None:
        rp = out / "REPORT.json"
        rep = json.loads(rp.read_text(encoding="utf-8"))
        rep["unresolved"] = unresolved
        rp.write_text(json.dumps(rep), encoding="utf-8")


class TestFinalizeDelivery:
    def test_refuses_incomplete_and_changes_nothing(self, tmp_path):
        proj = _project(tmp_path)
        assert _write(proj).ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        before = (out / "final.cif").read_bytes()
        r = td.FinalizeDelivery(proj).run(_ctx())
        assert not r.ok
        for missing in ("checkcif.json", "SUMMARY.md", "VALIDATION.md"):
            assert f"missing {missing}" in r.error
        assert "nothing was changed" in r.error
        assert (out / "final.cif").read_bytes() == before
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "provisional"

    def test_promotes_complete_delivery(self, tmp_path):
        proj = _project(tmp_path, masked=True)
        assert _write(proj).ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out)
        r = td.FinalizeDelivery(proj).run(_ctx(), note="done")
        assert r.ok, r.error
        assert r.summary["status"] == "final"
        assert r.summary["sealed"] is True and r.summary["promoted"] is True
        assert r.summary["waived_count"] == 0 and r.summary["open_items"] == []
        cif = (out / "final.cif").read_text(encoding="utf-8")
        assert td.read_status_header(cif) == "final"
        lines = cif.splitlines()
        assert lines[0] == "# CrystalPilot delivery status: final"
        # 0 waivers: the header meaning is the plain STATUS_MEANING text,
        # not a waiver count - it must not claim anything was waived
        assert lines[1] == ("# CrystalPilot delivery meaning: "
                            + td.STATUS_MEANING["final"])
        # STATUS_MEANING["final"] itself mentions waivers as a general
        # concept ("...resolved or waived..."); what must NOT appear is
        # the per-delivery waived-count override finalize_delivery adds
        # only when n_waived > 0
        assert "blocking items waived with reasons" not in lines[1]
        assert "MANIFEST.json" not in lines[1]
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "final"
        assert rep["status_history"][-1]["by"] == "finalize_delivery"
        assert rep["finalized"]["waivers"] == []
        assert rep["finalized"]["waived_count"] == 0
        assert rep["finalized"]["open_items"] == []
        assert rep["finalized"]["promoted"] is True
        assert rep["finalized"]["note"] == "done"
        man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        assert man["status"] == "final"
        assert man["waived"] == [] and man["waived_count"] == 0
        assert man["open_items"] == [] and man["promoted"] is True
        for f in ("SUMMARY.md", "VALIDATION.md", "checkcif.json",
                  "final.fab", "REPORT.json", "final.cif"):
            assert f in man["files"], f
        # Changing status does not create a new scientific delivery version.
        r2 = td.FinalizeDelivery(proj).run(_ctx())
        assert r2.ok, r2.error

    def test_blocking_items_need_per_item_waivers(self, tmp_path):
        proj = _project(tmp_path)
        assert _write(proj, unresolved=["Cu2 axial site disorder unmodelled"]
                      ).ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out, alerts=[("183", "A"), ("183", "A"), ("242", "B")],
                  unresolved=["Cu2 axial site disorder unmodelled"])
        r = td.FinalizeDelivery(proj).run(_ctx())
        assert not r.ok
        assert "alert:183_A" in r.error and "unresolved#1" in r.error
        assert "242" not in r.error                     # B does not block
        assert r.error.count("alert:183_A") == 1        # de-duplicated
        # a too-short reason and an unknown id are rejected
        r = td.FinalizeDelivery(proj).run(_ctx(), waivers=[
            {"item": "alert:183_A", "reason": "n/a"},
            {"item": "alert:999_A", "reason": "this item does not exist"}])
        assert not r.ok and "too short" in r.error and "999_A" in r.error
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "provisional"
        r = td.FinalizeDelivery(proj).run(_ctx(), waivers=[
            {"item": "alert:183_A",
             "reason": "vendor hkl carries no cell-measurement statistics; "
                       "disclosed in VALIDATION.md"},
            {"item": "unresolved#1",
             "reason": "special-position disorder left for the user, see "
                       "SUMMARY.md"}])
        assert r.ok, r.error
        assert r.summary["waived_count"] == 2 and r.summary["promoted"] is True
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "final"
        assert {w["item"] for w in rep["finalized"]["waivers"]} == {
            "alert:183_A", "unresolved#1"}
        assert rep["finalized"]["waivers"][0]["text"]
        assert rep["finalized"]["waived_count"] == 2
        assert rep["finalized"]["open_items"] == []
        assert len(r.summary["waived"]) == 2
        # the header names how many blocking items were waived instead of
        # implying every one was resolved outright (pa-cage: 23 disclosure
        # waivers promoted an unpublishable model to 'final' behind a
        # generic "every blocking item resolved" claim)
        cif = (out / "final.cif").read_text(encoding="utf-8")
        lines = cif.splitlines()
        assert lines[0] == "# CrystalPilot delivery status: final"
        assert lines[1].startswith("# CrystalPilot delivery meaning: final")
        assert "2 blocking items waived with reasons" in lines[1]
        assert "MANIFEST.json" in lines[1]
        man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        assert man["status"] == "final" and man["waived_count"] == 2
        assert {w["item"] for w in man["waived"]} == {
            "alert:183_A", "unresolved#1"}
        assert all(w["reason"] for w in man["waived"])
        assert man["open_items"] == [] and man["promoted"] is True

    def test_checkcif_must_have_seen_this_cif(self, tmp_path):
        proj = _project(tmp_path)
        assert _write(proj).ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out)
        cc = json.loads((out / "checkcif.json").read_text(encoding="utf-8"))
        cc["source"]["delivery_revision"] += 1
        (out / "checkcif.json").write_text(json.dumps(cc), encoding="utf-8")
        r = td.FinalizeDelivery(proj).run(_ctx())
        assert not r.ok and "different final.cif" in r.error
        # A recent file alone is not a node/version association.
        _complete(out, with_source=False)
        r = td.FinalizeDelivery(proj).run(_ctx())
        assert not r.ok and "source is unknown" in r.error

    def test_masked_delivery_without_fab_is_fatal_even_when_diagnostic(
            self, tmp_path):
        # a diagnostic delivery can be SEALED without waivers (below), but
        # a masked model missing final.fab is still fatal - diagnostic
        # status changes what happens to BLOCKING items, not to FATAL ones
        proj = _project(tmp_path, masked=True)
        assert _write(proj, status="diagnostic").ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out)
        (out / "final.fab").unlink()
        r = td.FinalizeDelivery(proj).run(_ctx())
        assert not r.ok
        assert "missing final.fab" in r.error
        assert "nothing was changed" in r.error

    def test_diagnostic_delivery_is_sealed_not_promoted(self, tmp_path):
        proj = _project(tmp_path)
        assert _write(proj, status="diagnostic",
                      unresolved=["disorder unmodelled"]).ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out, alerts=[("183", "A")],
                  unresolved=["disorder unmodelled"])
        # round-3 WP7: a diagnostic seal must say what was NOT achieved
        r0 = td.FinalizeDelivery(proj).run(_ctx())
        assert not r0.ok and "did NOT achieve" in r0.error
        assert "nothing was changed" in r0.error
        r = td.FinalizeDelivery(proj).run(
            _ctx(), unmet_goals=["whole guest not located"])
        assert r.ok, r.error
        assert r.summary["status"] == "diagnostic"
        assert r.summary["sealed"] is True
        assert r.summary["promoted"] is False
        assert {i["item"] for i in r.summary["open_items"]} == {
            "alert:183_A", "unresolved#1", "unmet_goal#1"}
        assert r.summary["waived"] == [] and r.summary["waived_count"] == 0
        cif = (out / "final.cif").read_text(encoding="utf-8")
        assert td.read_status_header(cif) == "diagnostic"
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "diagnostic"
        assert rep["finalized"]["promoted"] is False
        assert {i["item"] for i in rep["finalized"]["open_items"]} == {
            "alert:183_A", "unresolved#1", "unmet_goal#1"}
        man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        assert man["status"] == "diagnostic"
        for f in ("SUMMARY.md", "VALIDATION.md", "checkcif.json",
                  "final.cif", "final.res", "final.fcf", "REPORT.json"):
            assert f in man["files"], f
        assert {i["item"] for i in man["open_items"]} == {
            "alert:183_A", "unresolved#1", "unmet_goal#1"}
        assert man["waived"] == [] and man["waived_count"] == 0
        # a diagnostic seal is idempotent - re-running still succeeds
        r2 = td.FinalizeDelivery(proj).run(
            _ctx(), unmet_goals=["whole guest not located"])
        assert r2.ok, r2.error
        assert r2.summary["status"] == "diagnostic"

    def test_explicit_dir_and_newest_default(self, tmp_path):
        proj = _project(tmp_path)
        assert _write(proj, output_dir="CrystalPilot Results/old").ok
        assert _write(proj, output_dir="CrystalPilot Results/new").ok
        root = tmp_path / "CrystalPilot Results"
        past = (root / "new" / "REPORT.json").stat().st_mtime - 3600
        os.utime(root / "old" / "REPORT.json", (past, past))
        assert td.find_newest_delivery(tmp_path) == root / "new"
        r = td.FinalizeDelivery(proj).run(_ctx(), output_dir="nowhere")
        assert not r.ok and "no REPORT.json" in r.error
        _complete(root / "old")
        r = td.FinalizeDelivery(proj).run(_ctx(),
                                          output_dir="CrystalPilot Results/old")
        assert r.ok, r.error
        assert td.read_status_header((root / "new" / "final.cif").read_text(
            encoding="utf-8")) == "provisional"
        # deeper layout (pa1 cu-l2-r2 wrote into <task>/deliverables/)
        deep = root / "task_x" / "deliverables"
        deep.mkdir(parents=True)
        (deep / "REPORT.json").write_text("{}", encoding="utf-8")
        (deep / "final.cif").write_text("data_x\n", encoding="utf-8")
        assert td.find_newest_delivery(tmp_path) == deep

    def test_registered(self):
        from crystalpilot.refine.tools_extra import register_refine_tools
        from crystalpilot.tools.base import ToolRegistry
        reg = ToolRegistry()
        register_refine_tools(reg, None)
        assert "finalize_delivery" in reg.names()


# ---------------------------------------------------------------------------
class TestRunCheckcifEnvironment:
    """PLATON rebuilds the .fcf by running SHELXL; it must be told where."""

    def test_shlexe_exposed_and_fcf_reason_structured(self, tmp_path,
                                                       monkeypatch):
        platon = tmp_path / "platon.exe"
        platon.write_bytes(b"MZ")
        shelxl = tmp_path / "vendor" / "shelxl.exe"
        shelxl.parent.mkdir()
        shelxl.write_bytes(b"MZ")
        monkeypatch.setenv("CRYSTALPILOT_PLATON", str(platon))
        monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(shelxl))
        proj = _project(tmp_path)
        assert _write(proj).ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        seen: dict = {}

        class FakePopen:
            """Synthetic execution fixture, not a real crystallographic check."""
            pid = 123

            def __init__(self, cmd, cwd=None, env=None, **kw):
                seen["env"] = env
                seen["runtime"] = Path(env["PATH"].split(os.pathsep)[0])
                assert (seen["runtime"] / "shelxl.exe").read_bytes() == b"MZ"
                job = Path(cwd)
                (job / "model.chk").write_text(
                    "# PLATON/CHECK-(synthetic)\n"
                    "995_ALERT_1_B Can not Recreate .fcf from Embedded  "
                    ".res & .hkl          ! Check\n"
                    "0 ALERT_Level_A = synthetic\n1 ALERT_Level_B = synthetic\n"
                    "0 ALERT_Level_C = synthetic\n0 ALERT_Level_G = synthetic\n", encoding="utf-8")
                (job / "platon.out").write_text(
                    " ** SHELXL20xy Type Executable Required! **\n"
                    "** PROBLEM to Recreate FCF for job(Native SHELXL20xy "
                    "Job Needed) **\n:: CheckCIF out on :model.chk\n", encoding="utf-8")

            def poll(self):
                return 0

            def active(self):
                return False

            def close(self):
                return True

        from crystalpilot.refine import checkcif_runner
        monkeypatch.setattr(checkcif_runner, "CheckcifProcess", FakePopen)
        monkeypatch.setattr(checkcif_runner, "STABLE_S", 0)
        r = td.RunCheckcif(proj).run(_ctx(), cif="CrystalPilot Results/t1/"
                                                  "final.cif", timeout_s=5)
        assert r.ok, r.error
        assert seen["env"]["SHLEXE"] == "shelxl.exe"
        assert not seen["runtime"].exists()
        fr = r.summary["fcf_recreation"]
        assert "Executable Required" in fr["problem"]
        assert fr["hint"].startswith("environmental")
        cc = json.loads((out / "checkcif.json").read_text(encoding="utf-8"))
        assert cc["source"] == td.validation_source(out / "final.cif")
        assert r.summary["source"] == cc["source"]
        assert cc["delivery_status"] == "provisional"
        assert cc["fcf_recreation"]["problem"]

    def test_no_complaint_gives_no_note(self, tmp_path):
        assert td._fcf_recreation_note(tmp_path / "absent", True) is None
        (tmp_path / "platon.out").write_text("all fine\n", encoding="utf-8")
        assert td._fcf_recreation_note(tmp_path / "platon.out", True) is None
        (tmp_path / "platon.out").write_text(
            "** PROBLEM to Recreate FCF for job **\n", encoding="utf-8")
        note = td._fcf_recreation_note(tmp_path / "platon.out", True)
        assert "ABIN" in note["hint"]          # a real mismatch, not env


class TestPublicationAssemblerAdditions:
    def test_legacy_default_without_lineage_unchanged(self):
        from crystalpilot.report.publication import assemble_publication_cif
        out, rep = assemble_publication_cif(ACTA_CIF)
        assert "CrystalPilot (charge flipping" in out
        assert isinstance(rep["missing_metadata"], list)

    def test_unconverged_mask_is_said_in_the_cif(self):
        from crystalpilot.report.publication import assemble_publication_cif
        info = dict(MASK_INFO, solvent_mask_converged=False)
        out, _ = assemble_publication_cif(ACTA_CIF, mask_info=info,
                                          mask_params=MASK_PARAMS)
        assert "did not converge" in out
        assert "_platon_squeeze_void_probe_radius 1.20" in out
        out2, _ = assemble_publication_cif(ACTA_CIF, mask_info=MASK_INFO)
        assert "did not converge" not in out2
        assert "_platon_squeeze_void_probe_radius" not in out2

    def test_reassembly_does_not_duplicate_squeeze_block(self):
        """A delivered CIF fed back in (smoke test on pa1 hex-l0-r1) must
        not gain a second _platon_squeeze_details - iotbx rejects it."""
        import iotbx.cif
        from crystalpilot.report.publication import assemble_publication_cif
        once, _ = assemble_publication_cif(ACTA_CIF, mask_info=MASK_INFO)
        twice, rep = assemble_publication_cif(once, mask_info=MASK_INFO)
        assert twice.count("_platon_squeeze_details") == 1
        assert any("_platon_squeeze" in c for c in rep["caveats"])
        iotbx.cif.reader(input_string=twice).model()


# ---------------------------------------------------------------------------
# pa2/pa3 delivery-gate fixes: the label/element gate, the explicit
# job-match refusal, and metadata-only changes that need no rerun.

def _acta_with_atoms(rows: str) -> str:
    """ACTA_CIF's header with a different _atom_site loop."""
    return (ACTA_CIF.split("loop_")[0] + "loop_\n _atom_site_label\n"
            " _atom_site_type_symbol\n _atom_site_fract_x\n"
            " _atom_site_fract_y\n _atom_site_fract_z\n" + rows)


# a Cu/Br structure whose SHELXT placeholder labels survived: the mu-O is
# still N62 (typed O), the copper is still C1 (typed Cu); OW1 / BR6 are
# conventional (OW is not an element -> O; BR -> Br)
RES_MISLABELLED = """TITL t
CELL 0.71073 10 10 10 90 90 90
ZERR 4 0 0 0 0 0 0
SFAC C H O Cu Br
UNIT 4 8 8 4 4
FVAR 1.0
N62 3 0.1 0.1 0.1 11.0 0.03
C1 4 0.2 0.2 0.2 11.0 0.03
OW1 3 0.3 0.3 0.3 11.0 0.04
BR6 5 0.4 0.4 0.4 11.0 0.04
H1 2 0.5 0.5 0.5 11.0 0.05
HKLF 4
END
"""
CIF_MISLABELLED = _acta_with_atoms(
    "N62 O 0.1 0.1 0.1\nC1 Cu 0.2 0.2 0.2\nOW1 O 0.3 0.3 0.3\n"
    "BR6 Br 0.4 0.4 0.4\nH1 H 0.5 0.5 0.5\n")

RES_WITH_Q = RES_3ATOMS.replace("HKLF 4", "Q1 1 0.6 0.6 0.6 11.0 0.05\nHKLF 4")
CIF_WITH_Q = _acta_with_atoms(
    "C1 C 0.1 0.1 0.1\nO1 O 0.2 0.2 0.2\nH1 H 0.3 0.3 0.3\n"
    "Q1 C 0.6 0.6 0.6\n")


def _report(tmp_path):
    return json.loads((tmp_path / "CrystalPilot Results" / "t1"
                       / "REPORT.json").read_text(encoding="utf-8"))


class TestLabelElementGate:
    def test_mismatch_blocks_with_the_one_call_fix(self, tmp_path):
        proj = _project(tmp_path, res_text=RES_MISLABELLED,
                        cif_text=CIF_MISLABELLED)
        r = _write(proj)
        assert r.ok, r.error
        assert r.summary["publication_cif"] is True      # the job matched
        issues = r.summary["coherence_issues"]
        msg = next(i for i in issues if i.startswith("label/element mismatch"))
        assert "N62 is labelled N but typed O" in msg
        assert "C1 is labelled C but typed Cu" in msg
        assert "OW1" not in msg and "BR6" not in msg
        assert "rename_atoms(mode='map', map={'N62': 'O62', 'C1': 'CU1'})" in msg
        assert "'action': 'reassign'" in msg and "N62 -> N" in msg
        assert "accept_label_mismatch=true" in msg
        assert "rename_atoms" in r.summary["coherence_note"]
        rep = _report(tmp_path)
        assert msg in rep["coherence_issues"]
        assert [m["label"] for m in rep["label_audit"]["mismatches"]] == \
            ["N62", "C1"]
        assert rep["label_audit"]["mismatches"][0]["where"] == \
            ["final.res", "final.cif"]
        assert rep["label_audit"]["n_checked"] == 4
        assert "label_mismatch_accepted" not in rep
        assert r.summary["label_audit"]["peak_labels"] == []
        # finalize_delivery refuses it as fatal, once (the write-time
        # record and the re-run on the files say the same thing)
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out)
        f = td.FinalizeDelivery(proj).run(_ctx())
        assert not f.ok
        assert f.error.count("label/element mismatch on 2 atom(s)") == 1
        assert "cannot be waived" in f.error

    def test_accept_records_the_reason_everywhere(self, tmp_path):
        proj = _project(tmp_path, res_text=RES_MISLABELLED,
                        cif_text=CIF_MISLABELLED)
        reason = ("placeholder labels kept on purpose for the reviewer diff "
                  "against the SHELXT model; stated in SUMMARY.md")
        r = _write(proj, accept_label_mismatch=True, reason=reason)
        assert r.ok, r.error
        assert "coherence_issues" not in r.summary
        rec = r.summary["label_mismatch_accepted"]
        assert rec["reason"] == reason
        assert [m["label"] for m in rec["mismatches"]] == ["N62", "C1"]
        assert rec["mismatches"][0] == {"label": "N62", "label_element": "N",
                                        "type": "O"}
        out = tmp_path / "CrystalPilot Results" / "t1"
        rep = _report(tmp_path)
        assert rep["label_mismatch_accepted"]["reason"] == reason
        assert rep["coherence_issues"] == []
        man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        assert man["label_mismatch_accepted"]["reason"] == reason
        # finalize_delivery honours the recorded acceptance...
        _complete(out)
        f = td.FinalizeDelivery(proj).run(_ctx())
        assert f.ok, f.error
        assert f.summary["label_mismatch_accepted"]["reason"] == reason
        # ...but only for the mismatches it actually covers
        rep = _report(tmp_path)
        rep["label_mismatch_accepted"]["mismatches"] = [
            m for m in rep["label_mismatch_accepted"]["mismatches"]
            if m["label"] != "C1"]
        (out / "REPORT.json").write_text(json.dumps(rep), encoding="utf-8")
        f = td.FinalizeDelivery(proj).run(_ctx())
        assert not f.ok
        assert "C1 is labelled C but typed Cu" in f.error
        assert "N62" not in f.error

    def test_accept_needs_a_reason_and_writes_nothing(self, tmp_path):
        proj = _project(tmp_path, res_text=RES_MISLABELLED,
                        cif_text=CIF_MISLABELLED)
        r = _write(proj, accept_label_mismatch=True)
        assert not r.ok and "reason" in r.error
        assert not (tmp_path / "CrystalPilot Results" / "t1").exists()
        r = _write(proj, accept_label_mismatch=True, reason="short")
        assert not r.ok and "reason" in r.error
        # the flag without any mismatch records nothing and says so
        clean = tmp_path / "clean"
        clean.mkdir()
        r = _write(_project(clean), accept_label_mismatch=True,
                   reason="no mismatch here but the flag is set anyway")
        assert r.ok and "label_note" in r.summary
        assert "label_mismatch_accepted" not in r.summary
        rep = json.loads((clean / "CrystalPilot Results" / "t1"
                          / "REPORT.json").read_text(encoding="utf-8"))
        assert "label_mismatch_accepted" not in rep
        assert rep["label_audit"]["n_checked"] == 2         # C1, O1 (H skipped)

    def test_peak_label_is_never_accepted(self, tmp_path):
        proj = _project(tmp_path, res_text=RES_WITH_Q, cif_text=CIF_WITH_Q)
        r = _write(proj, accept_label_mismatch=True,
                   reason="we know about the Q peak and accept it anyway")
        assert r.ok
        msg = next(i for i in r.summary["coherence_issues"]
                   if i.startswith("peak labels"))
        assert "Q1" in msg and "never accepted" in msg
        assert "edit_atoms" in msg and "rename_atoms" in msg
        assert r.summary["label_audit"]["peak_labels"] == ["Q1"]
        assert "label_mismatch_accepted" not in r.summary
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out)
        f = td.FinalizeDelivery(proj).run(_ctx())
        assert not f.ok and "Q1" in f.error

    def test_res_cif_type_conflict_is_a_coherence_issue(self, tmp_path):
        # the node's viewer CIF says O1 is N while model.res says O: the two
        # delivered files would describe different atoms
        cif = _acta_with_atoms("C1 C 0.1 0.1 0.1\nO1 N 0.2 0.2 0.2\n"
                               "H1 H 0.3 0.3 0.3\n")
        r = _write(_project(tmp_path, with_job=False, cif_text=cif))
        assert r.ok
        issues = r.summary["coherence_issues"]
        assert any("O1: final.res O vs final.cif N" in i for i in issues)
        assert any("O1 is labelled O but typed N" in i for i in issues)

    def test_clean_delivery_says_labels_agree(self, tmp_path):
        r = _write(_project(tmp_path))
        assert "labels/elements" in r.summary["coherence"]
        assert "label_audit" not in r.summary
        assert _report(tmp_path)["label_audit"] == {
            "n_checked": 2, "mismatches": [], "peak_labels": [],
            "type_conflicts": []}

    def test_gate_helpers_on_synthetic_text(self):
        from crystalpilot.refine.tools_deliver import (cif_atom_sites,
                                                       label_element_audit)
        rows = cif_atom_sites(CIF_MISLABELLED)
        assert rows[:2] == [("N62", "O"), ("C1", "Cu")]
        assert len(rows) == 5
        # status-header comments, an aniso loop and quoted values do not
        # confuse the text parser
        text = ("# CrystalPilot delivery status: provisional\n"
                + CIF_MISLABELLED.replace("BR6 Br", "'BR6' \"Br\"")
                + "\nloop_\n _atom_site_aniso_label\n _atom_site_aniso_U_11\n"
                  "N62 0.01\n")
        assert cif_atom_sites(text)[3] == ("BR6", "Br")
        assert len(cif_atom_sites(text)) == 5
        assert cif_atom_sites("data_x\n_cell_length_a 10.0\n") == []
        audit = label_element_audit(RES_MISLABELLED, CIF_MISLABELLED)
        assert [(m["label"], m["label_element"], m["type"])
                for m in audit["mismatches"]] == [("N62", "N", "O"),
                                                  ("C1", "C", "Cu")]
        assert audit["type_conflicts"] == [] and audit["peak_labels"] == []
        assert audit["n_checked"] == 4
        # lowercase and suffixed labels of a metal-free molecule are clean
        res = RES_3ATOMS.replace("C1 1", "c1a 1").replace("O1 3", "O1' 3")
        assert label_element_audit(res, None)["mismatches"] == []
        # the convention's trap: NA1 for an amine N reads as sodium
        res = RES_3ATOMS.replace("SFAC C H O", "SFAC C H N").replace(
            "O1 3", "NA1 3")
        mm = label_element_audit(res, None)["mismatches"]
        assert [(m["label"], m["label_element"], m["type"]) for m in mm] == \
            [("NA1", "Na", "N")]


class TestJobMatchRefusal:
    def test_refusal_states_conditions_numbers_and_action(self, tmp_path):
        proj = _project(tmp_path)
        meta_p = proj.nodes.node_dir("n0002") / "node.json"
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        meta["metrics"]["r1_strong"] = 0.09
        meta_p.write_text(json.dumps(meta), encoding="utf-8")
        r = _write(proj)
        assert r.ok and r.summary["publication_cif"] is False
        jm = r.summary["job_match"]
        assert jm["matched"] is False
        assert jm["node"] == {"node": "n0002", "r1": 0.09, "atoms": 3,
                              "h": 1, "n_fvar": 1, "z": 4, "masked": False}
        assert len(jm["conditions"]) == 3
        assert jm["newest_job"] == "job_1"
        assert jm["newest_job_failed_on"] == [
            "R1 0.0400 vs node 0.0900 (tolerance 0.005)"]
        cand = jm["candidates"][0]
        assert (cand["r1"], cand["atoms"], cand["h"], cand["n_fvar"],
                cand["z"], cand["masked"]) == (0.04, 3, 1, 1, 4, False)
        assert "set_experiment" in jm["action"]
        assert "run_shelxl(mode='adopt')" in jm["action"]
        text = jm["refusal"]
        assert text.startswith("no SHELXL job matches the active node n0002")
        assert "R1 0.0900, 3 atoms / 1 H / 1 FVAR, Z 4, unmasked" in text
        assert ("Newest job job_1 (R1 0.0400, 3 atoms / 1 H / 1 FVAR, Z 4, "
                "unmasked) failed on: R1 0.0400 vs node 0.0900") in text
        assert "(1) R1" in text and "(2) model" in text and "(3) bookkeeping" in text
        assert "no rerun is needed" in text
        assert text in r.summary["cif_caveats"]
        # the R1 rejection is no longer silent in job_mismatches either
        rep = _report(tmp_path)
        assert rep["publication_cif"]["job_mismatches"] == [
            "job_1: R1 0.0400 vs node 0.0900 (tolerance 0.005)"]
        assert rep["publication_cif"]["job_match"]["refusal"] == text

    def test_h_coordinate_drift_rejects_a_matching_count_and_r1(self, tmp_path):
        moved = RES_3ATOMS.replace("H1 2 0.3 0.3 0.3", "H1 2 0.31 0.3 0.3")
        proj = _project(tmp_path, res_text=moved, job_res_text=RES_3ATOMS)
        r = _write(proj)
        assert r.ok and r.summary["publication_cif"] is False
        failures = r.summary["job_match"]["newest_job_failed_on"]
        assert any("coordinates (including H): H1" in reason for reason in failures)

    def test_integer_translation_and_serialization_precision_keep_match(self, tmp_path):
        shifted = RES_3ATOMS.replace("H1 2 0.3 0.3 0.3", "H1 2 1.300001 0.3 0.3")
        r = _write(_project(tmp_path, res_text=shifted, job_res_text=RES_3ATOMS))
        assert r.ok and r.summary["publication_cif"] is True

    def test_no_job_at_all(self, tmp_path):
        r = _write(_project(tmp_path, with_job=False))
        jm = r.summary["job_match"]
        assert jm["n_jobs_seen"] == 0 and jm["newest_job"] is None
        assert "No run_shelxl job exists" in jm["refusal"]
        assert jm["candidates"] == []

    def test_incomplete_newest_job_is_named(self, tmp_path):
        proj = _project(tmp_path)
        job2 = tmp_path / ".crystalpilot" / "refine" / "shelxl" / "job_2"
        job2.mkdir()
        (job2 / "job.cif").write_text(ACTA_CIF, encoding="utf-8")   # no .ok
        r = _write(proj)
        assert r.summary["publication_cif"] is True                 # job_1
        assert r.summary["shelxl_job"] == "job_1"
        rep = _report(tmp_path)
        assert rep["publication_cif"]["job_mismatches"] == [
            "job_2: no completion marker (failed or pre-marker job)"]
        assert rep["publication_cif"]["job_match"]["matched"] is True

    def test_fvar_count_retype_and_relabel_legs(self, tmp_path):
        # a free variable added after the job
        proj = _project(tmp_path,
                        res_text=RES_3ATOMS.replace("FVAR 1.0", "FVAR 1.0 0.5"),
                        job_res_text=RES_3ATOMS)
        r = _write(proj)
        assert r.summary["publication_cif"] is False
        assert r.summary["job_match"]["newest_job_failed_on"] == [
            "FVAR count 1 vs node 2 (a free variable was added or removed "
            "after the job)"]
        # O1 retyped to N (edit_atoms reassign) after the job: every count
        # and the copied R1 still agree, the job is stale anyway
        d2 = tmp_path / "retype"
        d2.mkdir()
        proj = _project(d2, res_text=RES_3ATOMS.replace("SFAC C H O",
                                                        "SFAC C H N"),
                        job_res_text=RES_3ATOMS)
        r = _write(proj)
        assert r.summary["publication_cif"] is False
        assert r.summary["job_match"]["newest_job_failed_on"] == [
            "element types: O1 job O vs node N (atoms retyped after the "
            "job - re-run run_shelxl)"]
        # O1 renamed to O1A (rename_atoms) after the job
        d3 = tmp_path / "relabel"
        d3.mkdir()
        proj = _project(d3, res_text=RES_3ATOMS.replace("O1 3", "O1A 3"),
                        job_res_text=RES_3ATOMS)
        r = _write(proj)
        assert r.summary["publication_cif"] is False
        assert r.summary["job_match"]["newest_job_failed_on"] == [
            "labels: job has ['O1'] the node lacks, node has ['O1A'] the "
            "job lacks (atoms relabelled after the job - re-run run_shelxl)"]


class TestMetadataOnlyChange:
    """set_experiment after the matching job: the pairing is keyed on the
    model, so no rerun - and the CIF carries the NEW metadata."""

    def test_set_experiment_keeps_the_match_and_updates_the_cif(
            self, tmp_path):
        from crystalpilot.refine.tools_ingest import SetExperiment
        proj = _project(tmp_path)
        # Project.experiment() semantics: the context.json block wins
        proj.experiment = lambda: dict(proj.context.get("experiment") or {})
        r1 = _write(proj)
        assert r1.ok and r1.summary["publication_cif"] is True
        assert r1.summary["shelxl_job"] == "job_1"
        out = tmp_path / "CrystalPilot Results" / "t1"
        cif1 = (out / "final.cif").read_text(encoding="utf-8")
        assert "_exptl_crystal_description        ?" in cif1
        assert "_diffrn_radiation_type            ?" in cif1
        # a metadata-only change through the real tool (writes context.json)
        s = SetExperiment(proj).run(
            _ctx(),
            experiment={"temperature_K": 100,
                        "crystal": {"description": "block", "colour": "blue",
                                    "size_mm": [0.2, 0.1, 0.05]},
                        "instrument": {"source": "synchrotron, BL17B"}},
            provenance="user email 2026-09-02 (mount notes)")
        assert s.ok, s.error
        assert (tmp_path / "context.json").exists()
        # no run_shelxl in between: the same job still matches
        r2 = _write(proj)
        assert r2.ok, r2.error
        assert r2.summary["publication_cif"] is True
        assert r2.summary["shelxl_job"] == "job_1"
        assert "job_match" not in r2.summary
        assert "coherence_issues" not in r2.summary
        rep = _report(tmp_path)
        assert rep["publication_cif"]["job_match"]["matched"] is True
        assert rep["experiment"]["temperature_K"] == 100.0
        assert rep["experiment"]["crystal"]["description"] == "block"
        cif2 = (out / "final.cif").read_text(encoding="utf-8")
        assert "_exptl_crystal_description        block" in cif2
        assert "_exptl_crystal_colour             blue" in cif2
        assert "_diffrn_radiation_type            synchrotron" in cif2
        tags = {m["tag"] for m in r2.summary.get("cif_missing_metadata", [])}
        assert "_exptl_crystal_description" not in tags
        # and the tool text no longer tells the agent to rerun after metadata
        assert "need NO rerun" in td.WriteOutputs.description
        assert "no rerun is needed" in td.JOB_MATCH_ACTION

    def test_size_corrected_after_the_job_wins_in_the_cif(self):
        from crystalpilot.report.publication import assemble_publication_cif
        cif = ACTA_CIF.replace(
            "_exptl_crystal_colour             ?",
            "_exptl_crystal_colour             ?\n"
            "_exptl_crystal_size_max           0.300\n"
            "_exptl_crystal_size_mid           0.200\n"
            "_exptl_crystal_size_min           0.100")
        out, rep = assemble_publication_cif(
            cif, experiment={"crystal": {"size_mm": [0.05, 0.1, 0.2]}})
        assert "_exptl_crystal_size_max           0.200" in out
        assert "_exptl_crystal_size_mid           0.100" in out
        assert "_exptl_crystal_size_min           0.050" in out
        assert "_exptl_crystal_size_max" in rep["filled"]


# ---------------------------------------------------------------------------
class TestHandoverSet:
    """2026-09-08 usertest test3-1 / test3-2: the group hands over res /
    cif / ins / hkl / p4p. write_outputs wrote none of ins / hkl / p4p, so
    both agents built them by hand (a final.ins without L.S., a vendor hkl
    Olex2 refused, a p4p found by guessing). Now they are products of the
    tool, each with a recorded source, and the delivery says what is
    missing instead of pretending."""

    def test_ins_and_hkl_are_written_with_provenance(self, tmp_path):
        proj = _project(tmp_path)          # job_1 pairs, but has no job.ins
        r = _write(proj)
        assert r.ok, r.error
        out = tmp_path / "CrystalPilot Results" / "t1"
        for f in ("final.res", "final.cif", "final.ins", "final.hkl"):
            assert (out / f).exists(), f
        # final.hkl: the bound observations, terminator appended
        hkl = (out / "final.hkl").read_bytes().decode("ascii")
        assert hkl.startswith("   1   0   0  100.00    2.00")
        assert hkl.rstrip("\r\n").endswith("   0   0   0    0.00    0.00")
        # final.ins: a restart deck (L.S. + ACTA), not a bare copy of the res
        ins = (out / "final.ins").read_text(encoding="utf-8")
        keys = [ln.split()[0] for ln in ins.splitlines() if ln.strip()]
        assert "L.S." in keys and "ACTA" in keys and "HKLF" in keys
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        files = rep["files"]
        assert files["final.hkl"]["from"] == str(tmp_path / "crystal.hkl")
        assert files["final.hkl"]["terminator_added"] is True
        assert files["final.hkl"]["n_reflections"] == 3
        assert files["final.ins"]["from"].startswith("final.res + command block")
        assert files["final.p4p"]["absent"] is True
        assert "cannot be derived from the model" in files["final.p4p"]["note"]
        assert rep["cif_grade"]["grade"] == "shelxl-acta"
        man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        for f in ("final.ins", "final.hkl"):
            assert f in man["files"], f
        assert man["provenance"]["final.hkl"]["terminator_added"] is True
        mc = man["manual_continuation"]
        assert mc["ready"] is True and mc["missing"] == ["final.p4p"]
        assert r.summary["manual_continuation"] == mc
        assert r.summary["cif_grade"] == "shelxl-acta"
        assert r.summary["file_provenance"]["final.hkl"] == str(tmp_path / "crystal.hkl")

    def test_paired_job_ins_is_the_delivered_deck(self, tmp_path):
        proj = _project(tmp_path)
        job_ins = RES_3ATOMS.replace("FVAR", "L.S. 10\nACTA\nWGHT 0.1\nFVAR", 1)
        (tmp_path / ".crystalpilot" / "refine" / "shelxl" / "job_1"
         / "job.ins").write_text(job_ins, encoding="utf-8")
        r = _write(proj)
        assert r.ok, r.error
        out = tmp_path / "CrystalPilot Results" / "t1"
        assert (out / "final.ins").read_text(encoding="utf-8") == job_ins
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["files"]["final.ins"]["from"].startswith("SHELXL job job_1 job.ins")

    def test_p4p_recorded_at_ingest_is_delivered(self, tmp_path):
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "x.p4p").write_text("CELL 10 10 10 90 90 90 1000\n",
                                      encoding="ascii")
        (vendor / "y.p4p").write_text("CELL 11 11 11 90 90 90 1331\n",
                                      encoding="ascii")
        proj = _project(tmp_path)
        proj.context = {"data": {"vendor_source": str(vendor),
                                 "vendor_p4p": "y.p4p"}}
        r = _write(proj)
        assert r.ok, r.error
        out = tmp_path / "CrystalPilot Results" / "t1"
        assert (out / "final.p4p").read_text(encoding="ascii").startswith("CELL 11")
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert "vendor directory" in rep["files"]["final.p4p"]["from"]
        assert r.summary["manual_continuation"]["missing"] == []
        assert "final.p4p" in r.summary["files"]

    def test_unpaired_node_gets_a_graded_model_cif_not_a_silent_minimal_one(
            self, tmp_path, monkeypatch):
        # no SHELXL on this machine for the test: the zero-cycle job is
        # skipped and the CIF says where its numbers come from instead
        monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(tmp_path / "none" / "shelxl.exe"))
        minimal = "\n".join(ln for ln in ACTA_CIF.splitlines()
                            if not ln.startswith(("_refine_ls_R", "_refine_ls_wR",
                                                  "_refine_ls_goodness"))) + "\n"
        proj = _project(tmp_path, with_job=False, cif_text=minimal)
        nd = proj.nodes.node_dir("n0002")
        meta = json.loads((nd / "node.json").read_text(encoding="utf-8"))
        meta["data"] = {"n_obs": 1200, "n_unique": 400, "r_int": 0.045,
                        "d_min": 0.80, "wavelength": 0.71073, "completeness": 0.99}
        meta["metrics_source"] = {"engine": "SHELXL", "job": "job_gone"}
        (nd / "node.json").write_text(json.dumps(meta), encoding="utf-8")
        r = _write(proj, status="diagnostic")
        assert r.ok, r.error
        assert r.summary["publication_cif"] is False
        assert r.summary["cif_grade"] == "model"
        assert "shelxl.exe not available" in r.summary["zero_cycle_job"]["skipped"]
        out = tmp_path / "CrystalPilot Results" / "t1"
        cif = (out / "final.cif").read_text(encoding="utf-8")
        assert any(ln.startswith("# CrystalPilot delivery cif: model")
                   for ln in cif.splitlines()[:4])
        # the node's own current metrics and data record, tagged with source
        assert "_refine_ls_R_factor_gt            0.0400" in cif
        assert "_diffrn_reflns_av_R_equivalents   0.0450" in cif
        assert "# CrystalPilot statistics block: node n0002 current metrics" in cif
        assert not (out / "final.fcf").exists()
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["cif_grade"]["grade"] == "model"
        assert "_refine_ls_R_factor_gt" in rep["cif_grade"]["added"]
        assert rep["files"]["final.cif"]["from"].startswith("node n0002 model.cif")
        import iotbx.cif
        block = next(iter(iotbx.cif.reader(input_string=cif).model().values()))
        assert str(block["_refine_ls_R_factor_gt"]) == "0.0400"

    def test_diagnostic_seal_without_fcf_checkcif_validation(self, tmp_path,
                                                             monkeypatch):
        """test3-2 18:39: the agent's diagnostic seal was refused for a
        missing final.fcf / checkcif.json, so the user got nothing sealed.
        Those are OPEN ITEMS of a diagnostic delivery, not fatal errors;
        a provisional delivery still needs them for promotion."""
        monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(tmp_path / "none" / "shelxl.exe"))
        proj = _project(tmp_path, with_job=False)
        assert _write(proj, status="diagnostic",
                      unresolved=["twin law not applied"]).ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        assert not (out / "final.fcf").exists()
        (out / "SUMMARY.md").write_text("# 总结\n", encoding="utf-8")
        before = {f.name: f.read_bytes() for f in out.iterdir()}
        r = td.FinalizeDelivery(proj).run(_ctx(), unmet_goals=["no SHELXL job paired"])
        assert r.ok, r.error
        assert r.summary["status"] == "diagnostic" and r.summary["sealed"] is True
        items = {i["item"] for i in r.summary["open_items"]}
        assert {"file:final.fcf", "file:checkcif.json", "file:VALIDATION.md",
                "unresolved#1", "unmet_goal#1"} <= items
        assert r.summary["missing_inputs"] and \
            r.summary["missing_inputs"][0]["item"] == "file:final.p4p"
        # nothing already delivered was touched except the status headers
        for name, raw in before.items():
            if name in ("final.cif", "REPORT.json", "MANIFEST.json"):
                continue
            assert (out / name).read_bytes() == raw, name
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["status"] == "diagnostic"
        assert rep["finalized"]["missing_inputs"][0]["item"] == "file:final.p4p"
        assert "file:final.fcf" in {i["item"] for i in rep["finalized"]["open_items"]}
        cif = (out / "final.cif").read_text(encoding="utf-8")
        assert td.read_status_header(cif) == "diagnostic"
        assert any(ln.startswith("# CrystalPilot delivery cif: model")
                   for ln in cif.splitlines()[:4])
        # the same directory as a PROVISIONAL delivery is still refused
        proj2 = _project(tmp_path / "p2", with_job=False)
        assert _write(proj2).ok
        out2 = tmp_path / "p2" / "CrystalPilot Results" / "t1"
        (out2 / "SUMMARY.md").write_text("# 总结\n", encoding="utf-8")
        r2 = td.FinalizeDelivery(proj2).run(_ctx())
        assert not r2.ok and "final.fcf" in r2.error and "nothing was changed" in r2.error

    def test_linked_job_pairs_despite_riding_h_drift(self, tmp_path):
        """test3-2 18:35: after adopt re-derived the riding H in-process,
        the job's H coordinates differed from the node's in the 4th
        decimal and the newest job no longer 'matched' - the delivery
        fell back to the minimal model CIF. The node's linked job
        (metrics_source.job) pairs with H excluded from the coordinate
        leg; the non-H atoms must still agree."""
        drifted = RES_3ATOMS.replace("H1 2 0.3 0.3 0.3", "H1 2 0.3012 0.2991 0.3007")
        proj = _project(tmp_path, job_res_text=drifted)
        nd = proj.nodes.node_dir("n0002")
        meta = json.loads((nd / "node.json").read_text(encoding="utf-8"))
        meta["metrics_source"] = {"engine": "SHELXL", "job": "job_1"}
        (nd / "node.json").write_text(json.dumps(meta), encoding="utf-8")
        r = _write(proj)
        assert r.ok, r.error
        assert r.summary["publication_cif"] is True
        assert r.summary["shelxl_job"] == "job_1"
        rep = json.loads((tmp_path / "CrystalPilot Results" / "t1" / "REPORT.json")
                         .read_text(encoding="utf-8"))
        jm = rep.get("job_match") or {}
        assert jm.get("linked_job") == "job_1" and jm.get("via") == "node metrics_source"
        assert jm["riding_h_tolerance"]["h_not_compared"] is True
        assert jm["riding_h_tolerance"]["n_h_drifted"] == 1
        # a heavy atom that moved is still a mismatch, linked or not
        moved = RES_3ATOMS.replace("C1 1 0.1 0.1 0.1", "C1 1 0.1100 0.1 0.1")
        proj2 = _project(tmp_path / "p2", job_res_text=moved)
        nd2 = proj2.nodes.node_dir("n0002")
        meta2 = json.loads((nd2 / "node.json").read_text(encoding="utf-8"))
        meta2["metrics_source"] = {"engine": "SHELXL", "job": "job_1"}
        (nd2 / "node.json").write_text(json.dumps(meta2), encoding="utf-8")
        r2 = _write(proj2, status="diagnostic")
        assert r2.ok, r2.error
        assert r2.summary["publication_cif"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
