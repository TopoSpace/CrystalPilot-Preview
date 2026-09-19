"""Project storage: lossless links/strips, restorable CIFs, bounded cleanup
(crystalpilot/refine/storage.py, 2026-09-16).

Synthetic projects are built in tmp_path; the one test on real data uses a
COPY of one SHELXL job from the read-only regression copy and is skipped
when that copy is absent.
"""
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from crystalpilot.refine import storage
from crystalpilot.refine.storage import (
    Action, apply_cleanup, hkl_embed_text, is_stripped, link_or_copy, measure_project,
    plan_cleanup, project_usage, referenced_shelxl_jobs, restore_embedded_hkl,
    same_bytes, same_file, strip_embedded_hkl,
)

HKL = (b"".join(b"%4d%4d%4d%8.2f%8.2f\r\n" % (h, k, l, 10.0 + h + k, 0.5)
               for h in range(20) for k in range(10) for l in range(10))
       + b"   0   0   0    0.00    0.00\r\n; trailing free text with a semicolon line\r\n"
       b"more text\r\n")
FAB = b"   1   0   0  -0.1234   0.5678\r\n   0   0   0   0.0000   0.0000\r\n"


def cif_with_hkl(hkl: bytes, r1: str = "0.0500") -> bytes:
    return (b"data_job\r\n_refine_ls_R_factor_gt " + r1.encode() + b"\r\n"
            b"_shelx_res_file\r\n;\r\nTITL x\r\n;\r\n_shelx_res_checksum 1\r\n"
            b"_shelx_hkl_file\r\n;\r\n" + hkl_embed_text(hkl) + b"\r\n;\r\n"
            b"_shelx_hkl_checksum 19066\r\n_atom_site_label X\r\n")


def make_project(root: Path, n_jobs: int = 5) -> Path:
    p = root / "proj"
    p.mkdir()
    refine = p / ".crystalpilot" / "refine"
    (p / "crystal.hkl").write_bytes(HKL)
    (p / "start.res").write_text("TITL user\n")
    (p / "my notes.txt").write_text("user file\n")
    rev = refine / "data" / "d000001"
    rev.mkdir(parents=True)
    (rev / "observations.hkl").write_bytes(HKL)
    (rev / "data.json").write_text(json.dumps({"schema": 1, "id": "d000001"}))
    (rev / "sources").mkdir()
    (rev / "sources" / "source-0000.hkl").write_bytes(HKL)
    for i in range(n_jobs):
        job = refine / "shelxl" / f"job_2026091{i}_120000"
        job.mkdir(parents=True)
        (job / "job.hkl").write_bytes(HKL)
        (job / "job.cif").write_bytes(cif_with_hkl(HKL, f"0.0{50 + i}"))
        (job / "job.fcf").write_bytes(b"fcf" * 1000)
        (job / "job.fab").write_bytes(FAB)
        (job / "job.ins").write_text("L.S. 4\n")
        (job / "job.res").write_text("TITL\n")
        (job / "job.lst").write_text("lst\n")
        (job / ".ok").write_text("")
    # node n0001 adopted job 1
    node = refine / "nodes" / "n0001"
    node.mkdir(parents=True)
    (node / "node.json").write_text(json.dumps({
        "id": "n0001", "metrics_source": {"engine": "SHELXL", "job": "job_20260911_120000"}}))
    (node / "model.res").write_text("TITL\n")
    # a delivery names job 0
    deliv = p / "CrystalPilot Results" / "task_1"
    deliv.mkdir(parents=True)
    (deliv / "final.cif").write_bytes(cif_with_hkl(HKL))
    (deliv / "REPORT.json").write_text(json.dumps({
        "publication_cif": {"shelxl_job": "job_20260910_120000", "job_match": {"job": "job_20260910_120000"}}}))
    (deliv / "MANIFEST.json").write_text(json.dumps({"provenance": {
        "final.cif": {"from": "SHELXL job job_20260910_120000 job.cif + session metadata"}}}))
    # finished checkCIF job
    cc = refine / "checkcif" / "job_20260910_130000_1_abc"
    cc.mkdir(parents=True)
    (cc / "checkcif.json").write_text("{}")
    (cc / "model.cif").write_bytes(cif_with_hkl(HKL))
    (cc / "model.ckf").write_bytes(b"x" * 5000)
    (cc / "model.ps").write_bytes(b"y" * 3000)
    (cc / "model.chk").write_text("report\n")
    # finished staging whose big file is in data/
    stg = refine / ".staging" / "abc123"
    (stg / "inputs").mkdir(parents=True)
    big = HKL * 3              # > 64 KB
    (stg / "inputs" / "crystal.hkl").write_bytes(big)
    (rev / "sources" / "source-0001.hkl").write_bytes(big)
    (stg / "completed.json").write_text("{}")
    old = time.time() - 2 * 3600
    os.utime(stg / "completed.json", (old, old))
    (refine / "scene-cache").mkdir()
    (refine / "scene-cache" / "n0001.json").write_text("{}")
    return p


