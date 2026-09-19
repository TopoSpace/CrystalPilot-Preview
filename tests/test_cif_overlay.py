"""Mentor-side overlay of two structures: alignment, pairing, the lists of
what does not pair, and a self-contained HTML page."""
from __future__ import annotations

from pathlib import Path

from crystalpilot.benchmark import cif_overlay as ov


def _xs(atoms, sg="P -1", cell=(10, 11, 12, 90, 95, 90)):
    from cctbx import crystal, xray
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=cell, space_group_symbol=sg))
    for lbl, el, site, occ in atoms:
        xs.add_scatterer(xray.scatterer(label=lbl, scattering_type=el,
                                        site=site, occupancy=occ, u=0.03))
    return xs


REF = [("Cu1", "Cu", (0.25, 0.25, 0.25), 1.0),
       ("O1", "O", (0.40, 0.30, 0.20), 1.0),
       ("O2", "O", (0.10, 0.20, 0.35), 1.0),
       ("C1", "C", (0.50, 0.40, 0.15), 1.0),
       ("Br1", "Br", (0.70, 0.60, 0.60), 0.25),      # the guest
       ("H1", "H", (0.52, 0.45, 0.10), 1.0)]
MOD = [("Cu1", "Cu", (0.25, 0.25, 0.25), 1.0),
       ("O1", "O", (0.41, 0.30, 0.21), 1.0),         # 0.1 A off
       ("N2", "N", (0.10, 0.20, 0.35), 1.0),         # element mismatch
       ("C1", "C", (0.50, 0.40, 0.15), 0.5),         # occupancy mismatch
       ("C9", "C", (0.80, 0.80, 0.80), 1.0)]         # extra; Br missing


def test_compare_lists_every_kind_of_disagreement():
    cmp = ov.compare(_xs(REF).select(
        __import__("cctbx.array_family", fromlist=["flex"]).flex.bool(
            [a[1] != "H" for a in REF])), _xs(MOD))
    assert cmp["n_pairs"] == 4
    assert cmp["n_element_mismatch"] == 1
    assert cmp["n_occ_mismatch"] == 1
    assert [r["label"] for r in cmp["only_ref"]] == ["Br1"]
    assert [r["label"] for r in cmp["only_model"]] == ["C9"]
    assert cmp["heavy_match"]["n_pairs"] == 1          # Cu (Br has no mate)
    mis = [p for p in cmp["pairs"] if p["element_mismatch"]][0]
    assert (mis["ref_el"], mis["model_el"]) == ("O", "N")
    off = next(p for p in cmp["pairs"] if p["ref"] == "O1")
    assert 0.05 < off["dist_A"] < 0.2


def test_html_carries_both_models_and_the_flags(tmp_path):
    from cctbx.array_family import flex
    ref = _xs(REF).select(flex.bool([a[1] != "H" for a in REF]))
    cmp = ov.compare(ref, _xs(MOD))
    page = ov.render_html(cmp, "t", "ref.cif", "model.cif",
                          {"ref_r1": 0.05, "model_r1": 0.07})
    assert "3Dmol" in page and "CRYST1" in page
    assert "UNM" in page and "MIS" in page              # flagged residues
    assert "Br1" in page and "C9" in page
    assert "只在参考 A 中" in page


def test_different_space_groups_are_compared_in_p1():
    from cctbx.array_family import flex
    ref = _xs(REF).select(flex.bool([a[1] != "H" for a in REF]))
    # the same content declared in P1: a "wrong group" delivery
    mod = _xs(MOD, sg="P 1")
    cmp = ov.compare(ref, mod)
    assert cmp["same_sg_type"] is False and cmp["compared_in_p1"] is True
    assert "error" not in cmp
    assert cmp["n_pairs"] >= 4                    # per cell now (Z=2 in P-1)
    assert "P1" in cmp["note"]


def _res_text(atoms, title="t") -> str:
    els = []
    for _, el, _, _ in atoms:
        if el not in els:
            els.append(el)
    lines = [f"TITL {title}", "CELL 0.71073 10 11 12 90 95 90",
             "ZERR 1 0 0 0 0 0 0", "LATT 1", "SFAC " + " ".join(els),
             "UNIT " + " ".join("2" for _ in els), "FVAR 1.0"]
    for lbl, el, (x, y, z), occ in atoms:
        lines.append(f"{lbl} {els.index(el) + 1} {x:.5f} {y:.5f} {z:.5f} "
                     f"{10 + occ:.5f} 0.03")
    lines += ["HKLF 4", "END"]
    return "\n".join(lines) + "\n"


def test_cli_writes_the_page(tmp_path):
    (tmp_path / "ref.res").write_text(
        _res_text([a for a in REF if a[1] != "H"]), encoding="utf-8")
    (tmp_path / "model.res").write_text(_res_text(MOD), encoding="utf-8")
    out = tmp_path / "o.html"
    rc = ov.main([str(tmp_path / "ref.res"), str(tmp_path / "model.res"),
                  "-o", str(out), "--json", str(tmp_path / "o.json")])
    assert rc == 0 and out.exists()
    j = (tmp_path / "o.json").read_text(encoding="utf-8").upper()
    # the SHELX reader upper-cases labels
    assert '"ONLY_REF"' in j and "BR1" in j and "C9" in j
