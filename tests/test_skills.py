"""Skill layer: dynamic crystallographic expert knowledge (round-10 arch).

Knowledge lives as retrievable markdown units under knowledge/, managed by
list/read/save/delete_skill - never hardcoded into tool logic. Tests run
against a temp knowledge dir (monkeypatched) except the read-only index
tests, which also verify the real shipped cards are indexable.
"""
from types import SimpleNamespace

import pytest

from crystalpilot.refine import tools_skills as ts


def _ctx():
    return SimpleNamespace(session=None)


@pytest.fixture()
def kdir(tmp_path, monkeypatch):
    d = tmp_path / "knowledge"
    (d / "skills").mkdir(parents=True)
    monkeypatch.setattr(ts, "KNOWLEDGE_DIR", d)
    return d


class TestFrontmatter:
    def test_new_schema(self):
        meta, body = ts.parse_frontmatter(
            "---\nname: x\ndescription: d\nalerts: [PLAT097, 041]\n"
            "tools: [refine]\n---\n\nbody text\n")
        assert meta["alerts"] == ["PLAT097", "041"]
        assert meta["tools"] == ["refine"]
        assert body.strip() == "body text"

    def test_legacy_card_schema(self):
        meta, _ = ts.parse_frontmatter(
            "---\nsymptom: 高R且Rint不高\nalerts: []\n"
            "tags: [孪晶]\nsource: https://x\n---\nbody\n")
        assert meta["symptom"] == "高R且Rint不高"
        assert meta["tags"] == ["孪晶"]

    def test_no_frontmatter(self):
        meta, body = ts.parse_frontmatter("just text")
        assert meta == {} and body == "just text"


class TestRealLibraryIndex:
    """The shipped knowledge/ tree must be indexable as-is."""

    def test_shipped_cards_indexed(self):
        idx = ts.skill_index()
        names = {e["name"] for e in idx}
        assert "disorder-ruleset" in names
        assert "plat097-resolution-cutoff" in names

    def test_alert_match_finds_plat097_card(self):
        hits = ts.skills_for_alerts(["097"])
        assert any(h["skill"] == "plat097-resolution-cutoff" for h in hits)


class TestSaveReadDelete:
    def test_save_read_roundtrip(self, kdir):
        r = ts.SaveSkill().run(
            _ctx(), name="test-rule", description="a test rule",
            body="x" * 60, alerts=["PLAT097"], tools=["refine"],
            source="unit-test", confidence="low", reason="testing")
        assert r.ok, r.error
        assert r.summary["action"] == "created"
        assert (kdir / "skills" / "test-rule.md").exists()

        r2 = ts.ReadSkill().run(_ctx(), name="test-rule")
        assert r2.ok and "a test rule" in r2.summary["text"]

        lst = ts.ListSkills().run(_ctx(), alert="097")
        assert lst.summary["n_skills"] == 1

        r3 = ts.SaveSkill().run(
            _ctx(), name="test-rule", description="updated rule",
            body="y" * 60, source="unit-test", reason="update")
        assert r3.ok and r3.summary["action"] == "updated"
        assert "updated rule" in ts.ReadSkill().run(
            _ctx(), name="test-rule").summary["text"]

        r4 = ts.DeleteSkill().run(_ctx(), name="test-rule",
                                  reason="test cleanup")
        assert r4.ok
        assert not (kdir / "skills" / "test-rule.md").exists()

    def test_slug_and_body_guards(self, kdir):
        bad = ts.SaveSkill().run(
            _ctx(), name="Bad Name!", description="d", body="x" * 60,
            source="s", reason="r")
        assert not bad.ok and "kebab-case" in bad.error
        short = ts.SaveSkill().run(
            _ctx(), name="ok-name", description="d", body="tiny",
            source="s", reason="r")
        assert not short.ok and "too short" in short.error

    def test_delete_unknown_fails(self, kdir):
        r = ts.DeleteSkill().run(_ctx(), name="ghost", reason="r")
        assert not r.ok

    def test_update_in_place_for_other_category(self, kdir):
        # a card living under expert-cases/ must be edited there, not
        # shadowed by a new skills/ copy
        ec = kdir / "expert-cases"
        ec.mkdir()
        (ec / "old-card.md").write_text(
            "---\nsymptom: s\n---\nold body\n", encoding="utf-8")
        r = ts.SaveSkill().run(
            _ctx(), name="old-card", description="refreshed",
            body="z" * 60, source="s", reason="refresh")
        assert r.ok and r.summary["saved"].startswith("expert-cases/")
        assert not (kdir / "skills" / "old-card.md").exists()


