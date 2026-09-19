"""Regression: the riding-H replay (run_shelxl adopt / checkout / import)
must never alias the loaded model's H labels.

pa2 cage-l0-r2, n0101 (add_hydrogens, 28 H) -> n0102 (run_shelxl adopt):
SHELXL's 25 cycles moved the model enough for the classifier to re-read
six CH2 carriers as aromatic CH and a tertiary CH / an aromatic CH / a
vinyl CH2 as CH2 / CH2 / CH3. add_hydrogens' sequential fallback names
(H1, H2, ...) then landed on carriers different from the ones that owned
those labels in the SHELXL model; rescue_lost_h deleted the 'lost' labels
- now other carriers' freshly derived H - and restored the verbatim H under
labels the surviving replay entries still referenced. Result: 171 atoms,
20 H, eleven H labels written twice in model.res, every later checkout
dead in iotbx's duplicate-label error. Same in n0106 -> n0107."""
import textwrap
from types import SimpleNamespace

#: P1, 12 A cell, three riding-H carriers >= 6 A apart.
#:   C1   - the loaded (SHELXL) model says CH2 (AFIX 23: H1, H2) but the
#:          geometry (two 1.25 A neighbours, 125 deg) reads as aromatic CH:
#:          the replay derives ONE H, C1 is 'short', rescue path.
#:   C123 - a genuine CH2 (two 1.52 A neighbours, 109.5 deg) whose 4-char
#:          label forces add_hydrogens' sequential fallback names (H123A is
#:          5 chars): without a reservation the replay calls its H 'H1'
#:          and 'H2' - C1's labels in the loaded model.
#:   C7   - the loaded model says tertiary CH (AFIX 13: H7) but the same
#:          CH2 geometry as C123: the replay derives TWO H - the n0131 ->
#:          n0132 direction (adopt gained an H, write_outputs: 'H 31 vs
#:          node 32'); the file's single H must be kept.
ADOPT_RES = textwrap.dedent("""\
    TITL adopt alias test
    CELL 0.71073 12.0 12.0 12.0 90.0 90.0 90.0
    ZERR 1 0.001 0.001 0.001 0.0 0.0 0.0
    LATT -1
    SFAC C H O
    UNIT 4 4 2
    WGHT 0.1
    FVAR 1.0
    C1   1  0.500000  0.500000  0.500000  11.00000  0.02000
    AFIX 23
    H1   2  0.500000  0.577000  0.500000  11.00000 -1.20000
    H2   2  0.545000  0.560000  0.500000  11.00000 -1.20000
    AFIX 0
    O1   3  0.592400  0.451900  0.500000  11.00000  0.02500
    O2   3  0.407600  0.451900  0.500000  11.00000  0.02500
    C123 1  0.100000  0.100000  0.100000  11.00000  0.02000
    AFIX 23
    H3   2  0.073000  0.062000  0.166000  11.00000 -1.20000
    H4   2  0.073000  0.062000  0.034000  11.00000 -1.20000
    AFIX 0
    C2   1  0.226700  0.100000  0.100000  11.00000  0.02000
    C3   1  0.057700  0.219400  0.100000  11.00000  0.02000
    C7   1  0.100000  0.500000  0.800000  11.00000  0.02000
    AFIX 13
    H7   2  0.052900  0.433300  0.800000  11.00000 -1.20000
    AFIX 0
    C8   1  0.226700  0.500000  0.800000  11.00000  0.02000
    C9   1  0.057700  0.619400  0.800000  11.00000  0.02000
    HKLF 4
    END
    """)


class _Store:
    def emit(self, *a, **k):
        return SimpleNamespace(event_id="e0")


def _is_h(sc) -> bool:
    return sc.scattering_type.strip().capitalize() == "H"


