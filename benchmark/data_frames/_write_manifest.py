import json
import pathlib

M = []

M.append({
    "id": "frames_bruker_photon3_thiourea",
    "source_repo": "Zenodo (record 18937802)",
    "doi": "10.5281/zenodo.18937802",
    "url": "https://zenodo.org/records/18937802",
    "license": "CC-BY-4.0",
    "vendor_family": "Bruker (modern)",
    "instrument": "Bruker D8 VENTURE PHOTON-III C14, Mo K-alpha, 250 K (Univ. Santiago de Compostela, Llamas-Saiz)",
    "detector": "PHOTON-III C14",
    "format": "dxtbx.format.FormatBrukerModern.FormatBrukerModern (.sfrm)",
    "n_frames": 794,
    "size_GB": 0.68,
    "compound": "thiourea (high-temperature non-modulated phase)",
    "formula": "CH4N2S",
    "cell_published": [7.6093, 8.5410, 5.4750, 90, 90, 90],
    "sg_published": "Pnma",
    "human_R1": 0.0325,
    "ref_cif_path": "frames_bruker_photon3_thiourea/ref/thiourea_250K_author_refined.cif",
    "downloaded": True,
    "dials_import_ok": True,
    "notes": ("Author's refined CIF found inside archive (work/18MPC001T250K.cif; CCDC 2039166; "
              "published with 10.1039/D6TA00623J). 794 scan frames in 14 sweeps (runs 71-77 + xa reruns); "
              "work/ + precession/ subdirs hold 26 extra non-scan sfrm snapshots that break dials.import "
              "template parsing - import only mo_18MPC001_rampT250K_*.sfrm. Secondary ref: "
              "ref/cod_8103728_thiourea_pnma.cif and cell-only COD 3000152. dials.import: 794 images, "
              "14 sweeps, FormatBrukerModern.")})

M.append({
    "id": "frames_bruker_apex2_laspartic",
    "source_repo": "Zenodo (record 15432050)",
    "doi": "10.5281/zenodo.15432050",
    "url": "https://zenodo.org/records/15432050",
    "license": "CC-BY-4.0",
    "vendor_family": "Bruker (Kappa APEX II CCD generation)",
    "instrument": "Bruker Kappa ApexII, Utrecht University (Martin Lutz)",
    "detector": "APEX II CCD",
    "format": "dxtbx.format.FormatBruker.FormatBruker (.sfrm)",
    "n_frames": 3360,
    "size_GB": 0.87,
    "compound": "L-aspartic acid (twinned monoclinic polymorph; IUCrData Raw Data Letter)",
    "formula": "C4H7NO4",
    "cell_published": [5.1237, 6.9197, 7.6006, 90, 100.442, 90],
    "sg_published": "P21",
    "human_R1": 0.0258,
    "ref_cif_path": "frames_bruker_apex2_laspartic/ref/cod_1577465_laspartic.cif",
    "downloaded": True,
    "dials_import_ok": True,
    "notes": ("Raw Data Letter: 10.1107/S241431462500879X (Lutz, IUCrData 2025); ref CIF = COD 1577465 "
              "(the RDL structure itself; twin refinement). CAVEAT: crystal is twinned - a hard case by "
              "design. dials.import recognises all 3360 frames (7 runs) but fragments them into 1206 "
              "mini-sweeps: old Kappa APEX-II sfrm scan concatenation is imperfect in dxtbx; the same "
              "record also offers an author-converted CBF variant (cbf_m0255a.tar.bz2, 0.465 GB, not "
              "downloaded) as fallback.")})

M.append({
    "id": "frames_rigakuOD_eiger2_asbr3",
    "source_repo": "Zenodo (record 18704110)",
    "doi": "10.5281/zenodo.18704110",
    "url": "https://zenodo.org/records/18704110",
    "license": "CC-BY-4.0",
    "vendor_family": "Rigaku Oxford Diffraction + Dectris (hybrid)",
    "instrument": "Rigaku OD XtaLAB Synergy-S Dualflex, PhotonJet Ag K-alpha (0.56087 A), 100 K",
    "detector": "Dectris EIGER2 R CdTe 1M",
    "format": "dxtbx.format.FormatROD.FormatROD (.odeiger)",
    "n_frames": 1638,
    "size_GB": 0.57,
    "compound": "arsenic tribromide AsBr3 (redetermination)",
    "formula": "AsBr3",
    "cell_published": [4.20575, 10.08102, 12.0632, 90, 90, 90],
    "sg_published": "P212121",
    "human_R1": 0.0161,
    "ref_cif_path": "frames_rigakuOD_eiger2_asbr3/ref/AsBr3_refined.cif",
    "downloaded": True,
    "dials_import_ok": True,
    "notes": ("Reference = IUCrData redetermination 10.1107/S241431462600235X; refined CIF (olex2/SHELXL) "
              "shipped inside the archive (struct/olex2_AsBr3_1_1/AsBr3_1_1.cif), copied to ref/. "
              "dials.import: all 1638 .odeiger frames recognised by FormatROD. CrysAlisPro processing "
              "files and logs included. Frame numbering unpadded - use wildcards, not template=.")})

