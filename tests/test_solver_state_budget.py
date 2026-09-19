"""Hard worker deadlines and durable atomless space-group decisions."""

from __future__ import annotations

import sys
import threading
import time

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.io.shelx_writer import ShelxModel, write_res
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.refine.project import RefineProject
from crystalpilot.tools.base import ToolContext
from crystalpilot.tools.solution_tools import ChargeFlippingSolve


def session():
    xs = xray.structure(
        crystal_symmetry=crystal.symmetry(
            unit_cell=(10, 11, 12, 90, 100, 90), space_group_symbol="P 1"
        )
    )
    for label, element, site in (
        ("C1", "C", (0.1, 0.2, 0.3)),
        ("C2", "C", (0.22, 0.26, 0.3)),
        ("O1", "O", (0.3, 0.24, 0.35)),
    ):
        xs.add_scatterer(xray.scatterer(label=label, scattering_type=element, site=site, u=0.03))
    data = xs.structure_factors(d_min=1, algorithm="direct").f_calc().norm()
    data = data.customized_copy(
        sigmas=flex.sqrt(data.data()) + 1
    ).set_observation_type_xray_intensity()
    return SolveSession(
        dataset=ReflectionDataset(data, 0.71073),
        symmetry=xs.crystal_symmetry(),
        fo_sq=data,
        model=xs,
    )


@pytest.mark.parametrize(
    "stage", ["initialization", "native iteration", "peak extraction", "result serialization"]
)
def test_deadline_interrupts_a_stage_that_never_yields(monkeypatch, stage):
    from crystalpilot.tools import charge_flipping_worker as worker

    ses = session()
    original = {"seed": 99, "peak_sites": [(0.1, 0.2, 0.3)]}
    ses.cf_info = original

    def command(directory):
        code = (
            "import json,time; from pathlib import Path; "
            f"Path({str(directory / 'progress.json')!r}).write_text(json.dumps("
            f"{{'stage':{stage!r},'attempt_table':[{{'seed':1,'iterations':7}}]}})); "
            "time.sleep(60)"
        )
        return [sys.executable, "-c", code]

    monkeypatch.setattr(worker, "_worker_command", command)
    start = time.monotonic()
    result = ChargeFlippingSolve().run(
        ToolContext(None, ses), time_budget_s=0.5, max_iterations=250
    )
    elapsed = time.monotonic() - start
    assert not result.ok and result.summary["timed_out"]
    assert result.summary["stage"] == stage
    assert result.summary["attempt_table"][0]["iterations"] == 7
    assert elapsed < 0.5 + worker.CLEANUP_GRACE_S + 0.5
    assert ses.cf_info is original


def test_cancellation_preserves_previous_phases(monkeypatch):
    from crystalpilot.tools import charge_flipping_worker as worker

    ses = session()
    ses.cf_info = {"seed": 17}
    monkeypatch.setattr(
        worker, "_worker_command", lambda _: [sys.executable, "-c", "import time; time.sleep(60)"]
    )
    stop = threading.Event()
    timer = threading.Timer(0.2, stop.set)
    timer.start()
    try:
        result = ChargeFlippingSolve().run(ToolContext(None, ses, cancel_event=stop), timeout_s=10)
    finally:
        timer.cancel()
    assert not result.ok and result.summary["cancelled"]
    assert ses.cf_info == {"seed": 17}


def test_real_worker_returns_a_bounded_result():
    ses = session()
    result = ChargeFlippingSolve().run(
        ToolContext(None, ses),
        timeout_s=5,
        max_solving_iterations=50,
        max_attempts_per_seed=1,
        seeds=[1],
    )
    assert "worker_exit_code" not in result.summary, result.summary
    assert "budget" in result.summary and result.summary["elapsed_s"] < 7
    if result.ok:
        assert ses.cf_info["peak_sites"]
    else:
        assert ses.cf_info == {}


def test_alias_conflicts_refuse_without_starting_worker(monkeypatch):
    from crystalpilot.tools import charge_flipping_worker as worker

    monkeypatch.setattr(worker, "_worker_command", lambda _: pytest.fail("worker launched"))
    r = ChargeFlippingSolve().run(ToolContext(None, session()), time_budget_s=55, timeout_s=50)
    assert not r.ok and "conflicts" in r.error


def test_declared_budget_includes_cleanup_and_understands_alias():
    from crystalpilot.tools.budget import declared_budget_s

    assert declared_budget_s("solve_charge_flipping", {"time_budget_s": 55}) == 57
    assert declared_budget_s("solve_charge_flipping", {"timeout_s": 0}) is None


def test_project_timeout_does_not_rebuild_an_unchanged_live_session(tmp_path, monkeypatch):
    ses = session()
    write_res(ShelxModel(ses.model), tmp_path / "start.res")
    with (tmp_path / "crystal.hkl").open("w") as out:
        ses.fo_sq.export_as_shelx_hklf(file_object=out)
    project = RefineProject(tmp_path)
    project.open()
    original = project.session
    node = project.nodes.state()["active_node"]
    monkeypatch.setattr(
        project, "checkout", lambda *a, **kw: pytest.fail("timeout started a costly model rebuild")
    )
    result = project.invoke_tool("solve_charge_flipping", {"timeout_s": 0.00001})
    assert not result.ok and result.summary["timed_out"]
    assert project.session is original and project.nodes.state()["active_node"] == node


def test_atomless_declaration_survives_failure_next_call_and_reopen(tmp_path):
    xs = xray.structure(
        crystal_symmetry=crystal.symmetry(
            unit_cell=(10, 10, 10, 90, 90, 90), space_group_symbol="P -1"
        )
    )
    xs.add_scatterer(
        xray.scatterer(label="C1", scattering_type="C", site=(0.13, 0.21, 0.37), u=0.03)
    )
    observations = xs.structure_factors(d_min=1.5).f_calc().norm()
    observations = observations.customized_copy(
        sigmas=flex.sqrt(observations.data()) + 1
    ).set_observation_type_xray_intensity()
    with (tmp_path / "crystal.hkl").open("w") as out:
        observations.export_as_shelx_hklf(file_object=out)
    write_res(ShelxModel(xs), tmp_path / "start.res")
    original = (tmp_path / "start.res").read_bytes()
    p = RefineProject(tmp_path)
    p.open()
    assert p.invoke_tool("edit_atoms", {"operations": [{"action": "delete", "atoms": ["C1"]}]}).ok
    before = p.nodes.state()["active_node"]
    old_data = p.nodes.node_meta(before)["data_revision"]
    result = p.invoke_tool(
        "change_space_group", {"space_group": "P n -3 m :2", "accept_absences": True}
    )
    assert result.ok, result.error
    node = result.summary["node"]
    assert node != before and p.nodes.node_meta(node)["data_revision"] == old_data
    declared = p.session.symmetry.space_group_info().type().hall_symbol()
    failed = p.invoke_tool("set_adp", {"atoms": ["missing"], "mode": "anisotropic"})
    assert not failed.ok
    assert p.session.model.space_group_info().type().hall_symbol() == declared
    next_call = p.invoke_tool("get_project_brief", {})
    assert next_call.ok, next_call.error
    assert p.session.symmetry.space_group_info().type().hall_symbol() == declared
    reopened = RefineProject(tmp_path)
    reopened.open()
    assert reopened.session.model.space_group_info().type().hall_symbol() == declared
    assert reopened.nodes.state()["active_node"] == node
    assert (tmp_path / "start.res").read_bytes() == original
    restored = reopened.invoke_tool("checkout", {"node": before})
    assert restored.ok, restored.error
    assert reopened.session.model.space_group_info().type().number() == 2