def _session_for(xs):
    from crystalpilot.core.dataset import ReflectionDataset
    from crystalpilot.pipeline.session import SolveSession
    from crystalpilot.refine.registry import refinement_registry
    from crystalpilot.tools.base import ToolContext
    xs.scattering_type_registry(table="it1992")
    ses = SolveSession(dataset=ReflectionDataset(intensities=None,
                                                 wavelength=0.71073))
    ses.model = xs
    ses.symmetry = xs.crystal_symmetry()
    return refinement_registry(None), ToolContext(store=_Store(),
                                                  session=ses), ses


def _adopt_session(tmp_path):
    """The state run_shelxl(mode='adopt') is in right before the replay:
    the SHELXL job.res loaded, the previous node's riding meta still in
    the flags."""
    from crystalpilot.io.shelx_model import load_res_model
    p = tmp_path / "job.res"
    p.write_text(ADOPT_RES, encoding="utf-8")
    parsed = load_res_model(p)
    reg, ctx, ses = _session_for(parsed.structure)
    ses.flags["h_riding_meta"] = {
        "elements": ["C"], "per_carrier": [dict(g) for g in parsed.h_riding],
        "params": {"elements": ["C"]}}
    return reg, ctx, ses, parsed


def _frac_dist(uc, a, b) -> float:
    return float(uc.length([x - y - round(x - y) for x, y in zip(a, b)]))


class TestAdoptReplayLabelAliasing:
    def test_replay_never_aliases_loaded_h_labels(self, tmp_path):
        from crystalpilot.io.shelx_model import load_res_model
        from crystalpilot.io.shelx_writer import ShelxModel, write_res_text
        from crystalpilot.refine.tools_shelxl import replay_riding_h

        reg, ctx, ses, parsed = _adopt_session(tmp_path)
        out = replay_riding_h(reg, ctx, ses, parsed.h_riding)

        pc = ses.flags["h_riding_meta"]["per_carrier"]
        refs = [h.upper() for g in pc for h in g["h"]]
        assert len(refs) == len(set(refs)), \
            f"an H label is referenced by two carriers: {pc}"
        labels = [sc.label.upper() for sc in ses.model.scatterers()]
        assert len(labels) == len(set(labels)), labels
        site = {sc.label.upper(): tuple(sc.site)
                for sc in ses.model.scatterers()}
        h_now = {sc.label.upper() for sc in ses.model.scatterers()
                 if _is_h(sc)}
        # exactly the H the loaded model carries - no more, no fewer
        assert len(h_now) == 5 and out["h_replay"]["n_h_after"] == 5, out
        uc = ses.model.unit_cell()
        for g in pc:
            for h in g["h"]:
                assert h.upper() in h_now, (g, h)
                d = _frac_dist(uc, site[h.upper()], site[g["carrier"].upper()])
                assert d < 1.3, f"{h} listed under {g['carrier']} sits {d:.2f} A away"
        by_c = {g["carrier"].upper(): sorted(h.upper() for h in g["h"])
                for g in pc}
        # C1 (short) and C7 (the replay wanted a second H) keep the SHELXL
        # H verbatim; C123 re-derived its two H and kept the loaded
        # model's labels for them
        assert by_c == {"C1": ["H1", "H2"], "C123": ["H3", "H4"],
                        "C7": ["H7"]}, by_c
        assert out["h_replay_rescued"]["carriers"] == ["C1", "C7"]
        assert "h_replay_lost" not in out
        assert out["h_replay"]["replaced"] == 2
        assert out["h_replay"]["kept_verbatim"] == 3
        # the stored params stay the agent's call (no internal channel)
        assert ses.flags["h_riding_meta"]["params"] == {"elements": ["C"]}

        # the node this state commits must be re-loadable: the pa2 failure
        # surfaced as iotbx's broken duplicate-label error on every checkout
        txt, rename = write_res_text(ShelxModel(
            xray_structure=ses.model, wavelength=0.71073, z=1, h_riding=pc))
        assert rename == {}
        p2 = tmp_path / "node.res"
        p2.write_text(txt, encoding="utf-8")
        again = load_res_model(p2)
        assert sum(1 for sc in again.structure.scatterers() if _is_h(sc)) == 5
        groups = {g["carrier"]: g for g in again.h_riding}
        assert set(groups) == {"C1", "C123", "C7"}
        # verbatim groups keep the file's AFIX codes, not the classifier's
        assert groups["C1"]["afix"] == 23 and groups["C7"]["afix"] == 13


