"""Resolution-shelled intensity statistics with directional verdicts.

Every fixture here is COMPUTED, never hand-written: Fo^2 comes from a
cctbx structure, twinning from mixing two intensities under a twin law,
a pseudo-translation from a genuinely doubled cell. Two baselines are
used on purpose:

* a Wilson-ideal control - the benzoic-acid formula unit with its atoms
  placed at random - which reproduces the tabulated references to within
  a few per cent and is therefore the only fair background against which
  a twin signature can be measured;
* the REAL benzoic-acid dimer geometry, which does NOT reproduce them: a
  flat rigid molecule reads <|E^2-1|> ~ 1.08 and <I^2>/<I>^2 ~ 4.1 where
  the ideal centric values are 0.968 and 3.000. Both published reference
  datasets in benchmark/data_ext2 read the same way. That is the
  calibration fact behind the asymmetry the tool implements: the UPWARD
  direction is where ordinary molecular crystals already live, so it is
  never claimed without an independent signature, while the DOWNWARD
  direction (which none of those contaminants can produce) is.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cctbx import crystal, miller, sgtbx, xray          # noqa: E402
from cctbx.array_family import flex                     # noqa: E402

from crystalpilot.refine import sg_screen as S          # noqa: E402

# --------------------------------------------------------------------- data


def _fo_sq(xs, d_min: float = 0.8, seed: int = 7, noise: float = 0.02):
    """Fo^2 from a structure: |Fc|^2 plus a small measurement jitter."""
    fc = xs.structure_factors(d_min=d_min, algorithm="direct").f_calc()
    i = fc.as_intensity_array()
    rng = flex.mersenne_twister(seed)
    data = i.data()
    sig = flex.double([max(noise * abs(v), 1e-3) for v in data])
    jitter = (rng.random_double(data.size()) - 0.5) * 2.0
    return miller.array(i.set(), data=data + jitter * sig,
                        sigmas=sig).set_observation_type_xray_intensity()


def _wilson_p1bar(cell=(7.4, 8.1, 8.3, 90.0, 97.0, 90.0), seed=13):
    """Benzoic-acid formula unit (C7 H6 O2) in P-1 with its atoms at
    random, minimum-distance-constrained positions: same composition and
    cell as the dimer fixture, but WITHOUT the rigid molecular geometry -
    the classical Wilson assumption made concrete."""
    from cctbx.development import random_structure
    flex.set_random_seed(seed)
    return random_structure.xray_structure(
        space_group_info=sgtbx.space_group_info("P -1"),
        unit_cell=cell,
        elements=["C"] * 7 + ["O"] * 2 + ["H"] * 6,
        min_distance=1.0, random_u_iso=True, u_iso=0.03)


def _acentric_p1(cell=(7.4, 8.1, 8.3, 90.0, 97.0, 90.0), seed=13):
    """The same composition and cell in P1 - an acentric structure whose
    metric still supports the two-fold used as the twin law below, i.e.
    the pseudo-merohedral twin precondition. Twinning by merohedry of an
    ACENTRIC structure is the case the tabulated perfect-twin values
    describe (1.500 / 0.885 / 0.541)."""
    from cctbx.development import random_structure
    flex.set_random_seed(seed)
    return random_structure.xray_structure(
        space_group_info=sgtbx.space_group_info("P 1"),
        unit_cell=cell,
        elements=["C"] * 7 + ["O"] * 2 + ["H"] * 6,
        min_distance=1.0, random_u_iso=True, u_iso=0.03)


def _benzoic_dimer(cell=(7.2, 8.1, 8.6, 90.0, 102.0, 90.0)):
    """The real thing: one benzoic acid molecule in the P-1 asymmetric
    unit, placed so the inversion centre at the origin builds the
    carboxylic-acid dimer (O...O 2.65 A), then rotated to a general
    orientation so no accidental half-cell translation is created."""
    r = 1.395
    ring = [(r, 0.0, 0.0), (r / 2, 1.208, 0.0), (-r / 2, 1.208, 0.0),
            (-r, 0.0, 0.0), (-r / 2, -1.208, 0.0), (r / 2, -1.208, 0.0)]
    atoms = [("C1", "C", ring[0]), ("C2", "C", ring[1]),
             ("C3", "C", ring[2]), ("C4", "C", ring[3]),
             ("C5", "C", ring[4]), ("C6", "C", ring[5]),
             ("C7", "C", (2.875, 0.0, 0.0)),
             ("O1", "O", (3.485, 1.056, 0.0)),
             ("O2", "O", (3.530, -1.134, 0.0))]
    for i in (1, 2, 3, 4, 5):
        c, f = ring[i], (r + 1.08) / r
        atoms.append((f"H{i + 1}", "H", (c[0] * f, c[1] * f, c[2] * f)))
    atoms.append(("H2A", "H", (3.88, -1.98, 0.0)))
    shift = (-2.1825, 0.039, 0.0)
    rx, ry, rz = math.radians(35), math.radians(25), math.radians(40)

    def _rot(c):
        x, y, z = c
        y, z = (y * math.cos(rx) - z * math.sin(rx),
                y * math.sin(rx) + z * math.cos(rx))
        x, z = (x * math.cos(ry) + z * math.sin(ry),
                -x * math.sin(ry) + z * math.cos(ry))
        x, y = (x * math.cos(rz) - y * math.sin(rz),
                x * math.sin(rz) + y * math.cos(rz))
        return (x, y, z)

    cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = xs.unit_cell()
    for lbl, el, c in atoms:
        site = uc.fractionalize(_rot((c[0] + shift[0], c[1] + shift[1],
                                      c[2] + shift[2])))
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=site, u=0.030 if el != "H" else 0.05,
            scattering_type=el))
    return xs


def _twin_50_50(arr, law=lambda h: (-h[0], h[1], -h[2])):
    """I_obs(h) = 0.5 I(h) + 0.5 I(h'), h' = the twin image of h - a
    perfectly twinned two-domain crystal, built from the SAME intensities
    so the only difference from the baseline is the superposition."""
    idx, data = arr.indices(), arr.data()
    lookup: dict[tuple, int] = {}
    for i, h in enumerate(idx):
        lookup[tuple(h)] = i
        lookup[(-h[0], -h[1], -h[2])] = i        # Friedel mate
    keep = flex.bool(idx.size(), False)
    mixed = flex.double()
    for i, h in enumerate(idx):
        j = lookup.get(tuple(law(h)))
        if j is None:
            continue
        keep[i] = True
        mixed.append(0.5 * float(data[i]) + 0.5 * float(data[j]))
    out = miller.array(arr.select(keep).set(), data=mixed,
                       sigmas=arr.sigmas().select(keep))
    return out.set_observation_type_xray_intensity()


def _doubled_cell(seed=13):
    """A real superstructure: the Wilson control's content repeated at
    z and z+1/2 in a c-doubled cell, the second copy displaced slightly.
    The l-odd reflections become a weak (not absent) class - textbook
    pseudo-translational symmetry."""
    src = _wilson_p1bar(seed=seed)
    a, b, c, al, be, ga = src.unit_cell().parameters()
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=(a, b, 2 * c, al, be, ga), space_group_symbol="P -1"))
    for sc in src.scatterers():
        s = sc.site
        xs.add_scatterer(xray.scatterer(
            label=sc.label + "a", site=(s[0], s[1], s[2] / 2.0),
            u=sc.u_iso, scattering_type=sc.scattering_type))
        xs.add_scatterer(xray.scatterer(
            label=sc.label + "b",
            site=(s[0] + 0.004, s[1] - 0.003, s[2] / 2.0 + 0.5),
            u=sc.u_iso, scattering_type=sc.scattering_type))
    return xs


def _zr_salt():
    """A Zr salt with the metal ON a special position: Zr at the P-1
    inversion centre, oxygens and carbons around it. Zr (Z=40) carries
    more than half of sum(n Z^2) by itself - the composition XPREP names
    as the |E^2-1| failure case, 'especially when they lie on special
    positions'."""
    cs = crystal.symmetry(unit_cell=(9.6, 10.4, 11.1, 91.0, 99.0, 104.0),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    xs.add_scatterer(xray.scatterer(label="ZR1", site=(0.0, 0.0, 0.0),
                                    u=0.02, scattering_type="Zr"))
    ligand = [("O1", "O", (0.131, 0.052, 0.184)),
              ("O2", "O", (0.212, 0.311, 0.043)),
              ("O3", "O", (0.041, 0.219, 0.372)),
              ("O4", "O", (0.318, 0.152, 0.291)),
              ("O5", "O", (0.402, 0.371, 0.196)),
              ("O6", "O", (0.246, 0.462, 0.351)),
              ("O7", "O", (0.113, 0.401, 0.512)),
              ("O8", "O", (0.371, 0.083, 0.472)),
              ("C1", "C", (0.181, 0.192, 0.121)),
              ("C2", "C", (0.288, 0.271, 0.361)),
              ("C3", "C", (0.442, 0.211, 0.081)),
              ("C4", "C", (0.062, 0.331, 0.451))]
    for lbl, el, site in ligand:
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.035,
                                        scattering_type=el))
    return xs


