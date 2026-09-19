# Two-lattice HKLF5 experiment (round 5, o-nitroaniline twin)

Deterministic rung-2 twin treatment on the IUCrData RDL benchmark set
(Zenodo 7193538, non-merohedral 2-domain twin; published ladder: naive
R1 0.0678 → PLATON-HKLF5 0.0465 → EVAL15 joint integration best).

Pipeline (scratch run in workdir/onitwin_2latt, scripts preserved here):

1. `dials.index imported.expt strong.refl max_lattices=2 joint_indexing=True`
   → both domains, 99.0–99.4 % indexed (single lattice: 86.9 %);
   DIALS reports the domain relation: 179.992° about lab (0.919,0.254,0.301).
2. `twinlaw.py` → hkl-space law T = A1⁻¹·R·A1 =
   [[1,0,0],[0,−1,0],[0.9553,0,−1]] (twin_law.json); the 0.045·|h|
   integer deviation IS the non-merohedral fingerprint.
3. dials.refine (14 expts, RMSD 0.10–0.15 px) → dials.integrate (61,940
   refl) → dials.scale model=KB reflection_selection.method=intensity_ranges
   cut_data.d_min=0.69 (both extra args = Windows scipy-crash workarounds,
   see ROUND5_NOTES).
4. `make_hklf5.py` (HKLF5_TOL=0.10): merge per (domain, hkl); domain-2
   reflection overlaps domain-1 when |T·h₂ − round| < tol → composite
   rows (h₂, −2)+(h₁, +1) carrying domain-1's box intensity; else pure
   row (h₂, +2). Exact basis map C = A_chain⁻¹·A_scratch (never trust
   cell-parameter matching alone).
5. SHELXL vs the agent's naive P2₁ model (L.S. 20, osf re-estimated):

   | dataset | R1(>4σ) | wR2 | BASF |
   |---|---|---|---|
   | naive single-domain (agent run) | 0.0812 | 0.3063 | – |
   | HKLF5 tol 0.10 (this) | 0.1066 | 0.3235 | **0.2214** |

   BASF converges to the physics: median I(pure dom-2)/I(pure dom-1
   equivalents) = 0.295 = k/(1−k) → k = 0.228 (independent of SHELXL).

Conclusions:
- The deterministic two-lattice → HKLF5 → BASF pipeline works end to end
  (semantics validated; BASF refines to the physical fraction).
- v1 does NOT yet beat the naive R1: (near-)overlapped spots are still
  integrated with single-domain boxes, so composite intensities are
  contaminated — exactly the RDL's conclusion that joint (EVAL15-style)
  integration is superior. Next rung: joint profile deconvolution.
- Anti-lesson: widening the overlap tolerance "improves" R1 (0.077 at
  tol 0.35) while BASF collapses to 0.065 — that is the minor domain
  being discarded, not modelled. Do not chase that R1.

Files: make_hklf5.py, twinlaw.py, twin_law.json, hklf5_stats.json,
shelxl_hklf5_test.py, refined_tol010.res/.lst, index2.log.
