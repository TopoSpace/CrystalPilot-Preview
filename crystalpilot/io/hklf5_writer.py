"""Compose SHELX HKLF5 twin data from two independently scaled DIALS
domains (the r15/p770-validated pipeline, see docs/AUDIT-2026-08.md).

Run as a SCRIPT with the DIALS environment python (reflection tables need
dials.array_family); the classification / composition core is pure numpy
so the repo venv can unit-test it without DIALS.

Physics / conventions (hard-won, do not "simplify"):

* Overlap classes come from predicted-centroid proximity per sweep:
  - coincident (< tight): the measured blob covers both domains' spots;
    written as a composite record - minor-domain line with batch -2,
    then the major-domain line carrying the blob intensity with batch 1
    (SHELXL reads intensity from the last, positive-batch line).
  - partial (tight..wide): mutually contaminated. partial_policy="drop"
    discards them (counted, disclosed); partial_policy="composite"
    pairs each partial A row with its nearest B row (globally greedy,
    exclusive) and writes a composite record carrying the A measurement
    as the blob estimate - the same convention as the coincident class.
    E1 evidence (p770 probe, 2026-08-31): at p50 pair separation 3.4 px
    the A shoebox holds most of both peaks, so the blob approximation
    costs little (R1 0.067->0.071 on combine-scaled data) while SHELXL's
    _diffrn_measured_fraction_theta_full rises 0.579->0.799 (0.991 on
    profile-rescaled data) - SHELXL counts ONLY batch-1 lines there, so
    partial composites are the one lever that moves reported
    completeness; minor singles (batch 3 or 2) never do. Known bias:
    the blob estimate undercounts the minor tail, so refined BASF reads
    low (0.11 -> ~0.05 on p770) - disclose that BASF from a composite-
    partial file underestimates the twin fraction.
  - clean: single-domain lines.
* Each domain's hkl stays in ITS OWN indexing frame - that is exactly
  what HKLF5 means (both frames index the same structure's lattice).
* The two domains are scaled by dials.scale SEPARATELY (the multi-crystal
  scaler is not needed), so their absolute scales are arbitrary. Minor
  singles therefore go to batch 3, whose free BASF absorbs the unknown
  scale x minor fraction product; composites keep batches 1/-2 so BASF 1
  refines to the true twin fraction on the major domain's scale.
* Minor-singles policy:
  - "none": best-R1 optics; minor data only via composites.
  - "coverage": include minor singles ONLY for unique reflections absent
    from the major+composite set. Selection is by hkl identity, never by
    intensity - statistically neutral, no cherry-picking bias.
  - "all": maximum completeness, weakest R1 optics (minor domain data is
    intrinsically weak); honest but needs disclosure.
"""
from __future__ import annotations

import json
from typing import Sequence

import numpy as np

TIGHT_XY, TIGHT_Z = 2.0, 1.0
WIDE_XY, WIDE_Z = 6.0, 3.0

#: classification codes
CLEAN, COINCIDENT, PARTIAL = 0, 1, 2