class TestEmbedRoundTrip:
    def test_hkl_embed_text_escapes_semicolon_lines_and_drops_the_last_newline(self):
        t = hkl_embed_text(HKL)
        assert b"\r\n) trailing" in t and not t.endswith(b"\n")
        assert hkl_embed_text(b"a\nb\n") == b"a\nb"
        assert hkl_embed_text(b"a\nb") == b"a\nb"

    def test_strip_then_restore_is_byte_identical(self, tmp_path):
        job = tmp_path / "job"
        job.mkdir()
        (job / "job.hkl").write_bytes(HKL)
        original = cif_with_hkl(HKL)
        (job / "job.cif").write_bytes(original)
        saved = strip_embedded_hkl(job)
        stripped = (job / "job.cif").read_bytes()
        assert saved > 0 and len(stripped) == len(original) - saved
        assert is_stripped(stripped.decode())
        assert b"_shelx_hkl_checksum 19066" in stripped
        restored = restore_embedded_hkl(stripped.decode("utf-8"), job)
        assert restored.encode("utf-8") == original
        # text-mode readers (CRLF -> LF) get an LF block, never CR CR LF
        lf = restored.replace("\r\n", "\n")
        assert restore_embedded_hkl(stripped.decode("utf-8").replace("\r\n", "\n"), job) == lf
        # idempotent
        assert strip_embedded_hkl(job) == 0
        assert restore_embedded_hkl(original.decode(), job).encode() == original

    def test_a_block_that_is_not_the_hkl_next_to_it_is_left_alone(self, tmp_path):
        job = tmp_path / "job"
        job.mkdir()
        (job / "job.hkl").write_bytes(HKL)
        other = cif_with_hkl(HKL.replace(b"0.50", b"0.60", 1))
        (job / "job.cif").write_bytes(other)
        assert strip_embedded_hkl(job) == 0
        assert (job / "job.cif").read_bytes() == other

    def test_restore_refuses_silently_incomplete_when_the_hkl_is_gone(self, tmp_path):
        job = tmp_path / "job"
        job.mkdir()
        (job / "job.hkl").write_bytes(HKL)
        (job / "job.cif").write_bytes(cif_with_hkl(HKL))
        strip_embedded_hkl(job)
        (job / "job.hkl").unlink()
        with pytest.raises(FileNotFoundError):
            restore_embedded_hkl((job / "job.cif").read_text(), job)


