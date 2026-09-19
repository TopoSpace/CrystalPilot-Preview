"""DISP cards for wavelengths SHELXL has no built-in f'/f'' for.

pa1 backflow (audit_heavy_sites, commit 6af3c74): every run_shelxl job on
the 0.68883 A synchrotron data (the Zr K edge, f'(Zr) = -9.0 e) went to
SHELXL without DISP cards. SHELXL then prints "DISP instructions may be
required for this wavelength" and computes with its Mo K-alpha table, so
the R-vs-Z ladders compared a ~37-electron Zr with data that see ~31 and
Zn won (hex-l1-r1 delivered NU-1000 as Zn3). The in-process engine had the
Sasaki terms all along. Facts pinned here were measured on
vendor/shelx/shelxl.exe (2019/3) on 2026-09-02:

* the card needs all three numbers (f' f'' mu) and must sit between SFAC
  and UNIT;
* only Cu / Mo / Ag K-alpha are built in (Cr and Fe warn, unlike the
  manual's list); within +-0.01 A of a line SHELXL uses that line's table;
* mu is the atomic attenuation cross-section in barn: the .lst "Mu" is
  sum(n_i mu_i) / (10 V).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SHELXL = REPO / "vendor" / "shelx" / "shelxl.exe"
ZR_EDGE = 0.68883                     # pa1 synchrotron wavelength
ELEMENTS = ("C", "H", "O", "Zn", "Zr")


def _structure(elements=ELEMENTS):
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=(8, 9, 10, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    for i, el in enumerate(elements):
        xs.add_scatterer(xray.scatterer(
            label=f"{el.upper()}{i + 1}", site=(0.05 + 0.15 * i, 0.2, 0.3),
            u=0.03, scattering_type=el))
    return xs


def _text(wavelength, **kw) -> str:
    from crystalpilot.io.shelx_writer import ShelxModel, write_res_text
    return write_res_text(ShelxModel(xray_structure=_structure(),
                                     wavelength=wavelength, **kw))[0]


def _disp(text: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for ln in text.splitlines():
        toks = ln.split()
        if toks and toks[0].upper() == "DISP":
            out[toks[1].lstrip("$")] = [float(x) for x in toks[2:]]
    return out


def _index(text: str, card: str) -> int:
    return next(i for i, ln in enumerate(text.splitlines())
                if ln.split() and ln.split()[0] == card)


class TestDispCards:
    def test_synchrotron_wavelength_gets_a_card_per_sfac_element(self):
        text = _text(ZR_EDGE)
        disp = _disp(text)
        assert set(disp) == set(ELEMENTS)
        fp, fdp, mu = disp["Zr"]
        assert fp == pytest.approx(-9.0, abs=0.1)        # on the Zr K edge
        assert fdp == pytest.approx(2.8, abs=0.1)
        assert mu == pytest.approx(14340, rel=0.02)      # NIST 94.7 cm2/g x A
        assert all(len(v) == 3 for v in disp.values())   # SHELXL rejects 2
        assert "-0.000" not in text
        lines = text.splitlines()
        rows = [i for i, ln in enumerate(lines) if ln.startswith("DISP $")]
        assert _index(text, "SFAC") < min(rows)
        assert max(rows) < _index(text, "UNIT")
        assert any(ln.startswith("REM DISP") and "0.68883" in ln
                   for ln in lines)

    def test_cards_carry_the_in_process_engine_numbers(self):
        """The point of the fix: SHELXL and smtbx refine the same scatterer."""
        xs = _structure()
        xs.set_inelastic_form_factors(ZR_EDGE, "sasaki")
        engine = {sc.scattering_type: (sc.fp, sc.fdp)
                  for sc in xs.scatterers()}
        disp = _disp(_text(ZR_EDGE))
        for el in ("C", "O", "Zn", "Zr"):
            assert disp[el][0] == pytest.approx(engine[el][0], abs=0.001)
            assert disp[el][1] == pytest.approx(engine[el][1], abs=0.001)
        assert disp["H"][:2] == [0.0, 0.0]         # Henke: Sasaki has no H

    @pytest.mark.parametrize("wl", [0.71073, 0.7107, 0.71069, 1.54178,
                                    1.5418, 1.54184, 0.5608])
    def test_builtin_kalpha_lines_get_no_cards(self, wl):
        text = _text(wl)
        assert not _disp(text)
        assert "DISP" not in text

    @pytest.mark.parametrize("wl", [2.2909, 1.9373, 0.70930, 0.68914, 1.0])
    def test_everything_else_gets_cards(self, wl):
        """Cr / Fe K-alpha are in the manual's list but the 2019/3 binary
        warns for them; Mo K-alpha1 is outside our 0.0005 A window."""
        assert set(_disp(_text(wl))) == set(ELEMENTS)

    def test_unknown_wavelength_gets_a_rem_not_cards(self):
        text = _text(None)
        assert "CELL 0.71073" in text
        assert not _disp(text)
        rem = [ln for ln in text.splitlines() if ln.startswith("REM DISP")]
        assert rem and "no wavelength" in rem[0]
        assert any("ingest_vendor_data(wavelength=" in ln for ln in rem)

    def test_electron_wavelength_gets_a_rem_not_cards(self):
        text = _text(0.0251)
        assert not _disp(text)
        assert any("electron" in ln for ln in text.splitlines()
                   if ln.startswith("REM DISP"))

    def test_builtin_radiation_lookup(self):
        from crystalpilot.io.shelx_writer import shelxl_builtin_radiation
        assert shelxl_builtin_radiation(0.71073) == "Mo"
        assert shelxl_builtin_radiation(1.54184) == "Cu"
        assert shelxl_builtin_radiation(0.5608) == "Ag"
        assert shelxl_builtin_radiation(0.7093) is None
        assert shelxl_builtin_radiation(2.2909) is None
        assert shelxl_builtin_radiation(None) is None


class TestReadBack:
    def test_written_res_with_disp_round_trips(self, tmp_path):
        from crystalpilot.io.shelx import parse_ins_metadata
        from crystalpilot.io.shelx_model import load_res_model
        p = tmp_path / "t.res"
        p.write_text(_text(ZR_EDGE, z=1), encoding="ascii")
        parsed = load_res_model(p)
        assert parsed.structure.scatterers().size() == len(ELEMENTS)
        assert parsed.wavelength == pytest.approx(ZR_EDGE)
        assert parsed.sfac == ["C", "H", "O", "Zn", "Zr"]
        assert parsed.disp["Zr"][0] == pytest.approx(-9.0, abs=0.1)
        assert parsed.disp["Zr"][1] == pytest.approx(2.8, abs=0.1)
        assert set(parsed.disp) == set(ELEMENTS)
        assert not parsed.dropped_lines
        meta = parse_ins_metadata(p)
        assert meta["sfac"] == ["C", "H", "O", "Zn", "Zr"]   # no DISP leak
        assert meta["wavelength"] == pytest.approx(ZR_EDGE)

    def test_foreign_disp_forms_parse(self, tmp_path):
        """Olex2 / hand-written files: no '$', two numbers, lowercase."""
        from crystalpilot.io.shelx_model import load_res_model
        p = tmp_path / "f.res"
        p.write_text(
            "TITL f\nCELL 0.68883 8 9 10 90 90 90\nZERR 1 0 0 0 0 0 0\n"
            "LATT -1\nSFAC O Zr\nDISP Zr -9.0 2.8\ndisp $O 0.007 0.006 30.3\n"
            "UNIT 1 1\nFVAR 1\nZR1 2 0.1 0.2 0.3 11.0 0.02\n"
            "O1 1 0.3 0.1 0.2 11.0 0.03\nHKLF 4\nEND\n", encoding="ascii")
        parsed = load_res_model(p)
        assert parsed.structure.scatterers().size() == 2
        assert parsed.disp == {"Zr": (-9.0, 2.8), "O": (0.007, 0.006)}


@pytest.mark.skipif(not SHELXL.exists(), reason="vendor shelxl not deployed")
class TestRealShelxl:
    """Synthetic Zr/O data generated WITH the Sasaki terms on the Zr edge:
    the writer's own .ins must make SHELXL reproduce them."""

    @staticmethod
    def _job(tmp_path, strip_disp: bool):
        from crystalpilot.io.shelx_writer import (ShelxModel,
                                                  shelxl_command_block,
                                                  write_res_text)
        xs = _structure(("O", "Zr"))
        xs.scattering_type_registry(table="it1992")
        xs.set_inelastic_form_factors(ZR_EDGE, "sasaki")
        i = xs.structure_factors(d_min=1.0, anomalous_flag=True).f_calc() \
            .as_intensity_array()
        i = i.customized_copy(sigmas=i.data() * 0.02 + 0.01)
        job = tmp_path / ("plain" if strip_disp else "disp")
        job.mkdir()
        with open(job / "t.hkl", "w") as fh:
            i.export_as_shelx_hklf(fh)
        text, _ = write_res_text(ShelxModel(
            xray_structure=xs, wavelength=ZR_EDGE, z=1,
            instruction_cards=shelxl_command_block(l_s=0)))
        if strip_disp:
            text = "\n".join(ln for ln in text.splitlines()
                             if not ln.startswith("DISP")) + "\n"
        (job / "t.ins").write_text(text, encoding="ascii")
        proc = subprocess.run([str(SHELXL), "t"], cwd=str(job),
                              capture_output=True, text=True,
                              errors="replace", timeout=120)
        assert proc.returncode == 0, proc.stdout[-500:]
        lst = (job / "t.lst").read_text(encoding="utf-8", errors="replace")
        r1 = float(re.search(r"R1 =\s+[0-9.]+ for\s+\d+ Fo > 4sig\(Fo\) and"
                             r"\s+([0-9.]+) for all", lst).group(1))
        mu = float(re.search(r"Mu =\s+([0-9.]+) mm-1", lst).group(1))
        res = (job / "t.res").read_text(encoding="utf-8", errors="replace")
        return text, lst, r1, mu, res

    def test_cards_silence_the_warning_and_fix_r1(self, tmp_path):
        from crystalpilot.refine.tools_shelxl import next_round_ins_text
        text, lst, r1, mu, res = self._job(tmp_path, strip_disp=False)
        assert "DISP instructions may be required" not in lst
        assert "WRONG NUMBER" not in lst and "MUST COME BETWEEN" not in lst
        assert r1 < 0.01                          # the model made the data
        _, lst0, r1_plain, mu_plain, _ = self._job(tmp_path, strip_disp=True)
        assert "DISP instructions may be required" in lst0
        assert r1_plain > 0.03                    # Mo K-alpha terms on the edge
        # mu convention: .lst Mu = sum(mu_i) / (10 V), V = 720 A^3
        expect = sum(v[2] for v in _disp(text).values()) / (10 * 720.0)
        assert mu == pytest.approx(expect, abs=0.01)
        assert mu > 4 * mu_plain                  # SHELXL had reported Mo's
        # SHELXL echoes the cards: the adopt_wght loop and the CIF's
        # _shelx_res_file keep them
        assert _disp(res) == _disp(text)
        assert _disp(next_round_ins_text(res, [0.1, 0.0])) == _disp(text)
