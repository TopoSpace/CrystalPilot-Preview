# Contributing

CrystalPilot is published as a development preview under a non-commercial
academic license. Bug reports, reproducible failure cases and suggestions are
welcome through the issue tracker. Code contributions and derivative work
require a prior written agreement with TopoSpace (section 3 of the LICENSE), so
please open an issue first and describe what you have in mind.

## Reporting a problem

State the commit you are running, the operating system, and the model provider
in use. Attach the relevant part of the conversation transcript and, where
possible, a minimal `crystal.hkl` and `start.ins` pair that reproduces the
behaviour. Remove any API key or personal path before attaching files.

## Development setup

The README section "Running it" describes a full installation. In short:

```bash
python -m venv .venv
.venv/Scripts/pip install -e .[server,workbench,refine,dev]
cd ui && npm ci && cd ..
```

The Python test suite runs with `pytest`; `pyproject.toml` already places its
temporary directory outside the source tree. Tests that need SHELXL, PLATON,
DIALS or the sample projects skip when those are absent. The interface has unit
tests (`npm test` in `ui/`) and Playwright specifications (`npm run e2e`, which
expect a running server on port 8010).

## Conventions

- Python code targets 3.11 and is linted with `ruff` using the settings in
  `pyproject.toml`. TypeScript is checked by `tsc` as part of `npm run build`.
- Commit titles are short, written in English in the imperative mood; the body
  explains what changed and why.
- Nothing under `secrets/` and no API key may appear in a commit, a log line or
  a test fixture.
- Changes to the crystallographic tools must stay general. Behaviour tuned to a
  particular test crystal is not accepted; new criteria are covered by tests on
  synthetic structures.
