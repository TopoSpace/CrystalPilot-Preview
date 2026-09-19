"""dxtbx format plugin: Bruker .sfrm (FORMAT 100) with correct geometry.

Stock dxtbx FormatBruker delegates to iotbx.detectors.bruker.BrukerImage,
which HARDCODES the image size to 1024x1024 ("Bruker Proteus CCD" legacy).
Frames whose header says NROWS/NCOLS = 512 (APEX2 CCD binned modes and
others) get their 512x512 payload embedded in one quadrant of a 1024^2
canvas: 75% dead zeros, dispersion spotfinding drowns in edge artefacts,
and the detector two-theta offset (ANGLES[0]) is折进 beam-x instead of
tilting the panel. This class rebuilds everything from the header alone:

* true NROWS/NCOLS; pixel size from DETTYPE's pixels-per-cm field;
* explicit detector two-theta: panel rotated about the goniometer axis
  (Bruker 2th and omega share the vertical axis; in the dxtbx mapping
  used by stock FormatBruker that axis is +x with beam -z, fast +x,
  slow -y - we keep that self-consistent frame);
* reverse scans (INCREME < 0): axis flipped + angles negated, same trick
  as the CrystalPilot Rigaku plugin, so dials.import sees an increasing
  scan;
* native sfrm payload decoding (uint8/uint16 base plane + 2-byte and
  4-byte overflow tables, 16-byte padded), no iotbx detectorbase;
* fixed-chi stage support: phi (fixed per run) enters as the goniometer
  fixed rotation about the chi-tilted phi axis, so multi-run joint
  indexing shares one lab frame.

Geometry conventions were determined EMPIRICALLY on DJ_Tokyo practice
set 770 (D8 fixed-chi, APEX2-class CCD-LDI, 512x512, 0.12 mm px, 60 mm,
2theta swings -27/-33 deg, 0.5 deg omega scans, chi = 54.746):

* the payload is TRANSPOSED relative to the stock dxtbx assumption -
  file rows run along the goniometer/two-theta axis, file columns along
  the swing direction (radial |q| vs 1/d(hkl) of the 922 SAINT REF
  calibration spots: 0.002 A^-1 median for the transposed placement vs
  0.33 for the stock one);
* scan sense: pair-difference spectroscopy of the mapped rlp cloud shows
  discrete reciprocal-lattice peaks (c* 0.052, 0.083, 0.102 A^-1) for
  SCAN_SIGN=-1 and a featureless continuum for +1;
* certification: seeding dials.refine with the hand-derived UB under
  DET_CONFIG=py_px, TT_SIGN=-1, SCAN_SIGN=-1 converges at RMSD 0.40 px
  (X) / 0.35 px (Y) / 0.11 frames over 2723 reflections;
* fixed-chi phi conventions: joint 3-run indexing (phi 0/88/180) under
  one crystal model discriminates cleanly - TILT_SIGN=+1/PHI_SIGN=+1
  indexes 3996/3494/1790 spots across the runs, every other sign combo
  collapses the phi=88 run to ~570 (and phi=180, insensitive to the phi
  sign as R(a,180)=R(a,-180), tracks the tilt sign exactly as expected).

The defaults below encode that certified set; the environment switches
remain for instruments wired differently.
"""
from __future__ import annotations

import struct

from scitbx import matrix
from scitbx.array_family import flex

from dxtbx.format.FormatBruker import FormatBruker

__version__ = "0.2.0"


def _read_header(image_file):
    with FormatBruker.open_file(image_file, "rb") as fh:
        head = fh.read(512 * 5).decode("latin-1", "replace")
        hdrblks = 15
        d: dict[str, str] = {}
        for i in range(0, len(head), 80):
            line = head[i:i + 80]
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip() and k.strip() not in d:
                    d[k.strip()] = v.strip()
        try:
            hdrblks = int(d.get("HDRBLKS", "15").split()[0])
        except ValueError:
            pass
        if hdrblks * 512 > len(head):
            with FormatBruker.open_file(image_file, "rb") as fh2:
                head = fh2.read(512 * hdrblks).decode("latin-1", "replace")
            for i in range(0, len(head), 80):
                line = head[i:i + 80]
                if ":" in line:
                    k, v = line.split(":", 1)
                    if k.strip() and k.strip() not in d:
                        d[k.strip()] = v.strip()
        d["_HDRBLKS"] = str(hdrblks)
        return d