def _laue(xs):
    return xs.space_group().build_derived_laue_group()


NO_PASS_WORDS = ("pass", "passed", "passes", "通过", "合格", "ok,", " fine")


def _assert_no_pass_wording(text: str):
    low = text.lower()
    for w in NO_PASS_WORDS:
        assert w not in low, f"verdict claims a pass: {w!r} in {text!r}"


# ------------------------------------------------------- the shelled statistic


class TestShellTable:
    def test_shells_carry_d_ranges_counts_and_the_value(self):
        xs = _wilson_p1bar()
        arr = _fo_sq(xs)
        out = S.e2m1_by_shell(arr, _laue(xs), n_shells=8)
        assert out["n_shells"] >= 6
        for sh in out["shells"]:
            assert sh["d_min"] > 0 and sh["n"] > 0
            assert sh["d_max"] is None or sh["d_max"] >= sh["d_min"]
            assert 0.0 <= sh["mean_abs_e2_minus_1"] < 5.0
        # shells run from low to high resolution
        d = [sh["d_min"] for sh in out["shells"]]
        assert d == sorted(d, reverse=True)
        assert out["overall"]["n"] == sum(sh["n"] for sh in out["shells"])
        # the expectations are stated ONCE, in the module constant
        assert out["reference"] == S.E2M1_REFERENCE
        assert S.E2M1_REFERENCE == {"centrosymmetric": 0.968,
                                    "non_centrosymmetric": 0.736}

    def test_a_wilson_ideal_p1bar_control_reproduces_the_centric_values(self):
        xs = _wilson_p1bar()
        arr = _fo_sq(xs)
        out = S.e2m1_by_shell(arr, _laue(xs), n_shells=8)
        assert abs(out["overall"]["mean_abs_e2_minus_1"] - 0.968) < 0.08
        m = S.intensity_moments(arr, _laue(xs))
        # the second moment is the one that feels the finite atom count:
        # 9 non-H atoms in the asymmetric unit are not the asymptotic
        # Wilson limit, and the measured 2.70 sits about 10 % below the
        # ideal 3.0 (a 40-atom control lands at 2.96)
        assert abs(m["i2_over_i_sq"]["value"] - 3.0) < 0.4
        assert abs(m["f_sq_over_f2"]["value"] - 0.637) < 0.03
        lt = S.l_test(arr, _laue(xs))
        # every reflection of a centrosymmetric structure is centric, so
        # the untwinned expectation is 2/pi, not the macromolecular 0.5
        assert abs(lt["mean_abs_l"]["value"] - 0.637) < 0.04
        assert abs(lt["mean_l_sq"]["value"] - 0.5) < 0.05

    def test_no_verdict_anywhere_reads_as_a_pass(self):
        xs = _wilson_p1bar()
        arr = _fo_sq(xs)
        laue = _laue(xs)
        texts = [S.e2m1_by_shell(arr, laue, n_shells=8)["reading"]["verdict"]]
        m = S.intensity_moments(arr, laue)
        texts += [m[k]["verdict"] for k in ("mean_abs_e2_minus_1",
                                            "i2_over_i_sq", "f_sq_over_f2")]
        lt = S.l_test(arr, laue)
        texts += [lt[k]["verdict"] for k in ("mean_abs_l", "mean_l_sq")]
        for t in texts:
            _assert_no_pass_wording(t)
        # and a healthy baseline claims nothing in either direction
        assert m["i2_over_i_sq"]["argues_for"] == []


