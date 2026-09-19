"""SolveSession: the mutable state a solve run carries between tools.

Tools read/modify this state explicitly; every mutation goes through a tool call that
is event-logged, so the session's evolution is fully reconstructable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.dataset import ReflectionDataset


@dataclass
class RefinementSnapshot:
    label: str
    r1_strong: float
    r1_all: float
    wr2: float
    goof: float
    n_params: int
    n_reflections: int
    diff_map_max: float | None = None
    diff_map_min: float | None = None
    flack: float | None = None       # absolute-structure parameter (SHELXL)
    flack_su: float | None = None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items()}


@dataclass
class SolveSession:
    dataset: ReflectionDataset
    # working crystallographic state
    symmetry: Any = None            # cctbx crystal.symmetry currently assumed
    fo_sq: Any = None               # merged intensities in working symmetry (miller.array)
    model: Any = None               # cctbx xray.structure (current best in this trajectory)
    # bookkeeping
    sg_candidates: list[dict[str, Any]] = field(default_factory=list)
    cf_info: dict[str, Any] = field(default_factory=dict)
    refinement_history: list[RefinementSnapshot] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)   # agent scratch: suspicions, notes
    #: last merge statistics (space_group / n_unique / r_int / d_min /
    #: completeness) from set_symmetry - the data side of the picture
    merge_info: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # `model` is a property (installed below the class): every structure a
    # tool puts into the session - SHELXL adopt, a symmetry change, an
    # import, a split or a select() copy - gets the dataset's anomalous
    # terms on assignment. Round-3 2026-09-06: the engine set f'/f'' on
    # refine only; every other path left them at zero, and on Zr K-edge
    # data (f'(Zr) = -9 e) the same model masked to 2x the electrons.
    def _get_model(self) -> Any:
        return self.__dict__.get("_model")

    def _set_model(self, xs: Any) -> None:
        wavelength = getattr(self.dataset, "wavelength", None) \
            if self.dataset is not None else None
        if xs is not None and wavelength:
            from ..io.shelx_writer import apply_anomalous_terms
            apply_anomalous_terms(xs, wavelength)
        self.__dict__["_model"] = xs

    # ------------------------------------------------------------------
    def set_symmetry(self, symmetry: Any) -> dict[str, Any]:
        """Adopt a working space group: re-merge raw intensities accordingly."""
        from cctbx import crystal

        raw = self.dataset.intensities
        assert raw is not None
        cs = crystal.symmetry(unit_cell=raw.unit_cell(),
                              space_group=symmetry.space_group())
        data = raw.customized_copy(crystal_symmetry=cs)
        data = data.set_observation_type_xray_intensity()
        merged = data.eliminate_sys_absent().merge_equivalents()
        self.symmetry = cs
        self.fo_sq = merged.array()
        stats = {
            "space_group": str(cs.space_group_info()),
            "n_unique": self.fo_sq.size(),
            "r_int": round(merged.r_int(), 4),
            "d_min": round(self.fo_sq.d_min(), 3),
            "completeness": round(self.fo_sq.completeness(d_max=float("inf")), 3),
        }
        # keep them: the merge is the expensive part and every consumer
        # downstream (node commit, viewer, report) wants the same numbers
        self.merge_info = dict(stats)
        return stats

    # ------------------------------------------------------------------
    def model_summary(self, max_atoms: int = 200) -> dict[str, Any]:
        if self.model is None:
            return {"n_atoms": 0}
        from cctbx import adptbx

        xs = self.model
        uc = xs.unit_cell()
        atoms = []
        for sc in xs.scatterers():
            u_equiv = (adptbx.u_star_as_u_iso(uc, sc.u_star)
                       if sc.flags.use_u_aniso() else sc.u_iso)
            atoms.append({
                "label": sc.label,
                "element": sc.scattering_type.strip().capitalize(),
                "occ": round(sc.occupancy, 3),
                "u_iso_or_equiv": round(u_equiv, 4),
                "aniso": bool(sc.flags.use_u_aniso()),
            })
        counts: dict[str, int] = {}
        for a in atoms:
            counts[a["element"]] = counts.get(a["element"], 0) + 1
        return {
            "n_atoms": len(atoms),
            "element_counts": counts,
            "atoms": atoms[:max_atoms],
        }

    def last_refinement(self) -> RefinementSnapshot | None:
        return self.refinement_history[-1] if self.refinement_history else None


SolveSession.model = property(SolveSession._get_model, SolveSession._set_model)