def classify_overlaps(xyz_a: np.ndarray, id_a: np.ndarray,
                      xyz_b: np.ndarray, id_b: np.ndarray,
                      tight_xy: float = TIGHT_XY, tight_z: float = TIGHT_Z,
                      wide_xy: float = WIDE_XY, wide_z: float = WIDE_Z):
    """Per-sweep proximity classification of domain-A vs domain-B spots.

    xyz_* are predicted centroids (x_px, y_px, frame); id_* the sweep
    index of each row (same sweep numbering for both domains). Returns
    (class_a, class_b, match_b_for_a) with codes CLEAN/COINCIDENT/PARTIAL
    and, for each coincident A row, the paired B row index (else -1).
    A B row is claimed by at most one A row (first-nearest wins).
    """
    class_a = np.zeros(len(xyz_a), dtype=int)
    class_b = np.zeros(len(xyz_b), dtype=int)
    match_b_for_a = np.full(len(xyz_a), -1, dtype=int)
    for sweep in sorted(set(id_a.tolist()) | set(id_b.tolist())):
        ia = np.where(id_a == sweep)[0]
        ib = np.where(id_b == sweep)[0]
        if not len(ia) or not len(ib):
            continue
        xb = xyz_b[ib]
        order = np.argsort(xb[:, 2])
        ibs = ib[order]
        xbs = xb[order]
        bz = xbs[:, 2]
        for i in ia:
            x, y, z = xyz_a[i]
            lo = int(np.searchsorted(bz, z - wide_z))
            hi = int(np.searchsorted(bz, z + wide_z))
            if lo == hi:
                continue
            dxy = np.hypot(xbs[lo:hi, 0] - x, xbs[lo:hi, 1] - y)
            dz = np.abs(bz[lo:hi] - z)
            tight = (dxy < tight_xy) & (dz < tight_z)
            wide = (dxy < wide_xy) & (dz < wide_z)
            if tight.any():
                arg = int(np.argmin(np.where(tight, dxy, np.inf)))
                gb = int(ibs[lo + arg])          # window-relative -> global
                if class_b[gb] == COINCIDENT:
                    class_a[i] = PARTIAL         # B already claimed
                    continue
                class_a[i] = COINCIDENT
                match_b_for_a[i] = gb
                class_b[gb] = COINCIDENT
            elif wide.any():
                class_a[i] = PARTIAL
                for jj in np.where(wide)[0]:
                    gb = int(ibs[lo + jj])
                    if class_b[gb] == CLEAN:
                        class_b[gb] = PARTIAL
    return class_a, class_b, match_b_for_a


def pair_partials(xyz_a: np.ndarray, id_a: np.ndarray,
                  xyz_b: np.ndarray, id_b: np.ndarray,
                  class_a: np.ndarray, match_b_for_a: np.ndarray,
                  wide_xy: float = WIDE_XY, wide_z: float = WIDE_Z):
    """Exclusive globally-greedy pairing of PARTIAL A rows to B rows.

    B rows already claimed as coincident partners stay unavailable; each
    B row backs at most one composite. Returns per-A-row B index or -1.
    """
    used_b = np.zeros(len(xyz_b), dtype=bool)
    used_b[match_b_for_a[match_b_for_a >= 0]] = True
    cands: list[tuple[float, int, int]] = []
    for sweep in sorted(set(id_a.tolist()) | set(id_b.tolist())):
        ia = np.where((id_a == sweep) & (class_a == PARTIAL))[0]
        ib = np.where(id_b == sweep)[0]
        if not len(ia) or not len(ib):
            continue
        xb = xyz_b[ib]
        order = np.argsort(xb[:, 2])
        ibs = ib[order]
        xbs = xb[order]
        bz = xbs[:, 2]
        for i in ia:
            x, y, z = xyz_a[i]
            lo = int(np.searchsorted(bz, z - wide_z))
            hi = int(np.searchsorted(bz, z + wide_z))
            if lo == hi:
                continue
            dxy = np.hypot(xbs[lo:hi, 0] - x, xbs[lo:hi, 1] - y)
            dz = np.abs(bz[lo:hi] - z)
            okm = (dxy < wide_xy) & (dz < wide_z)
            for jj in np.where(okm)[0]:
                cands.append((float(dxy[jj]), int(i), int(ibs[lo + jj])))
    cands.sort()
    pc = np.full(len(xyz_a), -1, dtype=int)
    for _, i, j in cands:
        if pc[i] >= 0 or used_b[j]:
            continue
        pc[i] = j
        used_b[j] = True
    return pc


def _rec(h: Sequence[int], i: float, s: float, batch: int) -> str:
    return f"{h[0]:4d}{h[1]:4d}{h[2]:4d}{i:8.2f}{s:8.2f}{batch:4d}\n"


