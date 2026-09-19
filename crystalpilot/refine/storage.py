"""Project storage: accounting, lossless deduplication and bounded cleanup.

Why (measured 2026-09-16 on a copy of a real 8-hour session, test3-2): the
project held 713 MB of which the user's own data was 28 MB; the system's
``.crystalpilot/`` was 605 MB in 819 files. 69 ``.hkl`` = 391 MB (the same
6 MB ``crystal.hkl`` copied into every SHELXL / SHELXT job directory and
every finished input transaction), 118 ``.cif`` = 190 MB (SHELXL's ACTA
``job.cif`` embeds the whole reflection file, so every job carried the hkl a
second time inside its CIF; checkCIF staged another copy), ``.fab`` 49 MB
(identical mask coefficients per job), ``.ckf``/``.ps`` 16 MB (PLATON
by-products with no reader).

Three kinds of action, in increasing strength:

1. **link** - a byte-identical copy of an immutable file (a reflection
   revision's ``observations.hkl``, another job's ``job.fab``) is replaced by
   a hard link to it. Lossless: same bytes at the same path; the file is
   still there when the original directory is inspected by hand. Falls back
   to a copy when the filesystem refuses (different volume, FAT).
2. **strip** - the ``_shelx_hkl_file`` block inside an intermediate
   ``job.cif`` is replaced by a marker when it is byte-for-byte the SHELXL
   embedding of the ``job.hkl`` next to it (verified before every strip, see
   :func:`hkl_embed_text`). :func:`restore_embedded_hkl` puts the block back
   whenever the complete CIF is needed (publication CIF assembly, checkCIF
   staging), so a delivery still embeds the full reflection list; nothing
   scientific changes and SHELXL's own ``_shelx_hkl_checksum`` line is kept.
3. **delete** - by-products that no node, delivery or continuation reads:
   the ``job.fcf`` of a SHELXL job that no node adopted, no delivery names
   and that is not among the newest few (a pending ``write_outputs`` pairs
   the newest matching job); PLATON's ``model.ckf/.ps/.fcf/.lst`` in a
   finished checkCIF job; finished input-transaction staging directories
   whose large files exist byte-identically under ``data/``.

Never touched: anything outside ``.crystalpilot/`` (the user's files),
``nodes/``, ``data/`` (reflection revisions), ``CrystalPilot Results/``
(deliverables), the ``.ins/.res/.lst`` of every job, and any job a node or a
delivery references. :func:`plan_cleanup` is a dry run; :func:`apply_cleanup`
re-checks every precondition before acting.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

CRYSTALPILOT_DIR = ".crystalpilot"
RESULTS_DIRNAME = "CrystalPilot Results"

#: SHELXL jobs newer than this many are never candidates for deletion of
#: by-products: write_outputs pairs a node with the newest matching job, and
#: the agent may be about to deliver from one of them.
KEEP_RECENT_JOBS = 3
#: below this size a file is not worth a hard link, and the Windows full stat
#: that hard-link accounting needs is skipped when measuring
LINK_MIN_BYTES = 32 * 1024
#: finished staging directories younger than this are left alone
STAGING_MIN_AGE_S = 3600

STRIP_MARKER = "CrystalPilot: reflection block omitted from this intermediate CIF"
_STRIP_TEXT = (
    STRIP_MARKER + "\n"
    "The identical reflections are job.hkl in this directory (a hard link to\n"
    "the project's reflection revision); write_outputs re-embeds them verbatim\n"
    "into final.cif. _shelx_hkl_checksum below is SHELXL's checksum of that block."
)
_HKL_BLOCK_RE = re.compile(rb"(_shelx_hkl_file\r?\n;\r?\n)(.*?)(\r?\n;\r?\n)", re.S)
_HKL_BLOCK_RE_TEXT = re.compile(r"(_shelx_hkl_file\r?\n;\r?\n)(.*?)(\r?\n;\r?\n)", re.S)


# --------------------------------------------------------------- primitives

def same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def same_bytes(a: Path, b: Path) -> bool:
    """Byte-identical regular files (size first, then a streamed compare)."""
    try:
        sa, sb = a.stat(), b.stat()
    except OSError:
        return False
    if sa.st_size != sb.st_size or not a.is_file() or not b.is_file():
        return False
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            ca = fa.read(1 << 20)
            cb = fb.read(1 << 20)
            if ca != cb:
                return False
            if not ca:
                return True


def link_or_copy(src: Path, dst: Path, immutable: Iterable[Path] = ()) -> str:
    """Put ``src``'s bytes at ``dst`` without a second copy when possible.

    Prefers a hard link to an *immutable* byte-identical file (a reflection
    revision), then a hard link to ``src`` itself is NOT used (``src`` may be
    a mutable alias such as the project's ``crystal.hkl``), then a copy.
    Returns ``"link"`` or ``"copy"``."""
    src, dst = Path(src), Path(dst)
    if dst.exists():
        dst.unlink()
    for cand in immutable:
        cand = Path(cand)
        if cand.is_file() and same_bytes(cand, src):
            try:
                os.link(cand, dst)
                return "link"
            except OSError:
                break
    shutil.copy(src, dst)
    return "copy"


def reflection_revision_files(project_dir: Path) -> list[Path]:
    """Every immutable ``observations.hkl`` of the project, newest first."""
    d = Path(project_dir) / CRYSTALPILOT_DIR / "refine" / "data"
    if not d.is_dir():
        return []
    return sorted((p for p in d.glob("d*/observations.hkl") if p.is_file()),
                  key=lambda p: p.parent.name, reverse=True)


def hkl_embed_text(hkl: bytes) -> bytes:
    """The exact text SHELXL writes into ``_shelx_hkl_file`` for this hkl
    file: a ``;`` at the start of a line becomes ``)`` (it would otherwise
    terminate the CIF text field) and the final line terminator is dropped.
    Verified byte-for-byte on 22 + 8 real jobs from three projects
    (2026-09-16)."""
    body = re.sub(rb"(?m)^;", b")", hkl)
    if body.endswith(b"\r\n"):
        body = body[:-2]
    elif body.endswith(b"\n"):
        body = body[:-1]
    return body


def embedded_hkl_block(cif: bytes) -> re.Match[bytes] | None:
    return _HKL_BLOCK_RE.search(cif)


def strip_embedded_hkl(job_dir: Path, cif_name: str = "job.cif",
                       hkl_name: str = "job.hkl") -> int:
    """Replace the embedded reflection block of ``<job>/job.cif`` by the
    marker when it equals the SHELXL embedding of ``<job>/job.hkl``. Returns
    the bytes saved (0 when nothing was done: no block, no hkl, already
    stripped, or the block is NOT the hkl next to it - then the CIF is left
    exactly as SHELXL wrote it)."""
    job_dir = Path(job_dir)
    cif_p, hkl_p = job_dir / cif_name, job_dir / hkl_name
    if not cif_p.is_file() or not hkl_p.is_file():
        return 0
    cif = cif_p.read_bytes()
    m = embedded_hkl_block(cif)
    if m is None or STRIP_MARKER.encode() in m.group(2):
        return 0
    if m.group(2) != hkl_embed_text(hkl_p.read_bytes()):
        return 0
    marker = _STRIP_TEXT.replace("\n", "\r\n" if b"\r\n" in m.group(1) else "\n").encode()
    if len(m.group(2)) <= len(marker):
        return 0          # nothing to gain on a tiny reflection list
    new = cif[:m.start(2)] + marker + cif[m.end(2):]
    tmp = cif_p.with_suffix(".cif.tmp")
    tmp.write_bytes(new)
    os.replace(tmp, cif_p)
    return len(cif) - len(new)


def is_stripped(cif_text: str) -> bool:
    return STRIP_MARKER in cif_text


def restore_embedded_hkl(cif_text: str, job_dir: Path, hkl_name: str = "job.hkl") -> str:
    """The complete CIF again: the marker left by :func:`strip_embedded_hkl`
    is replaced by the SHELXL embedding of ``<job>/job.hkl``. A CIF without
    the marker is returned unchanged; a stripped CIF whose hkl is missing
    raises ``FileNotFoundError`` (never a silently incomplete delivery)."""
    if not is_stripped(cif_text):
        return cif_text
    hkl_p = Path(job_dir) / hkl_name
    if not hkl_p.is_file():
        raise FileNotFoundError(
            f"{hkl_p} is missing: the reflection block of this CIF was stripped "
            "and cannot be restored")
    m = _HKL_BLOCK_RE_TEXT.search(cif_text)
    if m is None or STRIP_MARKER not in m.group(2):
        return cif_text
    # the caller usually read the CIF in text mode (CRLF -> LF): the block
    # follows the text's own line-ending style so the file it is written
    # into stays uniform (a CRLF block inside LF text would come out as
    # CR CR LF on Windows)
    block = hkl_embed_text(hkl_p.read_bytes()).decode("utf-8", errors="surrogateescape")
    block = block.replace("\r\n", "\n")
    if "\r\n" in cif_text:
        block = block.replace("\n", "\r\n")
    return cif_text[:m.start(2)] + block + cif_text[m.end(2):]


# ------------------------------------------------------------- accounting

CATEGORY_LABELS = {
    "user": "用户数据（项目目录内非系统文件）",
    "results": "交付件（CrystalPilot Results）",
    "nodes": "节点库（模型快照）",
    "data": "反射数据版本",
    "shelxl": "SHELXL 作业",
    "shelxt": "SHELXT 作业",
    "checkcif": "checkCIF 作业",
    "staging": "输入事务暂存",
    "cache": "显示缓存（可再生）",
    "other_system": "其他系统文件",
}


def _walk_size(root: Path) -> tuple[int, int]:
    total = files = 0
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files


def _category_of(rel: Path) -> str:
    parts = rel.parts
    if not parts:
        return "other_system"
    if parts[0] == RESULTS_DIRNAME:
        return "results"
    if parts[0] != CRYSTALPILOT_DIR:
        return "user"
    if len(parts) >= 3 and parts[1] == "refine":
        sub = parts[2]
        if sub in ("nodes", "data", "shelxl", "shelxt", "checkcif"):
            return sub
        if sub == ".staging":
            return "staging"
        if sub in ("scene-cache",):
            return "cache"
        return "other_system"
    if len(parts) >= 2 and parts[1] in ("views", "analysis"):
        return "cache"
    return "other_system"


#: who owns a hard-linked file when it appears in several categories
_CATEGORY_PRIORITY = {"data": 0, "user": 1, "results": 2, "nodes": 3, "shelxl": 4, "shelxt": 5,
                      "checkcif": 6, "staging": 7, "cache": 8, "other_system": 9}


def measure_project(project_dir: Path) -> dict[str, Any]:
    """Bytes and file counts by category, plus the deduplication state of
    the hkl copies. Cheap (one scandir walk); no hashing."""
    project_dir = Path(project_dir)
    cats: dict[str, dict[str, int]] = {k: {"bytes": 0, "files": 0} for k in CATEGORY_LABELS}
    # (category, size, inode key) of every file; hard-linked files are then
    # attributed ONCE, to the category that owns the canonical copy (the
    # reflection revision), so the tiles add up to what the disk holds
    # instead of showing 280 MB of "SHELXL jobs" that are links into data/
    entries: list[tuple[str, int, tuple[int, int] | None]] = []
    total = 0
    stack = [project_dir]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                            continue
                        if not e.is_file(follow_symlinks=False):
                            continue
                        st = e.stat(follow_symlinks=False)
                        # Windows scandir leaves st_ino/st_dev/st_nlink at 0:
                        # a full stat is needed to see hard links. Only files
                        # big enough to be worth linking pay for it (2026-09-16:
                        # without this the cleaned copy still "measured" 483 MB
                        # while the disk held 212 MB).
                        if st.st_ino == 0 and st.st_size >= LINK_MIN_BYTES:
                            st = os.stat(e.path)
                    except OSError:
                        continue
                    rel = Path(e.path).relative_to(project_dir)
                    total += st.st_size
                    entries.append((_category_of(rel), st.st_size,
                                    (st.st_dev, st.st_ino) if st.st_ino else None))
        except OSError:
            continue
    seen_inodes: set[tuple[int, int]] = set()
    unique_bytes = 0
    for cat, size, key in sorted(entries, key=lambda t: _CATEGORY_PRIORITY.get(t[0], 99)):
        cats[cat]["files"] += 1
        if key is not None:
            if key in seen_inodes:
                continue
            seen_inodes.add(key)
        cats[cat]["bytes"] += size
        unique_bytes += size
    system = unique_bytes - cats["user"]["bytes"] - cats["results"]["bytes"]
    return {
        "path": str(project_dir),
        "total_bytes": total,                # naive sum (links counted per path)
        "unique_bytes": unique_bytes,        # what the disk actually holds
        "user_bytes": cats["user"]["bytes"],
        "results_bytes": cats["results"]["bytes"],
        "system_bytes": system,
        "categories": {k: {**v, "label": CATEGORY_LABELS[k]} for k, v in cats.items()},
        "measured_at": time.time(),
    }


# --------------------------------------------------------------- references

_JOB_RE = re.compile(r"job_\d{8}_\d{6}[\w.-]*")


def referenced_shelxl_jobs(project_dir: Path) -> dict[str, set[str]]:
    """SHELXL job names the project still points at: from every node's
    ``metrics_source.job`` and from every delivery's MANIFEST/REPORT
    (``publication_cif.shelxl_job``, ``job_match.job``, provenance texts)."""
    project_dir = Path(project_dir)
    by_node: set[str] = set()
    by_delivery: set[str] = set()
    for nj in (project_dir / CRYSTALPILOT_DIR / "refine" / "nodes").glob("n*/node.json"):
        try:
            meta = json.loads(nj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ms = meta.get("metrics_source") or {}
        if isinstance(ms, dict) and ms.get("job"):
            by_node.add(str(ms["job"]))
        for key in ("shelxl_job", "job"):
            if isinstance(meta.get(key), str):
                by_node.add(meta[key])
    results = project_dir / RESULTS_DIRNAME
    if results.is_dir():
        for name in ("MANIFEST.json", "REPORT.json"):
            for f in results.rglob(name):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if name == "MANIFEST.json":
                    by_delivery.update(_JOB_RE.findall(json.dumps(d.get("provenance") or {})))
                else:
                    pub = d.get("publication_cif") or {}
                    if isinstance(pub, dict):
                        if pub.get("shelxl_job"):
                            by_delivery.add(str(pub["shelxl_job"]))
                        jm = pub.get("job_match") or {}
                        if isinstance(jm, dict) and jm.get("job"):
                            by_delivery.add(str(jm["job"]))
                        if isinstance(pub.get("fab_source"), str):
                            by_delivery.update(_JOB_RE.findall(pub["fab_source"]))
    return {"nodes": by_node, "deliveries": by_delivery}


# --------------------------------------------------------------------- plan

@dataclass
class Action:
    kind: str            # link | strip | delete | rmdir
    path: str            # project-relative, forward slashes
    bytes: int
    reason: str
    target: str | None = None   # link target (project-relative)


@dataclass
class CleanupPlan:
    project: str
    actions: list[Action] = field(default_factory=list)
    protected: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def reclaimable_bytes(self) -> int:
        return sum(a.bytes for a in self.actions)

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, dict[str, int]] = {}
        for a in self.actions:
            k = by_kind.setdefault(a.kind, {"count": 0, "bytes": 0})
            k["count"] += 1
            k["bytes"] += a.bytes
        return {"project": self.project, "reclaimable_bytes": self.reclaimable_bytes,
                "n_actions": len(self.actions), "by_kind": by_kind,
                "protected": {k: sorted(v) for k, v in self.protected.items()},
                "notes": self.notes}

    def to_dict(self) -> dict[str, Any]:
        return {**self.summary(), "actions": [asdict(a) for a in self.actions]}


def _rel(project_dir: Path, p: Path) -> str:
    return p.relative_to(project_dir).as_posix()


def plan_cleanup(project_dir: Path, keep_recent: int = KEEP_RECENT_JOBS,
                 include_cache: bool = False) -> CleanupPlan:
    """Dry run: every action the cleanup would take, with its reason."""
    project_dir = Path(project_dir).resolve()
    refine = project_dir / CRYSTALPILOT_DIR / "refine"
    plan = CleanupPlan(project=str(project_dir))
    if not refine.is_dir():
        plan.notes.append("no .crystalpilot/refine directory")
        return plan
    revisions = reflection_revision_files(project_dir)
    refs = referenced_shelxl_jobs(project_dir)
    referenced = refs["nodes"] | refs["deliveries"]
    plan.protected = {"nodes": list(refs["nodes"]), "deliveries": list(refs["deliveries"])}

    # 1. hkl copies -> links to a reflection revision (lossless)
    hkl_copies: list[Path] = []
    for sub in ("shelxl", "shelxt"):
        hkl_copies += sorted((refine / sub).glob("job_*/job.hkl")) if (refine / sub).is_dir() else []
    for hkl in hkl_copies:
        if not hkl.is_file():
            continue
        for rev in revisions:
            if same_file(hkl, rev):
                break
            if same_bytes(hkl, rev):
                plan.actions.append(Action("link", _rel(project_dir, hkl), hkl.stat().st_size,
                                           "与反射数据版本逐字节相同：改为硬链接", _rel(project_dir, rev)))
                break

    # 1b. identical reflection files inside the immutable revision directories
    #     (observations.hkl and the kept sources/*.hkl of every revision are
    #     usually the same bytes: the original hkl, 6 MB each on a real MOF)
    data_dir = refine / "data"
    rev_files = (sorted(data_dir.glob("d*/observations.hkl")) + sorted(data_dir.glob("d*/sources/*.hkl"))) \
        if data_dir.is_dir() else []
    by_size_rev: dict[int, list[Path]] = {}
    for f in rev_files:
        try:
            if f.is_file() and f.stat().st_size >= LINK_MIN_BYTES:
                by_size_rev.setdefault(f.stat().st_size, []).append(f)
        except OSError:
            pass
    for size, group in by_size_rev.items():
        anchors: list[Path] = []
        for f in group:
            if any(same_file(a, f) for a in anchors):
                continue
            hit = next((a for a in anchors if same_bytes(a, f)), None)
            if hit is None:
                anchors.append(f)
            else:
                plan.actions.append(Action("link", _rel(project_dir, f), size,
                                           "反射数据版本内的副本与更早文件逐字节相同：改为硬链接", _rel(project_dir, hit)))

    # 2. embedded hkl inside intermediate job.cif -> marker (lossless, restorable)
    for cif in sorted(refine.glob("shelxl/job_*/job.cif")):
        hkl = cif.with_name("job.hkl")
        if not hkl.is_file():
            continue
        try:
            data = cif.read_bytes()
        except OSError:
            continue
        m = embedded_hkl_block(data)
        if m is None or STRIP_MARKER.encode() in m.group(2):
            continue
        if len(m.group(2)) > len(_STRIP_TEXT) + 8 and m.group(2) == hkl_embed_text(hkl.read_bytes()):
            plan.actions.append(Action("strip", _rel(project_dir, cif), len(m.group(2)) - len(_STRIP_TEXT),
                                       "CIF 内嵌反射块与 job.hkl 相同：改为引用，交付时原样恢复"))

    # 3. identical job.fab across SHELXL jobs -> links (lossless)
    fabs = sorted(refine.glob("shelxl/job_*/job.fab"))
    by_size: dict[int, list[Path]] = {}
    for f in fabs:
        try:
            by_size.setdefault(f.stat().st_size, []).append(f)
        except OSError:
            pass
    for size, group in by_size.items():
        if len(group) < 2 or size == 0:
            continue
        anchors: list[Path] = []
        for f in group:
            hit = next((a for a in anchors if same_file(a, f)), None)
            if hit is not None:
                continue
            hit = next((a for a in anchors if same_bytes(a, f)), None)
            if hit is None:
                anchors.append(f)
            else:
                plan.actions.append(Action("link", _rel(project_dir, f), size,
                                           "掩膜系数文件与更早作业逐字节相同：改为硬链接", _rel(project_dir, hit)))

    # 4. by-products of SHELXL jobs nobody references (not the newest few)
    jobs = sorted((p for p in refine.glob("shelxl/job_*") if p.is_dir()), key=lambda p: p.name)
    recent = {p.name for p in jobs[-keep_recent:]} if keep_recent > 0 else set()
    for job in jobs:
        if job.name in referenced or job.name in recent:
            continue
        for name in ("job.fcf",):
            f = job / name
            if f.is_file():
                plan.actions.append(Action("delete", _rel(project_dir, f), f.stat().st_size,
                                           "未被任何节点/交付引用的作业的结构因子表（.ins/.res/.lst 保留）"))

    # 5. PLATON by-products in finished checkCIF jobs
    for job in sorted(p for p in refine.glob("checkcif/job_*") if p.is_dir()):
        if not (job / "checkcif.json").is_file():
            continue          # unfinished or foreign: leave it
        for name in ("model.ckf", "model.ps", "model.fcf", "model.lst", "model.lis", "model.cif",
                     "model.hkl", "model.fab"):
            f = job / name
            if f.is_file():
                plan.actions.append(Action("delete", _rel(project_dir, f), f.stat().st_size,
                                           "checkCIF 已完成：PLATON 中间产物（报告 checkcif.json/.chk/.vrf 保留；被检 CIF 在交付目录）"))

    # 6. finished input-transaction staging whose big files live under data/
    data_files: dict[int, list[Path]] = {}
    for p in (refine / "data").rglob("*") if (refine / "data").is_dir() else []:
        if p.is_file():
            data_files.setdefault(p.stat().st_size, []).append(p)
    now = time.time()
    for stg in sorted(p for p in (refine / ".staging").glob("*") if p.is_dir()) if (refine / ".staging").is_dir() else []:
        done = stg / "completed.json"
        if not done.is_file() or now - done.stat().st_mtime < STAGING_MIN_AGE_S:
            continue
        if (stg / "failure.json").is_file():
            continue          # failed publication kept for manual recovery
        total = 0
        safe = True
        for f in stg.rglob("*"):
            if not f.is_file():
                continue
            size = f.stat().st_size
            total += size
            if size > 65536 and not any(same_bytes(f, c) for c in data_files.get(size, [])):
                safe = False
                break
        if safe:
            plan.actions.append(Action("rmdir", _rel(project_dir, stg), total,
                                       "输入事务已完成，大文件均已在反射数据版本目录中"))
        else:
            plan.notes.append(f"{_rel(project_dir, stg)}: 含未在 data/ 出现的大文件，保留")

    # 7. regenerable display caches (opt-in)
    if include_cache:
        for sub in (refine / "scene-cache", project_dir / CRYSTALPILOT_DIR / "views"):
            if sub.is_dir():
                size, n = _walk_size(sub)
                if n:
                    plan.actions.append(Action("rmdir", _rel(project_dir, sub), size,
                                               "显示缓存，打开结构时按需重算"))
    return plan


def apply_cleanup(plan: CleanupPlan) -> dict[str, Any]:
    """Execute a plan, re-checking each precondition; returns what happened."""
    project_dir = Path(plan.project)
    done: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    freed = 0
    for a in plan.actions:
        p = project_dir / a.path
        try:
            if not p.resolve().is_relative_to(project_dir.resolve()):
                skipped.append({**asdict(a), "why": "outside project"})
                continue
            rel_parts = Path(a.path).parts
            if a.kind != "rmdir" and (rel_parts[0] != CRYSTALPILOT_DIR):
                skipped.append({**asdict(a), "why": "not a system file"})
                continue
            if a.kind == "link":
                target = project_dir / (a.target or "")
                if not p.is_file() or not target.is_file():
                    skipped.append({**asdict(a), "why": "file gone"})
                    continue
                if same_file(p, target):
                    skipped.append({**asdict(a), "why": "already linked"})
                    continue
                if not same_bytes(p, target):
                    skipped.append({**asdict(a), "why": "content changed since the plan"})
                    continue
                tmp = p.with_name(p.name + ".linktmp")
                if tmp.exists():
                    tmp.unlink()
                try:
                    os.link(target, tmp)
                except OSError as e:
                    skipped.append({**asdict(a), "why": f"hard link refused: {e}"})
                    continue
                os.replace(tmp, p)
                freed += a.bytes
            elif a.kind == "strip":
                saved = strip_embedded_hkl(p.parent, p.name)
                if saved == 0:
                    skipped.append({**asdict(a), "why": "block no longer matches job.hkl"})
                    continue
                freed += saved
            elif a.kind == "delete":
                if not p.is_file():
                    skipped.append({**asdict(a), "why": "file gone"})
                    continue
                if rel_parts[:3] == (CRYSTALPILOT_DIR, "refine", "nodes") or \
                        rel_parts[:3] == (CRYSTALPILOT_DIR, "refine", "data"):
                    skipped.append({**asdict(a), "why": "protected directory"})
                    continue
                size = p.stat().st_size
                p.unlink()
                freed += size
            elif a.kind == "rmdir":
                if not p.is_dir():
                    skipped.append({**asdict(a), "why": "directory gone"})
                    continue
                if rel_parts[0] == RESULTS_DIRNAME or rel_parts[:3] in (
                        (CRYSTALPILOT_DIR, "refine", "nodes"), (CRYSTALPILOT_DIR, "refine", "data")):
                    skipped.append({**asdict(a), "why": "protected directory"})
                    continue
                size, _ = _walk_size(p)
                shutil.rmtree(p)
                freed += size
            else:
                skipped.append({**asdict(a), "why": f"unknown action {a.kind}"})
                continue
            done.append(asdict(a))
        except OSError as e:
            skipped.append({**asdict(a), "why": f"{type(e).__name__}: {e}"})
    return {"project": plan.project, "freed_bytes": freed, "done": done, "skipped": skipped,
            "n_done": len(done), "n_skipped": len(skipped)}


def project_usage(project_dir: Path, keep_recent: int = KEEP_RECENT_JOBS) -> dict[str, Any]:
    """What the project home shows: sizes by category + what a cleanup would
    reclaim (dry run), in one call."""
    usage = measure_project(project_dir)
    plan = plan_cleanup(project_dir, keep_recent=keep_recent)
    usage["reclaimable_bytes"] = plan.reclaimable_bytes
    usage["reclaimable_by_kind"] = plan.summary()["by_kind"]
    usage["n_actions"] = len(plan.actions)
    return usage
