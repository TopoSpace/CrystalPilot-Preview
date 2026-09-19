from crystalpilot.refine.tools_shelxl import refinement_counts, summarize_shelxl_job


RES = """REM R1 = 0.0381 for 1703 Fo > 4sig(Fo) and 0.0391 for all 1755 data
REM wR2 = 0.1300, GooF = S = 1.204
"""
CIF = """data_job
_refine_ls_number_parameters 119
_refine_ls_number_reflns 1755
_refine_ls_number_restraints 0
"""


def test_engine_counts_keep_strong_and_total_reflections_distinct(tmp_path):
    (tmp_path / "job.cif").write_text(CIF, encoding="utf-8")
    result, _, error = summarize_shelxl_job(tmp_path, RES, 8)
    assert error is None
    assert result["n_strong"] == 1703
    assert result["n_reflections"] == 1755
    assert result["n_params"] == 119
    assert result["n_restraints"] == 0


def test_missing_or_invalid_counts_do_not_become_zero_or_strong_count():
    assert refinement_counts("", RES) == {"n_reflections": 1755}
    assert refinement_counts("data_job\n_refine_ls_number_parameters ?\n_refine_ls_number_reflns -1\n") == {}
    assert refinement_counts("data_job\n_refine_ls_number_parameters 1.5\n") == {}
    assert refinement_counts("not a CIF", "R1 = 0.1 for 90 strong data") == {}


def test_quoted_cif_counts_are_valid_and_authoritative():
    assert refinement_counts("data_job\n_refine_ls_number_parameters '119'\n_refine_ls_number_reflns 1755\n", RES) == {
        "n_params": 119, "n_reflections": 1755,
    }
