"""SHELXL .lst readback (PLAN T1.1): warnings on the success path, the
analysis of variance, the most disagreeable reflections, restraint
residuals over 3 sigma and the convergence reading.

Every fragment below is hand-written in SHELXL-2019/3's exact layout (the
formats were read off four real job.lst files: an I-centred MOF, an
L-cysteine molecular structure, a merged-data framework and a Zr cage), so
no SHELXL run is needed. Synthetic inputs cover a healthy job, a weak-end
K anomaly, both directions of the Fo^2-Fc^2 imbalance, an index pattern,
a lattice-implied non-pattern, a missing block and a negative K.

Generalisation: nothing here is keyed to an element, a system type or a
particular crystal - the K rule is relative to each table's own median and
MAD, the imbalance rule is one binomial sigma of the row count, and the
index test is lattice arithmetic with the centring conditions excluded.
"""
import re

import pytest

from crystalpilot.refine.shelxl_lst import (
    SU_UNDERESTIMATED, parse_disagreeable_reflections, parse_latt,
    parse_shelxl_warnings, parse_variance_table, shift_esd_reading)
from crystalpilot.refine.tools_shelxl import (
    parse_disagreeable_restraints, summarize_shelxl_job)

#: words that would turn a one-directional criterion into a permit (P12)
_PASS_WORDS = re.compile(
    r"\b(pass|passed|passes|passing|fine|ok|okay|good|acceptable|"
    r"correct|valid|healthy)\b|通过|合格", re.I)


def _no_pass_language(*texts: str) -> None:
    for t in texts:
        m = _PASS_WORDS.search(t)
        assert m is None, f"pass-style wording {m.group(0)!r} in: {t}"


# --------------------------------------------------------------------- #
# fragments                                                              #
# --------------------------------------------------------------------- #

_VARIANCE_HEAD = (
    " Analysis of variance for reflections employed in refinement"
    "      K = Mean[Fo^2] / Mean[Fc^2]  for group\n\n")


def _fc_table(ks: list[float]) -> str:
    """The Fc/Fc(max) half of the analysis of variance, 10 groups."""
    return (
        " Fc/Fc(max)       0.000    0.026    0.040    0.051    0.062"
        "    0.075    0.088    0.108    0.136    0.196    1.000\n\n"
        " Number in group       274.     259.     251.     264.     264."
        "     243.     261.     263.     249.     261.\n\n"
        "            GooF      0.896    1.063    1.093    0.998    1.054"
        "    0.884    0.917    1.034    0.885    0.957\n\n"
        "             K       " + "".join(f"{k:9.3f}" for k in ks) + "\n\n")


def _res_table(ks: list[float], r1s: list[float]) -> str:
    """The Resolution(A) half: bounds run high-resolution -> inf."""
    return (
        " Resolution(A)    0.58     0.62     0.65     0.67     0.71"
        "     0.75     0.81     0.89     1.02     1.29     inf\n\n"
        " Number in group       265.     259.     259.     252.     261."
        "     256.     260.     260.     260.     257.\n\n"
        "            GooF      1.090    0.915    0.896    0.979    0.843"
        "    0.939    0.816    0.832    1.003    1.374\n\n"
        "             K       " + "".join(f"{k:9.3f}" for k in ks) + "\n\n"
        "             R1      " + "".join(f"{r:9.3f}" for r in r1s) + "\n\n")


_K_FLAT = [1.010, 1.048, 1.017, 1.019, 1.019, 1.023, 1.012, 0.990,
           0.985, 1.032]
_K_FLAT_FC = [0.995, 1.001, 1.031, 1.013, 1.001, 1.029, 1.024, 1.016,
              0.993, 1.021]
_R1_EXPECTED = [0.103, 0.077, 0.072, 0.065, 0.051, 0.045, 0.035, 0.033,
                0.032, 0.037]

_DISAGREE_HEAD = (
    " Most Disagreeable Reflections (* if suppressed or used for Rfree).\n"
    " Error/esd is calculated as sqrt(wD^2/<wD^2>) where w is given by "
    "the weight\n formula, D = Fo^2-Fc^2 and <> refers to the average "
    "over all reflections.\n\n"
    "     h   k   l          Fo^2          Fc^2    Error/esd  "
    "Fc/Fc(max)  Resolution(A)\n\n")