class TestRegistryWiring:
    def test_tools_registered(self):
        from crystalpilot.refine.registry import SESSIONLESS_TOOLS
        from crystalpilot.refine.tools_skills import register_skills_tools
        from crystalpilot.tools.base import ToolRegistry
        reg = ToolRegistry()
        register_skills_tools(reg, None)
        names = {s["name"] for s in reg.specs()}
        assert {"list_skills", "read_skill", "save_skill",
                "delete_skill"} <= names
        assert {"list_skills", "read_skill", "save_skill",
                "delete_skill"} <= SESSIONLESS_TOOLS

    def test_readonly_gate_covers_reads_only(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        assert "list_skills" in READ_ONLY_TOOLS
        assert "read_skill" in READ_ONLY_TOOLS
        assert "save_skill" not in READ_ONLY_TOOLS
        assert "delete_skill" not in READ_ONLY_TOOLS


class TestContextFreshness:
    def test_external_context_edit_visible(self, tmp_path):
        # round-10 p770 round 8: mentor backfilled context.json while the
        # session was open; the cached copy shadowed it and the CIF
        # assembler shipped '?' fields
        import json
        import os
        import time

        from crystalpilot.refine.project import RefineProject
        d = tmp_path / "proj"
        d.mkdir()
        (d / "crystal.hkl").write_text(
            "   1   0   0  100.00    5.00\n"
            "   0   0   0    0.00    0.00\n", encoding="utf-8")
        (d / "start.res").write_text(
            "TITL t\nCELL 0.71073 10 10 10 90 90 90\n"
            "ZERR 1 0 0 0 0 0 0\nLATT -1\nSFAC C\nUNIT 2\n"
            "C1 1 0.1 0.1 0.1 11.0 0.02\nHKLF 4\nEND\n", encoding="utf-8")
        cj = d / "context.json"
        cj.write_text(json.dumps({
            "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
            encoding="utf-8")
        p = RefineProject(d)
        assert "experiment" not in p.context
        data = json.loads(cj.read_text(encoding="utf-8"))
        data["experiment"] = {"cell_measurement": {"reflns_used": 9996}}
        cj.write_text(json.dumps(data), encoding="utf-8")
        # ensure a distinct mtime even on coarse filesystems
        os.utime(cj, (time.time() + 2, time.time() + 2))
        assert p.context["experiment"]["cell_measurement"][
            "reflns_used"] == 9996


class TestToolSetConsistency:
    """The three capability sets are maintained in two files - this guard
    catches drift (run_shelxt once had to be patched into both by hand)."""

    def _all_names(self):
        from crystalpilot.refine.registry import refinement_registry
        from crystalpilot.refine.tools_analysis import register_analysis_tools
        from crystalpilot.refine.tools_disorder import register_disorder_tools
        from crystalpilot.refine.tools_extra import register_refine_tools
        from crystalpilot.refine.tools_cap import register_cap_tools
        from crystalpilot.refine.tools_frames import register_frames_tools
        from crystalpilot.refine.tools_skills import register_skills_tools
        from crystalpilot.refine.tools_batch import register_batch_tools
        from crystalpilot.refine.tools_probe import register_probe_tools
        reg = refinement_registry(None)
        register_refine_tools(reg, None)
        register_analysis_tools(reg, None)
        register_disorder_tools(reg, None)
        register_frames_tools(reg, None)
        register_cap_tools(reg, None)
        register_skills_tools(reg, None)
        register_batch_tools(reg, None)
        register_probe_tools(reg, None)
        names = {s["name"] for s in reg.specs()}
        names.add("consult_specialist")     # opt-in gated registration
        return names

    def test_sets_reference_registered_tools(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.registry import (MUTATING_TOOLS,
                                                  SESSIONLESS_TOOLS)
        names = self._all_names()
        assert MUTATING_TOOLS <= names, MUTATING_TOOLS - names
        assert READ_ONLY_TOOLS <= names, READ_ONLY_TOOLS - names
        assert SESSIONLESS_TOOLS <= names, SESSIONLESS_TOOLS - names

    def test_mutating_and_readonly_disjoint(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.registry import MUTATING_TOOLS
        assert not (MUTATING_TOOLS & READ_ONLY_TOOLS)

    #: neither model-mutating nor read-only: each writes something else
    #: (files, the node pointer, the knowledge dir, the network). Listed
    #: so a NEW tool cannot silently land outside both sets - the subset
    #: guards above never caught that, which is how four pure-read
    #: analysis tools stayed blocked in read-only mode until 2026-09.
    NEITHER = {
        # node store pointer, not the model
        "branch", "checkout",
        # raw-frames / ingest pipeline: writes products under .crystalpilot
        "import_frames", "find_spots", "index_frames", "integrate_frames",
        "scale_and_export", "export_twin_hklf5", "create_start_model",
        "ingest_vendor_data", "import_cif_model", "set_experiment",
        # solvers: heavy compute, cache density/peaks (interpret_peaks is
        # the mutating step that turns a solution into a model)
        "solve_charge_flipping", "solve_superflip",
        # batch hypothesis tests: commit their own diagnostic nodes and
        # restore the baseline before returning (the model the caller
        # sees is unchanged, the node store is not)
        "ghost_test", "element_scan", "probe_site",
        # writes outside the session (finalize_delivery rewrites the
        # delivery directory's status header / REPORT / MANIFEST)
        "write_outputs", "finalize_delivery", "save_skill", "delete_skill",
        # round-3 WP7: writes the investigation record (goal / tiers /
        # ruled out / open directions) under .crystalpilot, never the model
        "set_investigation",
        # drives the vendor GUI to write reduction products into the
        # experiment directory; nothing enters the session until
        # ingest_vendor_data / swap_reflection_data is called
        "reduce_with_crysalis",
        # outbound network
        "submit_iucr_checkcif",
        # spawns a sub-agent; read-only inside, but not itself an
        # inspection call (and must not recurse in read-only mode)
        "consult_specialist",
    }

    def test_every_tool_is_classified(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.registry import MUTATING_TOOLS
        names = self._all_names()
        stray = names - MUTATING_TOOLS - READ_ONLY_TOOLS - self.NEITHER
        assert not stray, (
            f"unclassified tools {sorted(stray)}: add to MUTATING_TOOLS, "
            "READ_ONLY_TOOLS, or this test's NEITHER list (with a reason)")
        assert not (self.NEITHER - names), sorted(self.NEITHER - names)

    def test_solver_route_registered(self):
        names = self._all_names()
        assert {"solve_charge_flipping", "interpret_peaks",
                "run_shelxt"} <= names


class TestReadSkillPagination:
    def test_long_skill_paginates_with_metadata(self, kdir):
        body = "L" * 45000     # 3 pages at PAGE=20000 incl. frontmatter
        r = ts.SaveSkill().run(
            _ctx(), name="long-rule", description="long card",
            body=body, source="unit-test", confidence="low", reason="t")
        assert r.ok, r.error
        p1 = ts.ReadSkill().run(_ctx(), name="long-rule").summary
        assert p1["truncated"] is True and p1["offset"] == 0
        assert len(p1["text"]) == ts.ReadSkill.PAGE
        assert p1["next_offset"] == ts.ReadSkill.PAGE
        total = p1["n_chars_total"]
        # walk all pages and reassemble the exact file
        parts, off = [], 0
        for _ in range(10):
            pg = ts.ReadSkill().run(_ctx(), name="long-rule",
                                    offset=off).summary
            parts.append(pg["text"])
            if not pg["truncated"]:
                break
            off = pg["next_offset"]
        joined = "".join(parts)
        assert len(joined) == total
        on_disk = (kdir / "skills" / "long-rule.md").read_text(
            encoding="utf-8")
        assert joined == on_disk                  # exact reassembly
        assert "...[truncated]" not in joined     # old marker is gone

    def test_short_skill_untruncated(self, kdir):
        ts.SaveSkill().run(
            _ctx(), name="short-rule", description="short",
            body="z" * 80, source="unit-test", reason="t")
        s = ts.ReadSkill().run(_ctx(), name="short-rule").summary
        assert s["truncated"] is False and "next_offset" not in s


class TestRetrievalRecall:
    """Process-audit T12: ~25 empty list_skills calls across campaigns -
    zh queries against en cards, single-code alert loops, dead-end empty
    results."""

    @staticmethod
    def _card(kdir, name, description, tags=(), alerts=(), aliases=()):
        lines = ["---", f"name: {name}", f"description: {description}"]
        if tags:
            lines.append("tags: [" + ", ".join(tags) + "]")
        if alerts:
            lines.append("alerts: [" + ", ".join(alerts) + "]")
        if aliases:
            lines.append("aliases: [" + ", ".join(aliases) + "]")
        lines += ["---", "", "body " * 20]
        (kdir / "skills" / f"{name}.md").write_text(
            "\n".join(lines), encoding="utf-8")

    def test_zh_query_finds_en_card(self, kdir):
        self._card(kdir, "twin-warning-signs",
                   "twin warning signs before refinement", tags=["twin"])
        r = ts.ListSkills().run(_ctx(), query="孪晶")
        assert r.summary["n_skills"] == 1
        assert r.summary["skills"][0]["name"] == "twin-warning-signs"

    def test_multiword_and_semantics(self, kdir):
        self._card(kdir, "twin-refine", "twin refinement pacing")
        self._card(kdir, "twin-data", "twin data audit rules")
        r = ts.ListSkills().run(_ctx(), query="twin data")
        assert r.summary["n_skills"] == 1
        assert r.summary["skills"][0]["name"] == "twin-data"

    def test_alert_batch_one_call(self, kdir):
        self._card(kdir, "card-a", "a", alerts=("PLAT097",))
        self._card(kdir, "card-b", "b", alerts=("220",))
        self._card(kdir, "card-c", "c", alerts=("306",))
        r = ts.ListSkills().run(_ctx(), alert="097, 220")
        names = {s["name"] for s in r.summary["skills"]}
        assert names == {"card-a", "card-b"}
        assert r.summary["matched_alerts"] == {"card-a": ["097"],
                                               "card-b": ["220"]}

    def test_empty_result_reports_per_word_nearest(self, kdir):
        self._card(kdir, "twin-warning-signs", "twin warning signs")
        r = ts.ListSkills().run(_ctx(), query="孪晶 qqzz")
        assert r.summary["n_skills"] == 0
        near = r.summary["near_misses_per_word"]
        assert near["孪晶"]["n"] == 1
        assert near["孪晶"]["top"] == ["twin-warning-signs"]
        assert near["qqzz"]["n"] == 0
        assert "drop the word" in r.summary["note"]

    def test_aliases_searchable(self, kdir):
        self._card(kdir, "twin-workflow", "two-domain workflow",
                   aliases=("hklf5", "basf"))
        r = ts.ListSkills().run(_ctx(), query="hklf5")
        assert r.summary["n_skills"] == 1


class TestReadSkillSections:
    """pa1: the 108k-char review ruleset was read four pages at a time,
    ~13 reads per run, and re-read after every compaction. A card is now
    addressable by section."""

    CARD = ("# 规则集\n\n前言。\n\n## 一、报告规范\n\n### A1. 带 s.u.\n\nA1 正文\n\n"
            "### A2. 位数\n\nA2 正文\n\n## 二、R 因子\n\n### A5. 孪晶怀疑链\n\n"
            "A5 正文\n")

    def _save(self, kdir):
        r = ts.SaveSkill().run(
            _ctx(), name="sectioned", description="sectioned card",
            body=self.CARD, source="unit-test", confidence="low", reason="t")
        assert r.ok, r.error

    def test_sections_table_and_section_read(self, kdir):
        self._save(kdir)
        s = ts.ReadSkill().run(_ctx(), name="sectioned").summary
        heads = [x["heading"] for x in s["sections"]]
        assert "二、R 因子" in heads and "A5. 孪晶怀疑链" in heads
        # by code prefix: the shortest heading containing the key
        one = ts.ReadSkill().run(_ctx(), name="sectioned",
                                 section="A2").summary
        assert one["section"]["heading"] == "A2. 位数"
        assert one["text"].startswith("### A2. 位数")
        assert "A2 正文" in one["text"] and "A5 正文" not in one["text"]
        assert one["truncated"] is False
        # a level-2 section carries its subsections
        two = ts.ReadSkill().run(_ctx(), name="sectioned",
                                 section="R 因子").summary
        assert "A5 正文" in two["text"] and "A1 正文" not in two["text"]
        # by index from the table
        i = next(x["i"] for x in s["sections"] if x["heading"] == "A1. 带 s.u.")
        byi = ts.ReadSkill().run(_ctx(), name="sectioned",
                                 section=str(i)).summary
        assert byi["section"]["heading"] == "A1. 带 s.u."

    def test_unknown_section_lists_the_headings(self, kdir):
        self._save(kdir)
        r = ts.ReadSkill().run(_ctx(), name="sectioned", section="Z99")
        assert not r.ok and "A5. 孪晶怀疑链" in r.error

    def test_section_key_found_inside_a_body_falls_back_to_content(self, kdir):
        """reg1-ext2 cuox: read_skill(section='PLAT196') on a ruleset whose
        headings are topics - the alert code lives inside a section. The
        section that mentions it most is returned and the match is
        declared, so the agent knows it was not a heading."""
        card = ("# 规则集\n\n## 一、报告规范\n\n### A1. 位数\n\nA1 正文\n\n"
                "## 二、警报\n\n### B3. 氢原子\n\nPLAT196 说的是 H 的 U(iso)；"
                "PLAT196 出现两次。\n\n### B4. 其他\n\nPLAT196 一次。\n")
        r = ts.SaveSkill().run(_ctx(), name="coded", description="coded card",
                               body=card, source="unit-test",
                               confidence="low", reason="t")
        assert r.ok, r.error
        one = ts.ReadSkill().run(_ctx(), name="coded", section="PLAT196")
        assert one.ok, one.error
        assert one.summary["section_matched_by"] == "content"
        assert one.summary["section_heading"] == "B3. 氢原子"
        assert "出现两次" in one.summary["text"]
        # a heading match still wins and is declared as such
        two = ts.ReadSkill().run(_ctx(), name="coded", section="B4").summary
        assert two["section_matched_by"] == "heading"
        # nothing anywhere: still the honest refusal with the headings
        r = ts.ReadSkill().run(_ctx(), name="coded", section="PLAT999")
        assert not r.ok and "neither a heading nor a mention" in r.error

    def test_long_card_note_points_at_sections(self, kdir):
        body = "## S1\n\n" + "x" * 30000 + "\n\n## S2\n\n" + "y" * 100
        ts.SaveSkill().run(_ctx(), name="long-sectioned", description="d",
                           body=body, source="unit-test", reason="t")
        s = ts.ReadSkill().run(_ctx(), name="long-sectioned").summary
        assert s["truncated"] is True and "section=" in s["note"]
        s2 = ts.ReadSkill().run(_ctx(), name="long-sectioned",
                                section="S2").summary
        assert s2["text"].strip() == "## S2\n\n" + "y" * 100

    def test_helpers(self):
        secs = ts.skill_sections("# T\n\n## A\n\ntext\n\n### A.1\n\n## B\n")
        assert [(s["level"], s["heading"]) for s in secs] == [
            (1, "T"), (2, "A"), (3, "A.1"), (2, "B")]
        a = ts.find_section(secs, "a")
        assert a["heading"] == "A" and secs[1]["end"] == secs[3]["offset"]
        assert ts.find_section(secs, "4")["heading"] == "B"
        assert ts.find_section(secs, "zzz") is None
