"""Tests for src/parser.py. Run from the ArchLens folder:  python -m pytest -v"""
from pathlib import Path

import pytest

from src.parser import JavaParser, main

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_java"
BROKEN = FIXTURES / "broken_java"


@pytest.fixture(scope="module")
def sample_report():
    return JavaParser().parse_directory(SAMPLE)


def _type(report, qualified_name):
    for f in report["files"]:
        for t in f["types"]:
            if t["qualified_name"] == qualified_name:
                return t
    raise AssertionError(f"type not found: {qualified_name}")


def _refs(t, kind=None):
    return {(r["kind"], r["type_name"]) for r in t["references"]
            if kind is None or r["kind"] == kind}


def test_finds_all_files_recursively(sample_report):
    s = sample_report["summary"]
    assert s["files_found"] == 5
    assert s["files_ok"] == 5
    assert s["files_with_errors"] == 0


def test_declared_types_and_kinds(sample_report):
    declared = {t["qualified_name"]: t["kind"]
                for f in sample_report["files"] for t in f["types"]}
    assert declared == {
        "com.example.controller.UserController": "class",
        "com.example.model.User": "class",
        "com.example.repository.UserRepository": "interface",
        "com.example.repository.JdbcUserRepository": "class",
        "com.example.service.UserService": "class",
        "com.example.service.UserService.Cache": "class",
    }


def test_package_and_imports(sample_report):
    f = next(f for f in sample_report["files"] if f["path"].endswith("UserService.java"))
    assert f["package"] == "com.example.service"
    assert [i["name"] for i in f["imports"]] == [
        "com.example.model.User",
        "com.example.repository.JdbcUserRepository",
        "com.example.repository.UserRepository",
    ]


def test_service_references(sample_report):
    t = _type(sample_report, "com.example.service.UserService")
    assert _refs(t) == {
        ("field", "UserRepository"),
        ("object_creation", "JdbcUserRepository"),
        ("method_return", "User"),
    }


def test_type_parameters_and_var_are_not_dependencies(sample_report):
    t = _type(sample_report, "com.example.service.UserService")
    names = {r["type_name"] for r in t["references"]}
    assert "T" not in names
    assert "var" not in names


def test_nested_type_is_separate(sample_report):
    cache = _type(sample_report, "com.example.service.UserService.Cache")
    assert _refs(cache) == {("field", "User")}


def test_implements_generics_and_annotations(sample_report):
    t = _type(sample_report, "com.example.repository.JdbcUserRepository")
    refs = _refs(t)
    assert ("implements", "UserRepository") in refs
    assert ("field", "Map") in refs and ("field", "User") in refs  # inside Map<Long, User>
    assert ("annotation", "Override") in refs


def test_line_numbers_are_one_based(sample_report):
    t = _type(sample_report, "com.example.service.UserService")
    creation = next(r for r in t["references"] if r["kind"] == "object_creation")
    assert creation["line"] == 11
    assert t["line"] == 7


def test_syntax_error_is_reported_not_hidden():
    report = JavaParser().parse_directory(BROKEN)
    assert report["summary"]["files_with_errors"] == 1
    f = report["files"][0]
    assert f["status"] == "parsed_with_errors"
    assert f["errors"], "expected at least one recorded parse error"
    assert f["errors"][0]["line"] == 6


def test_parse_source_in_memory():
    src = b"package p; class A extends B implements C { D d = new E(); }"
    r = JavaParser().parse_source(src)
    refs = {(x.kind, x.type_name) for x in r.types[0].references}
    assert refs == {("extends", "B"), ("implements", "C"),
                    ("field", "D"), ("object_creation", "E")}


def test_qualified_type_names_kept_whole():
    r = JavaParser().parse_source(b"class A { a.b.Repo r; }")
    assert [x.type_name for x in r.types[0].references] == ["a.b.Repo"]


def test_unreadable_directory_returns_error_code(tmp_path):
    assert main([str(tmp_path / "does_not_exist")]) == 2


def test_cli_writes_json(tmp_path):
    out = tmp_path / "out.json"
    assert main([str(SAMPLE), "-o", str(out)]) == 0
    assert out.exists() and '"files_found": 5' in out.read_text(encoding="utf-8")


def test_class_literal_method_reference_and_static_access():
    src = b"""class A {
        void f() {
            register(B.class);
            list.sort(C::compare);
            D.run();
            int x = E.LIMIT;
            int y = MAX_SIZE.length;
            local.call();
        }
    }"""
    r = JavaParser().parse_source(src)
    refs = {(x.kind, x.type_name) for x in r.types[0].references}
    assert ("class_literal", "B") in refs
    assert ("method_reference", "C") in refs
    assert ("static_access", "D") in refs
    assert ("static_access", "E") in refs
    names = {x.type_name for x in r.types[0].references}
    assert "MAX_SIZE" not in names     # ALL_CAPS constant, not a type
    assert "local" not in names and "list" not in names
