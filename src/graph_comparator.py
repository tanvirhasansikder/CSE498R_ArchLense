"""ArchLens graph comparator (Phase 2).

Compares the architecture graphs of two versions and reports *structural*
changes only: added / removed / unchanged nodes and edges. It does not decide
whether a change is good or bad - that is the rule engine's job (Phase 3).

Identity is by fully qualified name, so a class that is renamed or moved to a
different package appears as one removed node plus one added node.

Usage (from the ArchLens folder):
    python -m src.graph_comparator results/before.json results/after.json -o results/diff.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import networkx as nx

from src.graph_builder import load_graph

SCHEMA = "archlens-diff/1"


def _edge_record(g: nx.DiGraph, s: str, t: str) -> dict:
    data = g.edges[s, t]
    return {"source": s, "target": t, "kinds": data.get("kinds", []),
            "evidence": data.get("evidence", [])}


def compare_graphs(before: nx.DiGraph, after: nx.DiGraph) -> dict:
    b_nodes, a_nodes = set(before.nodes), set(after.nodes)
    b_edges, a_edges = set(before.edges), set(after.edges)

    added_nodes = sorted(a_nodes - b_nodes)
    removed_nodes = sorted(b_nodes - a_nodes)
    added_node_set, removed_node_set = set(added_nodes), set(removed_nodes)

    added_edges = []
    for s, t in sorted(a_edges - b_edges):
        rec = _edge_record(after, s, t)      # evidence from the version where it exists
        rec["source_is_new"] = s in added_node_set
        rec["target_is_new"] = t in added_node_set
        added_edges.append(rec)

    removed_edges = []
    for s, t in sorted(b_edges - a_edges):
        rec = _edge_record(before, s, t)
        rec["source_removed"] = s in removed_node_set
        rec["target_removed"] = t in removed_node_set
        removed_edges.append(rec)

    unchanged_edges = [{"source": s, "target": t} for s, t in sorted(a_edges & b_edges)]

    return {
        "schema": SCHEMA,
        "before": before.graph.get("metadata", {}),
        "after": after.graph.get("metadata", {}),
        "summary": {
            "nodes_before": len(b_nodes), "nodes_after": len(a_nodes),
            "edges_before": len(b_edges), "edges_after": len(a_edges),
            "added_nodes": len(added_nodes), "removed_nodes": len(removed_nodes),
            "unchanged_nodes": len(a_nodes & b_nodes),
            "added_edges": len(added_edges), "removed_edges": len(removed_edges),
            "unchanged_edges": len(unchanged_edges),
        },
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "unchanged_edges": unchanged_edges,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare two ArchLens graph JSON files.")
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)

    for p in (args.before, args.after):
        if not p.is_file():
            print(f"ERROR: graph file not found: {p}", file=sys.stderr)
            return 2

    diff = compare_graphs(load_graph(args.before), load_graph(args.after))
    s = diff["summary"]
    label = lambda m: m.get("label") or m.get("commit") or m.get("source_dir", "?")
    print(f"Comparing {label(diff['before'])} -> {label(diff['after'])}")
    print(f"  nodes: {s['nodes_before']} -> {s['nodes_after']}  "
          f"(+{s['added_nodes']} / -{s['removed_nodes']})")
    print(f"  edges: {s['edges_before']} -> {s['edges_after']}  "
          f"(+{s['added_edges']} / -{s['removed_edges']} / ={s['unchanged_edges']})")
    for n in diff["added_nodes"]:
        print(f"  + node {n}")
    for n in diff["removed_nodes"]:
        print(f"  - node {n}")
    for e in diff["added_edges"]:
        print(f"  + {e['source']} -> {e['target']}  {e['kinds']}")
    for e in diff["removed_edges"]:
        print(f"  - {e['source']} -> {e['target']}  {e['kinds']}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(diff, indent=2) + "\n", encoding="utf-8")
        print(f"Written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
