"""dxtbx format plugin: Rigaku HyPix miniCBF written by CrysAlisPro
("CAP HPAD detectors export", ``_array_data.header_convention "RIGAKU_1.x"``).

Stock dxtbx has no Format class for this convention, so ``dials.import``
rejects the frames outright.  The header is fully self-describing - it
carries lab-frame unit vectors for the detector fast/slow axes, the
incident beam and the rotation axis - so we build the models directly
from those instead of assuming the Pilatus-style "+x/-y, beam along -z"
geometry of FormatCBFMini._detector.

Conventions verified against a HyPix-6000 dataset (Zenodo 14269933):

* ``Detector_2theta`` is already folded into the fast/slow vectors: the
  slow axis rotated back by R_z(+2theta) lands exactly on -Y, and
  fast x slow equals R_z(2theta) applied to the beam direction.  Hence
  ``Detector_distance`` is sample->detector along the (tilted) detector
  normal and ``Beam_xy`` is the calibrated beam position for 2theta=0,
  i.e. the foot of that normal:  origin = d*n - fast*bx - slow*by.
* ``Incident_beam_vector`` is the propagation direction (source->sample);
  here it runs along -X, not the usual -Z.
* ``Angle_increment`` may be negative (reverse scan).  dxtbx scans want a
  positive width, so we flip the rotation axis and negate the start angle
  (R(-axis, -theta) == R(axis, theta)), which also keeps multi-frame
  sequences monotonically increasing for dials.import.
* Registry note: the entry point declares FormatCBF (not FormatCBFMini)
  as the DAG parent, because FormatCBFMini.understand() has a hardcoded
  vendor whitelist that rejects RIGAKU and the registry only descends
  into children of classes that understand the image.  Python-level
  inheritance still uses FormatCBFMini for header parsing/decompression.
"""

from __future__ import annotations

import datetime
import re
import sys

from cctbx.eltbx import attenuation_coefficient
from scitbx import matrix

from dxtbx.format.FormatCBF import FormatCBF
from dxtbx.format.FormatCBFMini import FormatCBFMini
from dxtbx.model import ParallaxCorrectedPxMmStrategy

__version__ = "0.2.0"


class FormatCBFMiniRigaku(FormatCBFMini):
    """Rigaku HPAD (HyPix) miniCBF as exported by CrysAlisPro."""

    @staticmethod
    def understand(image_file):
        header = FormatCBF.get_cbf_header(image_file)
        for record in header.split("\n"):
            if "_array_data.header_convention" in record and "RIGAKU" in record:
                return True
        return False

    def _header_vector(self, key):
        return matrix.col(
            tuple(float(x) for x in self._cif_header_dictionary[key].split()[:3])
        )

    def _detector(self):
        d = self._cif_header_dictionary

        distance_mm = float(d["Detector_distance"].split()[0]) * 1000.0
        wavelength = float(d["Wavelength"].split()[0])

        beam_x, beam_y = map(
            float,
            d["Beam_xy"].replace("(", "").replace(")", "").replace(",", "").split()[:2],
        )
        pixel_x, pixel_y = map(
            float, d["Pixel_size"].replace("m", "").replace("x", "").split()
        )
        pixel_x_mm = pixel_x * 1000.0
        pixel_y_mm = pixel_y * 1000.0

        fast = self._header_vector("Detector_fast_axis_vector").normalize()
        slow = self._header_vector("Detector_slow_axis_vector").normalize()
        beam = self._header_vector("Incident_beam_vector").normalize()

        # Detector normal, signed to point from the sample towards the
        # panel (valid while |2theta| < 90 deg).
        normal = fast.cross(slow).normalize()
        if normal.dot(beam) < 0:
            normal = -normal

        origin = (
            distance_mm * normal
            - fast * beam_x * pixel_x_mm
            - slow * beam_y * pixel_y_mm
        )

        nx = int(d["X-Binary-Size-Fastest-Dimension"])
        ny = int(d["X-Binary-Size-Second-Dimension"])

        if "Count_cutoff" in d:
            overload = int(float(d["Count_cutoff"].split()[0]))
        else:
            # CrysAlisPro puts the saturation level in SPECIAL_CCD_2[4]
            try:
                overload = int(float(d["SPECIAL_CCD_2"].split()[4]))
            except (KeyError, IndexError, ValueError):
                overload = 10_000_000

        # "Silicon sensor, thickness 0.000645 m" -> key "Silicon"
        thickness_mm = 0.32
        if "Silicon" in d:
            try:
                thickness_mm = float(d["Silicon"].split()[2]) * 1000.0
            except (IndexError, ValueError):
                pass
        table = attenuation_coefficient.get_table("Si")
        mu = table.mu_at_angstrom(wavelength) / 10.0

        detector = self._detector_factory.complex(
            "PAD",
            origin.elems,
            fast.elems,
            slow.elems,
            (pixel_x_mm, pixel_y_mm),
            (nx, ny),
            (0, overload),
            px_mm=ParallaxCorrectedPxMmStrategy(mu, thickness_mm),
            mu=mu,
        )
        detector[0].set_thickness(thickness_mm)
        detector[0].set_material("Si")
        return detector

    def _beam(self):
        wavelength = float(self._cif_header_dictionary["Wavelength"].split()[0])
        sample_to_source = -self._header_vector("Incident_beam_vector").normalize()
        try:
            fraction = float(self._cif_header_dictionary["Polarization"].split()[0])
        except (KeyError, ValueError):
            fraction = 0.5
        return self._beam_factory.make_polarized_beam(
            sample_to_source=sample_to_source.elems,
            wavelength=wavelength,
            polarization=(0, 1, 0),
            polarization_fraction=fraction,
        )

    def _goniometer(self):
        axis = self._header_vector("Rotation_axis_vector").normalize()
        if float(self._cif_header_dictionary["Angle_increment"].split()[0]) < 0:
            axis = -axis
        return self._goniometer_factory.known_axis(axis.elems)

    def _scan(self):
        d = self._cif_header_dictionary
        exposure = float(
            d.get("Exposure_time", d.get("Exposure_period", "0")).split()[0]
        )
        osc_start = float(d["Start_angle"].split()[0])
        osc_width = float(d["Angle_increment"].split()[0])
        if osc_width < 0:
            # paired with the axis flip in _goniometer()
            osc_start, osc_width = -osc_start, -osc_width

        epoch = 0.0
        if "timestamp" in d:
            # CrysAlisPro writes single-digit days ("2024-03-4T13:36:04.000")
            # which fromisoformat rejects; normalise before parsing.
            m = re.match(
                r"(\d{4})-(\d{1,2})-(\d{1,2})T(\d{2}):(\d{2}):(\d{2})", d["timestamp"]
            )
            if m:
                y, mo, dy, h, mi, s = (int(g) for g in m.groups())
                try:
                    epoch = datetime.datetime(
                        y, mo, dy, h, mi, s, tzinfo=datetime.timezone.utc
                    ).timestamp()
                except ValueError:
                    epoch = 0.0

        return self._scan_factory.single_file(
            self._image_file, exposure, osc_start, osc_width, epoch
        )


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(FormatCBFMiniRigaku.understand(arg))
