# DRAFT upstream report: dxtbx FormatBruker geometry gaps (swung 2θ + tilted φ axis)

*Status: draft for the user to review; NOT submitted anywhere. Prepared
2026-08-29 from probe evidence in `workdir/onitwin_probe` /
`workdir/fix_bruker_tth.py` / `workdir/onitwin_2latt`.*

---

**Title:** FormatBruker: detector 2θ swing modeled as beam-center shift and
φ-scan rotation axis ignores the fixed χ tilt — indexing impossible on a
public Kappa APEXII dataset

**Environment:** DIALS 3.30 (conda, Windows 11), dxtbx bundled therein.

**Dataset (public, CC-BY):** Zenodo 10.5281/zenodo.7193538
(`sfrm_m0220c.tar.bz2`, 3324 Bruker sfrm frames, 7 sweeps; Bruker Kappa
APEXII CCD, Mo Kα, detector distance 41 mm, detector swing 2θ = 21.52°,
φ scans at fixed χ = 35°). Published as the IUCrData Raw Data Letter
10.1107/S2414314622010598 (twinned γ-o-nitroaniline). The same record
carries the authors' imgCIF/CBF conversion (`cbf_m0220c.tar.bz2`) whose
headers hold the full geometry — that is the ground truth used below.

## Symptom

`dials.import` on the sfrm sweeps succeeds (7 clean sweeps), spot finding
finds >18k strong spots, but **no settings of dials.index produce a
lattice** (fft3d/fft1d, max_cell overrides, multi-lattice,
`dials.search_beam_position` insoluble in every geometry we tried).
The same frames converted to CBF by the dataset authors index immediately
(86.9 % single lattice; 99+ % with `max_lattices=2` — the sample is a
two-domain twin).

## Gap 1: 2θ swing folded into a beam-center shift on a face-on panel

sfrm header of sweep 1: `ANGLES` = 21.52 (2θ), …; `DISTANC` 4.1 cm;
`CENTER` 255.68, 255.87 px.

Imported detector: panel face-on (`fast={1,0,0}`, `slow={0,−1,0}`,
origin z = −41 mm) with the beam centre displaced by 16.2 mm — which is
exactly 41·tan(21.52°). I.e. the swing was flattened into a beam-center
shift. At 41 mm distance and 21.5° swing this misplaces edge-of-panel
spots by tens of pixels (the flat-detector approximation of a tilted
panel), which alone badly degrades indexing.

The authors' CBF import shows the physically tilted panel instead:
`fast≈{0.005, 0.931, −0.365}`, `slow≈{1, −0.005, 0}`, origin
{−30.9, −43.7, −26.8}.

## Gap 2: φ-scan rotation axis ignores the χ = 35° tilt

Header: `AXIS=3` (φ scan), χ = 35° fixed. Imported goniometer:

    Rotation axis: {−1, 0, 0}
    Fixed rotation / setting rotation: identity

The 35° tilt of the physical φ axis is lost entirely. The authors' CBF
carries

    Rotation axis: {−0.819, −0.574, 0}   # = (−cos 35°, −sin 35°, 0)

i.e. the φ axis rotated by χ within the plane normal to the beam. With
the wrong rotation axis every reflection's predicted rotation position is
wrong and no lattice can survive refinement — consistent with everything
we observed.

## Suggested direction

- Detector: build the swung panel by rotating a face-on panel (beam at
  `CENTER`, distance `DISTANC`) by 2θ about the swing axis, instead of
  shifting the beam centre.
- Goniometer: compose the fixed χ (and ω offset if nonzero) into the
  goniometer fixed/setting rotation for φ scans, so the effective rotation
  axis matches the physical one (the CBF conversion above gives the
  target values for this public dataset).

Happy to provide probe scripts / parsed headers. Note sfrm headers are
fixed 80-byte records (7-char key + ':' + 72-char value, no newlines);
`ANGLES` = 2θ ω φ χ, `DISTANC` in cm, `CENTER` = zero-swing beam centre.

## Reproduction

    tar -xjf sfrm_m0220c.tar.bz2
    dials.import template=m0220c_01_####.sfrm
    dials.show imported.expt        # face-on panel, axis {-1,0,0}
    dials.find_spots imported.expt spotfinder.filter.min_spot_size=3
    dials.index imported.expt strong.refl   # no lattice, any settings

    tar -xjf cbf_m0220c.tar.bz2
    dials.import template=m0220c_01_####.cbf
    dials.show imported.expt        # tilted axis, swung panel
    dials.index …                   # indexes at once
