"""Build a SHELX HKLF5 file from DIALS two-lattice integration of the
o-nitroaniline twin.

Semantics (SHELX HKLF 5): one observation = one or more component rows;
all rows but the last carry a NEGATIVE batch number; the last row (batch
+1) carries the observed intensity. BASF k gives component-2's fraction.

Construction from per-domain integration:
- domain-2 reflection h2 falls at continuous domain-1 index t = T.h2
  (T = A1^-1 R A1). |t - round(t)|_max < TOL -> overlapped with domain-1
  reflection h1 = round(t): write rows (h2, -2) + (h1, +1), intensity =
  domain-1 merged I(h1) (the integration box contains both domains'
  counts; domain-2's separate integration of the same pixels is dropped
  to avoid double counting).
- otherwise pure domain-2: single row (h2, +2) with its own intensity.
- domain-1 reflections never claimed by an overlap: single row (h1, +1).

Everything is finally re-expressed in the conventional-cell basis (the
same beta=105.3 setting the single-lattice export used) via an index
transform C chosen so the transformed cell matches.
"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TOL = float(__import__("os").environ.get("HKLF5_TOL", "0.15"))
CONV = (8.359, 10.092, 15.096, 90.0, 105.33, 90.0)   # target cell


def load():
    from dials.array_family import flex           # noqa: F401
    from dxtbx.model.experiment_list import ExperimentList
    import pickle  # noqa: F401

    for refl_name in ("scaled.refl", "integrated.refl"):
        if (HERE / refl_name).exists():
            break
    expt_name = {"scaled.refl": "scaled.expt",
                 "integrated.refl": "integrated.expt"}[refl_name]
    el = ExperimentList.from_file(str(HERE / expt_name), check_format=False)
    from dials.array_family.flex import reflection_table
    rt = reflection_table.from_file(str(HERE / refl_name))
    return el, rt, refl_name


def domain_map(el):
    """Cluster per-experiment crystals into the two twin domains by
    U-matrix similarity (refinement/serialization splits shared models)."""
    def ang(Ua, Ub):
        c = (np.trace(Ua @ Ub.T) - 1.0) / 2.0
        return np.degrees(np.arccos(np.clip(c, -1, 1)))

    Us = [np.array(e.crystal.get_U()).reshape(3, 3) for e in el]
    ref = [Us[0]]
    m = {0: 0}
    for i in range(1, len(el)):
        for d, Ur in enumerate(ref):
            if ang(Us[i], Ur) < 30.0:
                m[i] = d
                break
        else:
            ref.append(Us[i])
            m[i] = len(ref) - 1
    assert len(ref) == 2, f"expected 2 domains, got {len(ref)}"
    i1 = next(i for i, d in m.items() if d == 0)
    i2 = next(i for i, d in m.items() if d == 1)
    A1 = np.array(el[i1].crystal.get_A()).reshape(3, 3)
    U1, U2 = Us[i1], Us[i2]
    R = U2 @ U1.T
    T = np.linalg.inv(A1) @ R @ A1
    cell = el[i1].crystal.get_unit_cell().parameters()
    return m, T, cell


def pick_cb(el, dmap):
    """Exact index transform C from THIS run's domain-1 basis to the main
    chain's export basis (the basis the refined model lives in): both
    index the same physical lattice, so A_chain.h_chain = A_mine.h_mine
    => C = A_chain^-1 A_mine, integer unimodular. Cell-parameter matching
    alone is NOT safe (a diagonal flip can look right and scramble
    monoclinic intensity equivalence)."""
    from dxtbx.model.experiment_list import ExperimentList
    chain = ExperimentList.from_file(
        "H:/CrystalPilot/workbench/r5-onitwin/.crystalpilot/frames/"
        "scaled.expt", check_format=False)
    Ac = np.array(chain[0].crystal.get_A()).reshape(3, 3)
    i1 = next(i for i, d in dmap.items() if d == 0)
    Am = np.array(el[i1].crystal.get_A()).reshape(3, 3)
    Craw = np.linalg.inv(Ac) @ Am
    C = np.round(Craw)
    dev = float(np.abs(Craw - C).max())
    det = float(np.linalg.det(C))
    assert abs(abs(det) - 1.0) < 0.05, f"C not unimodular: det={det}"
    p = chain[0].crystal.get_unit_cell().parameters()
    return dev, f"exact({C.astype(int).tolist()})", C, p


def main():
    el, rt, src = load()
    dmap, T, cell = domain_map(el)
    print(f"source={src} n_expts={len(el)} cell={[round(x,3) for x in cell]}")
    print("T=\n", np.round(T, 4))

    dev, cb_name, C, newp = pick_cb(el, dmap)
    print(f"cb={cb_name} -> chain cell {[round(x,2) for x in newp]} "
          f"(int dev {dev:.3f})")

    # intensity selection
    from dials.array_family import flex
    good = rt.get_flags(rt.flags.integrated_sum)
    rt = rt.select(good)
    if "intensity.scale.value" in rt and src == "scaled.refl":
        i_col, v_col = "intensity.scale.value", "intensity.scale.variance"
        scaled = True
    else:
        i_col, v_col = "intensity.sum.value", "intensity.sum.variance"
        scaled = False
    sel = rt[v_col] > 0
    if "partiality" in rt:
        sel &= rt["partiality"] > 0.4
    rt = rt.select(sel)
    print(f"n_obs={len(rt)} scaled={scaled}")

    # merge per (domain, hkl)
    acc: dict[tuple, list] = {}
    ids = rt["id"]
    mil = rt["miller_index"]
    ival = rt[i_col]
    ivar = rt[v_col]
    for i in range(len(rt)):
        d = dmap[ids[i]]
        key = (d, tuple(mil[i]))
        w = 1.0 / max(float(ivar[i]), 1e-9)
        e = acc.setdefault(key, [0.0, 0.0])
        e[0] += w * float(ival[i])
        e[1] += w
    merged = {k: (sw / w, (1.0 / w) ** 0.5) for k, (sw, w) in acc.items()}
    n1 = sum(1 for (d, _) in merged if d == 0)
    n2 = sum(1 for (d, _) in merged if d == 1)
    print(f"unique domain1={n1} domain2={n2}")

    # overlap classification for domain-2
    rows = []          # (h_tuple, I, sig, batch) ; negative batch = not last
    used_h1 = set()
    n_comp = n_pure2 = 0
    devs = []
    for (d, h2), (I2, s2) in merged.items():
        if d != 1:
            continue
        t = T @ np.array(h2, float)
        r = np.round(t)
        dev = float(np.max(np.abs(t - r)))
        devs.append(dev)
        h1 = tuple(int(x) for x in r)
        if dev < TOL and (0, h1) in merged:
            I1, s1 = merged[(0, h1)]
            rows.append((h2, I1, s1, -2))
            rows.append((h1, I1, s1, 1))
            used_h1.add(h1)
            n_comp += 1
        else:
            rows.append((h2, I2, s2, 2))
            n_pure2 += 1
    n_pure1 = 0
    for (d, h1), (I1, s1) in merged.items():
        if d != 0 or h1 in used_h1:
            continue
        rows.append((h1, I1, s1, 1))
        n_pure1 += 1
    print(f"composite={n_comp} pure1={n_pure1} pure2={n_pure2}")
    print("overlap |t-round| percentiles:",
          np.percentile(devs, [10, 50, 90]).round(3).tolist())

    # transform to conventional basis + scale + write
    peak = max(r[1] for r in rows)
    scale = 1.0
    while peak * scale > 9999.99:
        scale /= 10.0
    out = HERE / "onitwin_hklf5.hkl"
    with out.open("w", newline="\n") as f:
        for h, I, s, b in rows:
            hc = C @ np.array(h, float)
            hi = [int(round(x)) for x in hc]
            f.write(f"{hi[0]:4d}{hi[1]:4d}{hi[2]:4d}"
                    f"{I * scale:8.2f}{max(s, 0.01) * scale:8.2f}{b:4d}\n")
        f.write(f"{0:4d}{0:4d}{0:4d}{0.0:8.2f}{0.0:8.2f}{0:4d}\n")
    stats = {"source": src, "scaled": scaled, "cb": cb_name,
             "n_composite": n_comp, "n_pure_domain1": n_pure1,
             "n_pure_domain2": n_pure2, "scale": scale,
             "tol": TOL, "file": str(out)}
    (HERE / "hklf5_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
