"""SHELX writer round-trip + real-SHELXL reproduction tests (M1 gate)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CASE = (REPO / "benchmark" / "data" /
        "重复SJTU-9_SJTU-9_or_post_晶体数据_原始SJTU-9_olex2_temp_sjtu-9")
REF = CASE / "ref_res.res"
# The .fab lives next to the case (benchmark/data is a local, untracked set).
FAB_SRC = CASE / "SJTU-9.fab"
SHELXL = REPO / "vendor" / "shelx" / "shelxl.exe"

pytestmark = pytest.mark.skipif(not REF.exists(), reason="SJTU-9 case missing")


@pytest.fixture(scope="module")
def parsed():
    from crystalpilot.io.shelx_model import load_res_model
    return load_res_model(REF)


def test_loader_extracts_everything(parsed):
    assert parsed.structure.scatterers().size() == 21
    assert parsed.structure.space_group_info().type().number() == 141
    assert parsed.scale == pytest.approx(0.12928)
    assert parsed.weights == pytest.approx((0.1429, 8.497398))
    assert parsed.wavelength == pytest.approx(1.54178)
    assert parsed.z == 4
    assert parsed.rem_r1 == pytest.approx(0.0617)
    assert len(parsed.h_riding) == 5
    assert all(g["afix"] == 43 for g in parsed.h_riding)


def test_roundtrip_identity(parsed, tmp_path):
    from cctbx import euclidean_model_matching as emma
    from crystalpilot.io.shelx_model import load_res_model
    from crystalpilot.io.shelx_writer import ShelxModel, write_res_text

    text, rename = write_res_text(ShelxModel(
        xray_structure=parsed.structure, wavelength=parsed.wavelength,
        z=parsed.z, title="rt", weights=parsed.weights, scale=parsed.scale,
        h_riding=parsed.h_riding))
    assert rename == {}
    out = tmp_path / "rt.res"
    out.write_text(text, encoding="ascii")
    m2 = load_res_model(out)
    assert m2.structure.scatterers().size() == 21
    best = emma.model_matches(parsed.structure.as_emma_model(),
                              m2.structure.as_emma_model(), tolerance=0.1,
                              break_if_match_with_no_singles=False
                              ).refined_matches[0]
    assert len(best.pairs) == 21
    assert best.rms < 1e-3
    uc1, uc2 = parsed.structure.unit_cell(), m2.structure.unit_cell()
    ue1 = {sc.label: sc.u_iso_or_equiv(uc1) for sc in parsed.structure.scatterers()}
    ue2 = {sc.label: sc.u_iso_or_equiv(uc2) for sc in m2.structure.scatterers()}
    assert max(abs(ue1[k] - ue2[k]) for k in ue1) < 1e-6
    w1 = [sc.weight() for sc in parsed.structure.scatterers()]
    w2 = [sc.weight() for sc in m2.structure.scatterers()]
    assert w1 == pytest.approx(w2, abs=1e-6)
    assert len(m2.h_riding) == 5   # AFIX blocks survived


def test_label_sanitizer():
    from crystalpilot.io.shelx_writer import sanitize_labels
    m = sanitize_labels(["C1", "C1A2B", "C1A2B", "ZR01"])
    assert m["C1A2B"].startswith("C") and len(m["C1A2B"]) <= 4
    vals = ["C1", m["C1A2B"], "ZR01"]
    assert len(set(v.upper() for v in vals)) == len(vals)


@pytest.mark.skipif(not SHELXL.exists(), reason="vendor shelxl not deployed")
@pytest.mark.skipif(not FAB_SRC.exists(), reason="SJTU-9 .fab not in the local case folder")
def test_real_shelxl_reproduces_reference(parsed, tmp_path):
    """Written model + original solvent mask (.fab) must reproduce the human
    R1/wR2/GooF (SHELXL-2019/3, L.S. 4, ABIN)."""
    from crystalpilot.io.shelx_writer import (ShelxModel, shelxl_command_block,
                                              write_res_text)
    text, _ = write_res_text(ShelxModel(
        xray_structure=parsed.structure, wavelength=parsed.wavelength,
        z=parsed.z, title="rt", weights=parsed.weights, scale=parsed.scale,
        h_riding=parsed.h_riding,
        instruction_cards=shelxl_command_block(l_s=4, extra=["ABIN"])))
    (tmp_path / "rt.ins").write_text(text, encoding="ascii")
    shutil.copy(CASE / "hkl.hkl", tmp_path / "rt.hkl")
    shutil.copy(FAB_SRC, tmp_path / "rt.fab")
    proc = subprocess.run([str(SHELXL), "rt"], cwd=str(tmp_path),
                          capture_output=True, text=True, errors="replace",
                          timeout=300)
    assert proc.returncode == 0
    res = (tmp_path / "rt.res").read_text(encoding="utf-8", errors="replace")
    r1 = float(re.search(r"R1\s*=\s*([0-9.]+)\s*for", res).group(1))
    wr2 = float(re.search(r"wR2\s*=\s*([0-9.]+)", res).group(1))
    goof = float(re.search(r"GooF\s*=\s*S\s*=\s*([0-9.]+)", res).group(1))
    assert r1 == pytest.approx(0.0617, abs=0.005)
    assert wr2 == pytest.approx(0.2048, abs=0.01)
    assert goof == pytest.approx(1.062, abs=0.05)