# ----------------------------------------------------------------- twinning


class TestFiftyFiftyTwin:
    def test_second_moment_drops_below_the_acentric_value(self):
        """A 50:50 twin of an ACENTRIC structure: <I^2>/<I>^2 falls to the
        tabulated perfect-twin value 1.500, i.e. clearly below the
        untwinned acentric 2.000, and the verdict says twinning without
        mentioning a pseudo-translation."""
        xs = _acentric_p1()
        base = _fo_sq(xs)
        laue = _laue(xs)
        twin = _twin_50_50(base)
        m_base = S.intensity_moments(base, laue)
        m_twin = S.intensity_moments(twin, laue)
        assert m_twin["i2_over_i_sq"]["value"] < 2.0
        assert abs(m_twin["i2_over_i_sq"]["value"] - 1.5) < 0.15
        assert (m_twin["i2_over_i_sq"]["value"]
                < m_base["i2_over_i_sq"]["value"])
        r = m_twin["i2_over_i_sq"]
        assert r["argues_for"] == ["twinning"]
        assert r["strength"] == "clear"
        assert r["direction"] == "beyond_acentric_on_the_twin_side"
        v = r["verdict"].lower()
        assert "twin" in v
        assert "pseudo-translation" not in v and "pseudo translation" not in v
        _assert_no_pass_wording(v)
        # the excluded reading lives in its own field, not in the verdict
        assert "pseudo-translation" in r["not_argued_for"]

    def test_the_other_two_moments_reach_their_perfect_twin_values(self):
        xs = _acentric_p1()
        laue = _laue(xs)
        twin = _twin_50_50(_fo_sq(xs))
        m = S.intensity_moments(twin, laue)
        lt = S.l_test(twin, laue)
        # <F>^2/<F^2> RISES to 0.885 while <|E^2-1|> FALLS to 0.541: same
        # diagnosis, opposite signs - which is why the direction, not the
        # offset, is what the verdict reports
        assert abs(m["f_sq_over_f2"]["value"] - 0.885) < 0.03
        assert abs(m["mean_abs_e2_minus_1"]["value"] - 0.541) < 0.05
        assert abs(lt["mean_abs_l"]["value"] - 0.375) < 0.05
        assert abs(lt["mean_l_sq"]["value"] - 0.200) < 0.05
        for r in (m["f_sq_over_f2"], m["mean_abs_e2_minus_1"],
                  lt["mean_abs_l"], lt["mean_l_sq"]):
            assert r["argues_for"] == ["twinning"], r["formula"]

    def test_failure_condition_c_fires_and_states_the_direction(self):
        xs = _acentric_p1()
        laue = _laue(xs)
        twin = _twin_50_50(_fo_sq(xs))
        m = S.intensity_moments(twin, laue)
        v = S.e2m1_hint_validity(
            readings=[m[k] for k in ("mean_abs_e2_minus_1", "i2_over_i_sq",
                                     "f_sq_over_f2")],
            n_reflections=int(twin.size()), d_min=0.8,
            weak_class=S.weak_index_class(twin), hint="non_centrosymmetric")
        assert v["hint_valid"] is False
        assert "twinning_by_merohedry" in v["conditions_triggered"]
        cond = next(c for c in v["conditions"]
                    if c["id"] == "twinning_by_merohedry")
        # the direction has to be the RIGHT way round: twinning makes a
        # centrosymmetric structure read acentric, never the reverse
        assert "acentric" in cond["bias"] and "0.968 -> 0.736" in cond["bias"]

    def test_a_twinned_centric_structure_hides_inside_the_bracket(self):
        """The XPREP warning, made checkable: mixing the P-1 (all-centric)
        intensities 50:50 lands every moment ON the untwinned ACENTRIC
        references - a perfectly twinned centrosymmetric crystal is
        statistically indistinguishable from an untwinned acentric one.
        No statistic may claim anything here, and the hint (which now
        reads 'non_centrosymmetric') must be barred from dropping the
        centre it just lost."""
        xs = _wilson_p1bar()
        laue = _laue(xs)
        base = _fo_sq(xs)
        twin = _twin_50_50(base)
        m_base = S.intensity_moments(base, laue)
        m_twin = S.intensity_moments(twin, laue)
        assert abs(m_base["i2_over_i_sq"]["value"] - 3.0) < 0.35
        # lands ON the untwinned ACENTRIC reference, either side of it
        assert abs(m_twin["i2_over_i_sq"]["value"] - 2.0) < 0.15
        assert abs(m_twin["mean_abs_e2_minus_1"]["value"] - 0.736) < 0.06
        # so nothing may be called: whichever side of 2.000 the sample
        # falls, the deviation is inside the band this dataset resolves
        assert m_twin["i2_over_i_sq"]["strength"] != "clear"
        assert m_twin["mean_abs_e2_minus_1"]["strength"] != "clear"
        # the hint now reads acentric on a centrosymmetric crystal - the
        # r16 trap - and is barred from being used that way
        assert m_twin["mean_abs_e2_minus_1"]["value"] < 0.852   # 'acentric'
        u = S.hint_usability("non_centrosymmetric")
        assert "DROPPING an inversion centre" in u["not_usable_for"]
        assert "Marsh" in u["not_usable_for"]

    def test_on_the_real_dimer_the_twin_hides_and_nothing_is_invented(self):
        """The limit of these statistics, measured rather than assumed.
        On the rigid flat dimer every statistic starts far above its
        reference, so a 50:50 twin moves them all in the right DIRECTION
        without any of them crossing: the honest output is silence. The
        tool must not manufacture a reading from the movement - it cannot
        see the baseline - and the twin has to be found elsewhere (the
        metric-vs-Laue precondition in audit_reflection_data, a solution
        trial, or check_symmetry's heavy-anchor search)."""
        xs = _benzoic_dimer()
        laue = _laue(xs)
        base, twin = _fo_sq(xs), _twin_50_50(_fo_sq(xs))
        m_base, m_twin = (S.intensity_moments(base, laue),
                          S.intensity_moments(twin, laue))
        l_base = S.l_test(base, laue)["mean_abs_l"]
        l_twin = S.l_test(twin, laue)["mean_abs_l"]
        # everything moves toward the twin side ...
        assert m_twin["i2_over_i_sq"]["value"] < \
            m_base["i2_over_i_sq"]["value"]
        assert m_twin["mean_abs_e2_minus_1"]["value"] < \
            m_base["mean_abs_e2_minus_1"]["value"]
        assert l_twin["value"] < l_base["value"]
        # ... and nothing crosses, so nothing is claimed
        for r in (m_base["i2_over_i_sq"], m_twin["i2_over_i_sq"],
                  m_twin["mean_abs_e2_minus_1"], l_base, l_twin):
            assert "twinning" not in (r["argues_for"] or []), r["formula"]