def _disagree(rows: list[tuple[int, int, int, float, float]]) -> str:
    body = "".join(
        f"{h:6d}{k:4d}{l:4d}{fo:14.2f}{fc:14.2f}"
        f"{4.0:11.2f}{0.10:12.3f}{1.50:11.2f}\n"
        for h, k, l, fo, fc in rows)
    return _DISAGREE_HEAD + body + "\n\n Bond lengths and angles\n"


#: 4 rows with Fo^2 > Fc^2 and 4 with Fo^2 < Fc^2: no directional
#: imbalance, and no index relation survives the chance bar at n = 8
_BALANCED_ROWS = [
    (0, 2, 2, 206.60, 110.72),
    (1, 3, 5, 3.29, 31.43),
    (-2, 3, 12, 0.99, 10.47),
    (5, 9, 4, 27.25, 14.53),
    (0, 1, 1, 223.47, 309.19),
    (3, 4, 7, 98.35, 42.81),
    (1, 1, 0, 698.68, 925.28),
    (2, 0, 7, 74.61, 36.26),
]

LST_HEALTHY = (
    " TITL synthetic\n LATT 1\n\n"
    " Mean shift/esd =   0.002  Maximum =     0.029 for  U22 C9X\n\n"
    + _VARIANCE_HEAD + _fc_table(_K_FLAT_FC)
    + _res_table(_K_FLAT, _R1_EXPECTED)
    + " Recommended weighting scheme:  WGHT    0.0610    0.0464\n\n"
    + _disagree(_BALANCED_ROWS))

#: same job, but the weakest Fc group has K = 0.6
LST_WEAK_K_LOW = (
    " TITL synthetic\n LATT 1\n\n" + _VARIANCE_HEAD
    + _fc_table([0.600] + _K_FLAT_FC[1:])
    + _res_table(_K_FLAT, _R1_EXPECTED))

#: ... and the mirror case, K = 2.4 in the weakest group (§2.7 direction)
LST_WEAK_K_HIGH = (
    " TITL synthetic\n LATT 1\n\n" + _VARIANCE_HEAD
    + _fc_table([2.400] + _K_FLAT_FC[1:])
    + _res_table(_K_FLAT, _R1_EXPECTED))

RES_MINIMAL = """TITL job
CELL 0.71073 10.0 11.0 12.0 90 90 90
ZERR 4 0.001 0.001 0.001 0 0 0
LATT 1
WGHT 0.100000 0.000000
FVAR 1.00000
C1    1  0.1000  0.1000  0.1000  11.00000  0.05000
HKLF 4
END
REM  wR2 = 0.1199, GooF = S = 0.981, Restrained GooF = 0.984 for all data
REM  R1 = 0.0424 for 2369 Fo > 4sig(Fo) and 0.0468 for all 2589 data
REM Highest difference peak  0.35, deepest hole  -0.28
"""


# --------------------------------------------------------------------- #
# 1. warnings on the success path                                        #
# --------------------------------------------------------------------- #

class TestWarnings:
    """Before r33 the `**` lines were read ONLY when the R1/wR2/GooF
    regexes failed, so a job that finished normally threw them away. Four
    real banners found on disk that no tool had ever surfaced: 'atoms may
    be split', 'DISP instructions may be required for this wavelength',
    'Input data appear to be merged: CIF file will be incomplete' and
    'Absolute structure cannot be determined reliably'."""

    LST = (LST_HEALTHY
           + "\n ** Warning:     1  atoms may be split and     0  atoms "
             "NPD **\n"
             " ** WARNING: Input data appear to be merged: CIF file will "
             "be incomplete **\n"
             " ** Warning:     1  atoms may be split and     0  atoms "
             "NPD **\n")

    def test_success_path_surfaces_warnings_in_the_summary(self, tmp_path):
        job = tmp_path / "job_1"
        job.mkdir()
        (job / "job.lst").write_text(self.LST, encoding="utf-8")
        shelxl, _q, err = summarize_shelxl_job(job, RES_MINIMAL, l_s=4)
        assert err is None
        # the job parsed cleanly - R1/wR2/GooF are all there ...
        assert shelxl["r1_strong"] == 0.0424 and shelxl["goof"] == 0.981
        # ... and the banners came through anyway
        assert shelxl["n_warnings"] == 2            # de-duplicated
        assert any("may be split" in w for w in shelxl["warnings"])
        assert any("appear to be merged" in w for w in shelxl["warnings"])

    def test_no_banner_means_an_empty_list_not_a_key(self):
        assert parse_shelxl_warnings(LST_HEALTHY) == []

    def test_wrapped_banner_keeps_both_halves(self):
        text = (" ** WARNING: These times are only approximate for "
                "multiple threads.\n"
                "             To get better estimates run with -t1 **\n")
        assert len(parse_shelxl_warnings(text)) == 2


