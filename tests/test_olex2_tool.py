"""run_olex2: the third refinement engine (check-only, native HKLF5).

The console driver itself (io/olex2c.py) needs the vendor install and a
ConPTY; these tests mock refine_job and verify the tool's guards, job
export and result parsing."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.refine import tools_olex2 as t2


def _toy_xs():
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=(8, 9, 10, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in (("C1", "C", (0.1, 0.1, 0.1)),
                          ("O1", "O", (0.25, 0.1, 0.1))):
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                        scattering_type=el))
    return xs


def _project(tmp_path, session_r1=0.040):
    hkl = tmp_path / "crystal.hkl"
    hkl.write_text("   1   0   0  100.00    5.00\n"
                   "   0   0   0    0.00    0.00\n", encoding="utf-8")
    return SimpleNamespace(
        dir=tmp_path, hkl_path=hkl,
        nodes=SimpleNamespace(
            state=lambda: {"active_node": "n1"},
            node_meta=lambda n: {"metrics": {"r1_strong": session_r1}}))


def _ctx(flags=None):
    return SimpleNamespace(
        session=SimpleNamespace(model=_toy_xs(), flags=flags or {},
                                dataset=SimpleNamespace(wavelength=0.71073)),
        progress=None)


class TestGuards:
    def test_no_model_refused(self):
        r = t2.RunOlex2(None).run(SimpleNamespace(session=None))
        assert not r.ok

    def test_missing_vendor_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(t2, "OLEX2_APP", tmp_path / "nowhere")
        r = t2.RunOlex2(_project(tmp_path)).run(_ctx())
        assert not r.ok and "not installed" in r.error

    def test_masked_model_refused(self, tmp_path, monkeypatch):
        app = tmp_path / "app"
        app.mkdir()
        (app / "olex2c.dll").write_bytes(b"MZ")
        monkeypatch.setattr(t2, "OLEX2_APP", app)
        r = t2.RunOlex2(_project(tmp_path)).run(
            _ctx(flags={"f_mask": object()}))
        assert not r.ok and "run_shelxl" in r.error


class TestMockedRun:
    @staticmethod
    def _wire(tmp_path, monkeypatch, r1_cif="0.0412", finished=True):
        app = tmp_path / "app"
        app.mkdir()
        (app / "olex2c.dll").write_bytes(b"MZ")
        monkeypatch.setattr(t2, "OLEX2_APP", app)

        def fake_refine_job(workdir, res_name="job.res", cycles=8,
                            app=None, refine_timeout_s=900.0,
                            **_kw):
            wd = Path(workdir)
            assert (wd / "job.res").exists()      # export happened
            assert (wd / "job.hkl").exists()
            cif = wd / "job.cif"
            cif.write_text(
                "data_job\n_refine_ls_R_factor_gt %s\n"
                "_refine_ls_wR_factor_ref 0.1103\n"
                "_refine_ls_goodness_of_fit_ref 1.041\n" % r1_cif,
                encoding="utf-8")
            return {"ok": finished, "refinement_finished": finished,
                    "r1_console": float(r1_cif), "cif": str(cif),
                    "elapsed_s": 12.3,
                    "console_tail": "Refinement finished" if finished
                    else "Error: no atoms"}
        import crystalpilot.io.olex2c as oc
        monkeypatch.setattr(oc, "refine_job", fake_refine_job)

    def test_success_parses_cif_and_delta(self, tmp_path, monkeypatch):
        self._wire(tmp_path, monkeypatch)
        r = t2.RunOlex2(_project(tmp_path, session_r1=0.040)).run(_ctx())
        assert r.ok, r.error
        s = r.summary
        assert s["r1_gt"] == 0.0412 and s["wr2"] == 0.1103
        assert s["delta_r1_vs_session"] == 0.0012
        assert "agrees" in s["note"]
        assert s["no_state_change"] is True

    def test_large_delta_flagged(self, tmp_path, monkeypatch):
        self._wire(tmp_path, monkeypatch, r1_cif="0.0700")
        r = t2.RunOlex2(_project(tmp_path, session_r1=0.040)).run(_ctx())
        assert r.ok
        assert "differs" in r.summary["note"]

    def test_unfinished_run_fails_with_tail(self, tmp_path, monkeypatch):
        self._wire(tmp_path, monkeypatch, finished=False)
        r = t2.RunOlex2(_project(tmp_path)).run(_ctx())
        assert not r.ok and "did not finish" in r.error


class TestWiring:
    def test_registered_and_read_only(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.registry import MUTATING_TOOLS
        assert "run_olex2" in READ_ONLY_TOOLS
        assert "run_olex2" not in MUTATING_TOOLS


VENDOR = REPO / "vendor" / "olex2" / "app" / "olex2c.dll"


@pytest.mark.skipif(not VENDOR.exists(), reason="vendor olex2 not installed")
class TestLiveSmoke:
    def test_help_boot(self):
        # boot-only liveness: the full refine smoke lives in the bring-up
        # scripts; here we just prove the console still answers
        from crystalpilot.io.olex2c import Olex2Console
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with Olex2Console(Path(td)) as ol:
                res = ol.command("echo alive", max_s=30.0)
        assert "alive" in res.output
