"""Mentor-side grader: delivery location, self-consistency gates, reindex
search, fallback mode. Reference-based layers use tiny synthetic fixtures."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.benchmark import grade as G

MINI_CIF = """\
data_test
_cell_length_a     10.000
_cell_length_b     11.000
_cell_length_c     12.000
_cell_angle_alpha  90.000
_cell_angle_beta   95.000
_cell_angle_gamma  90.000
_space_group_name_H-M_alt  'P 21/c'
_chemical_formula_sum  'C2 O2 Cu1'
_cell_formula_units_Z  4
_refine_ls_R_factor_gt  0.0400
_refine_ls_wR_factor_ref  0.1000
_refine_ls_goodness_of_fit_ref  1.050
_refine_ls_number_parameters  50
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 Cu1 Cu 0.2500 0.2500 0.2500 1.0
 O1 O 0.4000 0.3000 0.2000 1.0
 O2 O 0.1000 0.2000 0.3500 1.0
 C1 C 0.5000 0.4000 0.1500 1.0
 C2 C 0.0000 0.1000 0.4000 1.0
"""


def _fcf_for(r1_target: float) -> str:
    # LIST-4 rows: h k l Fc2 Fo2 sigma; craft |sqrt(Fo2)-sqrt(Fc2)| sums to
    # the wanted R1 with strong reflections (Fo2 >> 2 sigma)
    rows = []
    fo = 100.0
    fc = (fo ** 0.5 * (1 - r1_target)) ** 2
    for i in range(1, 11):
        rows.append(f"   {i}   0   0 {fc:9.2f} {fo:9.2f}      1.00")
    return "\n".join(rows) + "\n"


MINI_RES = """\
TITL test
CELL 0.71073 10.000 11.000 12.000 90.000 95.000 90.000
ZERR 4 0.001 0.001 0.001 0.0 0.01 0.0
LATT 1
SYMM -X, Y+1/2, -Z+1/2
SFAC C O CU
UNIT 8 8 4
L.S. 10
ACTA
FVAR 1.0
CU1 3 0.2500 0.2500 0.2500 11.0 0.03
HKLF 4
END
"""


def _mk_delivery(tmp_path, cif=MINI_CIF, r1_fcf=0.04, report_r1=0.04,
                 with_report=True, complete=True, alerts=()):
    """A delivery in the standard layout. complete=True writes the whole
    file set (final.res, checkcif.json, VALIDATION.md, SUMMARY.md) so a
    grade can reach publication; `alerts` seeds the delivered
    checkcif.json ({code, type, level, text} rows)."""
    proj = tmp_path / "proj"
    d = proj / "CrystalPilot Results" / "task_1"
    d.mkdir(parents=True)
    (d / "final.cif").write_text(cif, encoding="utf-8")
    (d / "final.fcf").write_text(_fcf_for(r1_fcf), encoding="utf-8")
    if with_report:
        (d / "REPORT.json").write_text(json.dumps(
            {"metrics": {"r1_strong": report_r1},
             "model": {"n_atoms": 5}, "unresolved": []}), encoding="utf-8")
    if complete:
        (d / "final.res").write_text(MINI_RES, encoding="utf-8")
        (d / "checkcif.json").write_text(json.dumps(
            {"counts": {"A": sum(1 for a in alerts if a["level"] == "A")},
             "alerts": list(alerts)}), encoding="utf-8")
        (d / "VALIDATION.md").write_text(
            "# VALIDATION\n" + "".join(f"- {a['code']}: explained\n"
                                       for a in alerts), encoding="utf-8")
        (d / "SUMMARY.md").write_text("# SUMMARY\n", encoding="utf-8")
    return proj


def test_find_delivery_requires_fcf(tmp_path):
    proj = tmp_path / "p"
    d = proj / "CrystalPilot Results" / "task_1"
    d.mkdir(parents=True)
    (d / "final.cif").write_text(MINI_CIF, encoding="utf-8")
    assert G.find_delivery(proj) is None          # cif alone is no delivery
    (d / "final.fcf").write_text(_fcf_for(0.04), encoding="utf-8")
    assert G.find_delivery(proj) == d / "final.cif"


def test_no_delivery_grade(tmp_path):
    r = G.grade_delivery(tmp_path, out_dir=tmp_path / "out")
    assert r["grade"] == "no_delivery"


def test_self_consistent_pass_and_outputs(tmp_path):
    proj = _mk_delivery(tmp_path)
    out = tmp_path / "out"
    r = G.grade_delivery(proj, out_dir=out, run_checkcif=False, run_reproduce=False)
    assert r["grade"] == "self_consistent_pass"
    sc = r["self_consistency"]
    assert sc["s2_cif_matches_fcf"] is True
    assert sc["s3_report_matches_cif"] is True
    assert sc["cif"]["space_group"] == "P 21/c"
    assert (out / "grade.json").exists() and (out / "GRADE.md").exists()
    # grades never land inside the project directory
    assert not list(proj.rglob("grade.json"))


def test_fcf_mismatch_fails_consistency(tmp_path):
    # CIF claims 0.04 but the fcf reproduces ~0.09 -> cooked number
    proj = _mk_delivery(tmp_path, r1_fcf=0.09)
    r = G.grade_delivery(proj, out_dir=tmp_path / "out", run_checkcif=False, run_reproduce=False)
    assert r["self_consistency"]["s2_cif_matches_fcf"] is False
    assert r["grade"] == "self_consistent_fail"


def test_report_mismatch_fails_consistency(tmp_path):
    proj = _mk_delivery(tmp_path, report_r1=0.06)
    r = G.grade_delivery(proj, out_dir=tmp_path / "out", run_checkcif=False, run_reproduce=False)
    assert r["self_consistency"]["s3_report_matches_cif"] is False
    assert r["grade"] == "self_consistent_fail"


def test_peek_report_flags_reference_files(tmp_path):
    proj = _mk_delivery(tmp_path)
    d = next(proj.glob("CrystalPilot Results/*"))
    (d / "reference_COD_1234567.cif").write_text("x", encoding="utf-8")
    (d / "transcript.jsonl").write_text(
        json.dumps({"cmd": "curl http://www.crystallography.net/cod/x.cif"}),
        encoding="utf-8")
    r = G.grade_delivery(proj, out_dir=tmp_path / "out", run_checkcif=False, run_reproduce=False)
    pk = r["self_consistency"]["peek_report"]
    assert not pk["clean"]
    assert any("reference_COD" in f for f in pk["suspect_files"])
    assert any(h["pattern"] == r"crystallography\.net"
               for h in pk["transcript_hits"])
    # report-level only: peeking does not change the grade by itself
    assert r["grade"] == "self_consistent_pass"


def test_peek_report_ignores_json_escaped_reference_key(tmp_path):
    """The e-statistics tool emits {"reference": {...}} in its output; in a
    JSONL transcript that key appears as \\"reference\\" and must not trip
    the peek gate (real false positive from r11 case-b)."""
    proj = _mk_delivery(tmp_path)
    d = next(proj.glob("CrystalPilot Results/*"))
    inner = json.dumps({"e_statistics": {
        "mean_abs_e2_minus_1": 1.024,
        "reference": {"centrosymmetric": 0.968}}})
    (d / "transcript.jsonl").write_text(
        json.dumps({"output": inner}), encoding="utf-8")
    r = G.grade_delivery(proj, out_dir=tmp_path / "out", run_checkcif=False, run_reproduce=False)
    assert r["self_consistency"]["peek_report"]["clean"]


def test_peek_report_still_catches_reference_paths(tmp_path):
    proj = _mk_delivery(tmp_path)
    d = next(proj.glob("CrystalPilot Results/*"))
    # JSONL-escaped Windows path: reference\\answer.cif inside a JSON string
    (d / "transcript.jsonl").write_text(
        json.dumps({"cmd": "type H:\\refs\\reference\\answer.cif"}),
        encoding="utf-8")
    r = G.grade_delivery(proj, out_dir=tmp_path / "out", run_checkcif=False, run_reproduce=False)
    pk = r["self_consistency"]["peek_report"]
    assert not pk["clean"]
    assert pk["transcript_hits"]


def test_peek_report_exempts_skill_card_lines(tmp_path):
    """Skill cards cite CCDC/COD teaching URLs; a read_skill tool event
    quoting one must not trip the gate (r13 false hit), while the same
    URL on a non-skill line still does."""
    proj = _mk_delivery(tmp_path)
    d = next(proj.glob("CrystalPilot Results/*"))
    skill_line = json.dumps({
        "kind": "tool_completed", "tool": "read_skill",
        "result": "CCDC 教学 https://www.ccdc.cam.ac.uk/media/x.pdf"})
    (d / "transcript.jsonl").write_text(skill_line + "\n", encoding="utf-8")
    r = G.grade_delivery(proj, out_dir=tmp_path / "out", run_checkcif=False, run_reproduce=False)
    assert r["self_consistency"]["peek_report"]["clean"]

    browse_line = json.dumps({
        "kind": "command_completed",
        "output": "GET https://www.ccdc.cam.ac.uk/structures/Search?x"})
    (d / "transcript.jsonl").write_text(
        skill_line + "\n" + browse_line + "\n", encoding="utf-8")
    r = G.grade_delivery(proj, out_dir=tmp_path / "out2", run_checkcif=False, run_reproduce=False)
    pk = r["self_consistency"]["peek_report"]
    assert not pk["clean"]
    assert pk["transcript_hits"][0]["count"] == 1  # skill line not counted


def test_non_ascii_cif_still_grades(tmp_path):
    """CIF 1.1 is ASCII-only and iotbx's lexer error path explodes on a
    sliced UTF-8 char (r13: 'Mo Kα' in _diffrn_source). The grader must
    sanitize and keep judging."""
    cif = MINI_CIF + "_diffrn_source  'Mo sealed tube, Mo K\u03b1, " \
        "\u03bb = 0.71073 \u00c5'\n"
    proj = _mk_delivery(tmp_path, cif=cif)
    r = G.grade_delivery(proj, out_dir=tmp_path / "out", run_checkcif=False, run_reproduce=False)
    sc = r["self_consistency"]
    assert sc["cif"]["cell"][0] == 10.0
    assert r["grade"] == "self_consistent_pass"


def test_reference_layer_exact_match_grades_publication(tmp_path):
    proj = _mk_delivery(tmp_path)
    ref = tmp_path / "ref.cif"
    # same structure, R1 slightly better than the agent's
    ref.write_text(MINI_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False, run_reproduce=False)
    rl = r["reference_layer"]
    assert rl["sg_type_equal"] is True
    assert rl["emma"]["solved"] is True
    assert rl["cell_compatible"] is True
    assert rl["r1_delta"] == pytest.approx(0.002, abs=1e-6)
    assert r["grade"] == "publication"


def test_large_structure_emma_guard(tmp_path, monkeypatch):
    """400-atom P1 frameworks make full emma matching combinatorial (real
    stall: r12 CD-MOF ground >9 min). Above EMMA_MAX_ATOMS with no usable
    heavy subset, coordinate matching is skipped and phase identity comes
    from cell + SG type + non-H composition (solved_proxy)."""
    proj = _mk_delivery(tmp_path)
    ref = tmp_path / "ref.cif"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    # force the guard on the tiny fixture (its C/N/O atoms hold no Z>=11
    # heavy subset, so the proxy path must engage)
    monkeypatch.setattr(G, "EMMA_MAX_ATOMS", 1)
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False, run_reproduce=False)
    rl = r["reference_layer"]
    assert rl["emma"].get("skipped_large_structure") is True
    assert rl.get("solved_proxy") is True
    assert r["grade"] == "publication"
    md = (tmp_path / "out" / "GRADE.md").read_text(encoding="utf-8")
    assert "相位同一性代理" in md


def test_heavy_subset_selects_by_z():
    from crystalpilot.benchmark.grade import _heavy_subset
    from cctbx.crystal import symmetry as csym
    from cctbx.xray import scatterer, structure

    xs = structure(crystal_symmetry=csym(unit_cell=(10, 10, 10, 90, 90, 90),
                                         space_group_symbol="P 1"))
    for lbl, st, site in (("W1", "W", (0.1, 0.1, 0.1)),
                          ("C1", "C", (0.3, 0.3, 0.3)),
                          ("O1", "O", (0.5, 0.5, 0.5)),
                          ("Na1", "Na", (0.7, 0.7, 0.7))):
        xs.add_scatterer(scatterer(label=lbl, scattering_type=st, site=site))
    sub, n = _heavy_subset(xs)
    assert n == 2
    assert {sc.label for sc in sub.scatterers()} == {"W1", "Na1"}


def test_reference_layer_wrong_structure_below_bar(tmp_path):
    proj = _mk_delivery(tmp_path)
    ref = tmp_path / "ref.cif"
    # different cell entirely -> not the same lattice, not solved
    ref.write_text(
        MINI_CIF.replace("10.000", "17.300").replace("11.000", "9.100")
        .replace("12.000", "23.400"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False, run_reproduce=False)
    assert r["reference_layer"]["emma"].get("solved") is not True
    assert r["grade"] == "below_bar"


def test_literature_kind_ignores_r1(tmp_path):
    proj = _mk_delivery(tmp_path)
    ref = tmp_path / "ref.cif"
    # same structure but much better R1 - exact kind would fail the +0.01 bar
    ref.write_text(MINI_CIF.replace("0.0400", "0.0200"), encoding="utf-8")
    r_exact = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "o1",
                               run_checkcif=False, run_reproduce=False)
    r_lit = G.grade_delivery(proj, reference=ref, reference_kind="literature",
                             out_dir=tmp_path / "o2", run_checkcif=False, run_reproduce=False)
    assert r_exact["grade"] != "publication"
    assert r_lit["grade"] == "publication"
    assert r_lit["reference_layer"]["r1_scored"] is False


def test_charged_scattering_types_stripped(tmp_path):
    # older CIFs type atoms as O-2 / C+2: element classification and emma
    # need bare symbols (live case: cod_8104482 broke the heavy selector)
    from crystalpilot.benchmark.evaluate import load_reference
    p = tmp_path / "charged.cif"
    p.write_text(MINI_CIF.replace(
        " Cu1 Cu ", " Cu1 Cu2+ ").replace(
        " O1 O ", " O1 O2- ").replace(" O2 O ", " O2 O2- "),
        encoding="utf-8")
    xs = load_reference(None, str(p))
    assert xs is not None
    types = sorted({sc.scattering_type for sc in xs.scatterers()})
    assert types == ["C", "Cu", "O"]


def test_emma_survives_thermal_expansion_cell(tmp_path):
    # literature reference at a different temperature: cell lengths differ
    # by ~1.5%, emma used to assert 'incompatible settings' and score 0
    from crystalpilot.benchmark.evaluate import (evaluate_against_reference,
                                                 load_reference)
    p1 = tmp_path / "a.cif"
    p1.write_text(MINI_CIF, encoding="utf-8")
    p2 = tmp_path / "b.cif"
    p2.write_text(MINI_CIF.replace("10.000", "10.150")
                  .replace("11.000", "11.160")
                  .replace("12.000", "12.170"), encoding="utf-8")
    a, b = load_reference(None, str(p1)), load_reference(None, str(p2))
    m = evaluate_against_reference(a, b)
    assert m["solved"] is True
    assert m["all_match_rate"] == 1.0


def test_unimodular_reindex_recovers_setting():
    # p770 live case: same lattice, both settings pass Niggli conditions,
    # related by [[-1,0,1],[0,-1,1],[0,0,1]]
    from cctbx import crystal, xray

    def xs_of(cell, sites):
        cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P -1")
        xs = xray.structure(crystal_symmetry=cs)
        for i, s in enumerate(sites):
            xs.add_scatterer(xray.scatterer(label=f"C{i}", site=s, u=0.03,
                                            scattering_type="C"))
        return xs

    ref = xs_of((10.1638, 12.7284, 20.816, 104.653, 104.046, 96.32),
                [(0.1, 0.2, 0.3), (0.4, 0.1, 0.6)])
    model = xs_of((10.1554, 12.707, 20.801, 107.691, 100.315, 96.233),
                  [(0.1, 0.2, 0.3), (0.4, 0.1, 0.6)])
    cands = G._reindex_onto(model, ref)
    assert cands, "at least one metric-matching operator expected"
    xs2, m, err = cands[0]
    assert err < 0.01
    p2, pr = xs2.unit_cell().parameters(), ref.unit_cell().parameters()
    assert all(abs(x - y) <= 2.0 for x, y in zip(p2[3:], pr[3:]))


def test_reindex_pre_alignment_recovers_setting_flip(tmp_path):
    """r18 live failure: agent delivered the ACUTE setting, reference is
    the OBTUSE one - Niggli parameters agree, so cells were 'compatible'
    and emma ran unaligned (0/2 heavies). The pre-alignment step +
    heavy-atom candidate voting must recover the match."""
    from cctbx import crystal, sgtbx, xray

    def xs_of(cell, sites, els):
        cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P -1")
        xs = xray.structure(crystal_symmetry=cs)
        for i, (s, el) in enumerate(zip(sites, els)):
            xs.add_scatterer(xray.scatterer(label=f"{el}{i}", site=s,
                                            u=0.02, scattering_type=el))
        return xs

    ref = xs_of((10.1638, 12.7284, 20.816, 104.653, 104.046, 96.32),
                [(0.3406, 0.4783, 0.2698), (0.2405, 0.6372, 0.2074),
                 (0.11, 0.22, 0.33)],
                ("La", "Ni", "C"))
    # the agent's acute setting = ref changed by an operator whose metric
    # matches; build it honestly by change_basis so coordinates track
    cb = sgtbx.change_of_basis_op(sgtbx.rt_mx(sgtbx.rot_mx(
        [-1, 0, 0, 0, -1, 0, 1, 1, 1], 1)))
    try:
        model = ref.change_basis(cb)
    except Exception:
        import pytest as _pytest
        _pytest.skip("basis op invalid for this setting")
    from crystalpilot.benchmark.evaluate import evaluate_against_reference

    # unaligned emma is expected to fail or match poorly - that WAS the
    # bug; the candidate list + heavy voting must contain a perfect op
    cands = G._reindex_onto(model, ref)
    assert cands, "metric candidates expected across the setting flip"
    rates = []
    for xs2, m, err in cands:
        e = evaluate_against_reference(G._heavy_subset(xs2)[0],
                                       G._heavy_subset(ref)[0])
        rates.append(e.get("heavy_match_rate") or 0.0)
    assert max(rates) == 1.0, (rates, [m for _, m, _ in cands])


def test_pseudo_degenerate_metric_fallback():
    """r14a live-fire: with a ~= b (0.8%), a correctly solved P212121
    structure sat in a quarter-shift-related equivalent description and
    emma graded it 0-matched -> below_bar. Unit-test the fallback's two
    mechanics directly: per-atom symmetry-copy scatter (orbit membership,
    t=0) and a whole-model quarter shift of a T-closed motif (translation
    grid). The real-world emma->fallback handoff is validated by the r14a
    regrade itself."""
    from cctbx import crystal, xray
    from crystalpilot.benchmark.evaluate import _pseudo_degenerate_match

    cs = crystal.symmetry(unit_cell=(13.687, 13.7912, 15.2165, 90, 90, 90),
                          space_group_symbol="P 21 21 21")
    base = [("Zn1", "Zn", (0.2624, 0.2945, 0.7261)),
            ("O1", "O", (0.31, 0.40, 0.68)),
            ("C1", "C", (0.10, 0.35, 0.55)),
            ("N1", "N", (0.44, 0.30, 0.44))]
    T = (0.25, 0.25, 0.0)
    # T-closed motif: every site is present together with its +T partner
    sites = base + [(f"{lab}b", el, tuple(x + d for x, d in zip(s, T)))
                    for lab, el, s in base]

    def build(shift, scatter_ops):
        xs = xray.structure(crystal_symmetry=cs)
        g = list(cs.space_group())
        for i, (lab, el, s) in enumerate(sites):
            site = tuple(x + d for x, d in zip(s, shift))
            if scatter_ops:
                site = g[i % len(g)] * site
            xs.add_scatterer(xray.scatterer(
                label=lab, site=site, scattering_type=el, u=0.02))
        xs.scattering_type_registry(table="it1992")
        return xs

    ref = build((0, 0, 0), scatter_ops=False)

    # (1) same coordinates, each atom on a different symmetry copy
    m1 = build((0, 0, 0), scatter_ops=True)
    r1 = _pseudo_degenerate_match(ref, m1)
    assert r1 is not None and r1["n_matched"] == len(sites), r1
    assert r1["rms"] < 0.02, r1

    # (2) whole model translated by T (legal here because the motif is
    # T-closed): the translation grid must recover it
    m2 = build(T, scatter_ops=False)
    r2 = _pseudo_degenerate_match(ref, m2)
    assert r2 is not None and r2["n_matched"] == len(sites), r2
    assert r2["rms"] < 0.02, r2

    # gate: a clearly non-degenerate cell returns None
    cs2 = crystal.symmetry(unit_cell=(10, 13, 17, 90, 90, 90),
                           space_group_symbol="P 21 21 21")
    xs_a = xray.structure(crystal_symmetry=cs2)
    xs_a.add_scatterer(xray.scatterer(
        label="Zn1", site=(0.1, 0.2, 0.3), scattering_type="Zn", u=0.02))
    xs_a.scattering_type_registry(table="it1992")
    assert _pseudo_degenerate_match(xs_a, xs_a) is None


class TestModelTransplant:
    """r24 verdict method automated: agent model + reference embedded hkl
    -> separate structure-determination quality from reduction quality."""

    def test_skips_without_embedded_hkl(self, tmp_path):
        ref = tmp_path / "ref.cif"
        ref.write_text("data_r\n_cell_length_a 10.0\n", encoding="utf-8")
        final = tmp_path / "final.cif"
        final.write_text("data_f\n", encoding="utf-8")
        r = G._model_transplant(final, ref, 0.05)
        assert r["skipped"].startswith("reference has no embedded")

    def test_skips_without_final_res(self, tmp_path):
        ref = tmp_path / "ref.cif"
        ref.write_text(
            "data_r\n_shelx_hkl_file\n;\n\n   1   0   0  1.0  0.1\n;\n",
            encoding="utf-8")
        final = tmp_path / "final.cif"
        final.write_text("data_f\n", encoding="utf-8")
        r = G._model_transplant(final, ref, 0.05)
        assert r["skipped"] == "delivery has no final.res"

    def test_live_r24_regrade_artifact(self):
        # the live regrade ran during development; assert its record if
        # present (evidence the arm reproduces the hand verdict), skip on
        # fresh checkouts
        g = G.REPO / "workdir" / "grades" / "r24_regrade" / "grade.json"
        if not g.exists():
            pytest.skip("no live regrade artifact")
        d = json.loads(g.read_text(encoding="utf-8"))
        mt = d.get("model_transplant") or {}
        assert mt.get("r1_on_reference_data") is not None
        assert abs(mt["r1_on_reference_data"] - 0.0909) < 0.01
        assert "publication-grade MODEL" in (mt.get("verdict") or "")


def test_element_identity_gates_the_grade(tmp_path):
    """pa1 hex-l1-r1: a Zn-labelled model on the Zr framework matched the
    reference atom-for-atom (emma is element-blind) and graded acceptable
    at R1 0.082 with the wrong formula, density, F000 and mu."""
    proj = _mk_delivery(tmp_path, cif=MINI_CIF.replace("Cu1 Cu", "Zr1 Zr")
                        .replace("'C2 O2 Cu1'", "'C2 O2 Zr1'"))
    ref = tmp_path / "ref.cif"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False, run_reproduce=False)
    emma = r["reference_layer"]["emma"]
    assert emma["solved"] is True                 # the coordinates still match
    assert emma["metal_identity_ok"] is False
    assert emma["n_heavy_element_mismatch"] == 1
    mm = emma["heavy"]["element_mismatches"][0]
    assert (mm["ref_el"], mm["model_el"], mm["dz"]) == ("Cu", "Zr", 11)
    assert r["grade"] == "below_bar"
    assert any("metal identity" in s for s in r["grade_reasons"])
    md = (tmp_path / "out" / "GRADE.md").read_text(encoding="utf-8")
    assert "Cu→Zr(+11)" in md


def test_same_elements_keep_identity_ok(tmp_path):
    proj = _mk_delivery(tmp_path)
    ref = tmp_path / "ref.cif"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False, run_reproduce=False)
    emma = r["reference_layer"]["emma"]
    assert emma["metal_identity_ok"] is True
    assert emma["n_element_mismatch"] == 0
    assert "grade_reasons" not in r


def test_r1_within_reach_of_the_reference_is_acceptable(tmp_path):
    """pa1 hex-l2-r1: a correct model at R1 0.1057 on data whose reference
    refines to ~0.09 was below_bar on the absolute 0.10 bar alone, while a
    wrong-element 0.0817 passed. Within 0.02 of the reference is acceptable;
    further than that on data over 0.10 is not."""
    proj = _mk_delivery(tmp_path, cif=MINI_CIF.replace("0.0400", "0.1050"),
                        r1_fcf=0.105, report_r1=0.105)
    ref = tmp_path / "ref.cif"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0900"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "o1",
                         run_checkcif=False, run_reproduce=False)
    assert r["reference_layer"]["r1_delta"] == pytest.approx(0.015, abs=1e-6)
    assert r["grade"] == "acceptable"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0800"), encoding="utf-8")
    r2 = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "o2",
                          run_checkcif=False, run_reproduce=False)
    assert r2["grade"] == "below_bar"
    assert any("above 0.10" in s for s in r2["grade_reasons"])


def test_find_delivery_accepts_one_level_deeper_and_flags_layout(tmp_path):
    """pa1 cu-l2-r2 wrote a complete final.cif/fcf into <task>/deliverables/
    and was graded no_delivery: the structure existed, the layout did not."""
    proj = tmp_path / "proj"
    deep = proj / "CrystalPilot Results" / "task_1" / "deliverables"
    deep.mkdir(parents=True)
    (deep / "final.cif").write_text(MINI_CIF, encoding="utf-8")
    (deep / "final.fcf").write_text(_fcf_for(0.04), encoding="utf-8")
    assert G.find_delivery(proj) == deep / "final.cif"
    assert G.delivery_layout(proj, deep / "final.cif") == "nonstandard"
    r = G.grade_delivery(proj, out_dir=tmp_path / "out", run_checkcif=False, run_reproduce=False)
    assert r["delivery_layout"] == "nonstandard"
    # a standard-depth delivery wins over the deeper one
    std = proj / "CrystalPilot Results" / "task_2"
    std.mkdir()
    (std / "final.cif").write_text(MINI_CIF, encoding="utf-8")
    (std / "final.fcf").write_text(_fcf_for(0.04), encoding="utf-8")
    assert G.find_delivery(proj) == std / "final.cif"


# --------------------------------------------------------------------------- #
# P2-17: the mentor-side gaps the pa1 post-mortem listed (§9)
# --------------------------------------------------------------------------- #

def _peek_of(tmp_path, lines, sub="out"):
    proj = _mk_delivery(tmp_path / sub)
    d = next(proj.glob("CrystalPilot Results/*"))
    (d / "transcript.jsonl").write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")
    r = G.grade_delivery(proj, out_dir=tmp_path / sub / "grade",
                         run_checkcif=False, run_reproduce=False)
    return r["self_consistency"]["peek_report"]


def test_peek_ignores_e_statistics_identifiers_but_keeps_reference_files(
        tmp_path):
    """pa1 cage-l2-r1 (10 hits) and cage-l2-r2 (6 hits) were flagged purely
    on the e-statistics field names reference_centric / reference_acentric
    in the agent's own script and its printed output - exactly the lines
    below. Real reference FILES and PATHS must still fire."""
    script = json.dumps({"kind": "command", "cmd":
                         'print("reference_centric=0.968 '
                         'reference_acentric=0.736")'})
    output = json.dumps({"kind": "command_completed", "output": json.dumps(
        {"mean_abs_E2_minus_1": 0.7845, "reference_centric": 0.968,
         "reference_acentric": 0.736})})
    prose = json.dumps({"kind": "message",
                        "text": "a reference-free, reference-based check"})
    assert _peek_of(tmp_path, [script, output, prose], "clean")["clean"]
    for i, hit in enumerate((
            json.dumps({"cmd": "type reference_COD_1234567.cif"}),
            json.dumps({"cmd": "cat ./reference/answer.cif"}),
            json.dumps({"cmd": "cat reference-answer.res"}),
            json.dumps({"cmd": "type reference.cif"}))):
        pk = _peek_of(tmp_path, [hit], f"hit{i}")
        assert not pk["clean"], hit
        assert pk["transcript_hits"][0]["pattern"].startswith("reference")


def test_classify_a_alert_splits_metadata_from_model_quality():
    """Codes and texts verified in the pa1 checkCIF outputs."""
    meta = [("183", "Missing _cell_measurement_reflns_used Value .... Please Do !"),
            ("660", "No Valid _diffrn_radiation_type Value Reported . Please Do !"),
            ("699", "Missing _exptl_crystal_description Value ....... Please Do !"),
            ("018", "_exptl_absorpt_correction_T_max Value Missing ..")]
    model = [("213", "Atom O8 has ADP max/min Ratio ..... 6.6 prolat"),
             ("374", "Long N - N Bond N2 - N3 . 1.76 Ang."),
             ("051", "Mu(calc) and Mu(CIF) Ratio Differs from 1.0 by . 433.59 %"),
             ("602", "Solvent Accessible VOID(S) in Structure ........ ! Check"),
             ("911", "Missing FCF Refl Between Thmin & STh/L=0.600 ... 12 Report")]
    for code, text in meta:
        assert G.classify_a_alert(code, text) == "metadata_missing", code
    for code, text in model:
        assert G.classify_a_alert(code, text) == "model_quality", code
    # PLATON rerun shape: 'A 185 text' rows + blocking_a '185 text' rows
    cc = {"available": True,
          "alerts_abc": ["A 185 Missing _cell_measurement_theta_max Value",
                         "A 213 Atom O8 has ADP max/min Ratio",
                         "B 020 The Value of Rint is Greater Than 0.12"],
          "blocking_a": ["185 Missing _cell_measurement_theta_max Value",
                         "213 Atom O8 has ADP max/min Ratio"]}
    sp = G.checkcif_a_split(cc, Path("nowhere/final.cif"))
    assert sp["source"] == "platon rerun"
    assert [s.split()[0] for s in sp["metadata_missing"]] == ["185"]
    assert [s.split()[0] for s in sp["model_quality"]] == ["213"]
    assert sp["blocking_model_quality"] == ["213"]


def test_metadata_a_alerts_do_not_block_publication_but_model_ones_do(
        tmp_path):
    """pa1 cu-l3-r2 (best model of the batch) rightly lost publication to
    PLAT215; the same gate would have demoted a flawless model for an
    unfilled _exptl_crystal_description. Without a PLATON rerun the split
    reads the delivered checkcif.json."""
    ref = tmp_path / "ref.cif"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    meta = {"code": "699", "type": 1, "level": "A",
            "text": "Missing _exptl_crystal_description Value ....... Please Do !"}
    proj = _mk_delivery(tmp_path / "a", alerts=[meta])
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "a" / "g",
                         run_checkcif=False, run_reproduce=False)
    assert r["grade"] == "publication"
    assert r["checkcif_a_split"]["source"] == "delivered checkcif.json"
    assert r["checkcif_a_split"]["blocking_model_quality"] == []
    assert any(s.startswith("metadata incomplete") and "699" in s
               for s in r["grade_reasons"])
    md = (tmp_path / "a" / "g" / "GRADE.md").read_text(encoding="utf-8")
    assert "元数据缺失（不计分）" in md

    model = {"code": "213", "type": 2, "level": "A",
             "text": "Atom O8 has ADP max/min Ratio ..... 6.6 prolat"}
    proj = _mk_delivery(tmp_path / "b", alerts=[meta, model])
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "b" / "g",
                         run_checkcif=False, run_reproduce=False)
    assert r["grade"] == "acceptable"
    assert r["checkcif_a_split"]["blocking_model_quality"] == ["213"]
    assert any("blocking A alerts (model quality): 213" in s
               for s in r["grade_reasons"])


EMBEDDED_CIF = MINI_CIF + """
_shelx_res_file
;
TITL test
    job.res
