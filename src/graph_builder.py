"""ArchLens architecture graph builder (Phase 2).

Turns the dependency extractor's output into a NetworkX directed graph and
saves / reloads it as JSON.

  node = a project type (class, interface, enum, record), id = fully qualified name
  edge = source depends on target; carries the reference kinds and all evidence

The JSON format is ArchLens's own (schema "archlens-graph/1") rather than
NetworkX's node_link format, whose key names have changed between versions.
Output is sorted and has no timestamps, so the same input always gives a
byte-identical file - this is what makes runs reproducible and diffable.

Usage (from the ArchLens folder):
    python -m src.graph_builder <java_source_dir> -o results/graph.json
        [--repo URL] [--commit HASH] [--label NAME]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import networkx as nx

from src.dependency_extractor import extract_dependencies
from src.parser import JavaParser

log = logging.getLogger("archlens.graph_builder")

SCHEMA = "archlens-graph/1"


def build_graph(dep_report: dict, metadata: dict | None = None) -> nx.DiGraph:
    """Build a directed graph from extract_dependencies() output."""
    g = nx.DiGraph()
    g.graph["metadata"] = dict(metadata or {})
    g.graph["analysis"] = {
        "summary": dep_report["summary"],
        "external_references": dep_report["external_references"],
        "unresolved_references": dep_report["unresolved_references"],
        "import_only": dep_report["import_only"],
    }
    for n in dep_report["nodes"]:
        node_id = n["id"]
        g.add_node(node_id, path=n["path"], line=n["line"], kind=n["kind"])
    for d in dep_report["dependencies"]:
        for end in (d["source"], d["target"]):
            if end not in g:   # should not happen: edges only connect project types
                raise ValueError(f"Edge endpoint {end!r} is not a known project type")
        g.add_edge(d["source"], d["target"], kinds=list(d["kinds"]),
                   evidence=list(d["evidence"]), weight=len(d["evidence"]))
    return g


def graph_to_dict(g: nx.DiGraph) -> dict:
    return {
        "schema": SCHEMA,
        "metadata": g.graph.get("metadata", {}),
        "stats": {"nodes": g.number_of_nodes(), "edges": g.number_of_edges()},
        "nodes": [{"id": n, **g.nodes[n]} for n in sorted(g.nodes)],
        "edges": [{"source": s, "target": t, **g.edges[s, t]}
                  for s, t in sorted(g.edges)],
        "analysis": g.graph.get("analysis", {}),
    }


def graph_from_dict(doc: dict) -> nx.DiGraph:
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"Unsupported graph schema {doc.get('schema')!r}, expected {SCHEMA!r}")
    g = nx.DiGraph()
    g.graph["metadata"] = doc.get("metadata", {})
    g.graph["analysis"] = doc.get("analysis", {})
    for n in doc["nodes"]:
        attrs = {k: v for k, v in n.items() if k != "id"}
        g.add_node(n["id"], **attrs)
    for e in doc["edges"]:
        attrs = {k: v for k, v in e.items() if k not in ("source", "target")}
        g.add_edge(e["source"], e["target"], **attrs)
    return g


def save_graph(g: nx.DiGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph_to_dict(g), indent=2, sort_keys=False) + "\n",
                    encoding="utf-8")


def load_graph(path: Path) -> nx.DiGraph:
    return graph_from_dict(json.loads(path.read_text(encoding="utf-8")))


def build_from_source(source_dir: Path, metadata: dict | None = None) -> nx.DiGraph:
    meta = {"source_dir": Path(source_dir).as_posix(), **(metadata or {})}
    return build_graph(extract_dependencies(JavaParser().parse_directory(source_dir)), meta)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build an ArchLens architecture graph.")
    ap.add_argument("source_dir", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--repo", help="Repository URL or name (recorded as metadata)")
    ap.add_argument("--commit", help="Commit hash (recorded as metadata)")
    ap.add_argument("--label", help="Version label, e.g. v1.0 or before (recorded as metadata)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    meta = {k: v for k, v in (("repo", args.repo), ("commit", args.commit),
                              ("label", args.label)) if v}
    try:
        g = build_from_source(args.source_dir, meta)
    except NotADirectoryError as exc:
        log.error("%s", exc)
        return 2
    save_graph(g, args.output)
    s = g.graph["analysis"]["summary"]
    print(f"Graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges "
          f"(unresolved references: {s['references_unresolved']}, "
          f"of which could be project types: {s['unresolved_could_be_internal']}, "
          f"files with parse errors: {s['files_with_parse_errors']})")
    print(f"Written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