M.append({
    "id": "frames_rigaku_hypix_lalanine",
    "source_repo": "Zenodo (record 11657765), RODIN community (Newcastle/CCDC)",
    "doi": "10.5281/zenodo.11657765",
    "url": "https://zenodo.org/records/11657765",
    "license": "CC-BY-4.0",
    "vendor_family": "Rigaku (HyPix-Arc hybrid photon counting)",
    "instrument": "Rigaku diffractometer, Mo radiation (RODIN teaching resource, Newcastle University)",
    "detector": "HyPix-Arc (curved; detected as FormatROD_Arc)",
    "format": "dxtbx.format.FormatROD.FormatROD_Arc (.rodhypix)",
    "n_frames": 616,
    "size_GB": 0.19,
    "compound": "L-alanine",
    "formula": "C3H7NO2",
    "cell_published": [5.9279, 12.2597, 5.7939, 90, 90, 90],
    "sg_published": "P212121",
    "human_R1": 0.0196,
    "ref_cif_path": "frames_rigaku_hypix_lalanine/ref/cod_1559794_lalanine.cif",
    "downloaded": True,
    "dials_import_ok": True,
    "notes": ("RODIN dataset (J. Chem. Educ. 10.1021/acs.jchemed.4c00797); the exact solved structure is "
              "CSD deposition CCDC 2360269 (10.5517/ccdc.csd.cc2k71ql, CIF not freely downloadable); ref "
              "CIF here is COD 1559794 (L-alanine, Chem. Sci. 2020, R1=0.0196) - same polymorph. "
              "dials.import: 698 images OK (616 scan in 6 sweeps + 30 pre-experiment rodhypix + "
              "tmp background .img).")})

M.append({
    "id": "frames_pilatus3_ofn_phth",
    "source_repo": "Zenodo (record 14975558)",
    "doi": "10.5281/zenodo.14975558",
    "url": "https://zenodo.org/records/14975558",
    "license": "CC-BY-4.0",
    "vendor_family": "Dectris Pilatus3 (synchrotron beamline)",
    "instrument": ("Synchrotron kappa diffractometer, lambda=0.434 A (28.6 keV); Carnegie Science "
                   "(Dunning & Strobel); frame paths suggest an APS BM-C beamline"),
    "detector": "PILATUS3 1M S/N 10-0169",
    "format": "dxtbx.format.FormatCBFMiniPilatus.FormatCBFMiniPilatus (miniCBF)",
    "n_frames": 1200,
    "size_GB": 1.2,
    "compound": "octafluoronaphthalene : phthalazine co-crystal (piezoelectric)",
    "formula": "C10F8 . C8H6N2",
    "cell_published": None,
    "sg_published": None,
    "human_R1": None,
    "ref_cif_path": None,
    "downloaded": True,
    "dials_import_ok": True,
    "notes": ("Human reference exists: CCDC 2429146 + paper 10.1021/acs.cgd.5c00669 (Cryst. Growth Des. "
              "2025); CIF not freely fetchable (ACS SI behind Cloudflare, CCDC page JS-only) - cell/SG/R1 "
              "left null rather than guessed. dials.import: 1200 images, 2 sweeps of 601 (sum.cbf "
              "composite must be excluded - breaks template detection). Esperanto-export .ini sidecars "
              "and pyFAI .poni included.")})

