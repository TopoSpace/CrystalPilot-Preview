"""Automatic space-group determination (XPREP-like) for CrystalPilot.

Input: unmerged intensity data (e.g. SHELX HKLF4) + unit cell + wavelength,
with NO symmetry assumed beyond what the cell implies.

Pipeline (standard XPREP/pointless-style approach, built on cctbx):
  1. Metric (lattice) symmetry of the unit cell
     -> cctbx.sgtbx.lattice_symmetry.metric_subgroups (bravais_types_only=False)
        gives every Laue subgroup of the lattice group, each with a
        change-of-basis to its conventional "best" cell.
  2. Laue-group scan: for each candidate, reindex the unmerged data and merge
     equivalents under the (centric) Laue group -> R_int.  The correct Laue
     group is the highest-order group whose R_int is still low.
  3. Lattice centering (A/B/C/I/F/R) from systematic absences of the whole
     data set in the chosen Laue setting.  Handles both "absent reflections
     measured as ~0" and "absent reflections pre-filtered from the file".
  4. Candidate space groups: every setting in sgtbx.space_group_symbol_iterator
     (530 ITA settings, i.e. all orientations) whose derived reflection
     intensity group equals the observed one (Laue group + centering).
  5. Translational-element scoring: per candidate, a mixture-model
     log-likelihood over normalized intensities z = (I/eps)/<I/eps>_shell of
     all reflections that are systematically absent in at least one candidate.
     This is robust against lambda/2 / multiple-diffraction contamination of
     "absent" reflections (small I but large I/sigma).
  6. Centro/non-centro evidence: <|E^2-1|> (0.736 acentric / 0.968 centric)
     used as a weighted tie-breaker between e.g. Cc and C2/c.

Main entry point: determine_space_group(miller_array_unmerged, ...)
Run as a script to validate against three real data sets (see __main__).
"""
from __future__ import absolute_import, division, print_function

import math

from cctbx import crystal, sgtbx
from cctbx.array_family import flex
from cctbx.sgtbx import change_of_basis_op, lattice_symmetry


# ----------------------------------------------------------------------------
# data input helpers
# ----------------------------------------------------------------------------

def read_shelx_hkl(hkl_path, unit_cell, wavelength=None):
  """Read a SHELX HKLF4 file as an unmerged intensity miller array in P1."""
  from iotbx.shelx import hklf
  cs = crystal.symmetry(unit_cell=unit_cell, space_group_symbol="P 1")
  arr = hklf.reader(file_name=hkl_path).as_miller_arrays(crystal_symmetry=cs)[0]
  arr.set_observation_type_xray_intensity()
  info = arr.info()
  if info is not None:
    arr.set_info(info.customized_copy(wavelength=wavelength))
  return arr


# ----------------------------------------------------------------------------
# step 1+2: metric symmetry and Laue-group scan
# ----------------------------------------------------------------------------

def laue_group_scan(unmerged, max_delta=3.0):
  """Merge the data under every Laue subgroup of the lattice symmetry.

  Returns a list of dicts sorted by decreasing group order then R_int.
  """
  input_symmetry = crystal.symmetry(
    unit_cell=unmerged.unit_cell(), space_group_symbol="P 1")
  subs = lattice_symmetry.metric_subgroups(
    input_symmetry=input_symmetry, max_delta=max_delta,
    bravais_types_only=False)
  data = unmerged.customized_copy(anomalous_flag=False)
  results = []
  for item in subs.result_groups:
    best = item["best_subsym"]           # centric (Laue) group, best cell
    cb = item["cb_op_inp_best"]          # input setting -> best setting
    reindexed = data.change_basis(cb).customized_copy(
      crystal_symmetry=best).map_to_asu()
    merger = reindexed.merge_equivalents()
    merged = merger.array()
    n_unique = merged.size()
    r_int = merger.r_int()
    multiplicity = data.size() / max(1, n_unique)
    results.append(dict(
      laue_group=str(best.space_group_info()),
      laue_symmetry=best,
      cb_op_inp_best=cb,
      order=best.space_group().order_p(),
      r_int=r_int,
      n_unique=n_unique,
      multiplicity=multiplicity,
      max_angular_difference=item["max_angular_difference"],
      cell=best.unit_cell().parameters(),
    ))
  results.sort(key=lambda d: (-d["order"], d["r_int"]))
  return results