# --------------------------------------------------------------------- #
# 2. analysis of variance                                                #
# --------------------------------------------------------------------- #

class TestVarianceTable:
    def test_healthy_table_reports_no_trend_and_no_pass_language(self):
        v = parse_variance_table(LST_HEALTHY)
        assert v is not None
        assert len(v["by_fc"]["k"]) == 10
        assert len(v["by_fc"]["bounds"]) == 11
        assert v["by_resolution"]["r1"] == _R1_EXPECTED
        joined = " ".join(v["reading"])
        assert "no K trend detected" in joined
        _no_pass_language(joined, v["rule"], v["capability_note"])

    def test_low_fc_group_k_06_names_the_weak_direction_without_goof(self):
        v = parse_variance_table(LST_WEAK_K_LOW)
        joined = " ".join(v["reading"])
        assert "WEAKEST reflections" in joined
        assert "BELOW Fc^2" in joined
        # §17.4: the acceptance criterion for a weighting scheme is the
        # absence of a trend in THIS table, not GooF - so the reading must
        # not fall back to talking about GooF
        assert "GooF" not in joined
        _no_pass_language(joined)

    def test_high_k_in_the_weak_group_is_the_twinning_direction(self):
        """Counter-example to the previous test: the same magnitude of
        deviation the other way gets the opposite candidate list."""
        v = parse_variance_table(LST_WEAK_K_HIGH)
        joined = " ".join(v["reading"])
        assert "WEAKEST reflections" in joined and "ABOVE Fc^2" in joined
        assert "twinning" in joined
        assert "extinction" not in joined.split("resolution shell")[0]

    def test_rising_r1_towards_high_resolution_is_not_flagged(self):
        v = parse_variance_table(LST_HEALTHY)
        joined = " ".join(v["reading"])
        assert "is EXPECTED" in joined and "NOT flagged" in joined
        assert "opposite of the expected direction" not in joined

    def test_r1_highest_at_the_low_resolution_end_is_flagged(self):
        inverted = list(reversed(_R1_EXPECTED))
        text = (_VARIANCE_HEAD + _fc_table(_K_FLAT_FC)
                + _res_table(_K_FLAT, inverted))
        joined = " ".join(parse_variance_table(text)["reading"])
        assert "opposite of the expected direction" in joined

    def test_monotonic_k_with_resolution_is_called_out(self):
        rising = [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20,
                  1.25]
        text = (_VARIANCE_HEAD + _fc_table(_K_FLAT_FC)
                + _res_table(rising, _R1_EXPECTED))
        joined = " ".join(parse_variance_table(text)["reading"])
        assert "monotonically" in joined and "scale/decay" in joined

    def test_negative_k_is_reported_without_a_ratio_claim(self):
        """Live ka1-cage job: K = -3.185 in one shell. Ratios to a median
        are meaningless there, and the block must say so rather than
        divide anyway."""
        ks = [20.564, -3.185, -2.072, 0.268, 1.237, 1.107, 1.013, 1.011,
              1.102, 1.192]
        text = (_VARIANCE_HEAD + _fc_table(_K_FLAT_FC)
                + _res_table(ks, _R1_EXPECTED))
        joined = " ".join(parse_variance_table(text)["reading"])
        assert "mean Fo^2 is not positive" in joined
        assert "not meaningful" in joined

    def test_absent_block_returns_none(self):
        assert parse_variance_table("TITL x\nno such table\n") is None
        assert parse_variance_table(_DISAGREE_HEAD) is None

    def test_the_timing_line_is_not_mistaken_for_the_table(self):
        """SHELXL's timing summary contains '0.01: Analysis of variance'
        - the parser anchors on the full header, not the phrase."""
        assert parse_variance_table("      0.01: Analysis of variance\n") \
            is None


# --------------------------------------------------------------------- #
# 3. most disagreeable reflections                                       #
# --------------------------------------------------------------------- #

