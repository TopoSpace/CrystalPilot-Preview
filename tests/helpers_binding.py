"""Bind a legacy fixture project the way a user would.

Since 2026-09-08 a node reads only the observation revision it is bound
to. Fixture projects copied from before data revisions existed (the
demo-live-sjtu9 / pa1 hex-l2-r1 / mvp-sjtu9 workspaces) have nodes with no
`data_revision`, so every reflection tool refuses them with
DataBindingRequired until someone states which HKL matches. That is the
rule the product enforces on real legacy projects too, so tests bind the
same way - through swap_reflection_data(model_node=...) - rather than by
editing node.json behind the store's back. Not a test module (no test_
prefix): import it.
"""
from __future__ import annotations


def bind_legacy_project(p, reason: str = "test fixture: bind the legacy model to its own crystal.hkl") -> str:
    """Bind the active (unbound) node to the project's own crystal.hkl and
    return the id of the bound child node that is now active."""
    active = p.nodes.state()["active_node"]
    r = p.invoke_tool("swap_reflection_data",
                      {"model_node": active, "hkl": "crystal.hkl", "reason": reason})
    assert r.ok, f"binding the legacy fixture failed: {r.error}"
    node = p.nodes.state()["active_node"]
    assert p.nodes.node_meta(node).get("data_revision"), "bound node carries no data_revision"
    return node