def _rec4(h: Sequence[int], i: float, s: float) -> str:
    return f"{h[0]:4d}{h[1]:4d}{h[2]:4d}{i:8.2f}{s:8.2f}\n"


def compose_hklf5(h_a, i_a, s_a, class_a, match_b_for_a,
                  h_b, i_b, s_b, class_b,
                  minor_keep: np.ndarray | None,
                  pc_match: np.ndarray | None = None):
    """Return (hklf5_lines, major_clean_lines, counts).

    minor_keep: boolean mask over B rows selected by the singles policy
    (None = policy "none"). pc_match: per-A-row paired B index for the
    partial-composite mode (None = drop partials). Intensities are
    divided by a common factor so the strongest fits the F8.2 field.
    """
    pc = pc_match if pc_match is not None \
        else np.full(len(h_a), -1, dtype=int)
    keep_a = (class_a != PARTIAL) | (pc >= 0)
    all_i = [np.abs(i_a[keep_a])]
    if minor_keep is not None and minor_keep.any():
        all_i.append(np.abs(i_b[minor_keep & (class_b == CLEAN)]))
    peak = max(float(np.max(x)) if len(x) else 0.0 for x in all_i)
    k = max(1.0, peak / 99000.0)

    lines: list[str] = []
    major: list[str] = []
    n_comp = n_pc = n_a_clean = n_b_single = 0
    for i in range(len(h_a)):
        if class_a[i] == PARTIAL:
            if pc[i] >= 0:  # partial composite: A measurement ~ blob
                j = int(pc[i])
                lines.append(_rec(h_b[j], i_a[i] / k, s_a[i] / k, -2))
                lines.append(_rec(h_a[i], i_a[i] / k, s_a[i] / k, 1))
                n_pc += 1
            continue
        if class_a[i] == COINCIDENT:
            j = int(match_b_for_a[i])
            lines.append(_rec(h_b[j], i_a[i] / k, s_a[i] / k, -2))
            lines.append(_rec(h_a[i], i_a[i] / k, s_a[i] / k, 1))
            n_comp += 1
        else:
            lines.append(_rec(h_a[i], i_a[i] / k, s_a[i] / k, 1))
            major.append(_rec4(h_a[i], i_a[i] / k, s_a[i] / k))
            n_a_clean += 1
    pc_used_b = set(int(j) for j in pc[pc >= 0])
    if minor_keep is not None:
        for j in range(len(h_b)):
            if class_b[j] == CLEAN and minor_keep[j] and j not in pc_used_b:
                lines.append(_rec(h_b[j], i_b[j] / k, s_b[j] / k, 3))
                n_b_single += 1
    lines.append(_rec((0, 0, 0), 0.0, 0.0, 0))
    major.append(_rec4((0, 0, 0), 0.0, 0.0))
    n_part_a = int((class_a == PARTIAL).sum())
    n_pc_b_partial = sum(1 for j in pc_used_b if class_b[j] == PARTIAL)
    counts = {
        "composites": n_comp,
        "pc_composites": n_pc,
        "major_clean": n_a_clean,
        "minor_singles_written": n_b_single,
        "major_partial_dropped": n_part_a - n_pc,
        "minor_partial_dropped":
            int((class_b == PARTIAL).sum()) - n_pc_b_partial,
        "minor_clean_available": int((class_b == CLEAN).sum()),
        "intensity_divisor": round(k, 4),
        "n_batches": 3 if n_b_single else 2,
    }
    return lines, major, counts


