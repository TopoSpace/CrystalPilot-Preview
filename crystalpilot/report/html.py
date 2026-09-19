"""Self-contained HTML report: metrics, validation, AI trajectory, embedded 3D viewer.

Single shareable file; 3Dmol.js is loaded from CDN (offline fallback: the static
content still renders without the viewer).
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

_CSS = """
:root { --fg:#18181b; --muted:#71717a; --line:#e4e4e7; --bg:#fff; --card:#fafafa;
        --accent:#4f46e5; --ok:#16a34a; --warn:#d97706; --bad:#dc2626; }
* { box-sizing:border-box; }
body { font:14px/1.55 -apple-system,'Segoe UI',Roboto,'Inter',sans-serif;
       color:var(--fg); background:var(--bg); margin:0 auto; max-width:960px;
       padding:48px 32px; }
h1 { font-size:22px; letter-spacing:-0.02em; margin:0 0 4px; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:0.08em;
     color:var(--muted); margin:36px 0 12px; font-weight:600; }
.sub { color:var(--muted); margin-bottom:28px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; }
.card { border:1px solid var(--line); border-radius:10px; padding:12px 14px;
        background:var(--card); }
.card .k { font-size:11px; text-transform:uppercase; letter-spacing:0.06em;
           color:var(--muted); }
.card .v { font-size:19px; font-variant-numeric:tabular-nums;
           font-family:ui-monospace,Consolas,monospace; margin-top:2px; }
.badge { display:inline-block; border-radius:99px; padding:1px 10px; font-size:12px; }
.badge.high { background:#dcfce7; color:var(--ok); }
.badge.medium { background:#fef3c7; color:var(--warn); }
.badge.low { background:#fee2e2; color:var(--bad); }
.alert { border-left:3px solid var(--warn); padding:6px 12px; margin:6px 0;
         background:var(--card); border-radius:0 8px 8px 0; font-size:13px; }
.alert.critical { border-color:var(--bad); }
.alert.info { border-color:var(--line); color:var(--muted); }
table { border-collapse:collapse; width:100%; font-size:13px;
        font-variant-numeric:tabular-nums; }
th,td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); }
th { font-size:11px; text-transform:uppercase; letter-spacing:0.06em;
     color:var(--muted); font-weight:600; }
#viewer { width:100%; height:480px; border:1px solid var(--line);
          border-radius:10px; position:relative; }
.thought { color:var(--muted); font-size:13px; margin:8px 0; padding-left:14px;
           border-left:2px solid var(--line); }
.mono { font-family:ui-monospace,Consolas,monospace; }
footer { margin-top:48px; color:var(--muted); font-size:12px; }
"""


def _metric_cards(stats: dict[str, Any]) -> str:
    items = [
        ("R1 (strong)", stats.get("r1_strong")), ("R1 (all)", stats.get("r1_all")),
        ("wR2", stats.get("wr2")), ("GooF", stats.get("goof")),
        ("Reflections", stats.get("n_reflections")),
        ("Parameters", stats.get("n_params")),
        ("Δρ max (e/Å³)", stats.get("diff_map_max")),
        ("Δρ min (e/Å³)", stats.get("diff_map_min")),
    ]
    cards = "".join(
        f'<div class="card"><div class="k">{html.escape(k)}</div>'
        f'<div class="v">{v if v is not None else "—"}</div></div>'
        for k, v in items)
    return f'<div class="grid">{cards}</div>'


def write_html_report(path: Path, *, title: str, report: dict[str, Any],
                      cif_text: str | None = None,
                      agent_thoughts: list[str] | None = None) -> Path:
    symmetry = report.get("symmetry") or {}
    refinement = report.get("refinement") or {}
    validation = report.get("validation") or {}
    conf = (validation.get("confidence") or {})
    mask = report.get("solvent_mask") or {}
    agent = report.get("agent") or {}

    parts: list[str] = []
    p = parts.append
    p("<!doctype html><html><head><meta charset='utf-8'>")
    p(f"<title>{html.escape(title)} - CrystalPilot</title>")
    p(f"<style>{_CSS}</style></head><body>")
    p(f"<h1>{html.escape(title)}</h1>")
    grade = conf.get("grade", "")
    p(f"<div class='sub'>CrystalPilot structure report · "
      f"space group <span class='mono'>{html.escape(str(symmetry.get('space_group', '?')))}</span>"
      + (f" · confidence <b>{conf.get('score', '—')}/100</b> "
         f"<span class='badge {grade}'>{grade}</span>" if conf else "")
      + "</div>")

    p("<h2>Refinement</h2>")
    p(_metric_cards(refinement))

    if mask:
        p("<h2>Solvent mask</h2>")
        p(f"<div class='sub'>{mask.get('n_voids_masked', 0)} void(s) masked · "
          f"{mask.get('total_solvent_electrons_per_cell', '?')} e⁻/cell · "
          f"{mask.get('solvent_volume_pct_of_cell', '?')}% of cell volume</div>")

    alerts = validation.get("alerts") or []
    p("<h2>Validation</h2>")
    if alerts:
        for a in alerts:
            p(f"<div class='alert {a.get('severity','info')}'>"
              f"<b>{html.escape(a.get('code',''))}</b> · "
              f"{html.escape(a.get('message',''))}</div>")
    else:
        p("<div class='sub'>No validation alerts.</div>")

    if agent.get("assessment"):
        p("<h2>AI assessment</h2>")
        p(f"<div class='sub'>{html.escape(agent['assessment'])}</div>")
        for issue in agent.get("remaining_issues") or []:
            p(f"<div class='alert info'>{html.escape(issue)}</div>")

    hist = report.get("refinement_history") or []
    if hist:
        p("<h2>Refinement trajectory</h2><table><tr><th>stage</th><th>R1</th>"
          "<th>wR2</th><th>GooF</th><th>Δρ max/min</th></tr>")
        for h_ in hist:
            p(f"<tr><td>{html.escape(str(h_.get('label')))}</td>"
              f"<td>{h_.get('r1_strong')}</td><td>{h_.get('wr2')}</td>"
              f"<td>{h_.get('goof')}</td>"
              f"<td>{h_.get('diff_map_max')} / {h_.get('diff_map_min')}</td></tr>")
        p("</table>")

    if agent_thoughts:
        p("<h2>AI reasoning highlights</h2>")
        for t in agent_thoughts[:12]:
            p(f"<div class='thought'>{html.escape(t[:400])}</div>")

    if cif_text:
        p("<h2>Structure</h2><div id='viewer'></div>")
        p("<script src='https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.4.0/3Dmol-min.js'></script>")
        cif_js = json.dumps(cif_text.replace("_space_group_symop_operation_xyz",
                                             "_symmetry_equiv_pos_as_xyz"))
        p("<script>(function(){if(!window.$3Dmol)return;"
          "var v=$3Dmol.createViewer('viewer',{backgroundColor:'white'});"
          f"var cif={cif_js};"
          "v.addModel(cif,'cif');v.setStyle({},{stick:{radius:0.12},"
          "sphere:{scale:0.25}});v.addUnitCell();v.zoomTo();v.zoom(1.2);v.render();})();"
          "</script>")

    p("<footer>Generated by CrystalPilot · all agent actions are recorded in "
      "events.jsonl alongside this report</footer>")
    p("</body></html>")
    path = Path(path)
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
