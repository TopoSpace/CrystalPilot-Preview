"""fourier_complete's ADP sweep must survive a suspect without a U value
(the refine engine reports `u_equiv: None` for an atom it reverted after
a runaway cycle) - comparing that None crashed the tool on a live cell
(R7 A1 cage, 2026-09-06 13:14)."""
from crystalpilot.tools.model_tools import adp_sweep

HEAVY = ["Zr"]


def test_none_u_is_named_not_compared():
    suspects = [
        {"atom": "C7", "element": "C", "u_equiv": None,
         "issue": "DIVERGED in this refinement (...) - reverted"},
        {"atom": "C9", "element": "C", "u_equiv": 0.31, "issue": "U very large"},
        {"atom": "ZR2", "element": "Zr", "u_equiv": 0.15, "issue": "U very large for a metal"},
        {"atom": "O3", "element": "O", "u_equiv": 0.05, "issue": "non-positive-definite ADP"},
    ]
    demote, delete, no_u = adp_sweep(suspects, HEAVY, 0.12, 0.25)
    assert no_u == ["C7"]          # named, never compared, never deleted
    assert delete == ["C9"]        # light atom with a huge U
    assert demote == ["ZR2"]       # heavy atom with a blown-up U
    assert "O3" not in delete and "O3" not in demote


def test_empty_and_missing_fields():
    assert adp_sweep([], HEAVY, 0.12, 0.25) == ([], [], [])
    assert adp_sweep(None, HEAVY, 0.12, 0.25) == ([], [], [])
    demote, delete, no_u = adp_sweep([{"element": "C", "u_equiv": None}], HEAVY, 0.12, 0.25)
    assert no_u == ["?"] and not demote and not delete
