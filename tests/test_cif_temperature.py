"""WP4: an unmeasured temperature must never reach the CIF as a number.

Evidence (docs/ka1-2026-09-03/ka1-readout-cage.md S5.3 item 1,
ka1-readout-hex.md finding 7): every delivered CIF in the ablation carried
`_cell_measurement_temperature 293(2)` / `_diffrn_ambient_temperature
293(2)` even on blind data where no temperature was ever provided, and even
after an agent correctly called set_experiment(temperature_K=null). Root
cause: SHELXL assumes 20 C (293 K) internally (a harmless approximation for
riding-H bond-length/ADP geometry when no TEMP card is given) and prints
that same 293(2) into the ACTA CIF's temperature tags as if it had been
measured; crystalpilot.report.publication.assemble_publication_cif() never
overrode it when the experiment block carried no temperature_K - it only
appended an explanatory caveat and left SHELXL's number standing.

These tests exercise the real assembler code path (assemble_publication_cif)
and the real set_experiment tool - no shelxl.exe subprocess is needed since
the bug and the fix both live entirely in Python CIF-text post-processing.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from crystalpilot.refine.tools_ingest import SetExperiment
from crystalpilot.report.publication import assemble_publication_cif
from test_publication import MINI_ACTA


def test_no_temperature_becomes_unknown_not_shelxl_default():
    """No experiment block at all -> both temperature tags forced to '?',
    never left at SHELXL's silently-assumed 293(2)."""
    out, rep = assemble_publication_cif(MINI_ACTA)
    assert "293(2)" not in out
    assert "_diffrn_ambient_temperature       ?" in out
    assert "_cell_measurement_temperature     ?" in out
    assert "_diffrn_ambient_temperature" in rep["remaining_placeholders"]
    assert "_cell_measurement_temperature" in rep["remaining_placeholders"]
    # the override is disclosed, not silent
    assert any("293(2)" in c for c in rep["caveats"])


def test_temperature_k_none_explicit_also_becomes_unknown():
    """experiment={'temperature_K': None} (the shape set_experiment leaves
    behind once a bogus placeholder is purged) behaves identically to no
    experiment block at all."""
    out, rep = assemble_publication_cif(MINI_ACTA,
                                        experiment={"temperature_K": None})
    assert "293(2)" not in out
    assert "_diffrn_ambient_temperature       ?" in out
    assert "_cell_measurement_temperature     ?" in out


def test_known_temperature_is_written_with_the_codes_own_formatting():
    """temperature_K=100.0 -> both tags carry '100', not a fabricated ESD
    like '100(2)' that the code never computed."""
    out, rep = assemble_publication_cif(
        MINI_ACTA, experiment={"temperature_K": 100.0})
    assert "_diffrn_ambient_temperature       100" in out
    assert "_cell_measurement_temperature     100" in out
    assert "100(2)" not in out
    assert "293(2)" not in out


def _proj(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    proj = SimpleNamespace(dir=d, context={})
    # mirror crystalpilot.refine.project.Project.experiment(): context.json
    # experiment block wins (no _model_experiment in this lightweight double)
    proj.experiment = lambda: dict(proj.context.get("experiment") or {})
    return proj


def _set_experiment(proj, **kw):
    return SetExperiment(proj).run(SimpleNamespace(session=None), **kw)


def test_set_experiment_null_reply_is_forward_looking_not_a_false_claim(
        tmp_path):
    """set_experiment(temperature_K=null) must not claim, in the present
    tense, that the publication CIF 'carries ?' - that only becomes true
    once write_outputs actually runs again. No delivery exists yet in this
    test, so there is nothing stale to flag."""
    proj = _proj(tmp_path)
    r0 = _set_experiment(proj, experiment={"temperature_K": 293},
                         provenance="placeholder injected by CIF import")
    assert r0.ok, r0.error

    r = _set_experiment(proj, experiment={"temperature_K": None},
                        provenance="placeholder was bogus - fact unknown")
    assert r.ok, r.error
    assert r.summary["removed"] == ["temperature_K"]
    note = r.summary["note"]
    # the old wording flatly asserted the CIF already carries '?' - false
    # whenever a delivery had already been written with the old value
    assert "the publication CIF carries" not in note
    assert "write_outputs" in note
    # nothing on disk yet -> nothing to flag as stale
    assert "stale_deliveries" not in r.summary
    assert "STALE DELIVERY" not in note


def test_set_experiment_null_flags_a_stale_delivery_on_disk(tmp_path):
    """If a final.cif was already written (by a prior write_outputs) with
    the temperature that is now being purged, the reply must say so
    explicitly and point at write_outputs - not stay silent about a
    delivery on disk that is now wrong."""
    proj = _proj(tmp_path)
    r0 = _set_experiment(proj, experiment={"temperature_K": 100.0},
                         provenance="user email 2026-08-30")
    assert r0.ok, r0.error

    out_dir = proj.dir / "deliverables"
    out_dir.mkdir()
    stale_cif = out_dir / "final.cif"
    stale_cif.write_text(
        "data_test\n"
        "_diffrn_ambient_temperature       100\n"
        "_cell_measurement_temperature     100\n",
        encoding="utf-8")

    r = _set_experiment(proj, experiment={"temperature_K": None},
                        provenance="100 K reading was for the wrong run")
    assert r.ok, r.error
    assert r.summary["removed"] == ["temperature_K"]

    stale = r.summary.get("stale_deliveries")
    assert stale, r.summary
    assert len(stale) == 1
    assert (proj.dir / stale[0]).resolve() == stale_cif.resolve()

    note = r.summary["note"]
    assert "STALE DELIVERY" in note
    assert "write_outputs" in note
    assert "final.cif" in note


def test_set_experiment_known_temperature_does_not_false_flag_a_matching_delivery(
        tmp_path):
    """A final.cif already on disk that AGREES with the newly-set
    temperature must not be reported as stale."""
    proj = _proj(tmp_path)
    out_dir = proj.dir / "deliverables"
    out_dir.mkdir()
    (out_dir / "final.cif").write_text(
        "data_test\n"
        "_diffrn_ambient_temperature       150\n"
        "_cell_measurement_temperature     150\n",
        encoding="utf-8")

    r = _set_experiment(proj, experiment={"temperature_K": 150.0},
                        provenance="user email 2026-08-30")
    assert r.ok, r.error
    assert "stale_deliveries" not in r.summary
    assert "STALE DELIVERY" not in r.summary["note"]