# ------------------------------------------------------- pseudo-translation


class TestPseudoTranslation:
    def test_doubled_cell_reads_above_the_centric_value(self):
        xs = _doubled_cell()
        laue = _laue(xs)
        arr = _fo_sq(xs, d_min=0.9)
        weak = S.weak_index_class(arr)
        assert weak is not None and weak["class"] == "l odd"
        assert weak["mean_i_ratio"] < 0.35
        corrob = [f"index class '{weak['class']}' carries "
                  f"{weak['mean_i_ratio']:.2f} of the average intensity"]
        m = S.intensity_moments(arr, laue, corroboration=corrob)
        r = m["i2_over_i_sq"]
        assert r["value"] > 2.0 and r["value"] > 3.0
        assert r["direction"] == "beyond_centric"
        assert r["argues_for"] == ["pseudo_translation"]
        v = r["verdict"].lower()
        assert "pseudo-translation" in v
        assert "twin" not in v
        _assert_no_pass_wording(v)
        assert "intensity averaging" in r["not_argued_for"]

    def test_the_l_test_is_not_fooled_by_the_pseudo_translation(self):
        """delta = 2 keeps both members of a pair in the same parity
        class, so the weak/strong split cancels: the L-test must NOT read
        on the twin side here (Padilla & Yeates' robustness claim, made
        checkable)."""
        arr = _fo_sq(_doubled_cell(), d_min=0.9)
        lt = S.l_test(arr, _laue(_doubled_cell()))
        assert "twinning" not in (lt["mean_abs_l"]["argues_for"] or [])

    def test_an_uncorroborated_excess_claims_nothing(self):
        """The real dimer sits above the centric reference too (so do both
        published reference datasets). Without an independent signature
        the tool must refuse to call it a pseudo-translation."""
        xs = _benzoic_dimer()
        arr = _fo_sq(xs)
        assert S.weak_index_class(arr) is None
        r = S.intensity_moments(arr, _laue(xs))["i2_over_i_sq"]
        assert r["value"] > 3.0
        assert r["direction"] == "beyond_centric"
        assert r["strength"] == "uncorroborated"
        assert r["argues_for"] == []
        _assert_no_pass_wording(r["verdict"])
        assert "index class" in r["verdict"].lower()