class FormatBrukerSfrmGeom(FormatBruker):
    """Bruker sfrm with header-true size, explicit 2theta and payload."""

    @staticmethod
    def understand(image_file):
        try:
            d = _read_header(image_file)
            int(d["NROWS"].split()[0])
            int(d["NCOLS"].split()[0])
            int(d["NPIXELB"].split()[0])
            float(d["DETTYPE"].split()[1])   # pixels-per-cm must be there
            return True
        except Exception:  # noqa: BLE001 - any parse failure: stand down
            return False

    def _start(self):
        self._h = _read_header(self._image_file)
        h = self._h
        self._nrows = int(h["NROWS"].split()[0])
        self._ncols = int(h["NCOLS"].split()[0])
        self._npixelb = [int(x) for x in h["NPIXELB"].split()[:2]]
        self._noverfl = [int(x) for x in h.get("NOVERFL", "-1 0 0").split()[:3]]
        self._px_mm = 10.0 / float(h["DETTYPE"].split()[1])
        self._dist_mm = 10.0 * float(h["DISTANC"].split()[0])
        c = h["CENTER"].split()
        self._center_px = (float(c[0]), float(c[1]))
        a = [float(x) for x in h["ANGLES"].split()[:4]]
        self._two_theta = a[0] if a[0] <= 180.0 else a[0] - 360.0
        # ANGLES = 2theta, omega, phi, chi. On fixed-chi stages (chi != 0)
        # the phi spindle is inclined to the omega axis by chi; phi is
        # fixed within a run but differs between runs, so it must enter
        # the goniometer as a fixed rotation for multi-run joint indexing.
        self._phi = a[2] if a[2] <= 180.0 else a[2] - 360.0
        self._chi = a[3] if a[3] <= 180.0 else a[3] - 360.0
        self._start_deg = float(h["START"].split()[0])
        self._increme = float(h["INCREME"].split()[0])
        self._wavelength = float(h["WAVELEN"].split()[0])
        self._exposure = float(h.get("CUMULAT", "1").split()[0])

    def _goniometer(self):
        import os
        # scan-axis sense (empirically validated switches, see _detector):
        #   CRYSTALPILOT_SFRM_SCAN_SIGN  = 1|-1 flips the omega axis
        #   CRYSTALPILOT_SFRM_TILT_SIGN  = 1|-1 beam-axis sense of the
        #                                       chi tilt of the phi axis
        #   CRYSTALPILOT_SFRM_PHI_SIGN   = 1|-1 sense of the phi angle
        scan_sign = float(os.environ.get("CRYSTALPILOT_SFRM_SCAN_SIGN", "-1"))
        tilt_sign = float(os.environ.get("CRYSTALPILOT_SFRM_TILT_SIGN", "1"))
        phi_sign = float(os.environ.get("CRYSTALPILOT_SFRM_PHI_SIGN", "1"))
        ax = scan_sign * (1.0 if self._increme >= 0 else -1.0)
        axis = (ax, 0.0, 0.0)
        if abs(self._chi) < 1e-6 and abs(self._phi) < 1e-6:
            return self._goniometer_factory.known_axis(axis)
        # phi axis at the omega datum: +x tilted by chi about the beam
        # axis (z); phi as the goniometer fixed rotation (S = R_omega * F)
        phi_axis = matrix.col((1.0, 0.0, 0.0)).rotate_around_origin(
            matrix.col((0.0, 0.0, tilt_sign)), self._chi, deg=True)
        fixed = phi_axis.axis_and_angle_as_r3_rotation_matrix(
            phi_sign * self._phi, deg=True)
        return self._goniometer_factory.make_goniometer(axis, fixed.elems)

    _DET_CONFIGS = {
        # in-plane orientation of the sfrm payload on the detector face:
        # fast = file-column direction, slow = file-row direction (the
        # payload is read row-major). The 8 entries are the D4 group of
        # the square - including the transposed placements the earlier
        # sign-only sweeps never covered.
        "px_py": ((1, 0, 0), (0, 1, 0)),
        "px_my": ((1, 0, 0), (0, -1, 0)),
        "mx_py": ((-1, 0, 0), (0, 1, 0)),
        "mx_my": ((-1, 0, 0), (0, -1, 0)),
        "py_px": ((0, 1, 0), (1, 0, 0)),
        "py_mx": ((0, 1, 0), (-1, 0, 0)),
        "my_px": ((0, -1, 0), (1, 0, 0)),
        "my_mx": ((0, -1, 0), (-1, 0, 0)),
    }

    def _detector(self):
        import os
        pixel = self._px_mm
        # frame: beam propagates -z, goniometer/2theta axis x, detector
        # face at the -z distance with the CENTER pixel on the beam at
        # the 2theta datum. Empirically validated switches:
        #   CRYSTALPILOT_SFRM_DET_CONFIG = px_my | ... (_DET_CONFIGS)
        #   CRYSTALPILOT_SFRM_TT_SIGN    = 1|-1 sense of the 2theta swing
        tt_sign = float(os.environ.get("CRYSTALPILOT_SFRM_TT_SIGN", "-1"))
        cfg = os.environ.get("CRYSTALPILOT_SFRM_DET_CONFIG", "py_px")
        f, s = self._DET_CONFIGS[cfg]
        fast0 = matrix.col(tuple(float(x) for x in f))
        slow0 = matrix.col(tuple(float(x) for x in s))
        cx, cy = self._center_px
        origin0 = (matrix.col((0.0, 0.0, -self._dist_mm))
                   - fast0 * cx * pixel
                   - slow0 * cy * pixel)
        r = matrix.col((1.0, 0.0, 0.0)).axis_and_angle_as_r3_rotation_matrix(
            tt_sign * self._two_theta, deg=True)
        return self._detector_factory.make_detector(
            "CCD", r * fast0, r * slow0, r * origin0,
            (pixel, pixel), (self._ncols, self._nrows),
            (0, 1.0e6))

    def _beam(self):
        return self._beam_factory.simple(self._wavelength)

    def _scan(self):
        start = self._start_deg
        width = self._increme
        if width < 0:
            # reverse scan: R(-axis, -ang) == R(axis, ang); axis already
            # flipped in _goniometer, so negate angles to keep a positive
            # width and a monotonically increasing multi-frame sequence
            start, width = -start, -width
        return self._scan_factory.single_file(
            filename=self._image_file, exposure_times=self._exposure,
            osc_start=start, osc_width=width, epoch=None)

    def get_raw_data(self):
        h = self._h
        nrows, ncols = self._nrows, self._ncols
        npix = nrows * ncols
        base_bytes = self._npixelb[0]
        with FormatBruker.open_file(self._image_file, "rb") as fh:
            fh.seek(int(h["_HDRBLKS"]) * 512)
            raw = fh.read(npix * base_bytes)
            if base_bytes == 1:
                vals = list(raw)
                cap = 255
            elif base_bytes == 2:
                vals = list(struct.unpack("<%dH" % npix, raw))
                cap = 65535
            else:
                vals = list(struct.unpack("<%dI" % npix, raw))
                cap = None

            def _padded(n):
                return (n + 15) & ~15

            # skip underflow table (baseline mode); values stay as read
            n_under = self._noverfl[0]
            if n_under > 0 and self._npixelb[1] > 0:
                fh.seek(_padded(n_under * self._npixelb[1]), 1)
            if cap == 255:
                two = self._noverfl[1]
                table2 = struct.unpack("<%dH" % two,
                                       fh.read(two * 2)) if two else ()
                fh.seek(_padded(two * 2) - two * 2, 1)
                four = self._noverfl[2]
                table4 = struct.unpack("<%dI" % four,
                                       fh.read(four * 4)) if four else ()
                i2 = i4 = 0
                for i, v in enumerate(vals):
                    if v == 255 and i2 < len(table2):
                        w = table2[i2]
                        i2 += 1
                        if w == 65535 and i4 < len(table4):
                            w = table4[i4]
                            i4 += 1
                        vals[i] = w
            elif cap == 65535:
                four = self._noverfl[2] or self._noverfl[1]
                table4 = struct.unpack("<%dI" % four,
                                       fh.read(four * 4)) if four else ()
                i4 = 0
                for i, v in enumerate(vals):
                    if v == 65535 and i4 < len(table4):
                        vals[i] = table4[i4]
                        i4 += 1
        data = flex.int(vals)
        data.reshape(flex.grid(nrows, ncols))
        return data
