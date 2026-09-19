"""Per-atom H classification overrides (process audit T10).

The geometry heuristics misread individual carriers in six campaigns
(r20 C11 five re-tunes then pinned sideways with DANG, r21 C14, r14a H11,
r11_d twice, r22 staggered XH3). Every one of them was fought with GLOBAL
thresholds, which move every other carrier too and get overwritten on the
next re-run. force_kind / exclude are the per-atom entry points.
"""
from cctbx import crystal, xray

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.tools.base import ToolContext
from crystalpilot.tools.hydrogen_tools import AddHydrogens


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _session():
    """C1-C2-C3 chain (106 deg at C2, 1.50 A bonds -> auto-read CH2),
    plus a terminal methyl carbon C4 and a hydroxyl O1."""
    cs = crystal.symmetry(unit_cell=(15, 15, 15, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()

    def add(label, el, cart):
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.03, occupancy=1.0))

    add("C1", "C", (3.80, 5.90, 5.0))
    add("C2", "C", (5.00, 5.00, 5.0))
    add("C3", "C", (6.20, 5.90, 5.0))
    # terminal methyl on C1
    add("C4", "C", (3.00, 4.60, 5.0))
    # hydroxyl O on C3
    add("O1", "O", (7.00, 4.70, 5.0))
    xs.scattering_type_registry(table="it1992")
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = cs
    return ses


def _ctx(ses):
    return ToolContext(store=_Store(), session=ses)


def _kinds(summary):
    return {p["carrier"]: p["kind"] for p in summary["per_carrier"]}


class TestForceKind:
    def test_auto_reads_the_narrow_angle_as_ch2(self):
        # control: 106 deg at C2 and 1.50 A bonds -> sp3 CH2 by the
        # thresholds. A chemist reading the wider fragment may know it is
        # an aromatic CH; that disagreement is what force_kind settles.
        r = AddHydrogens().run(_ctx(_session()), elements=["C"])
        assert r.ok, r.error
        assert _kinds(r.summary)["C2"] == "CH2"

    def test_force_kind_overrides_the_classification(self):
        r = AddHydrogens().run(_ctx(_session()), elements=["C"],
                               force_kind={"C2": "aromatic_CH"})
        assert r.ok, r.error
        k = _kinds(r.summary)
        assert k["C2"] == "aromatic_CH"
        # the other carriers keep their automatic reading
        assert k["C1"] == "CH2" and k["C4"] == "CH3"
        assert r.summary["forced_kinds"] == {"C2": "aromatic_CH"}
        assert any("FORCED" in w for w in r.summary["warnings"])

    def test_label_case_is_folded(self):
        r = AddHydrogens().run(_ctx(_session()), elements=["C"],
                               force_kind={"c2": "aromatic_CH"})
        assert r.ok, r.error
        assert _kinds(r.summary)["C2"] == "aromatic_CH"

    def test_force_kind_reaches_elements_not_listed(self):
        # O is not in elements=, but naming it explicitly is the opt-in
        r = AddHydrogens().run(_ctx(_session()), elements=["C"],
                               force_kind={"O1": "OH"})
        assert r.ok, r.error
        assert _kinds(r.summary)["O1"] == "OH"

    def test_wrong_neighbour_count_is_refused_not_fudged(self):
        # CH3 geometry is built from ONE bond vector; C2 has two
        r = AddHydrogens().run(_ctx(_session()), elements=["C"],
                               force_kind={"C2": "CH3"})
        assert r.ok, r.error
        assert "C2" not in _kinds(r.summary)
        reason = next(s["reason"] for s in r.summary["skipped"]
                      if s["atom"] == "C2")
        assert "heavy neighbour" in reason

    def test_unknown_kind_rejected_with_the_valid_list(self):
        r = AddHydrogens().run(_ctx(_session()), elements=["C"],
                               force_kind={"C2": "CH4"})
        assert not r.ok
        assert "CH4" in r.error and "aromatic_CH" in r.error

    def test_unknown_label_rejected(self):
        # a silent no-op typo is the exact friction being removed
        r = AddHydrogens().run(_ctx(_session()), elements=["C"],
                               force_kind={"C99": "CH2"})
        assert not r.ok
        assert "C99" in r.error


class TestExclude:
    def test_excluded_carrier_gets_no_h(self):
        base = AddHydrogens().run(_ctx(_session()), elements=["C"])
        r = AddHydrogens().run(_ctx(_session()), elements=["C"],
                               exclude=["C4"])
        assert r.ok, r.error
        assert "C4" not in _kinds(r.summary)
        # C4 was a methyl: three fewer H than the unrestricted run
        assert r.summary["n_h_added"] == base.summary["n_h_added"] - 3
        assert r.summary["excluded"] == ["C4"]
        assert any(s["atom"] == "C4" and "exclude" in s["reason"]
                   for s in r.summary["skipped"])

    def test_unknown_label_rejected(self):
        r = AddHydrogens().run(_ctx(_session()), elements=["C"],
                               exclude=["ZZ1"])
        assert not r.ok
        assert "ZZ1" in r.error


