"""pa2 regression fixes: absence evidence with a null comparison, the
change_space_group absence gate, SHELXT budget semantics, mask decision
wording, minimal-CIF Z, duplicate labels, and the better-node warning.

Every case here is a pa2 log line: hex-l2-r2 declared R-3 on noise,
cage-l0-r2 lost two nodes to a label collision and four write_outputs
calls to Z=1, both cage cells dropped a working mask, seven SHELXT calls
timed out on -m >= 300.
"""
from __future__ import annotations

import random
import textwrap
from types import SimpleNamespace

import pytest
from cctbx import crystal, miller, sgtbx, xray
from cctbx.array_family import flex

CELL = (10.0, 12.0, 14.0, 90.0, 90.0, 90.0)


def _data(absent_scale: float, noise_only: bool = False, seed: int = 1):
    rng = random.Random(seed)
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="P 1")
    ms = miller.build_set(cs, anomalous_flag=False, d_min=1.2)
    data, sig = flex.double(), flex.double()
    for h, k, l in ms.indices():
        if noise_only:
            i = rng.gauss(0.0, 1.0)
        else:
            i = rng.expovariate(1.0 / 50.0)
            if (h + k) % 2:
                i *= absent_scale
            i += rng.gauss(0.0, 1.0)
        data.append(i)
        sig.append(1.0)
    return miller.array(ms, data, sig).set_observation_type_xray_intensity()


# -- screen ranking -----------------------------------------------------------

class TestScreenRanking:
    def test_true_centring_leads_and_is_marked_absent(self):
        from crystalpilot.refine.sg_screen import screen_space_groups
        res = screen_space_groups(_data(0.0), sgtbx.space_group_info("P 2/m").group(),
                                  max_out=40)
        top = res["candidates"][0]
        assert top["space_group"].startswith("C")
        assert top["absence_evidence"] == "absent" and top["consistent"]
        assert top["absent_to_present_ratio"] < 0.3

    def test_noise_ranks_no_absence_groups_before_undecidable_centring(self):
        from crystalpilot.refine.sg_screen import screen_space_groups
        res = screen_space_groups(_data(1.0, noise_only=True),
                                  sgtbx.space_group_info("P 2/m").group(), max_out=40)
        rows = res["candidates"]
        assert rows[0]["absence_evidence"] == "no_absence_conditions"
        assert rows[0]["space_group"].startswith("P")
        c_rows = [r for r in rows if r["space_group"].startswith("C")]
        assert c_rows and all(r["absence_evidence"] == "undecidable"
                              and not r["consistent"] for r in c_rows)
        assert "undecidable" in res["note"]

    def test_rank_key_orders_the_three_states(self):
        from crystalpilot.refine.sg_screen import absence_rank_key
        rows = [{"space_group": "V", "absence_evidence": "violated",
                 "n_absent_obs": 10},
                {"space_group": "U-big", "absence_evidence": "undecidable",
                 "n_absent_obs": 1000},
                {"space_group": "U-small", "absence_evidence": "undecidable",
                 "n_absent_obs": 10},
                {"space_group": "P", "absence_evidence": "no_absence_conditions",
                 "n_absent_obs": 0},
                {"space_group": "A", "absence_evidence": "absent",
                 "n_absent_obs": 500}]
        order = [r["space_group"] for r in sorted(rows, key=absence_rank_key)]
        assert order == ["A", "P", "U-small", "U-big", "V"]


# -- change_space_group gate ----------------------------------------------------

