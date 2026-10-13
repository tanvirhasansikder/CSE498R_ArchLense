"""Tests for src/graph_builder.py. Run from the ArchLens folder: python -m pytest -v"""
import json
from pathlib import Path

import pytest

from src.graph_builder import (build_from_source, build_graph, graph_from_dict,
                               graph_to_dict, load_graph, main, save_graph)

SAMPLE = Path(__file__).parent / "fixtures" / "sample_java"


@pytest.fixture(scope="module")
def graph():
    return build_from_source(SAMPLE, {"label": "v1", "commit": "abc123"})


def test_nodes_and_edges_match_extractor(graph):
    assert graph.number_of_nodes() == 6
    assert graph.number_of_edges() == 9
    assert graph.has_edge("com.example.service.UserService",
                          "com.example.repository.JdbcUserRepository")


def test_node_and_edge_attributes(graph):
    node = graph.nodes["com.example.repository.UserRepository"]
    assert node["kind"] == "interface"
    assert node["path"].endswith("repository/UserRepository.java")
    e = graph.edges["com.example.controller.UserController", "com.example.service.UserService"]
    assert e["kinds"] == ["field", "object_creation"]
    assert e["weight"] == len(e["evidence"]) == 2   # field type + new UserService<>()


def test_metadata_is_recorded(graph):
    m = graph.graph["metadata"]
    assert m["label"] == "v1" and m["commit"] == "abc123"
    assert m["source_dir"].endswith("sample_java")


def test_save_and_reload_round_trip(graph, tmp_path):
    path = tmp_path / "g.json"
    save_graph(graph, path)
    reloaded = load_graph(path)
    assert set(reloaded.nodes) == set(graph.nodes)
    assert set(reloaded.edges) == set(graph.edges)
    assert graph_to_dict(reloaded) == graph_to_dict(graph)


def test_output_is_deterministic(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    save_graph(build_from_source(SAMPLE, {"label": "x"}), a)
    save_graph(build_from_source(SAMPLE, {"label": "x"}), b)
    assert a.read_bytes() == b.read_bytes()


def test_wrong_schema_is_rejected():
    with pytest.raises(ValueError):
        graph_from_dict({"schema": "something-else", "nodes": [], "edges": []})


def test_edge_to_unknown_node_is_rejected():
    report = {"summary": {}, "external_references": {}, "unresolved_references": [],
              "import_only": [], "nodes": [{"id": "a.A", "path": "A.java", "line": 1,
                                             "kind": "class"}],
              "dependencies": [{"source": "a.A", "target": "a.Ghost",
                                "kinds": ["field"], "evidence": []}]}
    with pytest.raises(ValueError):
        build_graph(report)


def test_cli(tmp_path):
    out = tmp_path / "g.json"
    assert main([str(SAMPLE), "-o", str(out), "--label", "v1"]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "archlens-graph/1"
    assert doc["stats"] == {"nodes": 6, "edges": 9}
