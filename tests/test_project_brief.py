"""pa1 fix list P1-9: get_project_brief reflects the DECLARED space group
(with provenance and confirmation state) and carries an experiment line.

Evidence (workdir/campaigns/pa1-hex/hex-l2-r2/logs/rollout.jsonl): after
change_space_group declared 'R -3 m :H' on the atomless session the brief
still printed model.space_group 'P 6/m m m'; after the next declaration
('P -3 m 1') it printed 'R -3 m :H'. cage-l2-r1 / cu-l3-r2 briefs showed
the vendor ins's 'P 1 21/c 1' / the placeholder 'P 1' as plain facts.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cctbx import crystal, sgtbx, xray

from crystalpilot.refine.tools_extra import (GetProjectBrief,
                                             experiment_line,
                                             symmetry_brief)

CELL_HEX = (39.5, 39.5, 16.7, 90, 90, 120)
CELL_ORTHO = (10.669, 28.8515, 31.1309, 90, 90, 90)


def _start_ins(path: Path, cell, symbol: str) -> None:
    """A SHELX start model carrying the LATT/SYMM of `symbol` - what
    change_space_group's atomless declaration writes."""
    from crystalpilot.refine.tools_shelxl import shelx_latt_symm
    latt, symm = shelx_latt_symm(sgtbx.space_group_info(symbol).group())
    path.write_text(
        "TITL start\nCELL 0.71073 " + " ".join(str(x) for x in cell)
        + "\nZERR 1 0 0 0 0 0 0\n" + f"LATT {latt}\n" + "\n".join(symm)
        + ("\n" if symm else "") + "SFAC C H N O\nUNIT 4 4 4 4\nHKLF 4\nEND\n",
        encoding="ascii")


class _Nodes:
    def __init__(self, rows, active):
        self.rows, self.active = rows, active

    def list_nodes(self, limit=50):
        return {"nodes": self.rows[-limit:], "active_node": self.active,
                "active_branch": "main", "branches": {"main": self.active}}


class _Proj:
    def __init__(self, d: Path, context: dict, rows=None, active="n0002",
                 merge_stats=None, write_context=True):
        d.mkdir(exist_ok=True)
        self.dir = d
        self.context = context
        self.hkl_path = d / "crystal.hkl"
        self.start_model_path = d / "start.ins"
        self.merge_stats = merge_stats
        self.nodes = _Nodes(rows or [], active)
        if write_context:
            (d / "context.json").write_text(json.dumps(context),
                                            encoding="utf-8")

    def experiment(self):
        return dict(self.context.get("experiment") or {})


def _session(model_symbol: str, declared_symbol: str, cell,
             atoms=(), merge_info=None):
    cs_model = crystal.symmetry(unit_cell=cell, space_group_symbol=model_symbol)
    xs = xray.structure(crystal_symmetry=cs_model)
    for i, (el, site) in enumerate(atoms):
        xs.add_scatterer(xray.scatterer(label=f"{el}{i + 1}", site=site,
                                        scattering_type=el))
    cs_decl = crystal.symmetry(unit_cell=cell,
                               space_group_symbol=declared_symbol)
    return SimpleNamespace(model=xs, symmetry=cs_decl,
                           dataset=SimpleNamespace(wavelength=0.68883),
                           flags={}, merge_info=merge_info or {})


def _brief(proj, ses):
    r = GetProjectBrief(proj).run(SimpleNamespace(session=ses))
    assert r.ok, r.error
    return r.summary


