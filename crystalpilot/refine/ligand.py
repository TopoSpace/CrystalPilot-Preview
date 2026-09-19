"""Ligand chemistry adapter: SMILES -> graph/3D template, model-fragment match.

check_ligand chains into fit_fragment: a subgraph MONOMORPHISM match of a
model fragment into the expected ligand graph yields (a) mapped pairs
[model_label, template_index] usable as fit anchors and (b) unmapped template
atoms adjacent to the mapped region = concrete missing-atom hypotheses.

All template numbering is RDKit's canonical atom order for the given SMILES;
3D templates are ETKDG-embedded with a fixed seed (deterministic).
Degrades to an explicit error dict when RDKit is unavailable.
"""
from __future__ import annotations

from typing import Any

_RD = None


def _rdkit():
    global _RD
    if _RD is None:
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem, rdMolDescriptors
            _RD = (Chem, AllChem, rdMolDescriptors)
        except ImportError:
            _RD = False
    return _RD


class LigandError(RuntimeError):
    pass


def ligand_graph(smiles: str) -> dict[str, Any]:
    rd = _rdkit()
    if not rd:
        raise LigandError("rdkit is not installed in this environment")
    Chem, _, rdMD = rd
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise LigandError(f"SMILES failed to parse: {smiles!r}")
    elements = [a.GetSymbol() for a in mol.GetAtoms()]
    adj: list[set[int]] = [set() for _ in elements]
    for b in mol.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        adj[i].add(j)
        adj[j].add(i)
    ring_info = mol.GetRingInfo()
    counts: dict[str, int] = {}
    for e in elements:
        counts[e] = counts.get(e, 0) + 1
    n_carboxylate = len(mol.GetSubstructMatches(
        Chem.MolFromSmarts("C(=O)[OX2H1,OX1-]")))
    return {
        "smiles": smiles,
        "formula": rdMD.CalcMolFormula(mol),
        "n_heavy": mol.GetNumHeavyAtoms(),
        "element_counts": counts,
        "ring_sizes": sorted(len(r) for r in ring_info.AtomRings()),
        "n_aromatic_rings": rdMD.CalcNumAromaticRings(mol),
        "n_carboxylate": n_carboxylate,
        "elements": elements,
        "adjacency": [sorted(s) for s in adj],
        "_mol": mol,
    }


def ideal_geometry(smiles: str, seed: int = 20260828) -> dict[str, Any]:
    """Heavy-atom 3D template (angstrom cartesian), deterministic."""
    rd = _rdkit()
    if not rd:
        raise LigandError("rdkit is not installed in this environment")
    Chem, AllChem, _ = rd
    g = ligand_graph(smiles)
    mol = Chem.AddHs(g["_mol"])
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    if AllChem.EmbedMolecule(mol, params) != 0:
        raise LigandError("3D embedding failed for this SMILES")
    AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
    conf = mol.GetConformer()
    coords = []
    for a in mol.GetAtoms():
        if a.GetAtomicNum() == 1:
            continue
        p = conf.GetAtomPosition(a.GetIdx())
        coords.append((p.x, p.y, p.z))
    g["coords"] = coords          # index-aligned with g["elements"]
    return g


# --------------------------------------------------------------------------
# subgraph monomorphism: model fragment graph -> ligand graph
# --------------------------------------------------------------------------
def match_fragment(fragment_elements: list[str],
                   fragment_adj: list[set[int]],
                   ligand: dict[str, Any],
                   time_budget_nodes: int = 200_000) -> list[dict[int, int]] | None:
    """Map every fragment atom onto a distinct ligand atom so that fragment
    edges map onto ligand edges. Returns up to 8 distinct mappings or None."""
    lig_elems = ligand["elements"]
    lig_adj = [set(x) for x in ligand["adjacency"]]
    n_f, n_l = len(fragment_elements), len(lig_elems)
    if n_f > n_l:
        return None
    order = sorted(range(n_f), key=lambda i: -len(fragment_adj[i]))
    candidates = [[j for j in range(n_l)
                   if lig_elems[j] == fragment_elements[i]
                   and len(lig_adj[j]) >= len(fragment_adj[i])]
                  for i in range(n_f)]
    if any(not c for c in candidates):
        return None
    results: list[dict[int, int]] = []
    used: set[int] = set()
    mapping: dict[int, int] = {}
    budget = [time_budget_nodes]

    def bt(k: int) -> None:
        if budget[0] <= 0 or len(results) >= 8:
            return
        if k == n_f:
            results.append(dict(mapping))
            return
        i = order[k]
        for j in candidates[i]:
            budget[0] -= 1
            if j in used:
                continue
            ok = True
            for nb in fragment_adj[i]:
                if nb in mapping and mapping[nb] not in lig_adj[j]:
                    ok = False
                    break
            if not ok:
                continue
            mapping[i] = j
            used.add(j)
            bt(k + 1)
            del mapping[i]
            used.discard(j)

    bt(0)
    return results or None


def assess_fragment(frag: dict[str, Any], ligand: dict[str, Any],
                    all_labels: list[str]) -> dict[str, Any]:
    """One organic fragment (from inspect.organic_fragments) vs the ligand."""
    labels = frag["atoms"]
    label_to_local = {l: k for k, l in enumerate(labels)}
    # rebuild the fragment's local adjacency from ring/dangling info is lossy;
    # caller passes the local adjacency in frag["_local_adj"] instead
    local_adj: list[set[int]] = frag["_local_adj"]
    elements = frag["_elements"]

    matches = match_fragment(elements, local_adj, ligand)
    out: dict[str, Any] = {
        "fragment_atoms": labels,
        "n_atoms": len(labels),
        "element_counts": frag["element_counts"],
        "matches_ligand_subgraph": bool(matches),
        "sym_bonded_atoms": frag.get("sym_bonded_atoms", []),
    }
    if not matches:
        out["note"] = ("fragment is NOT a subgraph of the expected ligand - "
                       "either solvent/other species, or wrongly connected atoms")
        return out
    m = matches[0]
    mapped_pairs = [[labels[i], int(m[i])] for i in sorted(m)]
    mapped_t = set(m.values())
    lig_adj = ligand["adjacency"]
    missing = []
    for t in sorted(mapped_t):
        for nb in lig_adj[t]:
            if nb not in mapped_t:
                missing.append({"template_index": int(nb),
                                "element": ligand["elements"][nb],
                                "bonded_to": [[labels[i], int(m[i])]
                                              for i in m if m[i] == t]})
    dedup: dict[int, dict] = {}
    for x in missing:
        e = dedup.setdefault(x["template_index"], x)
        if e is not x:
            e["bonded_to"].extend(b for b in x["bonded_to"]
                                  if b not in e["bonded_to"])
    out["mapped_pairs"] = mapped_pairs          # [model_label, template_index]
    out["missing_template_neighbors"] = list(dedup.values())
    out["n_matches_found"] = len(matches)
    if frag.get("sym_bonded_atoms"):
        out["caveat"] = (
            "atoms " + ",".join(frag["sym_bonded_atoms"]) + " bond to symmetry "
            "copies; apparent missing neighbors reached through them may exist "
            "crystallographically - verify against the difference map before adding")
    return out
