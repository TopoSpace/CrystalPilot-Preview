"""dxtbx format plugin: Oxford Diffraction legacy IMG (OD SAPPHIRE 3.0).

Old CrysAlis CCD frames (Sapphire3 / Gemini ultra era, ~2008-2015)
carry ASCII+binary headers that are byte-compatible with the modern
ROD 4.0 layout stock dxtbx already reads: identical section sizes
(ASCII 256 / general 512 / special 768 / KM4 1024 / statistics 512 /
history 2048, NHEADER 5120) and identical field offsets - verified
field-by-field against fabio's independent OxdImage parser on the
pg33 Zn coordination-polymer dataset (beam centre, distance, pixel
size, three wavelengths, detector tilts e1-e3, beam rotations,
alpha=50.05 kappa-support angle, OM/TH/KA/PH start angles all equal).
The TY5 compression is likewise the same stream format handled by
FormatROD's native decoder.

The ONLY blocker in stock dxtbx is an explicit version gate:
FormatROD.understand() accepts any "OD SAPPHIRE" header, then
_read_ascii_header raises NotImplementedError for version != 4.0.
This subclass claims exactly version 3.x files (deeper DAG node wins)
and re-implements the small ASCII parser without the gate; all
geometry, goniometer, scan and raw-data logic is inherited unchanged.

Registry note (hard-won, see the sibling plugins): the entry point
must name the DAG parent - "FormatRODLegacy:FormatROD" - because the
registry only descends into children of classes whose understand()
passed.
"""
from __future__ import annotations

import re

from dxtbx.format.FormatROD import FormatROD

__version__ = "0.2.0"


class FormatRODLegacy(FormatROD):
    """Oxford Diffraction legacy IMG (header version 3.x)."""

    @staticmethod
    def _ascii_version(image_file) -> float | None:
        try:
            with FormatRODLegacy.open_file(image_file, "rb") as f:
                hdr = f.read(256).decode("ascii")
        except UnicodeDecodeError:
            return None
        lines = hdr.splitlines()
        if len(lines) < 2:
            return None
        vers = lines[0].split()
        if len(vers) < 2 or vers[0] != "OD" or vers[1] != "SAPPHIRE":
            return None
        if not lines[1].startswith("COMPRESSION="):
            return None
        try:
            return float(vers[-1])
        except ValueError:
            return None

    @staticmethod
    def understand(image_file):
        v = FormatRODLegacy._ascii_version(image_file)
        return v is not None and 3.0 <= v < 4.0

    @staticmethod
    def _read_ascii_header(image_file):
        """Parent's parser minus the version-4.0 gate (v3 line layout is
        identical: NX/NY/OI/OL, NHEADER/NG/NS/NK/NS/NH, NSUPPLEMENT,
        TIME; the COMPRESSION value keeps a trailing '( ratio)\\x00'
        which startswith('TY5') downstream tolerates)."""
        hd = {}
        with FormatRODLegacy.open_file(image_file, "rb") as f:
            hdr = f.read(256).decode("ascii")
        lines = hdr.splitlines()

        vers = lines[0].split()
        if len(vers) < 2 or vers[0] != "OD" or vers[1] != "SAPPHIRE":
            raise ValueError("Wrong header format")
        hd["version"] = float(vers[-1])

        compression = lines[1].split("=")
        if compression[0] != "COMPRESSION":
            raise ValueError("Wrong header format")
        hd["compression"] = compression[1]

        defn = re.compile(r"([A-Z]+=[ 0-9]+)")
        for line in lines[2:5]:
            for s in defn.findall(line):
                n, v = s.split("=")
                hd[n] = int(v)

        hd["time"] = lines[5].split("TIME=")[-1].strip("\x1a").rstrip()
        return hd