class TestOverridesSurviveRerun:
    def test_same_overrides_reproduce_the_same_model(self):
        """The complaint was that a fixed carrier reverts on the next
        re-run. With the override in the call it does not."""
        ses = _session()
        t = AddHydrogens()
        first = t.run(_ctx(ses), elements=["C"], force_kind={"C2": "aromatic_CH"})
        second = t.run(_ctx(ses), elements=["C"], force_kind={"C2": "aromatic_CH"})
        assert second.ok, second.error
        assert _kinds(second.summary)["C2"] == "aromatic_CH"
        assert second.summary["n_h_added"] == first.summary["n_h_added"]
        assert second.summary["n_h_removed"] == first.summary["n_h_added"]


class TestAddAtomsAtExplicitSites:
    """Process audit T3 residual: the tool could only place atoms at
    CACHED difference-map peaks, so a site the agent derived itself (a
    symmetry image, a midpoint, a position read off another model) had no
    entry point at all - and without a prior refine it refused outright."""

    def test_places_atoms_without_any_stored_peaks(self):
        from crystalpilot.tools.model_tools import AddAtomsFromDifferenceMap
        ses = _session()
        assert not ses.flags.get("diff_map_peaks")
        r = AddAtomsFromDifferenceMap().run(
            _ctx(ses), sites=[[0.8, 0.8, 0.8]], element="O")
        assert r.ok, r.error
        assert r.summary["mode"] == "explicit_sites"
        assert r.summary["added"][0]["label"] == "O2X"
        assert ses.model.scatterers().size() == 6

    def test_explicit_labels_and_duplicate_guard(self):
        from crystalpilot.tools.model_tools import AddAtomsFromDifferenceMap
        ses = _session()
        t = AddAtomsFromDifferenceMap()
        r = t.run(_ctx(ses), sites=[[0.8, 0.8, 0.8]], element="O",
                  labels=["O9"])
        assert r.ok, r.error
        assert r.summary["added"][0]["label"] == "O9"
        clash = t.run(_ctx(ses), sites=[[0.2, 0.7, 0.7]], element="O",
                      labels=["O9"])
        assert not clash.ok and "already in the model" in clash.error

    def test_overlap_is_refused_atomically(self):
        from crystalpilot.tools.model_tools import AddAtomsFromDifferenceMap
        ses = _session()
        n0 = ses.model.scatterers().size()
        # C2 sits at (5,5,5) cart in a 15 A cell -> 1/3,1/3,1/3
        r = AddAtomsFromDifferenceMap().run(
            _ctx(ses), sites=[[0.9, 0.9, 0.9], [1 / 3, 1 / 3, 1 / 3]],
            element="C")
        assert not r.ok and "overlap" in r.error
        assert ses.model.scatterers().size() == n0, "must add nothing on refusal"

    def test_close_contact_warns_but_proceeds(self):
        from crystalpilot.tools.model_tools import AddAtomsFromDifferenceMap
        ses = _session()
        # ~0.9 A from C2 at (5,5,5): plausible for H, suspicious for C
        r = AddAtomsFromDifferenceMap().run(
            _ctx(ses), sites=[[(5.0 + 0.9) / 15, 1 / 3, 1 / 3]], element="C")
        assert r.ok, r.error
        assert any("ADP residual" in w for w in r.summary["warnings"])

    def test_mutually_exclusive_with_peak_indices(self):
        from crystalpilot.tools.model_tools import AddAtomsFromDifferenceMap
        r = AddAtomsFromDifferenceMap().run(
            _ctx(_session()), sites=[[0.5, 0.5, 0.5]], peak_indices=[0])
        assert not r.ok and "not both" in r.error

    def test_malformed_site_reported(self):
        from crystalpilot.tools.model_tools import AddAtomsFromDifferenceMap
        r = AddAtomsFromDifferenceMap().run(
            _ctx(_session()), sites=[[0.5, 0.5]])
        assert not r.ok and "fractional coordinates" in r.error

    def test_peak_route_points_at_the_new_one(self):
        from crystalpilot.tools.model_tools import AddAtomsFromDifferenceMap
        r = AddAtomsFromDifferenceMap().run(_ctx(_session()), element="O")
        assert not r.ok
        assert "sites=" in r.error


class TestUnknownLabelRefusalKeepsH:
    def test_stale_label_refused_before_the_strip(self):
        """hex-l2-r2 first adopt: the replay passed force_kind={'O007':
        'OH'} after rename_atoms had made it O5; add_hydrogens refused the
        label AFTER stripping every H, so a plain parameter error left the
        model with no H at all (all 7 came back 'rescued' as 'classifier
        drift'). The label check must run before anything is removed."""
        ses = _session()
        r0 = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r0.ok and r0.summary["n_h_added"] > 0
        n_h = sum(1 for sc in ses.model.scatterers()
                  if sc.scattering_type.strip().upper() == "H")
        meta = ses.flags["h_riding_meta"]
        r = AddHydrogens().run(_ctx(ses), elements=["C"],
                               force_kind={"O007": "OH"})
        assert not r.ok and "O007" in r.error
        assert sum(1 for sc in ses.model.scatterers()
                   if sc.scattering_type.strip().upper() == "H") == n_h
        assert ses.flags["h_riding_meta"] is meta
        r2 = AddHydrogens().run(_ctx(ses), elements=["C"], exclude=["C99"])
        assert not r2.ok and "C99" in r2.error