def _rows_gt(n_gt: int, n_total: int) -> list[tuple]:
    """n_total rows with n_gt of them Fo^2 > Fc^2, indices spread so no
    integer relation survives the chance bar."""
    hkl = [(0, 2, 2), (1, 3, 5), (-2, 3, 12), (5, 9, 4), (0, 1, 1),
           (3, 4, 7), (1, 1, 0), (2, 0, 7), (4, 6, 3), (-1, 5, 9)]
    out = []
    for i in range(n_total):
        h, k, l = hkl[i % len(hkl)]
        out.append((h, k, l, 200.0, 50.0) if i < n_gt
                   else (h, k, l, 50.0, 200.0))
    return out


class TestDisagreeableReflections:
    def test_balanced_split_is_reported_as_no_signal(self):
        d = parse_disagreeable_reflections(_disagree(_BALANCED_ROWS))
        assert d["n_rows"] == 8
        assert d["n_fo_gt_fc"] == 4 and d["n_fo_lt_fc"] == 4
        joined = " ".join(d["reading"])
        assert "no directional imbalance detected" in joined
        assert "index_pattern" not in d
        _no_pass_language(joined, d["rule"])

    def test_majority_fo_above_fc_points_at_a_missing_scatterer(self):
        d = parse_disagreeable_reflections(_disagree(_rows_gt(8, 10)))
        assert d["n_fo_gt_fc"] == 8 and d["n_fo_lt_fc"] == 2
        joined = " ".join(d["reading"])
        assert "missing scatterer" in joined
        assert "stronger than the model" in joined
        assert "twinning" in joined            # §2.7's companion candidate
        assert "extinction" not in joined
        _no_pass_language(joined)

    def test_counter_example_majority_fo_below_fc_flips_the_direction(self):
        d = parse_disagreeable_reflections(_disagree(_rows_gt(2, 10)))
        assert d["n_fo_gt_fc"] == 2 and d["n_fo_lt_fc"] == 8
        joined = " ".join(d["reading"])
        assert "OVER-predicts" in joined
        assert "extinction" in joined
        assert "missing scatterer" not in joined

    def test_parses_the_row_columns_and_stops_at_the_next_block(self):
        d = parse_disagreeable_reflections(_disagree(_BALANCED_ROWS))
        first = d["worst"][0]
        assert first["hkl"] == [0, 2, 2]
        assert first["fo_sq"] == 206.60 and first["fc_sq"] == 110.72
        assert first["error_esd"] == 4.0 and first["d_A"] == 1.50
        assert len(d["worst"]) == 8

    def test_suppressed_marker_is_read(self):
        text = (_DISAGREE_HEAD
                + "     0   2   2 *      206.60        110.72       "
                  "8.61       0.127       3.37\n")
        d = parse_disagreeable_reflections(text)
        assert d["n_suppressed"] == 1

    def test_absent_block_returns_none(self):
        assert parse_disagreeable_reflections("TITL x\n") is None
        assert parse_disagreeable_reflections(_DISAGREE_HEAD) is None


