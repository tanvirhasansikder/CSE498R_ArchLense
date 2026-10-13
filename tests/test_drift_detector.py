"""Tests for src/drift_detector.py. Run from the ArchLens folder: python -m pytest -v"""
import copy
import json
from pathlib import Path

import networkx as nx
import pytest

from src.drift_detector import DriftDetector, load_rules, main, validate_rules
from src.graph_builder import build_from_source, save_graph

FIX = Path(__file__).parent / "fixtures"
RULES = FIX / "sample_rules.json"
P = "com.example."


@pytest.fixture(scope="module")
def config():
    return load_rules(RULES)


@pytest.fixture(scope="module")
def v1():
    return build_from_source(FIX / "sample_java", {"repo": "sample", "commit": "c1"})


@pytest.fixture(scope="module")
def v2():
    return build_from_source(FIX / "sample_java_v2", {"repo": "sample", "commit": "c2"})


def keyset(report, status=None):
    return {(f["rule_id"], f["source"], f["target"]) for f in report["findings"]
            if status is None or f["status"] == status}


def test_snapshot_finds_known_violation(config, v1):
    r = DriftDetector(config).analyze_snapshot(v1)
    assert keyset(r) == {("T-001", P + "service.UserService", P + "repository.JdbcUserRepository")}
    assert r["findings"][0]["status"] == "present"


def test_valid_dependencies_are_not_findings(config, v1):
    r = DriftDetector(config).analyze_snapshot(v1)
    sources_targets = {(f["source"], f["target"]) for f in r["findings"]}
    # service -> repository interface is allowed; controller -> service is allowed
    assert (P + "service.UserService", P + "repository.UserRepository") not in sources_targets
    assert (P + "controller.UserController", P + "service.UserService") not in sources_targets


def test_change_analysis_introduced_resolved(config, v1, v2):
    r = DriftDetector(config).analyze_change(v1, v2)
    assert keyset(r, "introduced") == {
        ("T-002", P + "controller.AdminController", P + "repository.JdbcUserRepository")}
    assert keyset(r, "resolved") == {
        ("T-001", P + "service.UserService", P + "repository.JdbcUserRepository")}
    assert keyset(r, "persisting") == set()
    assert r["summary"]["introduced (drift)"] == 1


def test_structural_change_without_rule_breach_is_not_drift(config, v1, v2):
    """v1 -> v2 also removes UserService.Cache and its edge: a structural change, not drift."""
    r = DriftDetector(config).analyze_change(v1, v2)
    involved = {f["source"] for f in r["findings"]} | {f["target"] for f in r["findings"]}
    assert P + "service.UserService.Cache" not in involved
    assert len(r["findings"]) == 2


def test_unchanged_violation_is_persisting_not_drift(config, v1):
    r = DriftDetector(config).analyze_change(v1, v1.copy())
    assert {f["status"] for f in r["findings"]} == {"persisting"}
    assert r["summary"]["introduced (drift)"] == 0


def test_findings_carry_evidence_and_stable_ids(config, v1, v2):
    d = DriftDetector(config)
    a, b = d.analyze_change(v1, v2), d.analyze_change(v1, v2)
    assert [f["finding_id"] for f in a["findings"]] == [f["finding_id"] for f in b["findings"]]
    f = next(x for x in a["findings"] if x["status"] == "introduced")
    assert f["before_commit"] == "c1" and f["after_commit"] == "c2"
    assert f["evidence"][0]["file"].endswith("controller/AdminController.java")
    assert f["evidence"][0]["line"] == 7
    assert f["source_layer"] == "controller" and f["target_layer"] == "persistence_impl"
    assert "explicit class mapping" in f["reason"]


def test_rule_not_applicable_when_layer_is_empty(config, v1):
    cfg = copy.deepcopy(config)
    cfg["classes"] = {}            # nothing is persistence_impl any more
    r = DriftDetector(cfg).analyze_snapshot(v1)
    assert r["rule_applicability"]["T-001"]["applicable"] is False
    assert r["rule_applicability"]["T-002"]["applicable"] is True
    assert all(f["rule_id"] != "T-001" for f in r["findings"])