class TestAbsenceGate:
    def _ses(self, ma):
        return SimpleNamespace(dataset=SimpleNamespace(intensities=ma))

    def test_noise_centring_is_refused_with_the_numbers(self):
        from crystalpilot.refine.tools_symmetry import _absence_gate
        audit, refusal = _absence_gate(self._ses(_data(1.0, noise_only=True)),
                                       sgtbx.space_group("C 2y"), False,
                                       current_group=sgtbx.space_group("P 1"))
        assert audit["verdict"] == "undecidable"
        assert refusal and "refused" in refusal and "centring" in refusal
        assert "accept_absences=true" in refusal

    def test_accept_absences_records_the_override(self):
        from crystalpilot.refine.tools_symmetry import _absence_gate
        audit, refusal = _absence_gate(self._ses(_data(1.0, noise_only=True)),
                                       sgtbx.space_group("C 2y"), True)
        assert refusal is None and audit["accepted_by_caller"] is True

    def test_real_absence_passes(self):
        from crystalpilot.refine.tools_symmetry import _absence_gate
        audit, refusal = _absence_gate(self._ses(_data(0.0)),
                                       sgtbx.space_group("C 2y"), False)
        assert refusal is None and audit["verdict"] == "absent"

    def test_screw_and_glide_only_warn(self):
        # P2(1)/c on noise: unproven, but its classes are small - the tool
        # reports and lets the solution trials decide
        from crystalpilot.refine.tools_symmetry import _absence_gate
        audit, refusal = _absence_gate(self._ses(_data(1.0, noise_only=True)),
                                       sgtbx.space_group_info("P 21/c").group(),
                                       False,
                                       current_group=sgtbx.space_group("P 1"))
        assert refusal is None
        assert audit["verdict"] == "undecidable" and "warning" in audit
        assert "solution trials" in audit["warning"]

    def test_no_new_conditions_never_refuses(self):
        from crystalpilot.refine.tools_symmetry import _absence_gate
        # descending C2/m -> C2 adds no absences: nothing to refuse even on noise
        audit, refusal = _absence_gate(self._ses(_data(1.0, noise_only=True)),
                                       sgtbx.space_group("C 2y"), False,
                                       current_group=sgtbx.space_group("C 2y"))
        assert refusal is None

    def test_dataless_session_is_silent(self):
        from crystalpilot.refine.tools_symmetry import _absence_gate
        assert _absence_gate(SimpleNamespace(dataset=None),
                             sgtbx.space_group("C 2y"), False) == (None, None)


# -- SHELXT budget semantics ------------------------------------------------------

class TestShelxtBudget:
    def test_setting_suffix_is_stripped(self):
        from crystalpilot.refine.tools_shelxl import shelxt_space_group_name
        assert shelxt_space_group_name("R -3 :H") == "R-3"
        assert shelxt_space_group_name("R -3 c :H") == "R-3c"
        assert shelxt_space_group_name("P 1 21/c 1") == "P2(1)_c"

    def test_laue_set_to_number_is_phasing_not_startup(self):
        from crystalpilot.refine.tools_shelxl import RunShelxt
        txt = textwrap.dedent("""\
             Command line parameters:  -t4 -m1000 -d1 -sP6_m job

             Laue group set to number 11:   6/m

              Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N
                1  1000   80.07  0.2210  0.6980  0.5938  0.5938  2.093   606   31.71
            """)
        st = RunShelxt._lxt_status(txt)
        assert st["stage"] == "phasing" and st["laue"] == "6/m"
        assert st["m_iter"] == 1000
        verdict = RunShelxt._phasing_verdict(st, 50.0)
        assert "-m1000" in verdict and "-m100 would be ~5 s" in verdict

    def test_m_is_clamped(self):
        from crystalpilot.refine.tools_shelxl import SHELXT_M_CAP, RunShelxt
        flags = RunShelxt._cli_flags({"n_phase_sets": 1000}, cores=4)
        assert f"-m{SHELXT_M_CAP}" in flags and "-m1000" not in flags
        assert "-m100" in RunShelxt._cli_flags({"n_phase_sets": 100})

    def test_schema_says_per_try(self):
        from crystalpilot.refine.tools_shelxl import RunShelxt
        desc = RunShelxt.params_schema["properties"]["n_phase_sets"]["description"]
        assert "PER TRY" in desc and "NOT the number of phase sets" in desc


