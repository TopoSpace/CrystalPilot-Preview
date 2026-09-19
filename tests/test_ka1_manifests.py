"""ka1 knowledge-ablation manifests: the prompt is held at L0 in both arms
(unlike pa1's ladder) and only the project's own knowledge layer varies -
`tools_only` (operational contract + honesty rules only) versus `full`
(current AGENTS v32 + skill cards). See crystalpilot/benchmark/
ka1_manifests.py for the design; see docs on pa1_manifests.py for why the
prompt-ladder discipline (no answer leakage, mentor-side-only references)
matters here too."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from crystalpilot.benchmark import ka1_manifests as km
from crystalpilot.benchmark.agent_campaign import CaseRun
from crystalpilot.benchmark.pa1_manifests import L0

REPO = Path(__file__).resolve().parents[1]
ORG_STAGING = Path("H:/CrystalPilotData/staging/ka1o")


def _cases():
    return [c for man in km.build_all().values() for c in man["cases"]]


def _case_run(case: dict) -> CaseRun:
    c = object.__new__(CaseRun)
    c.name = case["name"]
    c.case = case
    return c


class TestBriefHeldAtL0:
    """The whole point of ka1 is that the MESSAGE does not change - only
    what is baked into the project's own instructions does. If the brief
    drifted per arm/crystal, or a context.json snuck in, the experiment
    would be measuring the prompt again, not the knowledge layer."""

    def test_every_case_brief_is_exactly_l0(self):
        for c in _cases():
            assert c["brief"] == L0, c["name"]

    def test_no_case_ever_gets_a_context_file(self):
        for c in _cases():
            assert "context" not in c, c["name"]

    def test_the_brief_never_carries_a_reference_path(self):
        for c in _cases():
            assert "refs/" not in c["brief"]
            assert "reference" not in c["brief"].lower()


class TestArmsPerLane:
    def test_three_lanes_named_ka1_hex_cage_org(self):
        assert set(km.build_all()) == {"ka1-hex", "ka1-cage", "ka1-org"}

    def test_each_lane_has_exactly_one_tools_only_and_one_full_case(self):
        for name, man in km.build_all().items():
            modes = [c["knowledge_mode"] for c in man["cases"]]
            assert modes == ["tools_only", "full"], f"{name}: {modes}"

    def test_six_cases_total_no_name_collisions(self):
        cases = _cases()
        assert len(cases) == 6
        assert len({c["name"] for c in cases}) == 6

    def test_case_names_follow_crystal_arm_replicate(self):
        for c in _cases():
            assert c["name"] == (
                f"{c['crystal']}-{c['arm']}-r{c['replicate']}")

    def test_every_case_names_a_reference_so_it_can_be_scored(self):
        for c in _cases():
            assert c["reference"] and c["reference_kind"]

    def test_hex_and_cage_reuse_the_pa1_specs_verbatim(self):
        from crystalpilot.benchmark.pa1_manifests import CRYSTALS as pa1c
        for crystal in ("hex", "cage"):
            got = {c["reference"] for c in _cases() if c["crystal"] == crystal}
            assert got == {pa1c[crystal]["reference"]}


class TestProjectsRootOutsideRepo:
    """Manifests must not put project dirs under the repo tree: a
    repo-root AGENTS.md was leaking into in-repo project dirs and would
    silently contaminate the tools_only arm."""

    def test_projects_root_starts_with_the_external_campaigns_root(self):
        for name, man in km.build_all().items():
            assert man["projects_root"].startswith(
                "H:/CrystalPilot-campaigns/"), name

    def test_projects_root_is_not_under_the_repo(self):
        # NB a naive string-prefix check is the wrong tool here: the
        # string "H:/CrystalPilot-campaigns" itself starts with the repo
        # path "H:/CrystalPilot" as raw text. Path.is_relative_to compares
        # path components, not characters, and is what actually answers
        # "is this directory inside the repo tree".
        for name, man in km.build_all().items():
            root = Path(man["projects_root"]).resolve()
            assert not root.is_relative_to(REPO), name


@pytest.mark.skipif(not ORG_STAGING.exists(),
                    reason=f"{ORG_STAGING} not staged (run the ka1 org "
                           "staging step first)")
class TestOrgStagingHygiene:
    """The org lane's staging dir is freshly hand-built (unlike hex/cage,
    which reuse already-audited pa1 staging trees), so it gets its own
    direct check with the real hygiene logic the runner uses."""

    def test_no_answer_shaped_files_via_the_real_hygiene_check(self):
        man = km.build_all()["ka1-org"]
        for c in man["cases"]:
            assert c["data_dir"] == str(ORG_STAGING).replace("\\", "/")
            leaks = _case_run(c).check_staging_hygiene()
            assert leaks == [], f"{c['name']}: {leaks}"

    def test_only_the_two_expected_files_are_present(self):
        names = sorted(p.name for p in ORG_STAGING.iterdir())
        assert names == ["crystal.hkl", "start.ins"]

    def test_start_ins_is_a_cold_start_placeholder(self):
        text = (ORG_STAGING / "start.ins").read_text(encoding="utf-8")
        assert "SYMM" not in text
        assert "P2" not in text and "21 21 21" not in text  # no space group
        assert re.search(r"^HKLF 4$", text, re.M)
        assert re.search(r"^END$", text, re.M)
        # no atom record lines (label, sfac#, x, y, z, sof, U...). Same
        # >=5 threshold as CaseRun.check_staging_hygiene: a lone spurious
        # match off a header line (ZERR's own numbers can look like one
        # x/y/z triple) must not trip this, only an actual atom list.
        atoms = re.findall(
            r"^[A-Za-z]{1,2}[A-Za-z0-9_]*\s+\d+\s+-?\d*\.\d+\s+"
            r"-?\d*\.\d+\s+-?\d*\.\d+", text, re.M)
        assert len(atoms) < 5, atoms

    def test_start_ins_cell_matches_the_deposited_cif(self):
        text = (ORG_STAGING / "start.ins").read_text(encoding="utf-8")
        m = re.search(r"^CELL\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+"
                      r"([\d.]+)\s+([\d.]+)\s+([\d.]+)", text, re.M)
        assert m is not None
        wavelength, a, b, c, al, be, ga = m.groups()
        assert float(wavelength) == pytest.approx(1.54178)
        assert float(a) == pytest.approx(5.0215)
        assert float(b) == pytest.approx(9.8852)
        assert float(c) == pytest.approx(17.7668)
        assert (float(al), float(be), float(ga)) == (90.0, 90.0, 90.0)
