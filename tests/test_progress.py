"""Process-audit T2: long-call liveness. Heartbeat helper, charge-flipping
completeness guard, superflip timeout trajectory."""
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


class TestProgressHeartbeat:
    def test_pings_flow_and_stop(self):
        from crystalpilot.tools.base import progress_heartbeat
        msgs: list[str] = []
        ctx = SimpleNamespace(progress=msgs.append)
        with progress_heartbeat(ctx, "refine[test]: 10 atoms",
                                interval=0.05):
            time.sleep(0.18)
        n_inside = len(msgs)
        assert n_inside >= 2
        assert "refine[test]" in msgs[0]
        assert "not waiting on approval" in msgs[0]
        time.sleep(0.12)                      # thread must have stopped
        assert len(msgs) == n_inside

    def test_noop_without_sink_and_survives_bad_sink(self):
        from crystalpilot.tools.base import progress_heartbeat
        with progress_heartbeat(SimpleNamespace(progress=None), "x",
                                interval=0.01):
            time.sleep(0.03)

        def _boom(_msg):
            raise RuntimeError("sink gone")
        with progress_heartbeat(SimpleNamespace(progress=_boom), "x",
                                interval=0.01):
            time.sleep(0.05)                  # must not raise


class TestCompletenessGuard:
    @staticmethod
    def _fo_sq(fraction: float):
        from cctbx import crystal, miller
        from cctbx.array_family import flex
        cs = crystal.symmetry(unit_cell=(8, 9, 10, 90, 95, 90),
                              space_group_symbol="P 21/c")
        ms = miller.build_set(cs, anomalous_flag=False, d_min=1.0)
        n = ms.indices().size()
        keep = flex.bool([(i * 7919) % 1000 < fraction * 1000
                          for i in range(n)])
        sub = ms.select(keep)
        arr = miller.array(sub, data=flex.double(sub.size(), 100.0),
                           sigmas=flex.double(sub.size(), 3.0))
        return arr.set_observation_type_xray_intensity()

    def test_sparse_refused_with_record(self):
        from crystalpilot.tools.solution_tools import _completeness_guard
        msg = _completeness_guard(self._fo_sq(0.4), {}, "built-in")
        assert msg is not None
        assert "0/6" in msg and "allow_low_completeness" in msg

    def test_override_and_dense_pass(self):
        from crystalpilot.tools.solution_tools import _completeness_guard
        assert _completeness_guard(
            self._fo_sq(0.4), {"allow_low_completeness": True}, "x") is None
        assert _completeness_guard(self._fo_sq(1.0), {}, "x") is None


class TestSuperflipTimeoutTrajectory:
    def test_flat_trajectory_reported(self, tmp_path, monkeypatch):
        from crystalpilot.tools import solution_tools as st
        fake_exe = tmp_path / "superflip.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(st, "SUPERFLIP_EXE", fake_exe)
        partial = "\n".join(
            f"cycle {i} R: 41.{i % 7}" for i in range(12))

        def _fake_run(*a, **k):
            raise subprocess.TimeoutExpired(
                cmd="superflip", timeout=5, output=partial)
        monkeypatch.setattr(st.subprocess, "run", _fake_run)

        sys.path.insert(0, str(REPO))
        sys.modules.pop("tests.test_superflip", None)
        from tests.test_superflip import _ctx, _synthetic_session
        ses, _ = _synthetic_session()
        r = st.SolveSuperflip().run(_ctx(ses), timeout_s=5)
        assert not r.ok
        assert "R trajectory" in r.error
        assert "FLAT" in r.error
        job = sorted((REPO / "workdir" / "superflip_jobs").glob("job_*"))[-1]
        assert (job / "superflip_partial.log").exists()

    def test_falling_trajectory_suggests_more_time(self, tmp_path,
                                                   monkeypatch):
        from crystalpilot.tools import solution_tools as st
        fake_exe = tmp_path / "superflip.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(st, "SUPERFLIP_EXE", fake_exe)
        rs = [45.0, 44.0, 43.0, 40.0, 35.0, 28.0, 22.0]
        partial = "\n".join(f"R: {v}" for v in rs)

        def _fake_run(*a, **k):
            raise subprocess.TimeoutExpired(
                cmd="superflip", timeout=5, output=partial)
        monkeypatch.setattr(st.subprocess, "run", _fake_run)
        from tests.test_superflip import _ctx, _synthetic_session
        ses, _ = _synthetic_session()
        r = st.SolveSuperflip().run(_ctx(ses), timeout_s=5)
        assert not r.ok and "still moving" in r.error
