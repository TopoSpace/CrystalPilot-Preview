# Extended benchmark set (data_ext)

Every case in this directory was fetched from the Crystallography Open Database
(COD, https://www.crystallography.net/), whose contents are placed in the public
domain by their contributors; each case couples the deposited measured structure
factors (COD hkl mirror, normalised here to fixed-format SHELX HKLF: h k l F^2
sigma(F^2), 3I4+2F8.2, zero-terminated) with the human-refined reference CIF
(atomic coordinates, cell, space group, published R1) from the same COD entry —
almost all originating from IUCr journals (Acta Cryst. B/C/E, IUCrData) that
require structure-factor deposition. Per-case provenance (COD id, DOI, source
URLs, license, instrument, category, validation notes - including any uniform
F^2 rescaling applied to fit the fixed-width columns) is recorded in
`benchmark/manifest_ext.json`; the set is reproducible via
`benchmark/tools/fetch_ext.py`, which re-downloads, re-validates, and rebuilds
this directory (contents are gitignored except this README).
