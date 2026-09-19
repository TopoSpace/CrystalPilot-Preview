"""High-level CAP reduction driver: watched send (hang discriminator)
and the cap_reduce chain, all against a mocked listen channel."""
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.io import crysalis_cap as cc
from crystalpilot.io.crysalis_listen import ListenModeClient


def _client(tmp_path):
    root = tmp_path / "listen"
    root.mkdir()
    return ListenModeClient(root)


def _answer(root: Path, delay: float, marker: str = "done"):
    def run():
        t0 = time.time()
        while time.time() - t0 < 10:
            if (root / "command.in").exists():
                try:
                    (root / "command.in").unlink()
                except OSError:
                    pass
                time.sleep(delay)
                (root / f"command.{marker}").write_text("")
                return
            time.sleep(0.02)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


class TestSendWatched:
    def test_done_flows_through(self, tmp_path):
        c = _client(tmp_path)
        _answer(c.root, 0.1)
        r = cc.send_watched(c, "ph snogui", timeout_s=5, poll_s=0.05)
        assert r.status == "done"

    def test_hang_discriminator_fires(self, tmp_path, monkeypatch):
        c = _client(tmp_path)
        # command.in consumed but neither done nor error ever appears,
        # and CAP burns no CPU -> HangSuspected, not a silent timeout
        _answer(c.root, 99, marker="never")
        monkeypatch.setattr(cc, "_cap_cpu_seconds", lambda: 100.0)
        with pytest.raises(cc.HangSuspected) as e:
            cc.send_watched(c, "dc proffittwin", timeout_s=10,
                            hang_after_s=0.1, burn_check_interval_s=0.2,
                            poll_s=0.05)
        assert "modal dialog" in str(e.value)

    def test_busy_with_burn_keeps_waiting(self, tmp_path, monkeypatch):
        c = _client(tmp_path)
        _answer(c.root, 1.2)
        burn = iter(range(0, 10000, 50))     # heavy CPU growth
        monkeypatch.setattr(cc, "_cap_cpu_seconds",
                            lambda: float(next(burn)))
        r = cc.send_watched(c, "dc proffit auto", timeout_s=8,
                            hang_after_s=0.1, burn_check_interval_s=0.2,
                            poll_s=0.05)
        assert r.status == "done"


class TestCapReduce:
    def test_chain_runs_and_extracts_log(self, tmp_path):
        c = _client(tmp_path)
        exp = tmp_path / "exp"
        (exp / "log").mkdir(parents=True)
        par = exp / "pg33.par"
        par.write_text("", encoding="utf-8")
        log = exp / "log" / "crysalispro_redLOGx.txt"
        log.write_text("", encoding="utf-8")
        hkl = exp / "pg33_autored.hkl"

        expected = [s[1].split()[0] + " " + s[1].split()[1]
                    for s in cc._STEPS]
        seen: list[str] = []

        def responder():
            t0 = time.time()
            n = 0
            while time.time() - t0 < 15 and n < len(cc._STEPS):
                f = c.root / "command.in"
                if f.exists():
                    cmd = f.read_text()
                    seen.append(" ".join(cmd.split()[:2]))
                    try:
                        f.unlink()
                    except OSError:
                        continue
                    name = cc._STEPS[n][0]
                    with log.open("a") as fh:
                        if name == "peaks":
                            fh.write("99999 peak locations are merged to "
                                     "40676 profiles (x)\n")
                        elif name == "refine":
                            fh.write("UB fit with 18921 obs out of "
                                     "40675\n")
                        elif name == "reduce":
                            fh.write("Reduction sum: file:///x/red.sum\n")
                            hkl.write_text("   1   0   0  1.0  0.1   1\n",
                                           encoding="utf-8")
                    (c.root / "command.done").write_text("")
                    n += 1
                time.sleep(0.02)
        threading.Thread(target=responder, daemon=True).start()

        pings: list[str] = []
        # fast polling for the test
        orig = cc.send_watched

        def fast(client, cmd, timeout_s=0, **kw):
            return orig(client, cmd, timeout_s=10, poll_s=0.03)
        cc_send = cc.send_watched
        cc.send_watched = fast
        try:
            r = cc.cap_reduce(par, client=c, progress=pings.append)
        finally:
            cc.send_watched = cc_send
        assert r["ok"], r
        assert [s.name for s in r["steps"]] == [s[0] for s in cc._STEPS]
        assert seen == expected
        assert r["hkl"].endswith("pg33_autored.hkl")
        peaks = next(s for s in r["steps"] if s.name == "peaks")
        assert any("40676 profiles" in x for x in peaks.log_extract)
        assert len(pings) == len(cc._STEPS)

    def test_missing_channel_reported(self, tmp_path):
        c = ListenModeClient(tmp_path / "nowhere")
        r = cc.cap_reduce(tmp_path / "x.par", client=c)
        assert not r["ok"] and "channel missing" in r["error"]

    def test_step_error_stops_chain(self, tmp_path):
        c = _client(tmp_path)
        exp = tmp_path / "exp"
        (exp / "log").mkdir(parents=True)
        par = exp / "pg33.par"
        par.write_text("", encoding="utf-8")
        _answer(c.root, 0.05, marker="error")
        orig = cc.send_watched

        def fast(client, cmd, timeout_s=0, **kw):
            return orig(client, cmd, timeout_s=5, poll_s=0.03)
        cc.send_watched = fast
        try:
            r = cc.cap_reduce(par, client=c)
        finally:
            cc.send_watched = orig
        assert not r["ok"]
        assert r["steps"][0].status == "error"
        assert len(r["steps"]) == 1
