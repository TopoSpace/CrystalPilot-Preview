"""Model-proportional detwinning for HKLF4 Fourier maps.

I_det(h) = I_obs(h) |Fc(h)|^2 / sum_j(alpha_j |Fc(T_j h)|^2).
This is a model-dependent allocation of overlapping intensities, not an
independent measurement of a domain. Unsupported observation models fail
explicitly instead of being interpreted as a low-density result.
"""
from __future__ import annotations

import math

from ..io.twin import twin_basf_error, twin_component_count

MAP_ALGORITHM_VERSION = 2


def detwinned_amplitudes(ses, xs, f_calc, f_mask=None):
    from cctbx.array_family import flex

    flags = ses.flags
    twin = flags.get("twin")
    if int(flags.get("hklf") or 4) == 5:
        raise ValueError(
            "HKLF5 composite observations cannot be used as single-domain "
            "difference density. A validated SHELXL detwinned map is required; "
            "density is unavailable, not evidence against an atom or fragment.")
    fo = ses.fo_sq.f_sq_as_f()
    if not twin:
        return fo, {"algorithm_version": MAP_ALGORITHM_VERSION,
                    "method": "single_domain", "twin_included": False}
    error = twin_basf_error(twin)
    if error:
        raise ValueError(error + "; no density was evaluated")
    matrix = twin.get("matrix") or []
    if (len(matrix) != 9 or any(not math.isfinite(v) or abs(v - round(v)) > 1e-8
                                for v in matrix)):
        raise ValueError(
            "Twin maps require an integral HKLF4 twin matrix; use a validated "
            "SHELXL detwinned map for other laws. Density is unavailable, not low.")
    count = twin_component_count(twin.get("n", 2))
    basf = list(twin.get("basf") or [1.0 / count] * (count - 1))
    fractions = [1.0 - math.fsum(basf)] + basf
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in fractions) or fractions[0] <= 0:
        raise ValueError("refined BASF fractions are not physical; no reliable twin density is available")
    matrix = [round(v) for v in matrix]
    original = list(ses.fo_sq.indices())

    def rotate(indices):
        return [tuple(sum(matrix[3 * row + col] * h[col] for col in range(3))
                      for row in range(3)) for h in indices]

    domains = [original]
    rotations = count // 2 if twin.get("n", 2) < 0 else count
    for _ in range(1, rotations):
        domains.append(rotate(domains[-1]))
    if rotations != count:
        domains += [[tuple(-v for v in h) for h in domain] for domain in domains[:]]

    mask_values = None
    if f_mask is not None:
        expanded = f_mask.expand_to_p1()
        if not expanded.anomalous_flag():
            expanded = expanded.generate_bijvoet_mates()
        mask_values = dict(zip(expanded.indices(), expanded.data()))
    total = fractions[0] * flex.norm(f_calc.data())
    for weight, indices in zip(fractions[1:], domains[1:]):
        if weight == 0:
            continue
        arr = ses.fo_sq.customized_copy(indices=flex.miller_index(indices))
        fc = arr.structure_factors_from_scatterers(
            xray_structure=xs, algorithm="direct").f_calc().data()
        if mask_values is not None:
            missing = sum(h not in mask_values for h in indices)
            if missing:
                raise ValueError(
                    f"solvent-mask coefficients are missing at {missing} twin-related "
                    "indices; no reliable twin density is available")
            fc = fc + flex.complex_double([mask_values[h] for h in indices])
        total += weight * flex.norm(fc)
    nonzero = total > 1e-20
    if not nonzero.count(True):
        raise ValueError("zero total twin Fc; no density can be evaluated")
    ratio = flex.double(total.size(), 0)
    ratio.set_selected(nonzero, flex.norm(f_calc.data()).select(nonzero) / total.select(nonzero))
    fo = fo.customized_copy(data=fo.data() * flex.sqrt(ratio))
    return fo, {
        "algorithm_version": MAP_ALGORITHM_VERSION,
        "method": "model_proportional_detwinning", "twin_included": True,
        "fractions": fractions, "n_components": count,
        "zero_model_intensity_reflections": nonzero.count(False),
        "caveat": "Detwinning depends on the current model. Low residual density "
                  "alone does not establish that an atom or fragment is absent.",
    }
