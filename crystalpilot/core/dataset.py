"""Core domain models: reflection data and composition, backend-agnostic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompositionHint:
    """Expected chemical composition per formula unit (may be approximate for MOFs)."""

    elements: dict[str, float]      # element symbol -> count per formula unit
    z: float | None = None          # formula units per cell
    source: str = ""                # where the hint came from (ins UNIT, user, agent)

    def heavy_elements(self, z_min: int = 11) -> list[str]:
        from cctbx.eltbx import tiny_pse
        out = []
        for el in self.elements:
            try:
                if tiny_pse.table(el).atomic_number() >= z_min:
                    out.append(el)
            except RuntimeError:
                continue
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"elements": self.elements, "z": self.z, "source": self.source}


@dataclass
class ReflectionDataset:
    """Uniform product of every RawDataAdapter: unmerged intensities + metadata.

    `intensities` is a cctbx miller.array carrying the unit cell in P1; symmetry is
    assigned downstream by the space-group determination stage. `symmetry_hint` holds
    any symmetry claimed by the source files (treated as a hint, not truth).
    """

    intensities: Any                      # cctbx miller.array (unmerged, P1 basis)
    wavelength: float | None
    symmetry_hint: Any = None             # cctbx crystal.symmetry or None
    composition: CompositionHint | None = None
    source_files: list[str] = field(default_factory=list)
    instrument_meta: dict[str, Any] = field(default_factory=dict)

    # -- convenience -------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        mi = self.intensities
        uc = mi.unit_cell()
        d_max, d_min = mi.d_max_min()
        s: dict[str, Any] = {
            "n_reflections": mi.size(),
            "unit_cell": [round(x, 4) for x in uc.parameters()],
            "cell_volume": round(uc.volume(), 2),
            "wavelength": self.wavelength,
            "d_min": round(d_min, 3),
            "d_max": round(d_max, 2),
            "source_files": self.source_files,
        }
        if self.instrument_meta.get("n_sigma_dropped"):
            s["n_sigma_dropped"] = self.instrument_meta["n_sigma_dropped"]
        if self.symmetry_hint is not None:
            s["symmetry_hint"] = str(self.symmetry_hint.space_group_info())
        if self.composition:
            s["composition_hint"] = self.composition.as_dict()
        return s