def test_rules_for_another_repository_are_not_applied(config):
    g = build_from_source(FIX / "sample_java", {"repo": "some-other-project"})
    r = DriftDetector(config).analyze_snapshot(g)
    assert not any(a["applicable"] for a in r["rule_applicability"].values())
    assert r["findings"] == []


def test_unclassified_edges_are_counted_not_judged(config):
    g = nx.DiGraph()
    g.graph["metadata"] = {"repo": "sample"}
    g.add_edge(P + "service.S", "org.other.Unknown", kinds=["field"], evidence=[])
    g.add_edge(P + "service.S", P + "repository.JdbcUserRepository", kinds=["field"], evidence=[])
    r = DriftDetector(config).analyze_snapshot(g)
    assert r["edges_not_evaluated_unclassified"]["snapshot"] == 1
    assert "org.other.Unknown" in r["classification"]["snapshot"]["unclassified"]
    assert len(r["findings"]) == 1


def test_invalid_rules_rejected(config):
    bad = copy.deepcopy(config)
    bad["rules"][0]["forbidden_target_layers"] = ["no_such_layer"]
    with pytest.raises(ValueError):
        validate_rules(bad)
    dup = copy.deepcopy(config)
    dup["rules"][1]["id"] = dup["rules"][0]["id"]
    with pytest.raises(ValueError):
        validate_rules(dup)


def test_project_rule_file_is_valid():
    cfg = load_rules(Path(__file__).parent.parent / "rules" / "spring-petclinic-rest.json")
    assert [r["id"] for r in cfg["rules"]] == ["ARCH-001", "ARCH-002", "ARCH-003"]


def test_cli_change_mode_writes_json_and_csv(v1, v2, tmp_path):
    save_graph(v1, tmp_path / "before_graph.json")
    save_graph(v2, tmp_path / "after_graph.json")
    assert main([str(RULES), "--run", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "findings.json").read_text(encoding="utf-8"))
    assert report["summary"]["findings"] == 2
    csv_lines = (tmp_path / "findings.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(csv_lines) == 3          # header + 2 findings


def test_cli_missing_graph_is_an_error(tmp_path):
    assert main([str(RULES), "--run", str(tmp_path / "nope")]) == 2


def test_violation_created_together_with_its_layers_is_introduced(config):
    """Regression test: the target layer is created in the same change as the violating
    dependency (as in spring-petclinic-rest commit c9c8c4e). The rule does not apply to
    BEFORE, so the violation must still be reported as introduced, and flagged."""
    before = nx.DiGraph()
    before.graph["metadata"] = {"repo": "sample", "commit": "c1"}
    before.add_node(P + "controller.C")
    before.add_node(P + "service.S")
    after = nx.DiGraph()
    after.graph["metadata"] = {"repo": "sample", "commit": "c2"}
    after.add_node(P + "service.S")
    after.add_edge(P + "controller.C", P + "repository.UserRepository",
                   kinds=["field"], evidence=[{"file": "C.java", "line": 5, "kind": "field"}])
    r = DriftDetector(config).analyze_change(before, after)
    assert r["rule_applicability"]["T-002"]["before"] is False
    assert r["rule_applicability"]["T-002"]["after"] is True
    f = next(x for x in r["findings"] if x["rule_id"] == "T-002")
    assert f["status"] == "introduced" and f["rule_newly_applicable"] is True


def test_layer_removed_with_violation_counts_as_resolved(config, v1):
    after = nx.DiGraph()
    after.graph["metadata"] = {"repo": "sample", "commit": "c2"}
    after.add_node(P + "service.UserService")
    r = DriftDetector(config).analyze_change(v1, after)
    f = next(x for x in r["findings"] if x["rule_id"] == "T-001")
    assert f["status"] == "resolved" and f["rule_no_longer_applicable"] is True
