r"""Main-thread pre-import of every C-extension module the tools load lazily.

WHY (reg9-dbu, 2026-09-05 00:05, py-spy dump of the MCP process 52540):

    Thread "AnyIO worker thread"
        create_module (importlib)          <- loading scipy\linalg\_fblas.pyd
        <module> (scipy\linalg\blas.py:247)
        <module> (scipy\spatial\_kdtree.py:8)
        _build_work (crystalpilot\chem\interactions.py:608)
        find_interactions -> interactions_from_res -> build_analysis
        run (crystalpilot\refine\tools_packing.py:170)

    Thread "MainThread": idle in asyncio select

The worker thread's FIRST import of scipy.spatial pulled scipy's own BLAS
DLL in, and that load never returned: the Windows loader lock and
OpenBLAS's thread-pool start-up do not survive being entered from a
non-main thread while the interpreter's main thread owns the event loop.
The call sat there for the whole 3900 s codex tool timeout; the agent
narrated "the packing analysis is still running" for an hour; CPU was
zero. The same trap was already known for cctbx/smtbx boost extensions
(server/app.py startup, mcp/server.py list_tools comment) - scipy had
simply never been on the list because the interaction engine (R2), the
pore geometry (R3) and the shape/topology modules (R4) introduced the
lazy `from scipy... import` lines after it.

RULE, enforced by tests/test_prewarm.py: any `import` of scipy / cctbx /
smtbx / iotbx / mmtbx / gemmi that sits INSIDE a function body anywhere in
crystalpilot/ must name a module listed in HEAVY_MODULES below, so it is
already in sys.modules by the time a worker thread reaches it. A lazy
import that is not listed fails the test - add it here, do not remove the
lazy import (they keep the CLI / tests fast).
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
import time
from typing import Any

#: modules whose DLLs start thread pools in DllMain (numpy / scipy each
#: carry an OpenBLAS): they must be resident BEFORE the anyio loop spawns
#: its stdio worker threads - importing them in-loop, on ANY thread,
#: deadlocks in the Windows loader lock (mcp/server.py main(); the
#: cold-cache handshake test reproduces it in 120 s when this is wrong)
PRELOOP_MODULES: tuple[str, ...] = (
    "numpy",
    "scipy",
    "scipy.linalg",
    "scipy.spatial",
    "scipy.spatial.distance",
    "scipy.ndimage",
    "scipy.sparse",
    "scipy.sparse.csgraph",
    "scipy.optimize",
)

# Linux wheels: boost_python_meta_ext.platform_info() crashes if its first
# import follows scipy.linalg (cctbx-base 2025.11 / scipy 1.17.1). Initialize
# Boost first on POSIX; retain the proven Windows DLL-loader ordering.
if os.name != "nt":
    PRELOOP_MODULES = ("cctbx.array_family.flex",) + PRELOOP_MODULES

#: boost / pybind extensions the tools import lazily; safe in-loop on the
#: main thread once numpy/scipy are resident, never first in a worker
HEAVY_MODULES: tuple[str, ...] = (
    "cctbx",
    "cctbx.array_family.flex",
    "cctbx.crystal",
    "cctbx.sgtbx",
    "cctbx.sgtbx.lattice_symmetry",
    "cctbx.sgtbx.subgroups",
    "cctbx.uctbx",
    "cctbx.xray",
    "cctbx.miller",
    "cctbx.adptbx",
    "cctbx.maptbx",
    "cctbx.masks",
    "cctbx.geometry_restraints",
    "cctbx.adp_restraints",
    "cctbx.euclidean_model_matching",
    "cctbx.eltbx.tiny_pse",
    "cctbx.eltbx.covalent_radii",
    "cctbx.eltbx.van_der_waals_radii",
    "cctbx.eltbx.xray_scattering",
    "cctbx.eltbx.henke",
    "cctbx.eltbx.sasaki",
    "cctbx.eltbx.attenuation_coefficient",
    "smtbx",
    "smtbx.utils",
    "smtbx.masks",
    "smtbx.refinement",
    "smtbx.refinement.constraints",
    "smtbx.refinement.least_squares",
    "smtbx.refinement.restraints",
    "smtbx.refinement.restraints.adp_restraints",
    "iotbx.shelx.hklf",
    "iotbx.merging_statistics",
    "iotbx.cif",
    "iotbx.mrcfile",
    "iotbx.xplor.map",
    "gemmi",
)

_done = threading.Event()
_report: dict[str, Any] = {}


def prewarm_preloop() -> dict[str, str]:
    """Import PRELOOP_MODULES; call it before anyio.run. Returns the
    failures ({name: error}); nothing is raised."""
    failed: dict[str, str] = {}
    for name in PRELOOP_MODULES:
        try:
            importlib.import_module(name)
        except Exception as e:  # noqa: BLE001 - optional packages
            failed[name] = f"{type(e).__name__}: {e}"
    return failed


def prewarm_heavy_imports(force: bool = False) -> dict[str, Any]:
    """Import HEAVY_MODULES now, on the calling thread (call it from the
    main thread). Idempotent; returns {"imported": [...], "failed":
    {name: error}, "seconds": float, "thread": name}. A module that is
    not installed is reported, never raised - engine-less installs keep
    working, they just cannot run the tools that need it."""
    if _done.is_set() and not force:
        return dict(_report)
    t0 = time.time()
    imported: list[str] = []
    failed: dict[str, str] = {}
    for name in PRELOOP_MODULES + HEAVY_MODULES:
        try:
            importlib.import_module(name)
            imported.append(name)
        except Exception as e:  # noqa: BLE001 - optional packages
            failed[name] = f"{type(e).__name__}: {e}"
    _report.clear()
    _report.update({"imported": imported, "failed": failed,
                    "seconds": round(time.time() - t0, 2),
                    "thread": threading.current_thread().name})
    _done.set()
    return dict(_report)


def is_prewarmed(name: str) -> bool:
    return name in sys.modules