def choose_laue_group(scan, r_abs_min=0.06, r_rel=1.3, r_add=0.04):
  """Highest-order Laue group with acceptable R_int (XPREP-style heuristic).

  The reference is the lowest R_int in the scan (~P-1): merging in the true
  Laue group should cost only a little extra R_int relative to that, whatever
  the absolute data quality is.
  """
  r_ref = min(d["r_int"] for d in scan)          # ~ R_int under P-1
  threshold = max(r_abs_min, r_rel * r_ref + r_add)
  acceptable = [d for d in scan if d["r_int"] <= threshold]
  if not acceptable:                              # fall back to lowest R_int
    acceptable = [min(scan, key=lambda d: d["r_int"])]
  best_order = max(d["order"] for d in acceptable)
  chosen = min((d for d in acceptable if d["order"] == best_order),
               key=lambda d: d["r_int"])
  for d in scan:
    d["accepted"] = d["r_int"] <= threshold
  return chosen, threshold


# ----------------------------------------------------------------------------
# step 3: lattice centering from systematic absences
# ----------------------------------------------------------------------------

_CENTERING_TESTS = {
  "A": lambda h: (h[1] + h[2]) % 2 != 0,
  "B": lambda h: (h[0] + h[2]) % 2 != 0,
  "C": lambda h: (h[0] + h[1]) % 2 != 0,
  "I": lambda h: (h[0] + h[1] + h[2]) % 2 != 0,
  "R_obv": lambda h: (-h[0] + h[1] + h[2]) % 3 != 0,
  "R_rev": lambda h: (h[0] - h[1] + h[2]) % 3 != 0,
}

_CENTERING_VECTORS = {   # tr_vec with denominator 12
  "A": [(0, 6, 6)],
  "B": [(6, 0, 6)],
  "C": [(6, 6, 0)],
  "I": [(6, 6, 6)],
  "F": [(0, 6, 6), (6, 0, 6)],
  "R_obv": [(8, 4, 4)],
}

_FAMILY_TESTS = {
  "Triclinic": [],
  "Monoclinic": ["A", "C", "I"],
  "Orthorhombic": ["A", "B", "C", "I"],
  "Tetragonal": ["I"],
  "Trigonal": ["R_obv", "R_rev"],
  "Hexagonal": ["R_obv", "R_rev"],
  "Cubic": ["I", "F"],
}


def _centering_class_stats(indices, i_over_sig, rel_i, test, isig_cut):
  n_all = len(indices)
  in_class = [i for i, h in enumerate(indices) if test(h)]
  n_class = len(in_class)
  n_rest = n_all - n_class
  if n_class == 0:
    return dict(n_class=0, n_rest=n_rest, frac_measured=0.0,
                mean_isig=0.0, mean_rel_i=0.0, frac_strong=0.0)
  isig = [i_over_sig[i] for i in in_class]
  ri = [rel_i[i] for i in in_class]
  n_strong = sum(1 for i in in_class
                 if i_over_sig[i] > isig_cut and rel_i[i] > 0.02)
  return dict(
    n_class=n_class, n_rest=n_rest,
    frac_measured=n_class / max(1, n_rest),   # ~1 if class fully measured
    mean_isig=sum(isig) / n_class,
    mean_rel_i=sum(ri) / n_class,
    frac_strong=n_strong / n_class,
  )


def detect_centering(unmerged_best, laue_symmetry, isig_cut=3.0):
  """Detect lattice centering from absences in the chosen Laue setting.

  A centering condition is accepted when the violating reflection class is
  either essentially not present in the file (pre-filtered by data
  processing) or present but systematically weak (relative intensity).
  Returns (letter, details) where letter is one of P/A/B/C/I/F/R_obv/R_rev.
  """
  family = laue_symmetry.space_group().crystal_system()
  tests = _FAMILY_TESTS.get(family, [])
  indices = list(unmerged_best.indices())
  data = unmerged_best.data()
  sigmas = unmerged_best.sigmas()
  mean_i = flex.mean(data) if data.size() else 1.0
  mean_i = max(abs(mean_i), 1e-9)
  i_over_sig = [(d / s if s > 0 else 0.0) for d, s in zip(data, sigmas)]
  rel_i = [d / mean_i for d in data]

  details = {}
  supported = []
  for letter in tests:
    st = _centering_class_stats(
      indices, i_over_sig, rel_i, _CENTERING_TESTS[letter], isig_cut)
    missing = st["frac_measured"] < 0.05
    weak = (st["n_class"] > 0 and st["frac_strong"] < 0.05
            and st["mean_rel_i"] < 0.05)
    st["supported"] = bool(missing or weak)
    st["inferred_from_missing"] = bool(missing and st["n_class"] == 0)
    details[letter] = st
    if st["supported"]:
      supported.append(letter)

  # combine to a single centering type (most restrictive consistent choice)
  abc = [x for x in ("A", "B", "C") if x in supported]
  if len(abc) == 3:
    letter = "F"
  elif "R_obv" in supported and "R_rev" in supported:
    # both fit => data probably already merged in a lower symmetry or
    # hexagonal cell with P lattice mis-flagged; prefer obverse
    letter = "R_obv"
  elif supported:
    # prefer body/face over single-face if multiple fit (rare)
    for pref in ("I", "R_obv", "R_rev", "C", "B", "A"):
      if pref in supported:
        letter = pref
        break
  else:
    letter = "P"
  return letter, details