# -- mask wording ----------------------------------------------------------------

class TestMaskDecision:
    def test_negative_diagnosis_keeps_the_last_mask(self):
        from crystalpilot.tools.mask_tools import negative_density_diagnosis
        msg = negative_density_diagnosis(1, 9000.0, 18000.0, [1])
        assert "if an earlier mask on this project converged, keep it" in msg
        assert "decide between masked and unmasked on R1/wR2" in msg
        assert "do NOT deliver unmasked" not in msg

    def test_confidence_levels(self):
        from crystalpilot.tools.mask_tools import electron_count_confidence as f
        assert f(True, False, 0.05, None)["level"] == "high"
        assert f(True, False, 0.10, None)["level"] == "medium"
        assert f(True, False, 0.25, None)["level"] == "low"
        assert f(False, False, None, None)["level"] == "low"
        assert f(True, True, 0.05, None)["level"] == "none"
        c = f(True, False, 0.05, -45.0)
        assert c["level"] == "low" and any("moved" in r for r in c["reasons"])

    def test_decision_note_names_the_criterion(self):
        from crystalpilot.tools.mask_tools import MASK_DECISION_NOTE
        assert "R1/wR2" in MASK_DECISION_NOTE
        assert "not a reason to drop the mask" in MASK_DECISION_NOTE


# -- minimal CIF Z, duplicate labels, better nodes ---------------------------------

def _xs(labels, sg="P 21/c"):
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=CELL, space_group_symbol=sg))
    for i, lbl in enumerate(labels):
        el = "".join(ch for ch in lbl if ch.isalpha())[:1] or "C"
        xs.add_scatterer(xray.scatterer(
            label=lbl, scattering_type=el,
            site=(0.1 + 0.05 * i, 0.2, 0.3), u=0.03))
    return xs


def test_minimal_cif_carries_z_and_per_unit_formula(tmp_path):
    from crystalpilot.report.cif import structure_to_cif
    p = tmp_path / "m.cif"
    structure_to_cif(_xs(["C1", "C2", "O1"]), p, z=4)
    text = p.read_text(encoding="utf-8")
    assert "_cell_formula_units_Z         4" in text
    # 3 atoms x 4 general positions / Z 4 = per formula unit C2 O1
    assert "_chemical_formula_sum         'C2 O1'" in text
    structure_to_cif(_xs(["C1"]), p)
    assert "_cell_formula_units_Z         1" in p.read_text(encoding="utf-8")


