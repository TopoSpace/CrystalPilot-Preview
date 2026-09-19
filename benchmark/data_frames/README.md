# Multi-vendor raw diffraction frame benchmark (`benchmark/data_frames/`)

Acquired 2026-08-28 to test the CrystalPilot frames→structure chain (DIALS backend,
`crystalpilot/io/frames_dials.py`) across vendor formats. Machine-readable details:
`benchmark/manifest_frames.json`. Verification here = **dials.import only** (DIALS 3.30,
conda env `C:\Users\lenovo\miniforge3\envs\dials`); no indexing/integration was run.
Import logs: `_import_tests/<case>/import*.log`.

## Datasets (8 new + 1 pre-existing)

| case_id | vendor / instrument | image format | frames | dials.import | reference |
|---|---|---|---|---|---|
| frames_bruker_photon3_thiourea | Bruker D8 VENTURE PHOTON-III, Mo, 250 K | .sfrm | 794 (14 sweeps) | OK - FormatBrukerModern | author CIF in ref/ (CCDC 2039166, Pnma, R1 0.0325) |
| frames_bruker_apex2_laspartic | Bruker Kappa APEX-II (Utrecht) | .sfrm | 3360 (7 runs) | OK but fragments to 1206 mini-sweeps | COD 1577465 = IUCrData RDL 10.1107/S241431462500879X (P2₁ twin, R1 0.0258) |
| frames_rigakuOD_eiger2_asbr3 | Rigaku XtaLAB Synergy-S + EIGER2 R CdTe 1M, Ag | .odeiger | 1638 | OK - FormatROD | CIF in ref/ (IUCrData 10.1107/S241431462600235X, P2₁2₁2₁, R1 0.0161) |
| frames_rigaku_hypix_lalanine | Rigaku HyPix-Arc, Mo (RODIN, Newcastle) | .rodhypix | 616 scan (6 sweeps) | OK - FormatROD_Arc | CCDC 2360269; COD 1559794 CIF in ref/ (P2₁2₁2₁) |
| frames_pilatus3_ofn_phth | Synchrotron kappa, λ=0.434 Å (Carnegie/Strobel) | miniCBF | 1200 (2×601) | OK - FormatCBFMiniPilatus | CCDC 2429146 + 10.1021/acs.cgd.5c00669 (no free CIF) |
| frames_nonius_kcd_fampridine | Bruker Nonius KappaCCD + FR591 (Southampton NCS) | .kcd (from .kcd.Z) | 592 (9 sweeps) | OK - FormatNoniusKappaCCD | papers 10.1039/c2ce25336d, 10.1515/pac-2022-1208 (CIF in CSD only) |
| frames_stoe_lalanine | STOE (RODIN, Newcastle) | .xi (X-Area) | 5439 files | **NOT importable**: no dxtbx Format for STOE X-Area | CCDC 2366175; COD 1559794 CIF in ref/ |
| frames_rigaku_saturn_lefpg | Rigaku FRE+ / Saturn 724+ CCD, CrysAlisPro (Southampton NCS) | .rod_img (OD v3.0, TY6) | 4996 | **NOT importable**: FormatROD supports header v4.0 only | data-collection CIF in ref/; model in 10.1021/acs.cgd.9b00335 (modulated, average structure) |
| (pre-existing) workdir/dials/lcyst | Diamond I19, PILATUS 2M | miniCBF | 1700 | OK (validated E2E previously) | L-cysteine, P2₁2₁2₁ |

## Provenance and licenses

- **All 8 downloaded datasets: CC-BY-4.0**, from Zenodo:
  - 10.5281/zenodo.18937802 - thiourea 250 K raw data (A. L. Llamas-Saiz, Univ. Santiago de
    Compostela; supports 10.1039/D6TA00623J, CCDC 2039166).
  - 10.5281/zenodo.15432050 - twinned L-aspartic acid, Bruker Kappa ApexII sfrm (M. Lutz,
    Utrecht; IUCrData Raw Data Letter 10.1107/S241431462500879X). The CBF conversion in the
    same record was not downloaded.
  - 10.5281/zenodo.18704110 - AsBr3 redetermination raw data incl. refined CIF
    (IUCrData 10.1107/S241431462600235X).
  - 10.5281/zenodo.11657765 and 10.5281/zenodo.12568551 - RODIN (Resource of Diffraction
    Images Newcastle; Waddell, Johnson & Probert; J. Chem. Educ. 2024,
    10.1021/acs.jchemed.4c00797). Teaching datasets; solved structures deposited as
    CCDC 2360269 / 2366175.
  - 10.5281/zenodo.14975558 - OFN:phthalazine co-crystal (Dunning & Strobel, Carnegie;
    CGD 2025 10.1021/acs.cgd.5c00669, CCDC 2429146).
  - 10.5281/zenodo.2595089 and 10.5281/zenodo.2585778 - Southampton NCS raw data
    (Coles et al.): fampridine·HCl phase 1 (Nonius KappaCCD) and LEF-PG co-crystal
    (Rigaku FRE+/Saturn 724+). LEF-PG record also provided ref CIF/ins/hkl/p4p (in ref/).
- Reference CIFs from the **Crystallography Open Database** (COD 1577465, 1559794, 8103728) —
  COD content is public domain / freely redistributable.
- The pre-existing L-cysteine set is the public DIALS small-molecule tutorial data
  (Diamond I19, mt11145-4).

## Verified format-support findings (DIALS 3.30 / dxtbx on Windows)

1. **Supported and verified here**: Bruker modern .sfrm (FormatBrukerModern), Bruker
   Kappa APEX-II .sfrm (FormatBruker - but see caveat), Rigaku OD .odeiger (FormatROD),
   Rigaku .rodhypix HyPix-Arc (FormatROD_Arc), Dectris miniCBF (FormatCBFMiniPilatus),
   Nonius .kcd (FormatNoniusKappaCCD).
2. **Gap - STOE X-Area `.xi`**: no dxtbx Format class; dials.import rejects the files.
3. **Gap - legacy Oxford Diffraction/CrysAlis `.rod_img` ("OD SAPPHIRE 3.0", TY6)**:
   FormatROD raises `NotImplementedError: only header version 4.0 is supported but got 3.0`.
4. **Caveat - old Kappa APEX-II sfrm**: imports, but 3360 frames fragment into 1206
   mini-sweeps (scan concatenation metadata not chained); the author's CBF conversion of the
   same data is the fallback (see manifest).
5. Practical importing notes: unpadded frame numbers (odeiger) need wildcard args, not
   `template=`; composite images (`sum.cbf`) and snapshot frames (`work/`, `precession/`)
   must be excluded or template detection fails.
6. **Not found openly** (after Zenodo/SBGrid/IUCrData searching): a small-molecule ADSC SMV
   dataset and a small-molecule Eiger-HDF5 (NXmx) dataset with a published reference —
   public ADSC/Eiger-HDF5 raw sets are essentially all macromolecular. These two dxtbx
   formats remain unexercised by this benchmark.

## Layout

```
data_frames/
  <case_id>/frames/   raw images as shipped (archives extracted 1:1; .kcd.Z gunzipped)
  <case_id>/ref/      reference CIF(s) where obtainable
  _import_tests/      dials.import working dirs + logs (evidence for manifest claims)
  _dl/                download scripts/logs (archives deleted after verified extraction)
  _zsearch.py/_zdetail.py/_verify_import.py/_write_manifest.py   acquisition tooling
```