def main(argv: list[str]) -> int:
    """DIALS-env entry: read scaled refl pairs, classify, write files.

    argv: workdir tight_xy tight_z wide_xy wide_z policy cell6(comma) sg
          [partial_policy]
    partial_policy: "drop" (default) or "composite" (pair partials and
    write them as composite records; see module docstring for evidence).
    Reads  <workdir>/twin_scaledA.refl / twin_scaledB.refl
    Writes <workdir>/twin5.hkl, twin_major_clean.hkl, twin5_report.json
    """
    from pathlib import Path

    from dials.array_family import flex

    wd = Path(argv[0])
    tight_xy, tight_z, wide_xy, wide_z = (float(x) for x in argv[1:5])
    policy = argv[5]
    cell = tuple(float(x) for x in argv[6].split(","))
    sg_symbol = argv[7]
    partial_policy = argv[8] if len(argv) > 8 else "drop"

    def load(path):
        r = flex.reflection_table.from_file(str(path))
        ok = r.get_flags(r.flags.scaled)
        bad = r.get_flags(r.flags.excluded_for_scaling) | \
            r.get_flags(r.flags.outlier_in_scaling)
        return r.select(ok & ~bad)

    ra = load(wd / "twin_scaledA.refl")
    rb = load(wd / "twin_scaledB.refl")

    def cols(r):
        return (np.array(r["miller_index"], dtype=int),
                np.array(r["id"], dtype=int),
                np.array(r["xyzcal.px"]),
                np.array(r["intensity.scale.value"]),
                np.sqrt(np.abs(np.array(r["intensity.scale.variance"]))))

    h_a, id_a, x_a, i_a, s_a = cols(ra)
    h_b, id_b, x_b, i_b, s_b = cols(rb)
    class_a, class_b, match = classify_overlaps(
        x_a, id_a, x_b, id_b, tight_xy, tight_z, wide_xy, wide_z)
    pc_match = None
    if partial_policy == "composite":
        pc_match = pair_partials(x_a, id_a, x_b, id_b, class_a, match,
                                 wide_xy, wide_z)

    minor_keep = None
    n_extra_unique = 0
    if policy == "all":
        minor_keep = np.ones(len(h_b), dtype=bool)
    elif policy == "coverage":
        from cctbx import crystal, miller
        from cctbx.array_family import flex as cflex
        cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg_symbol)

        def asu_set(idx):
            ms = miller.set(cs, cflex.miller_index(
                [tuple(int(v) for v in row) for row in idx]),
                anomalous_flag=False)
            return set(ms.map_to_asu().indices())

        cov_blocks = [h_a[class_a == CLEAN], h_a[class_a == COINCIDENT]]
        if pc_match is not None:
            pc_rows = np.where((class_a == PARTIAL) & (pc_match >= 0))[0]
            if len(pc_rows):
                cov_blocks += [h_a[pc_rows], h_b[pc_match[pc_rows]]]
        cov_major = asu_set(np.concatenate(cov_blocks)) \
            if len(h_a) else set()
        keep = np.zeros(len(h_b), dtype=bool)
        clean_rows = np.where(class_b == CLEAN)[0]
        if len(clean_rows):
            ms = miller.set(cs, cflex.miller_index(
                [tuple(int(v) for v in h_b[j]) for j in clean_rows]),
                anomalous_flag=False)
            asu = list(ms.map_to_asu().indices())
            extra_uniques = set()
            for row, u in zip(clean_rows, asu):
                if u not in cov_major:
                    keep[row] = True
                    extra_uniques.add(u)
            n_extra_unique = len(extra_uniques)
        minor_keep = keep

    lines, major, counts = compose_hklf5(
        h_a, i_a, s_a, class_a, match, h_b, i_b, s_b, class_b, minor_keep,
        pc_match)
    (wd / "twin5.hkl").write_text("".join(lines), encoding="ascii",
                                  newline="\n")
    (wd / "twin_major_clean.hkl").write_text("".join(major),
                                             encoding="ascii", newline="\n")
    counts["policy"] = policy
    counts["partial_policy"] = partial_policy
    if policy == "coverage":
        counts["coverage_extra_uniques"] = n_extra_unique
    counts["n_scaled_major"] = int(len(ra))
    counts["n_scaled_minor"] = int(len(rb))
    (wd / "twin5_report.json").write_text(json.dumps(counts, indent=1),
                                          encoding="ascii")
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