class TestAddHydrogensReservedLabels:
    @staticmethod
    def _ch2_model():
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(12, 12, 12, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        for lbl, site in (("C123", (0.1, 0.1, 0.1)),
                          ("C2", (0.2267, 0.1, 0.1)),
                          ("C3", (0.0577, 0.2194, 0.1))):
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=site, scattering_type="C", u=0.03))
        return xs

    def test_internal_reserve_keeps_fallback_numbering_off_taken_names(self):
        from crystalpilot.tools.base import invoke
        reg, ctx, ses = _session_for(self._ch2_model())
        r = invoke(reg, ctx, "add_hydrogens",
                   {"elements": ["C"], "exclude": ["C2", "C3"]})
        assert r.ok, r.error
        assert r.summary["per_carrier"][0]["h"] == ["H1", "H2"]

        reg, ctx, ses = _session_for(self._ch2_model())
        r = invoke(reg, ctx, "add_hydrogens",
                   {"elements": ["C"], "exclude": ["C2", "C3"],
                    "_reserve_labels": ["H1", "h2", "H3"]})
        assert r.ok, r.error
        assert r.summary["per_carrier"][0]["h"] == ["H4", "H5"]
        labels = {sc.label for sc in ses.model.scatterers()}
        assert {"H4", "H5"} <= labels and not {"H1", "H2", "H3"} & labels
        # the reservation is a replay-internal channel, never stored as
        # part of the agent's add_hydrogens parameters
        assert "_reserve_labels" not in ses.flags["h_riding_meta"]["params"]


class TestWriterEmitsEachRidingHOnce:
    def test_double_referenced_h_written_once(self, tmp_path):
        """Defence in depth: a per_carrier list that names one H under two
        carriers (the n0102 corruption) must not become a .res with the
        atom card twice - that file is unparseable by iotbx."""
        from cctbx import crystal, xray
        from crystalpilot.io.shelx_model import load_res_model
        from crystalpilot.io.shelx_writer import ShelxModel, write_res_text
        cs = crystal.symmetry(unit_cell=(12, 12, 12, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        for lbl, el, site in (("C1", "C", (0.5, 0.5, 0.5)),
                              ("H1", "H", (0.5, 0.577, 0.5)),
                              ("H2", "H", (0.545, 0.56, 0.5)),
                              ("C5", "C", (0.1, 0.1, 0.1))):
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=site, scattering_type=el, u=0.03))
        txt, _ = write_res_text(ShelxModel(
            xray_structure=xs, wavelength=0.71073, z=1,
            h_riding=[{"carrier": "C1", "kind": "CH2", "h": ["H1", "H2"]},
                      {"carrier": "C5", "kind": "CH2", "h": ["H1", "H2"]}]))
        cards = [ln.split()[0] for ln in txt.splitlines()
                 if ln[:1] in ("C", "H")]
        assert cards.count("H1") == 1 and cards.count("H2") == 1, txt
        assert cards.count("C1") == 1 and cards.count("C5") == 1, txt
        p = tmp_path / "dup.res"
        p.write_text(txt, encoding="utf-8")
        parsed = load_res_model(p)          # must not raise (duplicate labels)
        assert parsed.structure.scatterers().size() == 4
        # the H ride on the FIRST carrier that listed them; the second
        # carrier is written bare, not with an empty AFIX block
        assert [g["carrier"] for g in parsed.h_riding] == ["C1"]
        assert "AFIX 23\nAFIX 0" not in txt