# ----------------------------------------------------------------------------
# step 4+5: candidate space groups and absence scoring
# ----------------------------------------------------------------------------

def build_intensity_group(laue_symmetry, centering):
  """Laue group + centering -> reflection intensity group, plus the
  change-of-basis that brings it (and the data) to its reference setting."""
  group = sgtbx.space_group(laue_symmetry.space_group())
  for tr in _CENTERING_VECTORS.get(centering, []):
    group.expand_ltr(sgtbx.tr_vec(tr, 12))
  gi = sgtbx.space_group_info(group=group)
  cb_ref = gi.change_of_basis_op_to_reference_setting()
  return gi.change_basis(cb_ref).group(), cb_ref


def enumerate_candidates(intensity_group):
  """All ITA settings (530) whose derived intensity group matches exactly.

  Matching concrete groups (not just types) in the common reference setting
  automatically covers alternative orientations, e.g. C2221 / A2122 / B2212
  or the six settings of Amm2.
  """
  out = []
  for symbols in sgtbx.space_group_symbol_iterator():
    group = sgtbx.space_group(symbols)
    if group.build_derived_reflection_intensity_group(False) == intensity_group:
      out.append((symbols, group))
  return out


def _normalized_intensities(merged, n_per_shell=200, z_max=80.0):
  """z = (I/eps)/<I/eps>_shell per unique reflection (quasi-normalized I).

  Shell means are floored at 2% of the overall mean so that pure-noise
  high-resolution shells (mean ~ 0 or < 0) cannot blow z up.
  Returns (z, sig_z, shell_of, shell_isig) as python lists.
  """
  eps = merged.epsilons().data()
  d_star_sq = merged.d_star_sq().data()
  data = merged.data()
  sigmas = merged.sigmas()
  n = data.size()
  order = sorted(range(n), key=lambda i: d_star_sq[i])
  n_shells = max(1, min(60, n // n_per_shell))
  shell_of = [0] * n
  shell_sum = [0.0] * n_shells
  shell_cnt = [0] * n_shells
  shell_isig_sum = [0.0] * n_shells
  for rank, i in enumerate(order):
    s = min(n_shells - 1, rank * n_shells // n)
    shell_of[i] = s
    shell_sum[s] += data[i] / eps[i]
    shell_cnt[s] += 1
    shell_isig_sum[s] += (data[i] / sigmas[i]) if sigmas[i] > 0 else 0.0
  global_mean = max(sum(abs(x) for x in shell_sum) / max(1, n), 1e-9)
  floor = 0.02 * global_mean
  shell_mean = [max(shell_sum[s] / max(1, shell_cnt[s]), floor)
                for s in range(n_shells)]
  shell_isig = [shell_isig_sum[s] / max(1, shell_cnt[s])
                for s in range(n_shells)]
  z, sig_z = [], []
  for i in range(n):
    m = shell_mean[shell_of[i]]
    zi = (data[i] / eps[i]) / m
    z.append(max(-z_max, min(z_max, zi)))
    sig_z.append(min(z_max, (sigmas[i] / eps[i]) / m))
  return z, sig_z, shell_of, shell_isig


def _log_p_absent(z, sig_z, s0=0.04, f_out=0.03):
  """log P(z | reflection systematically absent): Gaussian around 0 with a
  Wilson-acentric contamination floor (robust to lambda/2 etc.)."""
  s = math.sqrt(sig_z * sig_z + s0 * s0)
  gauss = math.exp(-0.5 * (z / s) ** 2) / (math.sqrt(2 * math.pi) * s)
  wilson = math.exp(-max(z, 0.0))
  return math.log((1.0 - f_out) * gauss + f_out * wilson + 1e-300)


def _log_p_present(z, sig_z, s0=0.04, f_weak=0.03):
  """log P(z | reflection present): Wilson acentric with a small near-zero
  component (very weak but real reflections)."""
  s = math.sqrt(sig_z * sig_z + s0 * s0)
  gauss = math.exp(-0.5 * (z / s) ** 2) / (math.sqrt(2 * math.pi) * s)
  wilson = math.exp(-max(z, 0.0))
  return math.log((1.0 - f_weak) * wilson + f_weak * gauss + 1e-300)


def score_candidates(merged, candidates, isig_cut=3.0):
  """Mixture-model absence log-likelihood for each candidate space group.

  Only reflections that are absent in at least one candidate ("conditional
  zones") carry information; all candidates are scored on that common set.
  """
  indices = list(merged.indices())
  data = merged.data()
  sigmas = merged.sigmas()
  z, sig_z, _, _ = _normalized_intensities(merged)

  absent_flags = []
  union = [False] * len(indices)
  for symbols, group in candidates:
    flags = [group.is_sys_absent(h) for h in indices]
    absent_flags.append(flags)
    union = [u or f for u, f in zip(union, flags)]
  info_set = [i for i, u in enumerate(union) if u]

  scored = []
  for (symbols, group), flags in zip(candidates, absent_flags):
    ll = 0.0
    n_absent = 0
    n_viol = 0
    isig_sum = 0.0
    for i in info_set:
      if flags[i]:
        ll += _log_p_absent(z[i], sig_z[i])
        n_absent += 1
        isig = data[i] / sigmas[i] if sigmas[i] > 0 else 0.0
        isig_sum += isig
        if isig > isig_cut and z[i] > 0.02:
          n_viol += 1
      else:
        ll += _log_p_present(z[i], sig_z[i])
    scored.append(dict(
      symbols=symbols, group=group, absence_ll=ll,
      n_absent_measured=n_absent,
      isig_absent=(isig_sum / n_absent if n_absent else 0.0),
      n_absence_violations=n_viol,
      n_informative=len(info_set),
    ))
  return scored, set(info_set)


# ----------------------------------------------------------------------------
# step 5a': "missing-class" evidence for stripped systematic absences
# ----------------------------------------------------------------------------
#
# Merged files (SHELXL fcf LIST 4, IUCr/COD hkl supplements) usually have the
# systematically absent reflections REMOVED, so absences leave no measured
# near-zero intensities -- they leave holes.  Symmetric to the centering
# detection, we compare per candidate the completeness inside its absent
# classes against the baseline completeness of the rest of the data: if the
# data set is otherwise complete but a candidate's absent class is essentially
# not present in the file, the class was culled upstream, which is positive
# evidence for that candidate.

def _effective_d_min(merged, percentile=0.995):
  """d_min ignoring the outermost stray reflections (robust file cutoff)."""
  dss = sorted(merged.d_star_sq().data())
  if not dss:
    return None
  cut = dss[min(len(dss) - 1, int(math.floor(percentile * (len(dss) - 1))))]
  return 1.0 / math.sqrt(max(cut, 1e-12)), cut


def _zone_type(h):
  """2 = axial (00l-type), 1 = zonal (h0l-type), 0 = general."""
  return sum(1 for x in h if x == 0)


def score_missing_classes(merged, candidates, min_completeness=0.75,
                          class_presence_frac=0.25, w_miss_cap=2.0,
                          n_shells=24):
  """Per-candidate log-likelihood bonus for absence classes that are missing
  from the file (culled upstream as systematic absences).

  For each candidate the complete reflection set to the data's d_min is split
  into the candidate's absent classes (separately per zone type: axial /
  zonal / general, so a measured screw-axis row cannot mask a culled glide
  zone or vice versa) and everything else.  A class only earns the bonus when
  the surrounding data are otherwise complete while the class itself has
  near-zero presence (< class_presence_frac of baseline).

  Completeness is judged per resolution shell: only shells whose baseline
  (non-absent-class) completeness reaches max(min_completeness, best-0.1)
  contribute -- this keeps the evidence usable for e.g. charge-density data
  that are complete at low angle but sparse at extreme resolution, without
  mistaking overall incompleteness for absences.  The per-reflection log-odds
  ln(0.9 / (1 - c0)) is capped at w_miss_cap so that a handful of
  cusp-missing axial reflections cannot dominate the measured evidence.

  Returns (per_candidate_list, stats_dict).
  """
  from cctbx import miller
  eff = _effective_d_min(merged)
  empty = [dict(missing_ll=0.0, n_absent_expected=0, n_absent_missing=0)
           for _ in candidates]
  if eff is None:
    return empty, dict(completeness=0.0, gated=False)
  d_min_eff, cut = eff
  complete = miller.build_set(
    crystal_symmetry=merged.crystal_symmetry(), anomalous_flag=False,
    d_min=d_min_eff * 0.9999)
  comp = [(h, ds) for h, ds in zip(complete.indices(),
                                   complete.d_star_sq().data())
          if ds <= cut * 1.0001]
  comp.sort(key=lambda t: t[1])
  comp_idx = [h for h, _ in comp]
  n_comp = len(comp_idx)
  measured = set(merged.indices())

  absent_flags = []
  union = [False] * n_comp
  for symbols, group in candidates:
    flags = [group.is_sys_absent(h) for h in comp_idx]
    absent_flags.append(flags)
    union = [u or f for u, f in zip(union, flags)]

  # per-resolution-shell baseline completeness over non-informative refl.
  n_sh = max(1, min(n_shells, n_comp // 100))
  shell_of = [min(n_sh - 1, i * n_sh // n_comp) for i in range(n_comp)]
  sh_tot = [0] * n_sh
  sh_meas = [0] * n_sh
  for i, (h, u) in enumerate(zip(comp_idx, union)):
    if not u:
      sh_tot[shell_of[i]] += 1
      if h in measured:
        sh_meas[shell_of[i]] += 1
  sh_compl = [sh_meas[s] / max(1, sh_tot[s]) for s in range(n_sh)]
  best = max(sh_compl) if sh_compl else 0.0
  shell_gate = max(min_completeness, best - 0.10)
  keep = [s for s in range(n_sh) if sh_compl[s] >= shell_gate]
  gated = bool(keep) and best >= min_completeness
  kept_tot = sum(sh_tot[s] for s in keep)
  kept_meas = sum(sh_meas[s] for s in keep)
  c0 = kept_meas / max(1, kept_tot)
  w_miss = min(w_miss_cap, math.log(0.9 / max(0.02, 1.0 - c0)))
  keep_set = set(keep)

  # d*^2 intervals of the kept (complete) shells: E-statistics computed there
  # are unbiased by weak-reflection culling / resolution incompleteness
  kept_ranges = []
  for s in keep:
    lo = comp[next(i for i in range(n_comp) if shell_of[i] == s)][1]
    hi = comp[max(i for i in range(n_comp) if shell_of[i] == s)][1]
    kept_ranges.append((lo, hi))

  out = []
  for flags in absent_flags:
    n_tot_all = 0
    n_miss_all = 0
    n_tot = {0: 0, 1: 0, 2: 0}    # counts within kept (complete) shells
    n_meas = {0: 0, 1: 0, 2: 0}
    for i, (h, f) in enumerate(zip(comp_idx, flags)):
      if not f:
        continue
      n_tot_all += 1
      if h not in measured:
        n_miss_all += 1
      if shell_of[i] in keep_set:
        t = _zone_type(h)
        n_tot[t] += 1
        if h in measured:
          n_meas[t] += 1
    missing_ll = 0.0
    if gated:
      for t in (0, 1, 2):
        if n_tot[t] > 0 and \
            n_meas[t] < max(1.0, class_presence_frac * c0 * n_tot[t]):
          missing_ll += w_miss * max(0.0, c0 * n_tot[t] - n_meas[t])
    out.append(dict(
      missing_ll=missing_ll,
      n_absent_expected=n_tot_all,
      n_absent_missing=n_miss_all,
    ))
  return out, dict(completeness=c0, gated=gated, w_miss=w_miss,
                   n_complete=n_comp, d_min_eff=d_min_eff,
                   n_shells=n_sh, n_shells_kept=len(keep),
                   shell_gate=shell_gate,
                   kept_d_star_sq_ranges=kept_ranges)


# ----------------------------------------------------------------------------
# step 5b: centric / acentric statistics
# ----------------------------------------------------------------------------

def e_sq_minus_one(merged, exclude=(), min_shell_isig=1.5,
                   d_star_sq_ranges=None):
  """<|E^2-1|> from quasi-normalized intensities (0.736 acentric /
  0.968 centric).

  Reflections in `exclude` (e.g. potentially systematically absent ones) are
  skipped, as are resolution shells with mean I/sigma below min_shell_isig
  (pure-noise shells push the statistic towards its noise limit of ~1).
  If `d_star_sq_ranges` is given (list of (lo, hi) d*^2 intervals, e.g. the
  resolution ranges where the file is complete), only reflections inside
  those intervals are used: observed-only deposits that cull weak
  reflections otherwise bias the statistic towards 'acentric'."""
  z, _, shell_of, shell_isig = _normalized_intensities(merged)
  exclude = set(exclude)
  in_range = None
  if d_star_sq_ranges:
    dss = merged.d_star_sq().data()
    eps = 1e-9
    in_range = [any(lo - eps <= ds <= hi + eps for lo, hi in d_star_sq_ranges)
                for ds in dss]
  good = [i for i in range(len(z))
          if i not in exclude and shell_isig[shell_of[i]] >= min_shell_isig
          and (in_range is None or in_range[i])]
  if not good:   # data too weak overall -- fall back to everything
    good = [i for i in range(len(z)) if i not in exclude]
  if not good:
    return 0.0
  return sum(abs(z[i] - 1.0) for i in good) / len(good)


def centro_probability(e_stat, lo=0.736, hi=0.968):
  """Map <|E^2-1|> to a (soft) probability that the structure is
  centrosymmetric.

  Values outside the physically meaningful range signal a corrupted
  statistic rather than extreme structure types: below the acentric limit
  (observed-only deposits with the weak tail culled) or far above the
  centric value (hyper-centric artifacts from pseudo-symmetry, disorder or
  twinning).  Such values are demoted to weak evidence (0.25 / 0.75) so the
  centro term cannot override solid absence evidence."""
  if e_stat < lo - 0.04:
    return 0.25   # unphysically uniform -> weakly acentric at best
  if e_stat > hi + 0.10:
    return 0.75   # hyper-centric artifact -> weakly centric at best
  p = (e_stat - lo) / (hi - lo)
  return min(0.95, max(0.05, p))


# ----------------------------------------------------------------------------
# main entry point
# ----------------------------------------------------------------------------

def determine_space_group(miller_array_unmerged,
                          max_delta=3.0,
                          isig_cut=3.0,
                          centro_weight=4.0,
                          top_n=None):
  """Rank candidate space groups for unmerged intensity data.

  Parameters
  ----------
  miller_array_unmerged : cctbx.miller.array
      Unmerged intensities with sigmas; symmetry is ignored (only the unit
      cell is used, data are treated as P1/unknown symmetry).
  max_delta : float
      Angular tolerance (deg) for the metric-symmetry search.
  centro_weight : float
      Weight of the <|E^2-1|> centro/acentro term in the total score.

  Returns
  -------
  dict with keys:
    'laue_scan'   : list of Laue-group candidates with R_int
    'laue_group'  : chosen Laue group entry
    'centering'   : detected centering letter and per-class statistics
    'e_sq_minus_1': <|E^2-1|> statistic
    'completeness': baseline completeness of non-absent classes (drives the
                    missing-class evidence for merged files with stripped
                    absences)
    'candidates'  : ranked list of candidate dicts (best first) with keys
        space_group, sg_number, reference_symbol, hall, laue_group, r_int,
        absence_ll (= absence_ll_measured + missing_ll), missing_ll,
        n_absent_expected, n_absent_missing, n_absent_measured, isig_absent,
        n_absence_violations, centrosymmetric, centro_bonus, total_score,
        cb_op_inp, cell
  """
  assert miller_array_unmerged.sigmas() is not None
  # -- Laue group scan ------------------------------------------------------
  scan = laue_group_scan(miller_array_unmerged, max_delta=max_delta)
  chosen, threshold = choose_laue_group(scan)

  data = miller_array_unmerged.customized_copy(anomalous_flag=False)
  data_best = data.change_basis(chosen["cb_op_inp_best"]).customized_copy(
    crystal_symmetry=chosen["laue_symmetry"])

  # -- centering ------------------------------------------------------------
  centering, centering_details = detect_centering(
    data_best, chosen["laue_symmetry"], isig_cut=isig_cut)
  if centering == "R_rev":  # reindex reverse -> obverse and redo
    cb_rev = change_of_basis_op("-a,-b,c")
    data_best = data_best.change_basis(cb_rev)
    chosen = dict(chosen,
                  cb_op_inp_best=cb_rev * chosen["cb_op_inp_best"])
    centering = "R_obv"

  intensity_group, cb_ref = build_intensity_group(
    chosen["laue_symmetry"], centering)
  cb_op_inp_final = cb_ref * chosen["cb_op_inp_best"]

  # -- data in the final reference setting, merged under intensity group ----
  final_symmetry = crystal.symmetry(
    unit_cell=chosen["laue_symmetry"].change_basis(cb_ref).unit_cell(),
    space_group=intensity_group,
    assert_is_compatible_unit_cell=False)
  data_final = data.change_basis(cb_op_inp_final).customized_copy(
    crystal_symmetry=final_symmetry)
  # reflections absent under the centering cannot be merged/kept: drop them
  data_final = data_final.select(~data_final.sys_absent_flags().data())
  merger = data_final.map_to_asu().merge_equivalents()
  merged = merger.array()

  # -- candidates + scoring -------------------------------------------------
  candidates = enumerate_candidates(intensity_group)
  scored, info_set = score_candidates(merged, candidates, isig_cut=isig_cut)
  # evidence from absence classes stripped from the file (merged fcf etc.)
  missing_scores, missing_stats = score_missing_classes(merged, candidates)

  e_stat = e_sq_minus_one(
    merged, exclude=info_set,
    d_star_sq_ranges=(missing_stats.get("kept_d_star_sq_ranges")
                      if missing_stats.get("gated") else None))
  p_centro = centro_probability(e_stat)

  final_cell = final_symmetry.unit_cell().parameters()
  results = []
  for entry, missing in zip(scored, missing_scores):
    symbols, group = entry["symbols"], entry["group"]
    is_centric = group.is_centric()
    centro_bonus = centro_weight * math.log(
      p_centro if is_centric else (1.0 - p_centro))
    absence_ll = entry["absence_ll"] + missing["missing_ll"]
    results.append(dict(
      space_group=symbols.universal_hermann_mauguin(),
      sg_number=symbols.number(),
      reference_symbol=str(sgtbx.space_group_info(
        symbol=symbols.number()).symbol_and_number()),
      hall=symbols.hall(),
      laue_group=chosen["laue_group"],
      r_int=chosen["r_int"],
      absence_ll=absence_ll,
      absence_ll_measured=entry["absence_ll"],
      missing_ll=missing["missing_ll"],
      n_absent_expected=missing["n_absent_expected"],
      n_absent_missing=missing["n_absent_missing"],
      n_absent_measured=entry["n_absent_measured"],
      isig_absent=entry["isig_absent"],
      n_absence_violations=entry["n_absence_violations"],
      n_informative=entry["n_informative"],
      centrosymmetric=is_centric,
      e_sq_minus_1=e_stat,
      centro_bonus=centro_bonus,
      total_score=absence_ll + centro_bonus,
      cb_op_inp=str(cb_op_inp_final.as_abc()),
      cell=final_cell,
    ))
  # dedupe by space-group type, keeping the best-scoring setting
  best_by_number = {}
  for r in results:
    key = r["sg_number"]
    if key not in best_by_number or \
        r["total_score"] > best_by_number[key]["total_score"]:
      best_by_number[key] = r
  ranked = sorted(best_by_number.values(),
                  key=lambda r: (-r["total_score"], r["sg_number"]))
  if top_n:
    ranked = ranked[:top_n]

  return dict(
    laue_scan=scan,
    laue_threshold=threshold,
    laue_group=chosen,
    centering=dict(letter=centering, details=centering_details),
    e_sq_minus_1=e_stat,
    p_centro=p_centro,
    n_unique=merged.size(),
    completeness=missing_stats.get("completeness"),
    missing_class_stats=missing_stats,
    candidates=ranked,
  )


# ----------------------------------------------------------------------------
# pretty printing / test driver
# ----------------------------------------------------------------------------

def show_result(result, true_sg=None, out=None):
  import sys
  out = out or sys.stdout
  w = out.write
  w("Laue-group scan (R_int threshold %.3f):\n" % result["laue_threshold"])
  for d in result["laue_scan"]:
    w("  %-12s R_int=%7.4f  n_uniq=%6d  mult=%5.2f  delta=%5.2f  cell=%s%s\n"
      % (d["laue_group"], d["r_int"], d["n_unique"], d["multiplicity"],
         d["max_angular_difference"],
         " ".join("%.2f" % x for x in d["cell"]),
         "  <== chosen" if d is result["laue_group"] else
         ("" if d.get("accepted") else "  (rejected)")))
  w("Centering: %s\n" % result["centering"]["letter"])
  for letter, st in sorted(result["centering"]["details"].items()):
    w("  %-6s n_class=%6d frac_meas=%.2f <I/sig>=%6.2f <I>/<I>all=%6.3f "
      "strong=%.2f -> %s\n"
      % (letter, st["n_class"], st["frac_measured"], st["mean_isig"],
         st["mean_rel_i"], st["frac_strong"],
         "centered" if st["supported"] else "no"))
  w("<|E^2-1|> = %.3f (acentric 0.736 / centric 0.968), P(centro)=%.2f\n"
    % (result["e_sq_minus_1"], result["p_centro"]))
  ms = result.get("missing_class_stats") or {}
  w("Completeness (non-absent classes): %.2f -> missing-class evidence %s\n"
    % (ms.get("completeness", 0.0),
       "ACTIVE (w=%.2f/refl)" % ms.get("w_miss", 0.0)
       if ms.get("gated") else "inactive"))
  w("Ranked space-group candidates (%d unique reflections):\n"
    % result["n_unique"])
  for rank, r in enumerate(result["candidates"], start=1):
    mark = ""
    if true_sg is not None and r["sg_number"] == true_sg:
      mark = "   <== TRUE"
    w("  #%-2d %-12s (No.%3d) total=%9.2f  absLL=%9.2f  missLL=%7.2f "
      "centro=%d bonus=%6.2f  n_abs=%4d/%4d(miss %4d) <I/s>_abs=%6.2f "
      "viol=%3d%s\n"
      % (rank, r["space_group"], r["sg_number"], r["total_score"],
         r["absence_ll_measured"], r["missing_ll"],
         int(r["centrosymmetric"]), r["centro_bonus"],
         r["n_absent_measured"], r["n_absent_expected"],
         r["n_absent_missing"], r["isig_absent"],
         r["n_absence_violations"], mark))


def _run_test_case(name, hkl, cell, wavelength, true_sg_number, true_symbol):
  print("=" * 78)
  print("DATASET %s | true SG %s (No. %d)" % (name, true_symbol,
                                              true_sg_number))
  print("  cell = %s, wavelength = %s" % (str(cell), str(wavelength)))
  arr = read_shelx_hkl(hkl, cell, wavelength)
  print("  %d unmerged reflections, d range %.2f - %.2f A"
        % ((arr.size(),) + arr.d_max_min()))
  result = determine_space_group(arr)
  show_result(result, true_sg=true_sg_number)
  ranks = [i for i, r in enumerate(result["candidates"], start=1)
           if r["sg_number"] == true_sg_number]
  rank = ranks[0] if ranks else None
  print("TRUE SG RANK: %s of %d candidates"
        % (rank, len(result["candidates"])))
  return rank, result


if __name__ == "__main__":
  import os
  base = os.path.dirname(os.path.abspath(__file__))
  cases = [
    ("P2-4+Cu", os.path.join(base, "data", "P24Cu", "shelxt.hkl"),
     (15.79, 32.31, 11.86, 90, 90, 90), 0.68914, 20, "C222(1)"),
    ("034A1", os.path.join(base, "data", "034A1", "shelxt.hkl"),
     (39.19, 39.19, 16.61, 90, 90, 120), 0.68883, 183, "P6mm"),
    ("NU-1200+Cu", os.path.join(base, "data", "NU1200",
                                "cu_GYF_20240604.hkl"),
     (10.6701, 28.8505, 31.1309, 90, 90, 90), 1.54178, 66, "Cccm"),
  ]
  summary = []
  for name, hkl, cell, wl, sgno, sgsym in cases:
    rank, result = _run_test_case(name, hkl, cell, wl, sgno, sgsym)
    summary.append((name, sgsym, rank, len(result["candidates"])))
  print("=" * 78)
  print("SUMMARY")
  for name, sgsym, rank, ncand in summary:
    print("  %-12s true %-8s rank %s / %d" % (name, sgsym, rank, ncand))