class TestLinkOrCopy:
    def test_links_to_an_identical_immutable_file(self, tmp_path):
        rev = tmp_path / "observations.hkl"
        rev.write_bytes(HKL)
        alias = tmp_path / "crystal.hkl"
        alias.write_bytes(HKL)
        dst = tmp_path / "job.hkl"
        how = link_or_copy(alias, dst, immutable=[rev])
        assert dst.read_bytes() == HKL
        if how == "link":
            assert same_file(dst, rev) and not same_file(dst, alias)
        else:  # a filesystem without hard links: a copy is the fallback
            assert same_bytes(dst, rev)

    def test_copies_when_no_immutable_twin_exists(self, tmp_path):
        alias = tmp_path / "crystal.hkl"
        alias.write_bytes(HKL)
        other = tmp_path / "other.hkl"
        other.write_bytes(HKL + b"x")
        dst = tmp_path / "job.hkl"
        assert link_or_copy(alias, dst, immutable=[other]) == "copy"
        assert dst.read_bytes() == HKL and not same_file(dst, alias)

    def test_a_linked_job_hkl_does_not_follow_a_rewritten_alias(self, tmp_path):
        rev = tmp_path / "observations.hkl"
        rev.write_bytes(HKL)
        alias = tmp_path / "crystal.hkl"
        alias.write_bytes(HKL)
        dst = tmp_path / "job.hkl"
        if link_or_copy(alias, dst, immutable=[rev]) != "link":
            pytest.skip("no hard links here")
        alias.write_bytes(b"swapped")
        assert dst.read_bytes() == HKL


