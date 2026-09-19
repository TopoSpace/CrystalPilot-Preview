"""CrystalPilot Workbench: Codex app-server harness adapter (ADR-001).

Requires the `workbench` extra (`pip install crystalpilot[workbench]`), which
pins the official `openai-codex` SDK + bundled binary. Import submodules
directly (`crystalpilot.workbench.core`, `.service`, `.routes`); this package
init stays import-light so the engine works without the SDK installed.
"""
