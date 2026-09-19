"""Masked-delivery reporting obligations (write_outputs automation of the
expert SQUEEZE discipline)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.refine.tools_extra import _mask_obligations

CIF_WITH_SQUEEZE = "data_x\n_platon_squeeze_details\n;\n ok\n;\n"
CIF_PLAIN = "data_x\n_cell_length_a 10.0\n"


def test_unmasked_delivery_owes_nothing():
    assert _mask_obligations(None, None, CIF_PLAIN) == []


def test_masked_without_moiety_owes_three():
    duties = _mask_obligations({"info": {"n_voids": 1}}, None, CIF_PLAIN)
    assert len(duties) == 3
    assert any("formula_moiety" in d for d in duties)
    assert any("mof-guest-evidence-rule" in d for d in duties)
    assert any("_platon_squeeze" in d for d in duties)


def test_masked_with_moiety_and_squeeze_block_owes_narrative_only():
    duties = _mask_obligations({"info": {}}, "C6 H6, 2(H2O)",
                               CIF_WITH_SQUEEZE)
    assert len(duties) == 1
    assert "VALIDATION.md" in duties[0]


def test_missing_cif_text_skips_squeeze_check():
    duties = _mask_obligations({"info": {}}, "C6 H6", None)
    assert not any("_platon_squeeze" in d for d in duties)


def test_disorder_obligation_fires_on_part_groups():
    from crystalpilot.refine.tools_extra import _disorder_obligations
    duties = _disorder_obligations({"disorder_groups": [{"g": 1}, {"g": 2}]})
    assert len(duties) == 1 and "2 组" in duties[0]
    assert "refine-special-details-templates" in duties[0]
    # loose parts without formal groups still owe one description
    assert len(_disorder_obligations({"parts_extra": {"F1A": 1}})) == 1
    assert _disorder_obligations({}) == []