class TestIndexPattern:
    """§2.7: 'For all these reflections: h + l = 5n' - writing the indices
    of the most disagreeable reflections out often gives the twin law
    directly. Encoded as a hint (P12), never as a finding."""

    #: 16 rows, every l odd, l spread over 1..15 so no mod-4 or mod-6
    #: relation rides along, h and k varied
    _ODD_L = [(0, 2, 1), (1, 3, 3), (-2, 3, 5), (5, 9, 7), (0, 1, 9),
              (3, 4, 11), (1, 1, 13), (2, 0, 15), (4, 6, 1), (-1, 5, 3),
              (2, 7, 5), (6, 2, 7), (-3, 1, 9), (1, 8, 11), (5, 3, 13),
              (0, 4, 15)]

    def test_all_l_odd_is_detected_and_phrased_as_a_hint(self):
        rows = [(h, k, l, 200.0, 50.0) for h, k, l in self._ODD_L]
        d = parse_disagreeable_reflections(_disagree(rows))
        pat = d["index_pattern"]
        assert pat["kind"] == "modulus"
        assert pat["expression"] == "l"
        assert pat["modulus"] == 2 and pat["residue"] == 1
        assert pat["chance_probability"] <= 0.01
        assert "HINT" in pat["hint"] and "twin law" in pat["hint"]
        assert "l = 2n+1" in pat["hint"]
        _no_pass_language(pat["hint"])

    def test_a_short_table_does_not_report_a_parity_coincidence(self):
        """Counter-example: the same relation over 8 rows is well within
        chance, so nothing is reported."""
        rows = [(h, k, l, 200.0, 50.0) for h, k, l in self._ODD_L[:8]]
        d = parse_disagreeable_reflections(_disagree(rows))
        assert "index_pattern" not in d

    def test_a_lattice_implied_relation_is_not_reported(self):
        """Counter-example that a live I-centred job produced: with LATT
        2 every measured reflection has h+k+l even, so finding it among
        the worst rows says nothing. The same rows under LATT 1 do carry
        information and are reported."""
        even = [(0, 2, 2), (1, 3, 4), (-2, 3, 1), (5, 9, 2), (0, 1, 1),
                (3, 4, 1), (1, 1, 0), (2, 0, 2), (4, 6, 2), (-1, 5, 2),
                (2, 7, 1), (6, 2, 2), (-3, 1, 2), (1, 8, 1), (5, 3, 2),
                (0, 4, 2)]
        rows = [(h, k, l, 200.0, 50.0) for h, k, l in even]
        assert all((h + k + l) % 2 == 0 for h, k, l in even)
        body = _disagree(rows)
        centred = parse_disagreeable_reflections(" LATT 2\n" + body)
        assert "index_pattern" not in centred
        primitive = parse_disagreeable_reflections(" LATT 1\n" + body)
        assert primitive["index_pattern"]["expression"] == "h+k+l"
        assert primitive["index_pattern"]["lattice_centring"] == "LATT 1"

    def test_latt_is_read_and_missing_latt_is_declared_not_checked(self):
        assert parse_latt(" LATT 2\n") == 2
        assert parse_latt(" LATT -7\n") == 7          # acentric C-centred
        assert parse_latt("TITL x\n") is None
        rows = [(h, k, l, 200.0, 50.0) for h, k, l in self._ODD_L]
        d = parse_disagreeable_reflections(_disagree(rows))
        assert d["index_pattern"]["lattice_centring"].startswith(
            "not checked")

    def test_a_shared_zone_is_reported_as_a_zone(self):
        rows = [(0, k, l, 200.0, 50.0) for k, l in
                ((2, 3), (4, 1), (6, 5), (3, 7), (5, 2), (7, 9),
                 (1, 4), (8, 6))]
        d = parse_disagreeable_reflections(_disagree(rows))
        pat = d["index_pattern"]
        assert pat["kind"] == "zone"
        assert pat["expression"] == "h" and pat["value"] == 0
        assert "zone" in pat["hint"] and "HINT" in pat["hint"]


# --------------------------------------------------------------------- #
# 4. restraint residuals                                                 #
# --------------------------------------------------------------------- #

def _restraint_lst(lines: str) -> str:
    return (" Disagreeable restraints before cycle    6\n\n"
            "   Observed   Target    Error     Sigma     Restraint\n\n"
            + lines + "\n\n Summary of restraints applied in cycle    6\n")


class TestRestraintResiduals:
    """§15.2: 'Residuals larger than about three times the requested
    standard uncertainty should always be investigated.'"""

    def test_four_sigma_flagged_one_sigma_not(self):
        d = parse_disagreeable_restraints(_restraint_lst(
            "      1.6200      1.5400    0.0800    0.0200    DFIX C1 C2\n"
            "      1.5500      1.5400    0.0100    0.0100    DFIX C3 C4\n"))
        assert d["n"] == 2
        assert d["n_over_3_sigma"] == 1
        flags = {e["line"].split("DFIX")[1].strip(): e["over_3_sigma"]
                 for e in d["entries"]}
        assert flags == {"C1 C2": True, "C3 C4": False}
        assert "exceed" in d["reading"] and "4.0x" in d["reading"]
        assert SU_UNDERESTIMATED in d["reading"]

    def test_all_within_three_sigma_is_not_a_pass_claim(self):
        d = parse_disagreeable_restraints(_restraint_lst(
            "      1.5500      1.5400    0.0100    0.0100    DFIX C3 C4\n"
            "                       -0.0150    0.0100    SIMU U33 C1 C2\n"))
        assert d["n_over_3_sigma"] == 0
        assert "no restraint residual exceeds 3x" in d["reading"]
        # the sentence must not turn into a permit (P12)
        assert "not a statement that the restraints are appropriate" \
            in d["reading"]
        _no_pass_language(d["reading"].replace(
            "not a statement that the restraints are appropriate", ""))

    def test_sigma_free_lines_are_still_ratioed(self):
        """SIMU/DELU lines print Error/Sigma only - no Observed/Target."""
        d = parse_disagreeable_restraints(_restraint_lst(
            "                       -0.0317    0.0100    SIMU U33 C1 H6X\n"))
        assert d["n"] == 1 and d["n_over_3_sigma"] == 1
        assert d["entries"][0]["ratio"] == pytest.approx(3.17, abs=0.01)

    def test_absent_section_still_returns_none(self):
        assert parse_disagreeable_restraints("clean lst") is None