CELL 0.71073 10.000 11.000 12.000 90.000 95.000 90.000
SFAC C O CU
UNIT 8 8 4
L.S. 10
ACTA
LIST 4
FVAR 1.0
CU1 3 0.2500 0.2500 0.2500 11.0 0.03
HKLF 4
END
;
_shelx_res_checksum 1234

_shelx_hkl_file
;
   1   0   0  100.00   1.00
   2   0   0   50.00   1.00
   0   0   0    0.00   0.00
;
_shelx_hkl_checksum 5678

_shelx_fab_file
;
1 0 0 3.5000 0.0000
;
_shelx_fab_checksum 9012
"""


def test_reproduce_refinement_extracts_and_parses(tmp_path, monkeypatch):
    """Extraction of the embedded res/hkl/fab into a job SHELXL can run
    with zero cycles, and the R1 readback - with a fake launcher, so the
    test does not need the vendor binary. The ABIN retry covers the pa1
    shape (fab embedded, res without ABIN)."""
    final = tmp_path / "final.cif"
    final.write_text(EMBEDDED_CIF, encoding="utf-8")
    monkeypatch.setattr(G, "_shelxl_exe", lambda: tmp_path / "shelxl.exe")
    r = G._reproduce_refinement(final)
    assert r["skipped"].startswith("no SHELXL")
    (tmp_path / "shelxl.exe").write_text("", encoding="utf-8")

    jobs = []

    def fake_launcher(r1s):
        def run(job, exe, timeout_s):
            jobs.append({"ins": (job / "job.ins").read_text(encoding="utf-8"),
                         "hkl": (job / "job.hkl").read_text(encoding="utf-8"),
                         "fab": (job / "job.fab").read_text(encoding="utf-8")
                         if (job / "job.fab").exists() else None,
                         "timeout": timeout_s})
            r1 = r1s[min(len(jobs) - 1, len(r1s) - 1)]
            (job / "job.lst").write_text(
                f" R1 =  {r1:.4f} for      10 Fo > 4sig(Fo) and  0.0500 for "
                "all      12 data\n", encoding="utf-8")
            return {"returncode": 0, "stdout_tail": ""}
        return run

    monkeypatch.setattr(G, "_run_shelxl_job", fake_launcher([0.0410]))
    r = G._reproduce_refinement(final)
    assert r["reproduced_r1"] == 0.041 and r["r1_cif"] == 0.04
    assert r["delta"] == pytest.approx(0.001) and r["reproducible"] is True
    assert r["fab_embedded"] is True and r["res_has_abin"] is False
    assert "reproduced_r1_with_abin" not in r     # reproduced: no retry
    ins = jobs[0]["ins"]
    assert "L.S. 0" in ins and "L.S. 10" not in ins
    assert "ACTA" not in ins and "LIST" not in ins and "CU1 3" in ins
    assert "   2   0   0   50.00   1.00" in jobs[0]["hkl"]
    assert jobs[0]["fab"].startswith("1 0 0 3.5000")
    assert jobs[0]["timeout"] == 60

    # not reproduced as delivered, reproduced once ABIN is added
    jobs.clear()
    monkeypatch.setattr(G, "_run_shelxl_job", fake_launcher([0.1810, 0.0400]))
    r = G._reproduce_refinement(final)
    assert r["reproducible"] is False and r["reproduced_r1"] == 0.181
    assert r["reproduced_r1_with_abin"] == 0.04
    assert r["reproducible_with_abin"] is True
    assert "ABIN" in jobs[1]["ins"] and "ABIN" not in jobs[0]["ins"]
    assert "packaging defect" in r["note"]

    # no embedded blocks at all -> skipped, never an error
    plain = tmp_path / "plain.cif"
    plain.write_text(MINI_CIF, encoding="utf-8")
    assert "skipped" in G._reproduce_refinement(plain)


def test_replay_checks_delivered_res_separately_from_embedded_model(tmp_path, monkeypatch):
    final = tmp_path / "final.cif"
    final.write_text(EMBEDDED_CIF, encoding="utf-8")
    res = G._embedded_shelx_block(EMBEDDED_CIF, "_shelx_res_file")
    (tmp_path / "final.res").write_text(
        res.replace("L.S. 10", "").replace("0.2500 0.2500 0.2500", "0.2600 0.2500 0.2500"),
        encoding="utf-8")
    exe = tmp_path / "shelxl.exe"
    exe.touch()
    monkeypatch.setattr(G, "_shelxl_exe", lambda: exe)
    calls = []

    def run(job, executable, timeout_s):
        text = (job / "job.ins").read_text(encoding="utf-8")
        assert text.count("L.S. 0") == 1
        assert "ACTA" not in text
        calls.append(text)
        r1 = 0.08 if "0.2600" in text else 0.04
        (job / "job.lst").write_text(f" R1 = {r1:.4f} for 10 Fo > 4sig(Fo)\n", encoding="utf-8")
        return {"returncode": 0}

    monkeypatch.setattr(G, "_run_shelxl_job", run)
    r = G._reproduce_refinement(final)
    assert len(calls) == 2
    assert r["reproducible"] is True
    assert r["delivered_res_reproducible"] is False
    assert r["delivered_res_replay"]["r1"] == 0.08
    blockers, notes = G._mentor_reasons({"reproducibility": r})
    assert any("final.res" in b for b in blockers)
    assert any("separate artifact" in note for note in notes)


def test_reproducibility_arm_is_report_level_in_grade(tmp_path, monkeypatch):
    proj = _mk_delivery(tmp_path, cif=EMBEDDED_CIF)
    monkeypatch.setattr(G, "_reproduce_refinement",
                        lambda final_cif, timeout_s=60: {
                            "r1_cif": 0.04, "reproduced_r1": 0.181,
                            "delta": 0.141, "reproducible": False})
    ref = tmp_path / "ref.cif"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False)
    assert r["reproducibility"]["reproducible"] is False
    assert any("not reproduced by SHELXL" in s for s in r["grade_reasons"])
    assert r["grade"] == "publication"             # a note, not a demotion
    r2 = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out2",
                          run_checkcif=False, run_reproduce=False)
    assert r2["reproducibility"] == {"skipped": "disabled by caller"}


def _node(nid, r1, tool="refine", mask=None, parent=None):
    return {"id": nid, "parent": parent, "tool": tool,
            "metrics": ({"label": f"{tool} {nid}", "r1_strong": r1,
                         "wr2": 0.3, "goof": 1.0} if r1 is not None
                        else None),
            "metrics_current": r1 is not None, "mask": mask,
            "model": {"n_atoms": 26}}


def test_node_tree_report_and_better_node_reason(tmp_path):
    """pa1 hex-l3-r3 delivered R1 0.1851 while its tree held n0034 at 0.080
    with the mask; the grader never looked. Node R1 lives in
    metrics.r1_strong (None on import/edit nodes)."""
    nodes = {"n0000": _node("n0000", None, "import"),
             "n0034": _node("n0034", 0.080, mask={"params": {}}),
             "n0044": _node("n0044", 0.092, mask={"params": {}}),
             "n0075": _node("n0075", 0.1851, "run_shelxl")}
    nt = G.node_tree_report(nodes, 0.1851, "n0075")
    assert (nt["best_node_id"], nt["best_node_r1"]) == ("n0034", 0.080)
    assert nt["best_node_masked"] is True
    assert nt["delivered_node_r1"] == 0.1851
    assert nt["delivered_r1_source"] == "node metrics"
    assert nt["delivery_vs_best_delta"] == pytest.approx(0.1051)
    assert nt["better_node_existed"] is True
    # unknown delivered node: the CIF R1 stands in
    nt2 = G.node_tree_report(nodes, 0.085, None)
    assert nt2["delivered_r1_source"] == "final.cif"
    assert nt2["better_node_existed"] is False
    assert "note" in G.node_tree_report({"n0000": nodes["n0000"]}, 0.1, None)

    # through grade_delivery: node.json files under the project
    proj = _mk_delivery(tmp_path)
    for nid, n in nodes.items():
        nd = proj / ".crystalpilot" / "refine" / "nodes" / nid
        nd.mkdir(parents=True)
        (nd / "node.json").write_text(json.dumps(n), encoding="utf-8")
    rep = proj / "CrystalPilot Results" / "task_1" / "REPORT.json"
    rep.write_text(json.dumps({"final_node": "n0075",
                               "metrics": {"r1_strong": 0.04},
                               "model": {"n_atoms": 5}, "unresolved": []}),
                   encoding="utf-8")
    ref = tmp_path / "ref.cif"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False, run_reproduce=False)
    assert r["node_tree"]["best_node_id"] == "n0034"
    assert r["node_tree"]["delivered_node_id"] == "n0075"
    assert any(s.startswith("a better node existed: n0034")
               for s in r["grade_reasons"])
    assert r["grade"] == "publication"             # report-level only
    md = (tmp_path / "out" / "GRADE.md").read_text(encoding="utf-8")
    assert "树里有更好的节点" in md


POROUS_CIF = """\
data_porous
_cell_length_a     20.000
_cell_length_b     20.000
_cell_length_c     20.000
_cell_angle_alpha  90.000
_cell_angle_beta   90.000
_cell_angle_gamma  90.000
_space_group_name_H-M_alt  'P 1'
_chemical_formula_sum  'O1 Cu1'
_cell_formula_units_Z  1
_refine_ls_R_factor_gt  0.0400
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 Cu1 Cu 0.5000 0.5000 0.5000 1.0
 O1 O 0.5950 0.5000 0.5000 1.0