class TestPlanAndApply:
    def test_measure_separates_user_results_and_system(self, tmp_path):
        p = make_project(tmp_path)
        u = measure_project(p)
        expected_user = sum((p / n).stat().st_size for n in ("crystal.hkl", "start.res", "my notes.txt"))
        assert u["user_bytes"] == expected_user
        assert u["results_bytes"] > 0
        assert u["categories"]["shelxl"]["files"] == 5 * 8
        # system = what the disk holds minus the user's files and deliverables
        assert u["system_bytes"] == u["unique_bytes"] - u["user_bytes"] - u["results_bytes"]
        assert u["unique_bytes"] <= u["total_bytes"]

    def test_references_come_from_nodes_and_deliveries(self, tmp_path):
        p = make_project(tmp_path)
        refs = referenced_shelxl_jobs(p)
        assert refs["nodes"] == {"job_20260911_120000"}
        assert refs["deliveries"] == {"job_20260910_120000"}

    def test_plan_is_a_dry_run_and_protects_the_right_things(self, tmp_path):
        p = make_project(tmp_path)
        before = {q: q.stat().st_size for q in p.rglob("*") if q.is_file()}
        plan = plan_cleanup(p, keep_recent=2)
        after = {q: q.stat().st_size for q in p.rglob("*") if q.is_file()}
        assert before == after
        kinds = {(a.kind, a.path) for a in plan.actions}
        # every job.hkl links to the revision; every job.cif strips
        assert all(("link", f".crystalpilot/refine/shelxl/job_2026091{i}_120000/job.hkl") in kinds for i in range(5))
        assert all(("strip", f".crystalpilot/refine/shelxl/job_2026091{i}_120000/job.cif") in kinds for i in range(5))
        # fab: first is the anchor, the others link to it
        assert sum(1 for k, path in kinds if k == "link" and path.endswith("job.fab")) == 4
        # fcf deleted only for jobs 2 (unreferenced, not recent); 0 = delivery, 1 = node, 3/4 = recent
        fcf_deleted = {path for k, path in kinds if k == "delete" and path.endswith("job.fcf")}
        assert fcf_deleted == {".crystalpilot/refine/shelxl/job_20260912_120000/job.fcf"}
        # PLATON by-products go, the report stays
        assert ("delete", ".crystalpilot/refine/checkcif/job_20260910_130000_1_abc/model.ckf") in kinds
        assert not any(path.endswith("checkcif.json") or path.endswith("model.chk") for _, path in kinds)
        # finished staging goes
        assert ("rmdir", ".crystalpilot/refine/.staging/abc123") in kinds
        # nothing under nodes/, CrystalPilot Results/ or the user's files; inside
        # the immutable revision directories the only allowed action is a
        # hard link between byte-identical files (sources/*.hkl -> observations.hkl)
        for kind, path in kinds:
            assert not path.startswith(("CrystalPilot Results", ".crystalpilot/refine/nodes"))
            if path.startswith(".crystalpilot/refine/data"):
                assert kind == "link"
                action = next(a for a in plan.actions if a.path == path)
                assert action.target.startswith(".crystalpilot/refine/data")
                assert (p / path).read_bytes() == (p / action.target).read_bytes()
            assert path.startswith(".crystalpilot/")
        assert not any(path.endswith(("job.ins", "job.res", "job.lst")) for _, path in kinds)
        # the cache is opt-in
        assert not any("scene-cache" in path for _, path in kinds)
        assert any("scene-cache" in a.path for a in plan_cleanup(p, include_cache=True).actions)

    def test_apply_frees_space_and_keeps_every_delivery_restorable(self, tmp_path):
        p = make_project(tmp_path)
        usage0 = measure_project(p)
        plan = plan_cleanup(p, keep_recent=2)
        result = apply_cleanup(plan)
        assert result["n_skipped"] == 0, result["skipped"]
        usage1 = measure_project(p)
        assert usage1["unique_bytes"] < usage0["unique_bytes"]
        assert result["freed_bytes"] > 0
        # user data and deliverables untouched
        assert (p / "crystal.hkl").read_bytes() == HKL
        assert (p / "my notes.txt").read_text() == "user file\n"
        assert (p / "CrystalPilot Results" / "task_1" / "final.cif").read_bytes() == cif_with_hkl(HKL)
        # every job.cif is stripped but restores to the original text
        for i in range(5):
            job = p / ".crystalpilot" / "refine" / "shelxl" / f"job_2026091{i}_120000"
            text = (job / "job.cif").read_bytes().decode("utf-8")
            assert is_stripped(text)
            assert restore_embedded_hkl(text, job).encode() == cif_with_hkl(HKL, f"0.0{50 + i}")
            assert (job / "job.hkl").read_bytes() == HKL
            assert (job / "job.lst").exists() and (job / "job.ins").exists() and (job / "job.res").exists()
        # the referenced and recent jobs keep their fcf, the orphan lost it
        assert (p / ".crystalpilot/refine/shelxl/job_20260910_120000/job.fcf").exists()
        assert (p / ".crystalpilot/refine/shelxl/job_20260911_120000/job.fcf").exists()
        assert not (p / ".crystalpilot/refine/shelxl/job_20260912_120000/job.fcf").exists()
        assert not (p / ".crystalpilot/refine/.staging/abc123").exists()
        assert (p / ".crystalpilot/refine/checkcif/job_20260910_130000_1_abc/checkcif.json").exists()
        # a second run finds nothing left
        assert plan_cleanup(p, keep_recent=2).actions == []

    def test_apply_rechecks_preconditions(self, tmp_path):
        p = make_project(tmp_path)
        plan = plan_cleanup(p, keep_recent=2)
        # tamper: the orphan's fcf is gone, one job.hkl changed meanwhile
        (p / ".crystalpilot/refine/shelxl/job_20260912_120000/job.fcf").unlink()
        (p / ".crystalpilot/refine/shelxl/job_20260913_120000/job.hkl").write_bytes(b"changed")
        result = apply_cleanup(plan)
        whys = {s["why"] for s in result["skipped"]}
        assert "file gone" in whys and "content changed since the plan" in whys
        assert (p / ".crystalpilot/refine/shelxl/job_20260913_120000/job.hkl").read_bytes() == b"changed"

    def test_apply_refuses_actions_outside_the_system_directory(self, tmp_path):
        p = make_project(tmp_path)
        plan = plan_cleanup(p)
        plan.actions = [Action("delete", "crystal.hkl", 1, "forged"),
                        Action("rmdir", "CrystalPilot Results/task_1", 1, "forged"),
                        Action("delete", ".crystalpilot/refine/nodes/n0001/model.res", 1, "forged")]
        result = apply_cleanup(plan)
        assert result["n_done"] == 0 and result["n_skipped"] == 3
        assert (p / "crystal.hkl").exists() and (p / "CrystalPilot Results" / "task_1").exists()
        assert (p / ".crystalpilot/refine/nodes/n0001/model.res").exists()

    def test_project_usage_reports_reclaimable(self, tmp_path):
        p = make_project(tmp_path)
        u = project_usage(p)
        assert u["reclaimable_bytes"] > 0 and u["n_actions"] > 0
        assert set(u["reclaimable_by_kind"]) >= {"link", "strip", "delete", "rmdir"}