# ------------------------------------------- documented failure conditions


class TestFailureConditions:
    def test_there_are_exactly_five_named_conditions(self):
        ids = [c["id"] for c in S.E2M1_FAILURE_CONDITIONS]
        assert ids == ["dominant_heavy_scatterer",
                       "heavy_atom_on_special_position",
                       "twinning_by_merohedry",
                       "pseudo_translational_symmetry",
                       "too_few_reflections_or_too_low_resolution"]
        for c in S.E2M1_FAILURE_CONDITIONS:
            assert c["test"] and c["bias"] and c["source"]

    def test_zr_on_a_special_position_invalidates_the_hint(self):
        xs = _zr_salt()
        arr = _fo_sq(xs, d_min=0.8)
        laue = _laue(xs)
        shares = S.scattering_power_shares(xs)
        assert shares["dominant_element"] == "Zr"
        assert shares["dominant_share"] > 0.5
        orders = S.site_symmetry_orders(xs)
        assert orders[0] > 1, "Zr must sit on the inversion centre"
        m = S.intensity_moments(arr, laue)
        v = S.e2m1_hint_validity(
            model=xs, n_reflections=int(arr.size()), d_min=0.8,
            readings=[m[k] for k in ("mean_abs_e2_minus_1", "i2_over_i_sq",
                                     "f_sq_over_f2")],
            weak_class=S.weak_index_class(arr))
        assert v["hint_valid"] is False
        assert "heavy_atom_on_special_position" in v["conditions_triggered"]
        assert "dominant_heavy_scatterer" in v["conditions_triggered"]
        cond = next(c for c in v["conditions"]
                    if c["id"] == "heavy_atom_on_special_position")
        assert "ZR1" in cond["evidence"]
        assert "special position" in cond["evidence"]
        assert "unreliable" in v["note"].lower()

    def test_a_light_atom_structure_does_not_trip_the_heavy_conditions(self):
        """The composition rule is generic, not a metal blacklist: the
        same code must stay quiet on an all-C/O/H structure."""
        xs = _wilson_p1bar()
        v = S.e2m1_hint_validity(model=xs, n_reflections=4000, d_min=0.8)
        assert "dominant_heavy_scatterer" not in v["conditions_triggered"]
        assert ("heavy_atom_on_special_position"
                not in v["conditions_triggered"])

    def test_truncated_data_trip_the_resolution_condition(self):
        xs = _wilson_p1bar()
        arr = _fo_sq(xs).resolution_filter(d_min=1.5)
        v = S.e2m1_hint_validity(n_reflections=int(arr.size()),
                                 d_min=float(arr.d_max_min()[1]))
        assert v["hint_valid"] is False
        assert ("too_few_reflections_or_too_low_resolution"
                in v["conditions_triggered"])
        cond = next(c for c in v["conditions"]
                    if c["id"] == "too_few_reflections_or_too_low_resolution")
        assert "0.84" in cond["evidence"] or "1.0 A" in cond["evidence"]

    def test_a_clean_evaluation_is_not_sold_as_a_certificate(self):
        xs = _wilson_p1bar()
        arr = _fo_sq(xs)
        m = S.intensity_moments(arr, _laue(xs))
        v = S.e2m1_hint_validity(
            model=xs, n_reflections=int(arr.size()), d_min=0.8,
            readings=[m[k] for k in ("mean_abs_e2_minus_1", "i2_over_i_sq",
                                     "f_sq_over_f2")],
            weak_class=S.weak_index_class(arr))
        assert v["hint_valid"] is True
        _assert_no_pass_wording(v["note"])
        assert "not a certificate" in v["note"]
        assert len(v["conditions"]) == 5

    def test_conditions_that_cannot_be_evaluated_are_named(self):
        v = S.e2m1_hint_validity(n_reflections=4000, d_min=0.8)
        assert set(v["conditions_not_evaluable"]) >= {
            "dominant_heavy_scatterer", "heavy_atom_on_special_position"}