"""
MASK_LOOP = """
loop_
 _platon_squeeze_void_nr
 _platon_squeeze_void_average_x
 _platon_squeeze_void_average_y
 _platon_squeeze_void_average_z
 _platon_squeeze_void_volume
 _platon_squeeze_void_count_electrons
 1 0.000 0.000 0.000 7000.0 400.0
"""


#: what PLATON's 602 looks like coming back from an independent rerun
VOID_RERUN = {"available": True,
              "alerts_abc": ["B 602 VERY LARGE Solvent Accessible VOID(S)"]}


def test_porosity_flag_needs_void_without_mask_or_guests(tmp_path):
    """pa1: four hex deliveries were the bare framework in a 79 % void with
    no mask (the tool's silent 0 e read as 'data do not support a mask').
    Whether the void is reportable is PLATON's call (601/602/604/605), read
    back from its output; a mask block or modelled guest fragments then
    clear the flag, and with no PLATON result the check is not_checked."""
    from crystalpilot.benchmark.evaluate import load_reference
    bare = tmp_path / "bare.cif"
    bare.write_text(POROUS_CIF, encoding="utf-8")
    po = G.porosity_report(bare, load_reference(None, str(bare)), VOID_RERUN)
    assert po["void_fraction"] > 0.8 and po["n_voids"] >= 1
    assert po["mask_block_in_cif"] is False and po["n_guest_fragments"] == 0
    assert [a["code"] for a in po["platon_void_alerts"]] == ["602"]
    assert po["platon_source"] == "platon rerun"
    assert po["porous_unmasked_unmodelled"] is True

    # the same 79 % void with no PLATON verdict is an unknown, not a flag:
    # the 30 % constant this used to apply was a rewrite of PLATON's rule
    po = G.porosity_report(bare, load_reference(None, str(bare)))
    assert po["void_fraction"] > 0.8
    assert po["porous_unmasked_unmodelled"] is None
    assert po["porosity_check"] == "not_checked"

    masked = tmp_path / "masked.cif"
    masked.write_text(POROUS_CIF + MASK_LOOP, encoding="utf-8")
    po = G.porosity_report(masked, load_reference(None, str(masked)),
                           VOID_RERUN)
    assert po["mask_block_in_cif"] is True
    assert po["porous_unmasked_unmodelled"] is False

    guest = tmp_path / "guest.cif"
    guest.write_text(POROUS_CIF + " C1 C 0.1000 0.1000 0.1000 1.0\n"
                     " C2 C 0.1700 0.1000 0.1000 1.0\n", encoding="utf-8")
    po = G.porosity_report(guest, load_reference(None, str(guest)),
                           VOID_RERUN)
    assert po["n_guest_fragments"] == 1
    assert po["porous_unmasked_unmodelled"] is False

    # oversize structures are skipped with a note, never computed
    from cctbx import crystal, xray
    big = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=(30, 30, 30, 90, 90, 90), space_group_symbol="P 1"))
    for i in range(G.CHEM_MAX_P1_ATOMS + 1):
        big.add_scatterer(xray.scatterer(
            label=f"C{i}", scattering_type="C",
            site=((i % 13) / 13.0, (i // 13 % 13) / 13.0, (i // 169) / 13.0)))
    assert "skipped" in G.porosity_report(bare, big, VOID_RERUN)

    # and through the grader a delivered PLAT602 blocks publication
    proj = _mk_delivery(tmp_path, cif=POROUS_CIF, alerts=[
        {"code": "602", "type": 2, "level": "B",
         "text": "VERY LARGE Solvent Accessible VOID(S) in Structure"}])
    ref = tmp_path / "ref.cif"
    ref.write_text(POROUS_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False, run_reproduce=False)
    assert r["porosity"]["porous_unmasked_unmodelled"] is True
    assert any(s.startswith("porous delivery") for s in r["grade_reasons"])
    assert r["grade"] == "acceptable"


def test_missing_delivery_files_are_reasons(tmp_path):
    """pa1 hex-l2-r3 shipped without SUMMARY.md / VALIDATION.md and graded
    like a complete delivery."""
    proj = _mk_delivery(tmp_path, complete=False)
    final = proj / "CrystalPilot Results" / "task_1" / "final.cif"
    df = G.delivery_files(final)
    assert df["missing"] == ["final.res", "VALIDATION.md", "SUMMARY.md",
                             "checkcif"]
    assert df["final.cif"] and df["final.fcf"] and df["REPORT.json"]
    ref = tmp_path / "ref.cif"
    ref.write_text(MINI_CIF.replace("0.0400", "0.0380"), encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                         run_checkcif=False, run_reproduce=False)
    assert r["grade"] == "acceptable"
    assert any(s.startswith("delivery file set incomplete") and
               "SUMMARY.md" in s for s in r["grade_reasons"])
    # the checkCIF report may be any checkcif* json/md/html/txt
    (final.parent / "checkcif_alerts.md").write_text("x", encoding="utf-8")
    assert "checkcif" not in G.delivery_files(final)["missing"]
    # self-consistency mode carries the same reasons, grade untouched
    r2 = G.grade_delivery(proj, out_dir=tmp_path / "out2",
                          run_checkcif=False, run_reproduce=False)
    assert r2["grade"] == "self_consistent_pass"
    assert any("delivery file set incomplete" in s for s in r2["grade_reasons"])


def _synthetic_chemistry_structure():
    """One P1 cell holding, far apart: a Zn with 8 O at 2.2 A, a
    carboxylate-shaped X-C(-C)-X' with X labelled N (the cu runs' N1), a
    planar six-ring whose N carries a C substituent (cu-l1-r1 N2), a Zr
    with 5 C at 2.0 A, a Zr with 5 C at 2.5 A (eta5-Cp) and an Fe with 5 C
    at 2.05 A (ferrocene-type)."""
    import math

    from cctbx import crystal, xray
    a = 40.0
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=(a, a, a, 90, 90, 90), space_group_symbol="P 1"))

    def add(label, el, xyz):
        xs.add_scatterer(xray.scatterer(
            label=label, scattering_type=el,
            site=tuple(v / a for v in xyz), u=0.03))

    # (a) Zn in a cube of 8 O at 2.2 A
    c = (5.0, 5.0, 5.0)
    add("Zn1", "Zn", c)
    r = 2.2 / math.sqrt(3)
    for k, (sx, sy, sz) in enumerate(
            (sx, sy, sz) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)):
        add(f"O{k + 1}", "O", (c[0] + sx * r, c[1] + sy * r, c[2] + sz * r))
    # (b) carboxylate C at origin o: N at 1.25 A, O at 1.25 A / 120 deg,
    #     ring C at 1.50 A / 240 deg -> N...O 2.165 A
    o = (15.0, 5.0, 5.0)
    add("C9", "C", o)
    add("N1", "N", (o[0] + 1.25, o[1], o[2]))
    add("O9", "O", (o[0] + 1.25 * math.cos(2.0944),
                    o[1] + 1.25 * math.sin(2.0944), o[2]))
    add("C10", "C", (o[0] + 1.50 * math.cos(4.1888),
                     o[1] + 1.50 * math.sin(4.1888), o[2]))
    # (c) planar six-ring (radius 1.39 A) with one N, exocyclic C at 1.50 A
    o = (25.0, 5.0, 5.0)
    for k in range(6):
        ang = k * math.pi / 3
        add("N2" if k == 0 else f"C{20 + k}", "N" if k == 0 else "C",
            (o[0] + 1.39 * math.cos(ang), o[1] + 1.39 * math.sin(ang), o[2]))
    add("C30", "C", (o[0] + 1.39 + 1.50, o[1], o[2]))
    # (d) three metals with a C5 pentagon each
    for label, el, centre, radius in (("Zr1", "Zr", (5.0, 20.0, 5.0), 2.0),
                                      ("Zr2", "Zr", (20.0, 20.0, 5.0), 2.5),
                                      ("Fe1", "Fe", (32.0, 20.0, 5.0), 2.05)):
        add(label, el, centre)
        for k in range(5):
            ang = k * 2 * math.pi / 5
            add(f"C{label}{k}", "C", (centre[0] + radius * math.cos(ang),
                                      centre[1] + radius * math.sin(ang),
                                      centre[2]))
    return xs


def test_chemistry_flags_synthetic_motifs():
    ch = G.chemistry_flags(_synthetic_chemistry_structure())
    flags, notes = ch["flags"], ch["notes"]
    assert any(f.startswith("Zn1 (Zn) CN=8 outside") for f in flags)
    assert any(f.startswith("N1 is labelled N but sits in a carboxylate")
               and "X...X' 2.17 A" in f for f in flags)
    assert any(f.startswith("N2 is a planar six-ring atom carrying a C "
                            "substituent at 1.50 A") for f in flags)
    assert any(f.startswith("Zr1 (Zr) has 5 C at 1.9-2.1 A") for f in flags)
    assert any(n.startswith("Zr2 (Zr) has 5 C at 2.4-2.6 A: an eta-bound")
               for n in notes)
    assert any(n.startswith("Fe1 (Fe) has 5 C at 1.9-2.1 A: metallocene")
               for n in notes)
    assert not any(f.startswith(("Fe1", "N2 is labelled N but"))
                   for f in flags)
    cn = {m["atom"]: m["cn"] for m in ch["metal_coordination"]}
    assert cn["Zn1"] == 8 and cn["Fe1"] == 5
    assert G.chemistry_flags(None)["skipped"]


def _carboxylate_amide_imide_structure():
    """Three isolated X-C(-C)-X' motifs - the exact shape check (b) looks
    for - that differ only in how many heavy atoms the labelled-N atom
    itself carries. org-full-r1: (b) fired on the amide N of N-(3-
    oxobutanoyl)-L-homoserine lactone (N-C 1.34, N...O 2.24 A) and
    demoted a delivery whose composition matched the reference exactly;
    amide N-C(=O)-C and carboxylate O-C(=O)-C are identical around the
    carbon, so the fix has to look at the labelled atom, not the carbon:

      k1: a real carboxylate whose terminal O is mislabelled N (one
          heavy neighbour, the carboxyl C) - the cu runs' N1 shape,
          still a probable mislabel;
      k2: an amide N, N-methylacetamide geometry (N-C(acyl) 1.34,
          C=O 1.23, N-CH3 1.45) - two heavy neighbours, org-full-r1's
          false positive;
      k3: an imide-like N carrying a third heavy substituent.
    """
    import math

    from cctbx import crystal, xray
    a = 45.0
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=(a, a, a, 90, 90, 90), space_group_symbol="P 1"))

    def add(label, el, xyz):
        xs.add_scatterer(xray.scatterer(
            label=label, scattering_type=el,
            site=tuple(v / a for v in xyz), u=0.03))

    # k1: carboxylate C at o, terminal O mislabelled N1 at 1.25 A / 0 deg,
    #     real O at 1.25 A / 120 deg, alpha C at 1.50 A / 240 deg -> N1
    #     has exactly one heavy neighbour (the carboxyl C) - still flagged
    o = (5.0, 5.0, 5.0)
    add("k1C", "C", o)
    add("N60", "N", (o[0] + 1.25, o[1], o[2]))
    add("k1O", "O", (o[0] + 1.25 * math.cos(2.0944),
                     o[1] + 1.25 * math.sin(2.0944), o[2]))
    add("k1R", "C", (o[0] + 1.50 * math.cos(4.1888),
                     o[1] + 1.50 * math.sin(4.1888), o[2]))

    # k2: acyl C at o, amide N70 at 1.34 A / 0 deg, carbonyl O at 1.23 A /
    #     120 deg, acetyl-methyl C at 1.50 A / 240 deg, N-methyl C at
    #     1.45 A / 60 deg off N70 -> N70 has two heavy neighbours (the
    #     acyl C and its own methyl) - must NOT be flagged
    o = (20.0, 5.0, 5.0)
    add("k2C", "C", o)
    n70 = (o[0] + 1.34, o[1], o[2])
    add("N70", "N", n70)
    add("k2O", "O", (o[0] + 1.23 * math.cos(2.0944),
                     o[1] + 1.23 * math.sin(2.0944), o[2]))
    add("k2R", "C", (o[0] + 1.50 * math.cos(4.1888),
                     o[1] + 1.50 * math.sin(4.1888), o[2]))
    add("C72", "C", (n70[0] + 1.45 * math.cos(1.0472),
                     n70[1] + 1.45 * math.sin(1.0472), n70[2]))

    # k3: same acyl shape as k2 but N80 carries two extra heavy
    #     substituents (an imide-like N) -> three heavy neighbours -
    #     must NOT be flagged
    o = (35.0, 5.0, 5.0)
    add("k3C", "C", o)
    n80 = (o[0] + 1.34, o[1], o[2])
    add("N80", "N", n80)
    add("k3O", "O", (o[0] + 1.23 * math.cos(2.0944),
                     o[1] + 1.23 * math.sin(2.0944), o[2]))
    add("k3R", "C", (o[0] + 1.50 * math.cos(4.1888),
                     o[1] + 1.50 * math.sin(4.1888), o[2]))
    add("C82", "C", (n80[0] + 1.45 * math.cos(1.0472),
                     n80[1] + 1.45 * math.sin(1.0472), n80[2]))
    add("C83", "C", (n80[0] + 1.48 * math.cos(-1.0472),
                     n80[1] + 1.48 * math.sin(-1.0472), n80[2]))
    return xs


def test_chemistry_flags_b_terminal_n_only():
    """The fix for org-full-r1: check (b)'s X-C(-C)-X' shape cannot by
    itself tell a carboxylate O from an amide/imide N (they are
    geometrically identical around the carbon), so it must also require
    the labelled N to be terminal - exactly one heavy-atom neighbour."""
    ch = G.chemistry_flags(_carboxylate_amide_imide_structure())
    flags = ch["flags"]
    assert any(f.startswith("N60 is labelled N but sits in a "
                            "carboxylate-shaped") and "terminal N" in f
               for f in flags)
    assert not any(f.startswith("N70 is labelled N but sits in a "
                                "carboxylate-shaped") for f in flags)
    assert not any(f.startswith("N80 is labelled N but sits in a "
                                "carboxylate-shaped") for f in flags)


def test_chemistry_flags_are_reasons_not_demotions(tmp_path):
    """pa1 hex-l1-r1's Zn at CN 8 (validate warned twice) and cu-l1-r1's
    ring carbon labelled N reached the delivery; flags cost publication,
    never acceptable (the element gate handles wrong metals)."""
    cif = MINI_CIF.replace(" O1 O 0.4000 0.3000 0.2000 1.0",
                           " N1 N 0.4000 0.3000 0.2000 1.0") \
        .replace("'C2 O2 Cu1'", "'C2 N1 O1 Cu1'")
    proj = _mk_delivery(tmp_path, cif=cif)
    ref = tmp_path / "ref.cif"
    ref.write_text(cif.replace("0.0400", "0.0380"), encoding="utf-8")
    fake = {"flags": ["Cu1 (Cu) CN=8 outside the plausible [2, 6] for Cu"],
            "notes": [], "metal_coordination": []}
    import crystalpilot.benchmark.grade as gmod
    orig = gmod.chemistry_flags
    gmod.chemistry_flags = lambda xs: fake
    try:
        r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "out",
                             run_checkcif=False, run_reproduce=False)
    finally:
        gmod.chemistry_flags = orig
    assert r["chemistry"]["flags"] == fake["flags"]
    assert r["grade"] == "acceptable"
    assert any(s.startswith("chemistry: Cu1 (Cu) CN=8")
               for s in r["grade_reasons"])
    md = (tmp_path / "out" / "GRADE.md").read_text(encoding="utf-8")
    assert "标记：Cu1 (Cu) CN=8" in md


def test_data_quality_a_alerts_are_reported_not_blocking():
    """pa2 hex: PLAT020 (R_int 0.57) and PLAT023 (cut at 1.0 A) fire on
    every delivery of this dataset - and would on the group's manual
    structure. They describe the data; they cannot demote a model."""
    assert G.classify_a_alert("020", "The Value of Rint is Greater Than 0.12"
                              ) == "data_quality"
    assert G.classify_a_alert("023", "Resolution (too) Low [sin(theta)/"
                              "Lambda < 0.6]") == "data_quality"
    assert G.classify_a_alert("999", "Ratio Observed / Unique Reflections "
                              "(too) Low") == "data_quality"
    assert G.classify_a_alert("213", "Atom C1 has ADP max/min Ratio"
                              ) == "model_quality"
    cc = {"available": True,
          "alerts_abc": ["A 020 The Value of Rint is Greater Than 0.12",
                         "A 023 Resolution (too) Low",
                         "A 213 Atom C1 has ADP max/min Ratio"],
          "blocking_a": ["020 The Value of Rint is Greater Than 0.12",
                         "023 Resolution (too) Low",
                         "213 Atom C1 has ADP max/min Ratio"]}
    sp = G.checkcif_a_split(cc, Path("nowhere/final.cif"))
    assert sp["blocking_model_quality"] == ["213"]
    assert [s.split()[0] for s in sp["data_quality"]] == ["020", "023"]
    assert [s.split()[0] for s in sp["model_quality"]] == ["213"]


class TestTransplantAlignment:
    """pa4 hex: the agent's model sat on a symmetry-equivalent origin
    (every atom at z + 1/2, legal in P6/mmm); refined against the
    reference's .fab - mask coefficients for the REFERENCE origin - it
    reached R1 0.206 where the same framework on the reference origin
    (pa3) gave 0.133. The transplant now moves the model first."""

    RES = [
        "TITL t", "CELL 0.71073 10 11 12 90 95 90", "ZERR 4 0 0 0 0 0 0",
        "LATT 1", "SYMM -X, 0.5+Y, 0.5-Z", "SFAC C O Cu", "UNIT 8 8 4",
        "FVAR 0.1",
        "CU1   3   0.250000   0.250000   0.250000   11.00000   0.02000 "
        "  0.03000   0.04000 =",
        "    0.00100   0.00200   0.00300",
        "O1    2   0.400000   0.300000   0.200000   11.00000   0.03000",
        "C1    1  10.500000   0.400000   0.150000   11.00000   0.03000",
        "H1    1   0.520000   0.450000   0.100000   11.00000  -1.20000",
        "HKLF 4", "END",
    ]
    CELL = (10, 11, 12, 90, 95, 90)

    def test_pure_translation_moves_coordinates_and_keeps_u(self):
        out = G._transform_res_atoms(self.RES, (1, 0, 0, 0, 1, 0, 0, 0, 1),
                                     (0.5, 0, 0), self.CELL)
        cu = [l for l in out if l.startswith("CU1")][0].split()
        assert [float(v) for v in cu[2:5]] == pytest.approx([0.75, 0.25, 0.25])
        assert cu[6:9] == ["0.02000", "0.03000", "0.04000"] and cu[-1] == "="
        assert out[out.index([l for l in out if l.startswith("CU1")][0]) + 1] \
            == "    0.00100   0.00200   0.00300"
        c1 = [l for l in out if l.startswith("C1 ")][0].split()
        assert float(c1[2]) == pytest.approx(11.0)       # fixed flag kept
        h1 = [l for l in out if l.startswith("H1 ")][0].split()
        assert float(h1[2]) == pytest.approx(1.02) and h1[-1] == "-1.20000"
        assert "SYMM -X, 0.5+Y, 0.5-Z" in out and "HKLF 4" in out

    def test_rotation_transforms_uij(self):
        # inversion: coordinates negate, a symmetric U is unchanged
        out = G._transform_res_atoms(self.RES, (-1, 0, 0, 0, -1, 0, 0, 0, -1),
                                     (0, 0, 0), self.CELL)
        cu = [l for l in out if l.startswith("CU1")][0].split()
        assert [float(v) for v in cu[2:5]] == pytest.approx([-0.25, -0.25, -0.25])
        cont = out[out.index([l for l in out if l.startswith("CU1")][0]) + 1]
        u = [float(v) for v in cu[6:9]] + [float(v) for v in cont.split()]
        assert u == pytest.approx([0.02, 0.03, 0.04, 0.001, 0.002, 0.003], abs=1e-5)
        # a swap of x and y (legal in a tetragonal-like sense) permutes U11/U22
        out2 = G._transform_res_atoms(self.RES, (0, 1, 0, 1, 0, 0, 0, 0, 1),
                                      (0, 0, 0), (10, 10, 12, 90, 90, 90))
        cu2 = [l for l in out2 if l.startswith("CU1")][0].split()
        assert [float(v) for v in cu2[6:9]] == pytest.approx([0.03, 0.02, 0.04], abs=1e-5)

    def test_align_detects_a_symmetry_equivalent_origin(self, tmp_path):
        ref = tmp_path / "ref.cif"
        ref.write_text(MINI_CIF, encoding="utf-8")
        shifted = MINI_CIF
        for a, b in (("Cu1 Cu 0.2500", "Cu1 Cu 0.7500"), ("O1 O 0.4000", "O1 O 0.9000"),
                     ("O2 O 0.1000", "O2 O 0.6000"), ("C1 C 0.5000", "C1 C 0.0000"),
                     ("C2 C 0.0000", "C2 C 0.5000")):
            shifted = shifted.replace(a, b)
        final = tmp_path / "final.cif"
        final.write_text(shifted, encoding="utf-8")
        lines = ["CELL 0.71073 10 11 12 90 95 90", "SFAC C O Cu", "FVAR 0.1",
                 "CU1   3   0.750000   0.250000   0.250000   11.00000   0.02000",
                 "O1    2   0.900000   0.300000   0.200000   11.00000   0.03000",
                 "HKLF 4"]
        a = G._align_res_to_reference(lines, final, ref, [10, 11, 12, 90, 95, 90])
        assert a["applied"] is True, a
        cu = [l for l in a["lines"] if l.startswith("CU1")][0].split()
        x = float(cu[2]) % 1.0
        assert x == pytest.approx(0.25, abs=1e-3), a      # back on the reference origin
        assert abs(a["t"][0]) == pytest.approx(0.5, abs=1e-3), a
        # same origin: nothing moves
        final.write_text(MINI_CIF, encoding="utf-8")
        b = G._align_res_to_reference(lines, final, ref, [10, 11, 12, 90, 95, 90])
        assert b["applied"] is False and "same origin" in b["note"]