# --------------------------------------------------------------------- #
# 5. shift / esd                                                         #
# --------------------------------------------------------------------- #

class TestShiftEsdReading:
    """§17.5, IUCr editorial criterion: 'Poor convergence - maximum
    shift/s.u. > 1.5. ACTION: Author immediately asked to identify the
    problem (Flack parameter? extinction parameter? H atoms? disorder?)'"""

    def test_two_point_zero_lists_four_candidate_directions(self):
        r = shift_esd_reading(2.0)
        assert r is not None
        for n in ("(1)", "(2)", "(3)", "(4)"):
            assert n in r
        assert "not a conclusion" in r or "none of them a conclusion" in r
        assert SU_UNDERESTIMATED in r
        _no_pass_language(r)

    def test_below_the_bar_says_nothing(self):
        assert shift_esd_reading(0.029) is None
        assert shift_esd_reading(1.5) is None

    def test_a_large_negative_shift_counts_too(self):
        assert shift_esd_reading(-2.0) is not None

    def test_wired_into_the_summary(self, tmp_path):
        job = tmp_path / "job_2"
        job.mkdir()
        # parse_shift_esd takes the LAST cycle line, so the poorly
        # converged cycle goes after the rest of the job
        (job / "job.lst").write_text(
            LST_HEALTHY
            + " Mean shift/esd =   0.310  Maximum =     2.000 for  U33 "
              "C13\n", encoding="utf-8")
        shelxl, _q, err = summarize_shelxl_job(job, RES_MINIMAL, l_s=4)
        assert err is None
        assert shelxl["shift_esd"]["final_max"] == 2.0
        assert "(4)" in shelxl["shift_esd"]["reading"]


# --------------------------------------------------------------------- #
# 6. the summary as a whole                                              #
# --------------------------------------------------------------------- #

class TestSummaryWiring:
    def _summary(self, tmp_path, lst_text, name="job_x"):
        job = tmp_path / name
        job.mkdir()
        (job / "job.lst").write_text(lst_text, encoding="utf-8")
        shelxl, q, err = summarize_shelxl_job(job, RES_MINIMAL, l_s=4)
        assert err is None, err
        return shelxl

    def test_all_blocks_present_and_old_fields_kept(self, tmp_path):
        s = self._summary(tmp_path, LST_HEALTHY)
        # nothing that used to be there was dropped
        for key in ("r1_strong", "n_strong", "r1_all", "wr2", "goof",
                    "wght_used", "diff_map_max", "diff_map_min",
                    "n_q_peaks", "shift_esd"):
            assert key in s, key
        assert "variance_analysis" in s
        assert "disagreeable_reflections" in s
        assert s["variance_analysis"]["by_resolution"]["r1"] == _R1_EXPECTED

    def test_summary_still_builds_when_the_lst_blocks_are_absent(
            self, tmp_path):
        """A .lst with none of the new blocks (an L.S. 0 job that aborted
        printing early, or a vendor build that omits them) must not add a
        fabricated default - the keys are simply absent."""
        s = self._summary(tmp_path, " TITL nothing to see here\n")
        assert s["r1_strong"] == 0.0424 and s["goof"] == 0.981
        for key in ("variance_analysis", "disagreeable_reflections",
                    "warnings", "n_warnings", "shift_esd"):
            assert key not in s

    def test_summary_builds_with_no_lst_file_at_all(self, tmp_path):
        job = tmp_path / "job_no_lst"
        job.mkdir()
        shelxl, _q, err = summarize_shelxl_job(job, RES_MINIMAL, l_s=4)
        assert err is None
        assert "variance_analysis" not in shelxl

    def test_no_pass_language_anywhere_in_a_healthy_summary(self,
                                                            tmp_path):
        s = self._summary(tmp_path, LST_HEALTHY)
        texts = list(s["variance_analysis"]["reading"])
        texts.append(s["variance_analysis"]["rule"])
        texts.append(s["variance_analysis"]["capability_note"])
        texts += s["disagreeable_reflections"]["reading"]
        texts.append(s["disagreeable_reflections"]["rule"])
        _no_pass_language(*texts)