class TestDeclaredSpaceGroup:
    def test_declaration_beats_the_stale_model_symmetry(self, tmp_path):
        """hex-l2-r2 replay: ingest recorded the vendor ins's P6/mmm, the
        agent declared R-3m (start.ins rewritten, session re-merged), the
        model object still says P6/mmm."""
        ctx = {"symmetry": {"space_group": "P 6/m m m",
                            "source": "vendor start model start.ins "
                                      "LATT/SYMM - unverified here",
                            "confirmed": False}}
        proj = _Proj(tmp_path / "p", ctx,
                     merge_stats={"space_group": "P 6/m m m",
                                  "n_unique": 30000, "r_int": 0.55})
        _start_ins(proj.start_model_path, CELL_HEX, "R -3 m :H")
        ses = _session("P 6/m m m", "R -3 m :H", CELL_HEX,
                       merge_info={"space_group": "R -3 m :H",
                                   "n_unique": 6930, "r_int": 0.6233})
        s = _brief(proj, ses)
        sym = s["symmetry"]
        assert sym["declared_space_group"] == "R -3 m :H"
        assert s["model"]["space_group"] == "R -3 m :H"
        assert sym["model_space_group"] == "P 6/m m m"
        assert "still carries P 6/m m m" in sym["stale_model_symmetry"]
        assert "change_space_group" in sym["source"]
        assert "P 6/m m m" in sym["source"]        # what ingest had recorded
        assert sym["confirmed"] is False
        assert sym["status"].startswith("UNCONFIRMED")
        # data numbers follow the session's merge, not the frozen ones
        assert s["data"]["n_unique"] == 6930 and s["data"]["r_int"] == 0.6233
        assert s["data"]["space_group"] == "R -3 m :H"

    def test_ingest_record_is_echoed_with_its_provenance(self, tmp_path):
        """cage-l2-r1: 'P 1 21/c 1' came from the vendor ins - say so."""
        ctx = {"symmetry": {"space_group": "P 1 21/c 1",
                            "source": "vendor start model a.ins LATT/SYMM "
                                      "- the vendor's or a previous "
                                      "solver's guess, unverified here",
                            "confirmed": False, "ins_guess": None}}
        proj = _Proj(tmp_path / "p", ctx)
        _start_ins(proj.start_model_path, CELL_ORTHO, "P 1 21/c 1")
        ses = _session("P 1 21/c 1", "P 1 21/c 1", CELL_ORTHO)
        sym = _brief(proj, ses)["symmetry"]
        assert sym["declared_space_group"] == "P 1 21/c 1"
        assert "a.ins" in sym["source"] and "unverified" in sym["source"]
        assert "model_space_group" not in sym
        assert sym["confirmed"] is False

    def test_placeholder_start_shows_the_ins_guess(self, tmp_path):
        ctx = {"symmetry": {"space_group": "P -1",
                            "source": "generated atomless start (LATT 1 "
                                      "placeholder ...)",
                            "confirmed": False,
                            "ins_guess": {"file": "start.ins",
                                          "space_group": "P 6/m m m",
                                          "note": "NOT adopted"}}}
        proj = _Proj(tmp_path / "p", ctx)
        _start_ins(proj.start_model_path, CELL_HEX, "P -1")
        ses = _session("P -1", "P -1", CELL_HEX)
        sym = _brief(proj, ses)["symmetry"]
        assert sym["declared_space_group"] == "P -1"
        assert sym["ins_guess"]["space_group"] == "P 6/m m m"
        assert "placeholder" in sym["source"]

    def test_in_session_only_declaration_names_the_fallback(self, tmp_path):
        """No context record, start model untouched (P1) but the session
        was re-merged in Cccm: say it is not persisted."""
        proj = _Proj(tmp_path / "p", {})
        _start_ins(proj.start_model_path, CELL_ORTHO, "P 1")
        ses = _session("P 1", "C c c m", CELL_ORTHO)
        sym = _brief(proj, ses)["symmetry"]
        assert sym["declared_space_group"] == "C c c m"
        assert "in this session only" in sym["source"]
        assert "fall back to P 1" in sym["source"]
        assert sym["model_space_group"] == "P 1"

    def test_unrecorded_start_model_is_flagged_unverified(self, tmp_path):
        """Projects ingested before symmetry records existed."""
        proj = _Proj(tmp_path / "p", {})
        _start_ins(proj.start_model_path, CELL_ORTHO, "C c c m")
        ses = _session("C c c m", "C c c m", CELL_ORTHO)
        sym = _brief(proj, ses)["symmetry"]
        assert "provenance not recorded" in sym["source"]
        assert sym["confirmed"] is False

    def test_refined_model_gives_a_working_confirmation_only(self, tmp_path):
        ctx = {"symmetry": {"space_group": "C c c m",
                            "source": "declared by the agent",
                            "confirmed": False}}
        rows = [{"id": "n0007", "r1": 0.0952, "n_atoms": 27}]
        proj = _Proj(tmp_path / "p", ctx, rows=rows, active="n0007")
        _start_ins(proj.start_model_path, CELL_ORTHO, "C c c m")
        ses = _session("C c c m", "C c c m", CELL_ORTHO,
                       atoms=[("Cu", (0.1, 0.12, 0.2)),
                              ("O", (0.15, 0.2, 0.25))])
        sym = _brief(proj, ses)["symmetry"]
        assert sym["confirmed"] is False
        assert sym["status"].startswith("working confirmation only")
        assert "R1 0.0952" in sym["status"]

    def test_recorded_confirmation_is_honoured(self, tmp_path):
        ctx = {"symmetry": {"space_group": "C c c m",
                            "source": "check_symmetry verdict + screen",
                            "confirmed": True}}
        proj = _Proj(tmp_path / "p", ctx)
        _start_ins(proj.start_model_path, CELL_ORTHO, "C c c m")
        ses = _session("C c c m", "C c c m", CELL_ORTHO)
        sym = _brief(proj, ses)["symmetry"]
        assert sym["confirmed"] is True
        assert sym["status"].startswith("confirmed")

    def test_symbol_spelling_does_not_split_one_group(self):
        from crystalpilot.refine.tools_extra import _same_group
        assert _same_group("R -3 m :H", "R -3 m")
        assert _same_group("P 21/c", "P 1 21/c 1")
        assert not _same_group("P 1 21/c 1", "P 1 21/n 1")   # settings differ
        assert not _same_group(None, "P 1")


