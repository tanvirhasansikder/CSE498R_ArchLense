"""Tests for src/dependency_extractor.py. Run from the ArchLens folder: python -m pytest -v"""
from dataclasses import asdict
from pathlib import Path

import pytest

from src.dependency_extractor import extract_dependencies, main
from src.parser import JavaParser

SAMPLE = Path(__file__).parent / "fixtures" / "sample_java"


def build_report(sources: dict[str, str]) -> dict:
    """Parse several in-memory Java files into the same format parse_directory returns."""
    p = JavaParser()
    files = [asdict(p.parse_source(src.encode(), path)) for path, src in sources.items()]
    return {"summary": {"files_with_errors": sum(f["status"] != "ok" for f in files)},
            "files": files}


def edges(report):
    return {(d["source"], d["target"]) for d in report["dependencies"]}


@pytest.fixture(scope="module")
def sample():
    return extract_dependencies(JavaParser().parse_directory(SAMPLE))


def test_sample_project_edges_exact(sample):
    p = "com.example."
    assert edges(sample) == {
        (p + "controller.UserController", p + "service.UserService"),
        (p + "controller.UserController", p + "model.User"),
        (p + "service.UserService", p + "repository.UserRepository"),
        (p + "service.UserService", p + "repository.JdbcUserRepository"),
        (p + "service.UserService", p + "model.User"),
        (p + "service.UserService.Cache", p + "model.User"),
        (p + "repository.JdbcUserRepository", p + "repository.UserRepository"),
        (p + "repository.JdbcUserRepository", p + "model.User"),
        (p + "repository.UserRepository", p + "model.User"),
    }


def test_sample_has_no_unresolved_and_library_types_are_external(sample):
    assert sample["summary"]["references_unresolved"] == 0
    assert "java.util.Optional" in sample["external_references"]
    assert "java.lang.String" in sample["external_references"]


def test_evidence_points_to_file_and_line(sample):
    dep = next(d for d in sample["dependencies"]
               if d["target"] == "com.example.repository.JdbcUserRepository")
    ev = dep["evidence"][0]
    assert ev["kind"] == "object_creation"
    assert ev["line"] == 11
    assert ev["file"].endswith("service/UserService.java")
    assert ev["resolved_by"] == "single_import"


def test_same_package_needs_no_import():
    r = extract_dependencies(build_report({
        "a/A.java": "package a; class A { B b; }",
        "a/B.java": "package a; class B {}",
    }))
    assert edges(r) == {("a.A", "a.B")}
    assert r["dependencies"][0]["evidence"][0]["resolved_by"] == "same_package"


def test_wildcard_import_resolves_only_project_types():
    r = extract_dependencies(build_report({
        "a/A.java": "package a; import b.*; import java.util.*; class A { B b; List l; }",
        "b/B.java": "package b; public class B {}",
    }))
    assert edges(r) == {("a.A", "b.B")}
    # List comes through a library wildcard: we cannot prove where it is from.
    assert [u["raw_name"] for u in r["unresolved_references"]] == ["List"]


def test_nested_type_and_qualified_nested_reference():
    r = extract_dependencies(build_report({
        "a/Outer.java": "package a; class Outer { Inner i; static class Inner {} }",
        "b/User.java": "package b; import a.Outer; class User { Outer.Inner x; }",
    }))
    assert ("a.Outer", "a.Outer.Inner") in edges(r)
    assert ("b.User", "a.Outer.Inner") in edges(r)


def test_fully_qualified_reference_without_import():
    r = extract_dependencies(build_report({
        "a/A.java": "package a; class A { b.B x; java.util.List y; }",
        "b/B.java": "package b; public class B {}",
    }))
    assert edges(r) == {("a.A", "b.B")}
    assert "java.util.List" in r["external_references"]


def test_import_alone_does_not_create_edge():
    r = extract_dependencies(build_report({
        "a/A.java": "package a; import b.B; class A { }",
        "b/B.java": "package b; public class B {}",
    }))
    assert edges(r) == set()
    assert [i["import"] for i in r["import_only"]] == ["b.B"]


def test_unknown_name_is_reported_not_dropped():
    r = extract_dependencies(build_report({
        "a/A.java": "package a; class A { Mystery m; }",
    }))
    assert edges(r) == set()
    u = r["unresolved_references"][0]
    assert (u["source"], u["raw_name"], u["line"]) == ("a.A", "Mystery", 1)
    assert r["summary"]["resolution_rate"] == 0.0


def test_self_reference_is_not_an_edge():
    r = extract_dependencies(build_report({
        "a/A.java": "package a; class A { A next; static A of() { return new A(); } }",
    }))
    assert edges(r) == set()
    assert r["summary"]["references_self_skipped"] == 3


def test_class_literal_and_static_call_create_edges():
    r = extract_dependencies(build_report({
        "a/A.java": "package a; class A { void f() { use(B.class); C.make(); } }",
        "a/B.java": "package a; class B {}",
        "a/C.java": "package a; class C { static void make() {} }",
    }))
    assert edges(r) == {("a.A", "a.B"), ("a.A", "a.C")}


def test_multiple_references_merge_into_one_edge_with_all_evidence():
    r = extract_dependencies(build_report({
        "a/A.java": "package a;\nclass A {\n B f;\n B m(B p) { return new B(); }\n}",
        "a/B.java": "package a; class B {}",
    }))
    assert len(r["dependencies"]) == 1
    d = r["dependencies"][0]
    assert d["kinds"] == ["field", "method_param", "method_return", "object_creation"]
    assert len(d["evidence"]) == 4


def test_cli_writes_json(tmp_path):
    out = tmp_path / "deps.json"
    assert main([str(SAMPLE), "-o", str(out)]) == 0
    assert '"dependency_edges": 9' in out.read_text(encoding="utf-8")
