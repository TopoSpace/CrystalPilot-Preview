import pytest

from crystalpilot.workbench.agents_md import marker_for, render_agents_md


@pytest.mark.parametrize("mode", ["full", "tools_only"])
@pytest.mark.parametrize("delegate,aggressive",
                         [(False, False), (True, False), (True, True)])
def test_project_instructions_use_scientific_versions_and_structure_only_boundaries(mode, delegate, aggressive):
    text = render_agents_md(mode, delegate, aggressive)
    assert text.startswith(marker_for(mode, delegate, aggressive))
    assert "不做文件哈希/摘要审计" in text
    assert "structure_only" in text
    assert "不编造 R 值" in text
    # round-3 R7: the aggressive variant (max/ultra only) carries ~600
    # chars of checkpoint text on top of the hint variant's budget
    # 2026-09-06: two-step spawn text. 2026-09-08 (v43): 9200 -> 9500 for
    # the delivery-flow rewrite (adopt-then-write_outputs, the seven
    # hand-over files, diagnostic seals) the two usertest sessions demanded.
    # 2026-09-09 (v44): 9500 -> 9600 for the parameter-editing tools' two
    # one-line entries (set_adp / set_site_occupancy / set_afix); raw length
    # includes the interpolated engine path, so the bar is checkout-dependent
    assert len(text) < (9800 if aggressive else 9600)
    if mode == "full":
        assert "开放事实直接问具体值" in text
        assert "options 可为空" in text
        assert "不把“没提供”当成“不存在”" in text