def test_duplicate_labels_are_a_clear_error(tmp_path):
    from crystalpilot.io.shelx_model import (duplicate_atom_labels,
                                             load_res_model)
    res = textwrap.dedent("""\
        TITL t
        CELL 0.71073 10 12 14 90 90 90
        ZERR 4 0 0 0 0 0 0
        LATT 1
        SFAC C H
        UNIT 8 8
        FVAR 1
        C1 1 0.1 0.2 0.3 11 0.03
        H1 2 0.15 0.2 0.3 11 0.04
        H1 2 0.12 0.25 0.3 11 0.04
        HKLF 4
        END
        """)
    assert duplicate_atom_labels(res.splitlines(), 2) == ["H1"]
    p = tmp_path / "model.res"
    p.write_text(res, encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        load_res_model(p)
    assert "duplicate atom labels ['H1']" in str(ei.value)
    assert "%i" not in str(ei.value)


def test_commit_time_dedupe_relabels_later_twins():
    from crystalpilot.refine.nodes import dedupe_scatterer_labels
    xs = _xs(["C1", "H1", "H2", "H1", "H2", "H3"])
    changes = dedupe_scatterer_labels(xs)
    labels = [sc.label for sc in xs.scatterers()]
    assert len(set(l.upper() for l in labels)) == len(labels)
    assert labels[:3] == ["C1", "H1", "H2"]           # first twins keep names
    assert dict(changes) == {"H1": "H4", "H2": "H5"}   # H3 was taken
    assert dedupe_scatterer_labels(xs) == []


def test_better_nodes_does_not_rank_legacy_current_flags():
    from crystalpilot.refine.nodes import better_nodes
    rows = [{"id": "n1", "r1": 0.12, "metrics_current": True, "masked": True,
             "branch": "b", "tool": "refine", "wr2": 0.3, "n_atoms": 50},
            {"id": "n2", "r1": 0.11, "metrics_current": False},   # stale copy
            {"id": "n3", "r1": 0.215, "metrics_current": True},    # inside margin
            {"id": "n4", "r1": None, "metrics_current": True},
            {"id": "n5", "r1": 0.23, "metrics_current": True}]
    out = better_nodes(rows, "n5", 0.23)
    assert out == []  # legacy current flags do not establish matching data/metric definitions
    assert better_nodes(rows, "n5", None) == []


def test_add_hydrogens_rerun_keeps_explicit_h_on_other_carriers():
    from crystalpilot.tools.hydrogen_tools import _partition_existing_h
    cs = crystal.symmetry(unit_cell=(12, 12, 12, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in (("C1", "C", (0.10, 0.10, 0.10)),
                          ("H1", "H", (0.10 + 1.0 / 12, 0.10, 0.10)),   # C-H
                          ("O1", "O", (0.50, 0.50, 0.50)),
                          ("HW1", "H", (0.50 + 0.96 / 12, 0.50, 0.50)),  # O-H
                          ("H9", "H", (0.85, 0.85, 0.85))):             # stray
        xs.add_scatterer(xray.scatterer(label=lbl, scattering_type=el,
                                        site=site, u=0.03))
    keep, strip = _partition_existing_h(xs, ["C"], {}, {})
    assert sorted(strip) == ["H1", "H9"]
    assert keep == [{"h": "HW1", "carrier": "O1", "carrier_element": "O"}]
    # asking for O too, or having made HW1 earlier, replaces it as before
    assert "HW1" in _partition_existing_h(xs, ["C", "O"], {}, {})[1]
    assert "HW1" in _partition_existing_h(
        xs, ["C"], {}, {"per_carrier": [{"carrier": "O1", "h": ["HW1"]}]})[1]
    assert "HW1" in _partition_existing_h(xs, ["C"], {"O1": "OH"}, {})[1]


def test_agent_facing_text_carries_the_new_semantics():
    """The pa2/pa3 fix-wave semantics must reach the agent SOMEWHERE it
    reads: the AGENTS template or the tool descriptions/schemas. v33
    (2026-09-04) moved the per-tool recipes out of the template on purpose -
    the ka1 ablation showed both arms took the same judgment from the tool
    returns - so this guard checks template + registered tool specs, and
    only fails when a semantic vanished from both."""
    import re

    from crystalpilot.workbench.agents_md import TEMPLATE, VERSION_MARKER
    from test_agents_md import _registered_specs_text
    # v33 or later: the template/spec union guard is version-agnostic
    assert int(re.search(r"v(\d+)", VERSION_MARKER).group(1)) >= 33
    haystack = TEMPLATE + "\n" + _registered_specs_text()
    # (absence_evidence / electron_count_confidence are RESULT fields - they
    # are exercised directly above, not looked for in agent-facing text)
    for needle in ("accept_absences", "better_nodes", "acknowledge_real",
                   "r1_fence_informative", "probe_site", "mask='auto'",
                   "phasing_grace_s", "job_status", "metal_bonded_light_atom",
                   "mask_diagnosis", "decisions", "accept_label_mismatch",
                   "n_phase_sets"):
        assert needle in haystack, needle
    # the two rules that map to failure cells stay in the template itself
    for needle in ("composition=", "laue_group='all'", "check_symmetry",
                   "adopt_wght", "不杀进程"):
        assert needle in TEMPLATE, needle
