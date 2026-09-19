"""The deposited R1 is a fair bar only if the deposited model reaches it
on the delivered data (nm: HKLF5-derived composite list, 0.0526 deposited,
0.094 attainable)."""
from __future__ import annotations

from pathlib import Path

import pytest

from crystalpilot.benchmark import grade as G

RES = """TITL x
CELL 1.54178 6.98 9.36 12.58 102.8 94.3 107.6
ZERR 2 0 0 0 0 0 0
LATT 1
SFAC C N O
UNIT 32 4 10
L.S. 4
ACTA
SHEL 999 0.75
BASF 0.3
WGHT 0.1
FVAR 1.0
C1 1 0.1 0.2 0.3 11.0 0.05
HKLF 5
END"""


def _delivery(tmp_path, with_hkl=True):
    d = tmp_path / "task"
    d.mkdir()
    cif = d / "final.cif"
    body = "data_f\n_refine_ls_R_factor_gt 0.0948\n"
    if with_hkl:
        body += "_shelx_hkl_file\n;\n   1   0   0  100.0  1.0\n   0   0   0    0.0  0.0\n;\n"
    cif.write_text(body, encoding="utf-8")
    (d / "final.res").write_text("SHEL 999 0.80\nHKLF 4\nEND\n", encoding="utf-8")
    return cif


def test_skips_without_delivered_hkl(tmp_path):
    ref = tmp_path / "ref.cif"
    ref.write_text("data_r\n", encoding="utf-8")
    r = G._reference_on_delivered_data(_delivery(tmp_path, with_hkl=False), ref, 0.05)
    assert r["skipped"].startswith("delivery embeds no")


def test_masked_reference_is_skipped(tmp_path):
    ref = tmp_path / "ref.cif"
    ref.write_text("data_r\n_platon_squeeze_void_nr 1\n", encoding="utf-8")
    r = G._reference_on_delivered_data(_delivery(tmp_path), ref, 0.05)
    assert r["skipped"].startswith("masked reference")


def test_embedded_res_is_converted_and_refined(tmp_path, monkeypatch):
    ref = tmp_path / "ref.cif"
    ref.write_text("data_r\n_shelx_res_file\n;\n" + RES + "\n;\n", encoding="utf-8")
    exe = tmp_path / "shelxl.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(G, "_shelxl_exe", lambda: exe)
    seen = {}

    def fake_run(job, shelxl, timeout_s):
        seen["ins"] = (job / "job.ins").read_text(encoding="utf-8")
        seen["hkl"] = (job / "job.hkl").read_text(encoding="utf-8")
        (job / "job.lst").write_text("R1 =  0.0942 for   2715 Fo > 4sig(Fo)\n", encoding="utf-8")
        return {"returncode": 0}
    monkeypatch.setattr(G, "_run_shelxl_job", fake_run)
    monkeypatch.setattr(G, "REPO", tmp_path)
    r = G._reference_on_delivered_data(_delivery(tmp_path), ref, 0.0526)
    assert r["r1_reference_on_delivered_data"] == 0.0942
    assert r["delta_vs_deposited"] == pytest.approx(0.0416)
    assert r["reproducible"] is False
    assert "HKLF 5 -> HKLF 4" in r["basis"]
    ins = seen["ins"]
    assert "HKLF 4" in ins and "HKLF 5" not in ins
    assert "BASF" not in ins and "ACTA" not in ins
    assert "L.S. 10" in ins and "SHEL 999 0.80" in ins      # the agent's cut
    assert "1   0   0  100.0" in seen["hkl"]


def test_effective_reference_rewrites_the_delta_only_when_not_reproducible():
    rl = {"r1_agent": 0.0948, "r1_reference": 0.0526, "r1_delta": 0.0422}
    assert G._effective_reference_r1(rl, {"r1_reference_on_delivered_data": 0.0942}) == pytest.approx(0.0006)
    assert rl["r1_reference_effective"] == 0.0942
    assert rl["r1_delta_deposited"] == 0.0422
    assert "not reproducible" in rl["r1_delta_basis"]
    rl2 = {"r1_agent": 0.0948, "r1_reference": 0.0526, "r1_delta": 0.0422}
    assert G._effective_reference_r1(rl2, {"r1_reference_on_delivered_data": 0.056}) == 0.0422
    assert "r1_delta_basis" not in rl2
    assert G._effective_reference_r1(rl2, None) == 0.0422
    assert G._effective_reference_r1(rl2, {"skipped": "x"}) == 0.0422