M.append({
    "id": "frames_nonius_kcd_fampridine",
    "source_repo": "Zenodo (record 2595089)",
    "doi": "10.5281/zenodo.2595089",
    "url": "https://zenodo.org/records/2595089",
    "license": "CC-BY-4.0",
    "vendor_family": "Bruker Nonius (KappaCCD)",
    "instrument": ("Bruker Nonius KappaCCD on FR591 rotating anode, confocal mirrors "
                   "(Southampton NCS: Coles, Montis, Horton, Hursthouse)"),
    "detector": "KappaCCD",
    "format": "dxtbx.format.FormatNoniusKappaCCD.FormatNoniusKappaCCD (.kcd)",
    "n_frames": 592,
    "size_GB": 0.86,
    "compound": "fampridine (4-aminopyridine) hydrochloride, Phase 1",
    "formula": "C5H6N2 . HCl (phase 1 salt; see papers)",
    "cell_published": None,
    "sg_published": None,
    "human_R1": None,
    "ref_cif_path": None,
    "downloaded": True,
    "dials_import_ok": True,
    "notes": ("Frames shipped as .kcd.Z (Unix compress) + Denzo .x; decompressed in place with gzip -d "
              "(.x files kept). dials.import: 592 images, 9 sweeps, FormatNoniusKappaCCD. Published "
              "context: 10.1039/c2ce25336d (CrystEngComm 2012, fampridine hydrochloride family) and "
              "10.1515/pac-2022-1208; exact phase-1 CIF is in the CSD (not freely fetched) - cell/SG/R1 "
              "left null. DENZO/SCALEPACK artefacts (smart.p4p, sad.hkl etc.) exist on the Zenodo record "
              "but were not re-downloaded.")})

M.append({
    "id": "frames_stoe_lalanine",
    "source_repo": "Zenodo (record 12568551), RODIN community (Newcastle/CCDC)",
    "doi": "10.5281/zenodo.12568551",
    "url": "https://zenodo.org/records/12568551",
    "license": "CC-BY-4.0",
    "vendor_family": "STOE",
    "instrument": "STOE diffractometer (RODIN teaching resource, Newcastle University)",
    "detector": "unknown (STOE X-Area container)",
    "format": None,
    "n_frames": 5439,
    "size_GB": 5.6,
    "compound": "L-alanine",
    "formula": "C3H7NO2",
    "cell_published": [5.9279, 12.2597, 5.7939, 90, 90, 90],
    "sg_published": "P212121",
    "human_R1": 0.0196,
    "ref_cif_path": "frames_stoe_lalanine/ref/cod_1559794_lalanine.cif",
    "downloaded": True,
    "dials_import_ok": False,
    "notes": ("FORMAT GAP: frames are STOE X-Area .xi containers ('STOE_XFILE' binary); dials.import does "
              "not recognise them (no dxtbx Format class; exits rc=0 with 'Unable to handle the following "
              "arguments', no imported.expt). Would need STOE X-Area export (e.g. to cbf) or a custom "
              "Format class. Solved structure = CCDC 2366175 (10.5517/ccdc.csd.cc2kf67g); COD 1559794 "
              "kept as coordinate reference. 0.64 GB zip inflates to 5.6 GB of .xi.")})

M.append({
    "id": "frames_rigaku_saturn_lefpg",
    "source_repo": "Zenodo (record 2585778)",
    "doi": "10.5281/zenodo.2585778",
    "url": "https://zenodo.org/records/2585778",
    "license": "CC-BY-4.0",
    "vendor_family": "Rigaku (Saturn CCD via CrysAlisPro, legacy Oxford-Diffraction image format)",
    "instrument": ("Rigaku FRE+ SuperBright rotating anode, HF Varimax mirrors, AFC12 goniometer "
                   "(Southampton NCS: Coles, Klooster; sample Aitipamula)"),
    "detector": "HG Saturn 724+ CCD",
    "format": None,
    "n_frames": 4996,
    "size_GB": 2.0,
    "compound": ("LEF-PG co-crystal (leflunomide API + PG coformer; modulated structure, published "
                 "model averages the modulation)"),
    "formula": "not stated in data-collection CIF",
    "cell_published": [23.4057, 22.3471, 6.96622, 89.9959, 107.3098, 89.9917],
    "sg_published": "P-1 (average structure)",
    "human_R1": None,
    "ref_cif_path": "frames_rigaku_saturn_lefpg/ref/2019wtk0002.cif",
    "downloaded": True,
    "dials_import_ok": False,
    "notes": ("FORMAT GAP: frames are CrysAlisPro-written .rod_img with header 'OD SAPPHIRE 3.0', TY6 "
              "compression; dxtbx FormatROD supports only header version 4.0 -> NotImplementedError "
              "('only header version 4.0 is supported but got 3.0'). ref/ holds the record's "
              "data-collection CIF (cell/instrument, no coordinates/R) + .ins/.hkl/.p4p. Refined model: "
              "CGD paper 10.1021/acs.cgd.9b00335 (leflunomide cocrystals; CCDC deposition). CAVEAT: "
              "diffraction shows incommensurate modulation; published model is the average structure.")})

