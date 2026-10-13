"""Tests for src/graph_comparator.py. Run from the ArchLens folder: python -m pytest -v"""
from pathlib import Path

import networkx as nx

from src.graph_builder import build_from_source, save_graph
from src.graph_comparator import compare_graphs, main

FIX = Path(__file__).parent / "fixtures"
P = "com.example."


def g(nodes, edges, label):
    graph = nx.DiGraph()
    graph.graph["metadata"] = {"label": label}
    graph.add_nodes_from(nodes)
    for s, t in edges:
        graph.add_edge(s, t, kinds=["field"], evidence=[])
    return graph


def pairs(records):
    return {(r["source"], r["target"]) for r in records}


def test_identical_graphs_have_no_changes():
    a = g(["A", "B"], [("A", "B")], "v1")
    d = compare_graphs(a, a.copy())
    s = d["summary"]
    assert (s["added_nodes"], s["removed_nodes"], s["added_edges"], s["removed_edges"]) == (0, 0, 0, 0)
    assert s["unchanged_edges"] == 1


def test_small_known_difference():
    before = g(["A", "B", "C"], [("A", "B"), ("B", "C")], "v1")
    after = g(["A", "B", "D"], [("A", "B"), ("A", "D")], "v2")
    d = compare_graphs(before, after)
    assert d["added_nodes"] == ["D"] and d["removed_nodes"] == ["C"]
    assert pairs(d["added_edges"]) == {("A", "D")}
    assert pairs(d["removed_edges"]) == {("B", "C")}
    assert pairs(d["unchanged_edges"]) == {("A", "B")}
    assert d["added_edges"][0]["target_is_new"] is True
    assert d["removed_edges"][0]["target_removed"] is True
    assert d["before"]["label"] == "v1" and d["after"]["label"] == "v2"


def test_new_edge_between_existing_nodes_is_flagged_as_such():
    before = g(["A", "B"], [], "v1")
    after = g(["A", "B"], [("A", "B")], "v2")
    e = compare_graphs(before, after)["added_edges"][0]
    assert e["source_is_new"] is False and e["target_is_new"] is False


def test_empty_graphs():
    d = compare_graphs(g([], [], "a"), g([], [], "b"))
    assert d["summary"]["edges_before"] == d["summary"]["edges_after"] == 0


def test_fixture_versions_match_answer_key():
    """tests/fixtures/sample_java_v2/CHANGES.md documents these expected changes."""
    d = compare_graphs(build_from_source(FIX / "sample_java"),
                       build_from_source(FIX / "sample_java_v2"))
    assert d["added_nodes"] == [P + "controller.AdminController"]
    assert d["removed_nodes"] == [P + "service.UserService.Cache"]
    assert pairs(d["added_edges"]) == {
        (P + "controller.AdminController", P + "repository.JdbcUserRepository"),
        (P + "controller.AdminController", P + "model.User"),
    }
    assert pairs(d["removed_edges"]) == {
        (P + "service.UserService", P + "repository.JdbcUserRepository"),
        (P + "service.UserService.Cache", P + "model.User"),
    }
    assert d["summary"]["unchanged_edges"] == 7


def test_added_edge_carries_evidence_from_new_version():
    d = compare_graphs(build_from_source(FIX / "sample_java"),
                       build_from_source(FIX / "sample_java_v2"))
    e = next(x for x in d["added_edges"] if x["target"].endswith("JdbcUserRepository"))
    assert e["evidence"][0]["file"].endswith("controller/AdminController.java")
    assert {ev["line"] for ev in e["evidence"]} == {7}


def test_cli(tmp_path):
    a, b, out = tmp_path / "a.json", tmp_path / "b.json", tmp_path / "d.json"
    save_graph(build_from_source(FIX / "sample_java", {"label": "v1"}), a)
    save_graph(build_from_source(FIX / "sample_java_v2", {"label": "v2"}), b)
    assert main([str(a), str(b), "-o", str(out)]) == 0
    assert '"schema": "archlens-diff/1"' in out.read_text(encoding="utf-8")


def test_cli_missing_file(tmp_path):
    assert main([str(tmp_path / "nope.json"), str(tmp_path / "nope2.json")]) == 2