class TestExperimentLine:
    def test_not_set_with_context_present(self, tmp_path):
        proj = _Proj(tmp_path / "p", {"chemistry": {"metal": "Cu"}})
        ses = _session("P 1", "P 1", CELL_ORTHO)
        line = experiment_line(proj, ses)
        assert line.startswith("experiment: not set (context.json present: "
                               "set_experiment imports it)")
        assert "0.68883" in line
        assert _brief(proj, ses)["experiment_line"] == line

    def test_not_set_without_context(self, tmp_path):
        proj = _Proj(tmp_path / "p", {}, write_context=False)
        line = experiment_line(proj, None)
        assert line.startswith("experiment: not set (no context.json)")

    def test_summary_line_when_metadata_exist(self, tmp_path):
        ctx = {"experiment": {
            "temperature_K": 100.0,
            "instrument": {"source": "synchrotron",
                           "diffractometer": "Rigaku XtaLAB Synergy"},
            "absorption": {"type": "multi-scan", "t_min": 0.69, "t_max": 1.0},
            "crystal": {"colour": "yellow", "size_mm": [0.2, 0.1, 0.05]}}}
        proj = _Proj(tmp_path / "p", ctx)
        ses = _session("P 1", "P 1", CELL_ORTHO)
        line = experiment_line(proj, ses)
        assert line.startswith("experiment: lambda 0.68883 A, T 100.0 K, "
                               "synchrotron, Rigaku XtaLAB Synergy, "
                               "absorption multi-scan T 0.69-1.0, "
                               "size 0.2 x 0.1 x 0.05 mm, yellow")
        assert "missing" not in line
        partial = _Proj(tmp_path / "q", {"experiment": {"temperature_K": 150}})
        line2 = experiment_line(partial, ses)
        assert "T 150 K" in line2 and "missing: absorption, crystal" in line2

    def test_awaiting_data_brief_carries_the_line(self, tmp_path):
        proj = _Proj(tmp_path / "p", {})
        proj.session = None
        r = GetProjectBrief(proj).run(SimpleNamespace(session=None))
        assert r.ok, r.error
        assert r.summary["state"] == "awaiting_data"
        assert r.summary["experiment_line"].startswith("experiment: not set")


def test_symmetry_brief_survives_a_session_without_symmetry(tmp_path):
    proj = _Proj(tmp_path / "p", {})
    ses = SimpleNamespace(model=xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=CELL_ORTHO, space_group_symbol="P 1")), symmetry=None)
    out = symmetry_brief(proj, ses, None)
    assert out["declared_space_group"] == "P 1"
    assert out["confirmed"] is False
