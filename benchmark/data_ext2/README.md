# Extended benchmark set 2 (`benchmark/data_ext2/`)

Acquired 2026-08-29 to stress the three CrystalPilot entry stages beyond `data_ext`
(101 COD hkl+CIF cases) and `data_frames` (8 raw-frame sets, all organic/molecular).
Machine-readable provenance: `benchmark/manifest_ext2.json`. Everything here is public
data (COD public-domain / IUCr open-access supplements / Zenodo CC-BY-4.0); per-entry
details, URLs, DOIs and licenses are in each `<slug>/SOURCE.txt`.

## Part 1 - human-refined final structures + deposited structure factors (9 entries, stage "refined")

Each `<slug>/` holds `ref.cif` (final refined CIF as deposited), `ref.fcf` (deposited
structure-factor file; all are SHELX LIST-4 CIF reflection files: h k l Fc^2 Fo^2 sigma
status), and `ref.hkl` (DERIVED locally from ref.fcf: SHELX HKLF4 3I4+2F8.2 h k l Fo^2
sigma, zero-terminated; any uniform rescale to fit F8.2 is recorded in SOURCE.txt and
the manifest). Verification: gemmi parses every CIF/fcf; R1 recomputed from each fcf
against the deposited model reproduces the published R1 to <=0.002 for all 9 entries
(pairing proof, values in manifest).

Coverage: 2 clean baselines (organic, Cu coordination polymer), PART/occupancy disorder
(organic + Cu-sparfloxacin), a Cu3 MOF (Acta C 2024), and 4 twin cases spanning the
whole twin phenomenology: HKLF5 reflection twin with BASF 0.389 (5-iodouracil, heavy
atom), a non-merohedral twin whose CIF is silent about the twinning (trap case), an
explicit TWIN/BASF pseudo-merohedral twin with weak data (R1 ~0.10), and TWIN/BASF plus
massive disorder (ebastinium hydrogen fumarate, 82 part-occupied sites). Twin fcf files
are model-detwinned by SHELXL - disclosed in SOURCE.txt.

## Part 2 - raw diffraction frames (2 sets, stage "frames")

| case | chemistry | vendor format | frames | dials.import (DIALS 3.30) | twin ground truth |
|---|---|---|---|---|---|
| `frames_zn_dpnpp` | Zn coordination polymer (catena-Zn bis[di(4-nitrophenyl)phosphate], Pna2_1) | Oxford Diffraction `.img`, header "OD SAPPHIRE 3.0", TY5 | 1102 | see `_import_tests/zn_dpnpp/` (legacy v3.0 header = expected FormatROD gap) | CrysAlisPro 2-component twin reduction shipped in-place (twin1/twin2 HKLF4, twin1 HKLF5, .twinlog); final model = inversion twin BASF 0.496, ref CIF COD 7709880 in `ref/` |
| `frames_onitroaniline_twin` | gamma-o-nitroaniline (metastable polymorph, P2_1/a) | Bruker Kappa APEXII `.sfrm` | 3324 | see `_import_tests/onitroaniline/` | non-merohedral 2-component twin (180 deg about c); RDL gives published ladder: naive R1 0.0678 -> PLATON HKLF5 detwin 0.0465 -> EVAL15 two-lattice best; CCDC 2217206 (CSD-only, no free CIF) |

Both fill declared gaps of `data_frames`: no coordination-compound chemistry and only
one twinned set (L-aspartic acid, same Utrecht lab - the o-nitroaniline set enables
tune-on-one / verify-on-the-other twin-rescue experiments).

Larger candidates that were found but NOT downloaded (size/pertinence) are recorded in
the manifest with stage `frames_candidate` (incl. a 29 GB lanthanide-MOF set with node
disorder, and the 1.9 GB companion Zn-polymer and ferrocene-cage sets).

## Layout

```
data_ext2/
  <slug>/ref.cif|ref.fcf|ref.hkl|SOURCE.txt      stage "refined" (9 entries)
  frames_zn_dpnpp/frames/pg33_ZnDpNPP/           7z extracted 1:1 (CrysAlisPro workspace incl. frames/*.img)
  frames_zn_dpnpp/ref/ref.cif                    COD 7709880 reference model
  frames_onitroaniline_twin/frames/*.sfrm        tar.bz2 extracted 1:1
  _import_tests/<case>/                          dials.import evidence (log + expt)
```

Downloaded archives were checked byte-for-byte against Zenodo content-length before
extraction and deleted afterwards (working copies under `workdir/collect/`, gitignored).