# ------------------------------------------------------------------ the tools


def _session(arr, xs=None, sym=None):
    from types import SimpleNamespace
    return SimpleNamespace(
        dataset=SimpleNamespace(intensities=arr),
        symmetry=(sym or (xs.crystal_symmetry() if xs is not None else None)),
        model=xs, flags={}, fo_sq=None)


class TestReflectionStatisticsTool:
    def test_one_call_returns_shells_moments_and_the_l_test(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_analysis import ReflectionStatistics
        xs = _wilson_p1bar()
        r = ReflectionStatistics(None).run(
            SimpleNamespace(session=_session(_fo_sq(xs), xs)), n_shells=8)
        assert r.ok, r.error
        s = r.summary
        assert s["e_statistics"]["by_shell"]["shells"]
        assert s["intensity_moments"]["i2_over_i_sq"]["formula"] == \
            "<I^2>/<I>^2"
        assert s["intensity_moments"]["f_sq_over_f2"]["formula"] == \
            "<F>^2/<F^2>"
        assert s["l_test"]["mean_abs_l"]["value"] > 0
        assert s["e_statistics"]["hint_valid"] in (True, False)
        assert len(s["e_statistics"]["hint_validity"]["conditions"]) == 5
        for block, key in (("intensity_moments", "i2_over_i_sq"),
                           ("intensity_moments", "f_sq_over_f2"),
                           ("l_test", "mean_abs_l"), ("l_test", "mean_l_sq")):
            _assert_no_pass_wording(s[block][key]["verdict"])

    def test_the_model_composition_reaches_the_failure_conditions(self):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_analysis import ReflectionStatistics
        xs = _zr_salt()
        r = ReflectionStatistics(None).run(
            SimpleNamespace(session=_session(_fo_sq(xs), xs)), n_shells=8)
        assert r.ok, r.error
        v = r.summary["e_statistics"]["hint_validity"]
        assert r.summary["e_statistics"]["hint_valid"] is False
        assert "heavy_atom_on_special_position" in v["conditions_triggered"]
        # the hint itself is still reported, only labelled
        assert "hint" in r.summary["e_statistics"]


class TestScreenConflicts:
    @staticmethod
    def _run(evidence=None):
        xs = _wilson_p1bar()
        arr = _fo_sq(xs)
        return S.screen_space_groups(arr, _laue(xs), max_out=20,
                                     evidence=evidence)

    def test_every_candidate_carries_a_conflicts_list(self):
        res = self._run()
        assert res["candidates"]
        assert all(isinstance(c["conflicts"], list)
                   for c in res["candidates"])
        assert res["conflicts_summary"]["channels"]

    def test_conflicts_do_not_change_the_ranking(self):
        plain = [c["space_group"] for c in self._run()["candidates"]]
        ev = {"solver": {"engine": "SHELXT",
                         "best": {"space_group": "P 1", "number": 1,
                                  "is_centric": False}},
              "laue_r_int": 0.42, "working_space_group": "P 1",
              "working_laue_order": 2}
        loud = [c["space_group"] for c in self._run(ev)["candidates"]]
        assert plain == loud

    def test_a_solver_verdict_against_the_e_hint_is_reported(self):
        ev = {"solver": {"engine": "SHELXT",
                         "best": {"space_group": "P 1", "number": 1,
                                  "is_centric": False}}}
        res = self._run(ev)
        rows = {c["space_group"]: c for c in res["candidates"]}
        p_bar = next(k for k in rows if k.replace(" ", "") == "P-1")
        ids = [x["id"] for x in rows[p_bar]["conflicts"]]
        assert "solver_centricity_vs_candidate" in ids

    def test_a_bad_laue_r_int_is_reported_against_every_candidate(self):
        res = self._run({"laue_r_int": 0.42})
        ids = [x["id"] for c in res["candidates"] for x in c["conflicts"]]
        assert "laue_r_int_above_reference" in ids

    def test_the_hint_validity_rides_with_the_e_statistics(self):
        res = self._run()
        e = res["e_statistics"]
        assert e["hint"] in ("centrosymmetric", "non_centrosymmetric")
        assert e["hint_valid"] in (True, False)
        assert len(e["hint_validity"]["conditions"]) == 5
        assert "i2_over_i_sq" in e["moments"]


class TestCheckSymmetryRisk:
    @staticmethod
    def _ctx(xs, arr=None):
        from types import SimpleNamespace
        from types import SimpleNamespace as NS
        return SimpleNamespace(session=NS(
            model=xs, flags={},
            dataset=(NS(intensities=arr) if arr is not None else None)))

    def test_a_missed_centre_is_high_risk_and_named(self):
        from crystalpilot.refine.tools_symmetry import CheckSymmetry
        xs = _wilson_p1bar()
        arr = _fo_sq(xs)
        r = CheckSymmetry(None).run(self._ctx(xs.expand_to_p1(), arr))
        assert r.ok, r.error
        s = r.summary
        assert s["kind"] == "missed_centre"
        assert s["risk"] == "high"
        assert "bond lengths" in s["risk_reason"]
        assert s["reliability"]["level"] == "atomic_resolution"
        assert "0.84" in s["reliability"]["note"]

    def test_the_reliability_note_follows_the_data_resolution(self):
        from crystalpilot.refine.tools_symmetry import CheckSymmetry
        xs = _wilson_p1bar()
        coarse = _fo_sq(xs).resolution_filter(d_min=1.4)
        r = CheckSymmetry(None).run(self._ctx(xs.expand_to_p1(), coarse))
        assert r.summary["reliability"]["level"] == "coarse"
        assert "null result says almost nothing" in \
            r.summary["reliability"]["note"]
        # the finding is unchanged - only how far it may be trusted
        assert r.summary["kind"] == "missed_centre"

    def test_without_data_the_reliability_is_unknown_not_assumed(self):
        from crystalpilot.refine.tools_symmetry import CheckSymmetry
        xs = _wilson_p1bar()
        s = CheckSymmetry(None).run(self._ctx(xs.expand_to_p1())).summary
        assert s["reliability"]["level"] == "unknown"
        assert s["reliability"]["d_min"] is None

    def test_a_quiet_answer_is_still_one_sided(self):
        from crystalpilot.refine.tools_symmetry import CheckSymmetry
        xs = _wilson_p1bar()
        s = CheckSymmetry(None).run(self._ctx(xs, _fo_sq(xs))).summary
        assert s["kind"] == "none_found"
        assert s["risk"] in ("low", "medium")
        _assert_no_pass_wording(s["one_sided"])
        assert "never a certificate" in s["one_sided"]


# ---------------------------------------------------------------- real data


EXT2 = REPO / "benchmark" / "data_ext2"
PROBES = [
    ("twintrap_nm_cod2229074",
     (6.9802, 9.3570, 12.5779, 102.833, 94.296, 107.567), "P -1"),
    ("twin_rz5267_iucr",
     (15.954, 5.4599, 28.397, 90, 92.299, 90), "C 2/c"),
]


@pytest.mark.parametrize("slug,cell,sg", PROBES)
def test_published_twin_datasets_read_as_detwinned(slug, cell, sg):
    """Both files are LIST-4 fcf-derived, i.e. the observed intensities a
    twin-aware refinement produced. The twin signature has therefore
    ALREADY been removed from them, and the statistics must not invent
    one: no statistic may read on the twin side. What they do show is the
    ordinary molecular-crystal excess above the centric reference - which
    the tool must refuse to call a pseudo-translation, there being no weak
    index class to corroborate it."""
    hkl = EXT2 / slug / "ref.hkl"
    if not hkl.exists():
        pytest.skip(f"reference data not present: {hkl}")
    arr = S.read_shelx_hkl_intensities(hkl, cell)
    laue = sgtbx.space_group_info(sg).group().build_derived_laue_group()
    m = S.intensity_moments(arr, laue)
    lt = S.l_test(arr, laue)
    readings = [m[k] for k in ("mean_abs_e2_minus_1", "i2_over_i_sq",
                               "f_sq_over_f2")]
    readings += [lt[k] for k in ("mean_abs_l", "mean_l_sq")]
    assert all("twinning" not in (r["argues_for"] or []) for r in readings)
    assert S.weak_index_class(arr) is None
    assert m["i2_over_i_sq"]["value"] > 3.0
    assert m["i2_over_i_sq"]["argues_for"] == []
    assert lt["n_pairs"] > 1000
    for r in readings:
        _assert_no_pass_wording(r["verdict"])