M.append({
    "id": "frames_pilatus2m_lcysteine_existing",
    "source_repo": ("pre-existing local copy (workdir/dials/lcyst/data); Diamond Light Source I19, "
                    "visit mt11145-4; distributed as the DIALS small-molecule tutorial dataset"),
    "doi": None,
    "url": None,
    "license": "public tutorial dataset (DIALS project); recorded here for coverage accounting only",
    "vendor_family": "Dectris Pilatus (synchrotron, already covered before this task)",
    "instrument": "Diamond I19, lambda=0.6889 A, 2016",
    "detector": "PILATUS 2M S/N 24-0107",
    "format": "dxtbx miniCBF (FormatCBFMiniPilatus family)",
    "n_frames": 1700,
    "size_GB": None,
    "compound": "L-cysteine",
    "formula": "C3H7NO2S",
    "cell_published": None,
    "sg_published": "P212121",
    "human_R1": None,
    "ref_cif_path": None,
    "downloaded": True,
    "dials_import_ok": True,
    "notes": ("NOT downloaded by this task - already on disk and validated end-to-end through "
              "crystalpilot.io.frames_dials (exact cell, auto P212121). Listed so the vendor-coverage "
              "picture in this manifest is complete.")})

CAND = [
    {"id": "cand_gunka_ccdc_series",
     "source_repo": "Zenodo (Piotr A. Gunka, Warsaw UT)",
     "doi": ("10.5281/zenodo.5596198 (+5470707, 12187765, 6346906, 10784740, 10401233, 7862050, "
             "8013735, 10477457, 12527454, 15655614)"),
     "url": "https://zenodo.org/records/5596198",
     "license": "CC-BY-4.0 (some records unspecified)",
     "vendor_family": "unknown (single .7z per record; not inspected)",
     "size_GB": "1.75-18.1 per record",
     "compound": "various CCDC-paired small molecules (e.g. ferrocene cage CCDC 2085773)",
     "downloaded": False, "not_downloaded": True,
     "notes": ("Each pairs raw data with CCDC depositions/papers. Skipped: vendor unknown without "
               "downloading 1.8+ GB opaque .7z; revisit if another Bruker/Agilent-era format is needed.")},
    {"id": "cand_xef2_ptf5_odeiger",
     "source_repo": "Zenodo", "doi": "10.5281/zenodo.18428037",
     "url": "https://zenodo.org/records/18428037", "license": "CC-BY-4.0",
     "vendor_family": "Rigaku OD XtaLAB Synergy-S + Eiger2 R CdTe 1M (.odeiger)",
     "size_GB": 2.41,
     "compound": "[Xe2F3][PtF6].XeF2 etc.",
     "downloaded": False, "not_downloaded": True,
     "notes": ("Same vendor/format as frames_rigakuOD_eiger2_asbr3 (which is 8x smaller) - redundant. "
               "Sister record 10.5281/zenodo.17787891 (2.99 GB).")},
    {"id": "cand_thiourea_incommensurate_series",
     "source_repo": "Zenodo (Llamas-Saiz)",
     "doi": "10.5281/zenodo.18926480 et al. (174-200 K) + 18937564/18937706 (202/210 K)",
     "url": "https://zenodo.org/records/18926480", "license": "CC-BY-4.0",
     "vendor_family": "Bruker D8 VENTURE PHOTON-III (.sfrm)",
     "size_GB": "0.40-0.43 each",
     "compound": "thiourea incommensurate phase",
     "downloaded": False, "not_downloaded": True,
     "notes": ("Deliberately skipped: incommensurately modulated - outside the standard "
               "frames->structure chain; 250 K non-modulated sister record downloaded instead.")},
    {"id": "cand_rodin_other_vendor_sets",
     "source_repo": "Zenodo RODIN community (47 records)",
     "doi": ("e.g. 10.5281/zenodo.11958481 (L-alanine Bruker 1.83 GB), 11946282 (L-alanine synchrotron "
             "2.95 GB), 11964555 (indomethacin Bruker 2.38 GB), 12090078 (aspirin 0.43 GB), 17288006 "
             "(biotin twin 0.38 GB), 20557962 (incommensurate 1.51 GB)"),
     "url": "https://zenodo.org/communities/rodin", "license": "CC-BY-4.0",
     "vendor_family": "Bruker / Rigaku / STOE / synchrotron",
     "size_GB": "0.03-2.95 each",
     "compound": "CSD teaching subset compounds, each with a CCDC number",
     "downloaded": False, "not_downloaded": True,
     "notes": ("Rich fallback pool: same compounds across vendors. Bruker/synchrotron entries redundant "
               "with sets already taken; grab more here if the benchmark needs volume.")},
    {"id": "cand_hypix_arc_test_sets",
     "source_repo": "Zenodo",
     "doi": "10.5281/zenodo.15189287 (150deg, Cu) / 10.5281/zenodo.15189396 (100deg, Mo)",
     "url": "https://zenodo.org/records/15189287", "license": "CC-BY-4.0",
     "vendor_family": "Rigaku HyPix-Arc (.rodhypix)",
     "size_GB": "0.19 / 0.02",
     "compound": "undisclosed test samples (CHNOS / YbCDTA)",
     "downloaded": False, "not_downloaded": True,
     "notes": ("Skipped: no published reference structure - fails the pairing requirement; HyPix-Arc "
               "covered by RODIN L-alanine.")},
    {"id": "cand_lanthanide_mof",
     "source_repo": "Zenodo", "doi": "10.5281/zenodo.14269933",
     "url": "https://zenodo.org/records/14269933", "license": "CC-BY-4.0",
     "vendor_family": "unknown", "size_GB": 29.0,
     "compound": "lanthanide MOF with nanostructured node disorder",
     "downloaded": False, "not_downloaded": True,
     "notes": "Over the 8 GB per-set cap (29 GB)."},
    {"id": "cand_onitroaniline_twin",
     "source_repo": "Zenodo (Utrecht)", "doi": "10.5281/zenodo.7193538",
     "url": "https://zenodo.org/records/7193538", "license": "CC-BY-4.0",
     "vendor_family": "Bruker (companion RDL to L-aspartic set)", "size_GB": 1.17,
     "compound": "o-nitroaniline gamma-form (twinned)",
     "downloaded": False, "not_downloaded": True,
     "notes": "Second twinned Bruker set from the same group - redundant with frames_bruker_apex2_laspartic."},
    {"id": "cand_laspartic_cbf_variant",
     "source_repo": "Zenodo", "doi": "10.5281/zenodo.15432050",
     "url": "https://zenodo.org/records/15432050", "license": "CC-BY-4.0",
     "vendor_family": "Bruker Kappa APEX-II converted to imgCIF/CBF (Apex6)", "size_GB": 0.465,
     "compound": "L-aspartic acid (same data as sfrm set)",
     "downloaded": False, "not_downloaded": True,
     "notes": ("Author-converted CBF twin of the sfrm set - useful fallback if the fragmented-sweep "
               "sfrm import blocks processing.")},
    {"id": "cand_fampridine_phases_2_4",
     "source_repo": "Zenodo (Southampton NCS)",
     "doi": "10.5281/zenodo.2585776 / 2593670 / 2593677",
     "url": "https://zenodo.org/records/2585776", "license": "CC-BY-4.0",
     "vendor_family": "Bruker Nonius KappaCCD", "size_GB": "0.13-0.85",
     "compound": "fampridine hydrochloride phases 2-4",
     "downloaded": False, "not_downloaded": True,
     "notes": "Same instrument/format as phase 1 - redundant for format coverage."},
]

out = {
    "generated": "2026-08-28",
    "task": ("multi-vendor raw-frame benchmark acquisition "
             "(dials.import verification only; no indexing/integration)"),
    "disk_budget_GB": 25,
    "downloaded_archive_total_GB": 4.9,
    "extracted_on_disk_total_GB": 12.0,
    "datasets": M,
    "candidates_not_downloaded": CAND,
}
p = pathlib.Path(r"H:\CrystalPilot\benchmark\manifest_frames.json")
p.write_text(json.dumps(out, indent=2), encoding="utf-8")
print("wrote", p, "-", len(M), "datasets,", len(CAND), "candidates")
