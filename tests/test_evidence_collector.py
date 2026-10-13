"""Tests for src/evidence_collector.py. Run from the ArchLens folder: python -m pytest -v"""
import csv

from src.evidence_collector import finding_id, make_finding, write_findings_csv
from src.layer_classifier import Classification

RULE = {"id": "R-1", "description": "a must not use b", "source_layers": ["a"],
        "forbidden_target_layers": ["b"], "severity": "high", "provenance": "test"}


def finding(edge):
    return make_finding(rule=RULE, source="x.A", target="y.B",
                        source_cls=Classification("a", "package_prefix", "x"),
                        target_cls=Classification("b", "class_mapping", "y.B"),
                        edge=edge, status="introduced", repo="demo",
                        before_commit="c1", after_commit="c2", evidence_version="after")


def test_id_is_stable_and_distinguishes_inputs():
    assert finding_id("R-1", "x.A", "y.B") == finding_id("R-1", "x.A", "y.B")
    assert finding_id("R-1", "x.A", "y.B") != finding_id("R-2", "x.A", "y.B")
    assert finding_id("R-1", "x.A", "y.B").startswith("F-")


def test_finding_copies_only_supplied_facts():
    f = finding({"evidence": [{"file": "A.java", "line": 3, "kind": "field",
                               "raw_name": "B", "resolved_by": "single_import"}]})
    assert f["evidence"] == [{"file": "A.java", "line": 3, "kind": "field", "raw_name": "B"}]
    assert f["reference_kinds"] == ["field"]
    assert "package x" in f["reason"] and "explicit class mapping" in f["reason"]
    assert (f["before_commit"], f["after_commit"], f["repo"]) == ("c1", "c2", "demo")


def test_missing_evidence_stays_empty_not_invented():
    f = finding({})
    assert f["evidence"] == [] and f["reference_kinds"] == []


def test_csv_export(tmp_path):
    path = tmp_path / "f.csv"
    write_findings_csv([finding({"evidence": [{"file": "A.java", "line": 3, "kind": "field"}]})], path)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["first_evidence"] == "A.java:3"
    assert rows[0]["evidence_count"] == "1"
    assert rows[0]["status"] == "introduced"