REAL_JOB = Path("H:/cp-pytest-tmp/handover-real/test3-2/.crystalpilot/refine/shelxl/job_20260908_163051")


@pytest.mark.skipif(not (REAL_JOB / "job.cif").is_file(), reason="regression copy not on this machine")
def test_real_shelxl_job_cif_strips_and_restores_byte_identically(tmp_path):
    job = tmp_path / REAL_JOB.name
    job.mkdir()
    for name in ("job.cif", "job.hkl"):
        shutil.copy(REAL_JOB / name, job / name)
    if is_stripped((job / "job.cif").read_bytes().decode("utf-8", errors="surrogateescape")):
        # the regression copy has been cleaned already: rebuild the full CIF
        # first (bytes, keeping the file's own CRLF line endings: read_text
        # would translate them and the block would no longer match job.hkl),
        # then strip it again
        full = restore_embedded_hkl((job / "job.cif").read_bytes().decode("utf-8", errors="surrogateescape"), job)
        (job / "job.cif").write_bytes(full.encode("utf-8", errors="surrogateescape"))
    original = (job / "job.cif").read_bytes()
    saved = strip_embedded_hkl(job)
    assert saved > 6_000_000
    stripped = (job / "job.cif").read_bytes().decode("utf-8", errors="surrogateescape")
    assert len(stripped) < 100_000
    restored = restore_embedded_hkl(stripped, job)
    assert restored.encode("utf-8", errors="surrogateescape") == original
    # the production reader (read_text, newline translation) gets uniform LF text
    text_mode = (job / "job.cif").read_text(encoding="utf-8", errors="replace")
    restored_lf = restore_embedded_hkl(text_mode, job)
    assert "\r" not in restored_lf
    assert restored_lf == original.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _real_unique_bytes(root: Path) -> int:
    """Independent oracle: os.stat (never DirEntry.stat) inode dedup for the
    files large enough to be hard-linked (smaller ones are counted naively,
    like measure_project does)."""
    seen, total = set(), 0
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            st = os.stat(Path(dirpath) / n)
            if st.st_size >= storage.LINK_MIN_BYTES:
                if (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
            total += st.st_size
    return total


def test_measure_counts_hard_links_once_on_every_platform(tmp_path):
    """Windows scandir reports inode 0; measure_project must still see that
    41 job.hkl files sharing one revision are 6 MB on disk, not 250 MB."""
    p = make_project(tmp_path, n_jobs=4)
    plan = plan_cleanup(p, keep_recent=1)
    apply_cleanup(plan)
    m = measure_project(p)
    assert m["unique_bytes"] == _real_unique_bytes(p)
    assert m["unique_bytes"] < m["total_bytes"] - 3 * len(HKL)


def test_plan_links_identical_files_inside_revision_directories(tmp_path):
    p = make_project(tmp_path, n_jobs=1)
    plan = plan_cleanup(p, keep_recent=1)
    links = [(a.path, a.target) for a in plan.actions if a.kind == "link" and "/data/" in a.path]
    assert links == [(".crystalpilot/refine/data/d000001/sources/source-0000.hkl",
                      ".crystalpilot/refine/data/d000001/observations.hkl")]
    apply_cleanup(plan)
    assert storage.same_file(p / links[0][0], p / links[0][1])
    assert (p / links[0][0]).read_bytes() == HKL
    # idempotent: nothing left to link in data/
    assert not [a for a in plan_cleanup(p, keep_recent=1).actions if a.kind == "link" and "/data/" in a.path]
