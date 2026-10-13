"""Tests for src/repo_ingestion.py. They build a small throwaway Git repository.
Run from the ArchLens folder: python -m pytest -v"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.repo_ingestion import (IngestionError, analyze_versions, find_source_roots,
                                main, resolve_commit)

FIX = Path(__file__).parent / "fixtures"
P = "com.example."


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=ArchLens Test",
                           "-c", "user.email=test@example.invalid", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """Repo with two commits: v1 = sample_java, v2 = sample_java_v2, plus test code."""
    r = tmp_path / "demo"
    r.mkdir()
    git(r, "init", "-q")
    shutil.copytree(FIX / "sample_java", r, dirs_exist_ok=True)
    test_dir = r / "src" / "test" / "java" / "com" / "example"
    test_dir.mkdir(parents=True)
    (test_dir / "UserServiceTest.java").write_text(
        "package com.example;\nclass UserServiceTest { }\n", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "v1")
    v1 = git(r, "rev-parse", "HEAD")
    shutil.rmtree(r / "src" / "main")
    shutil.copytree(FIX / "sample_java_v2", r, dirs_exist_ok=True)
    (r / "CHANGES.md").unlink()
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "v2")
    v2 = git(r, "rev-parse", "HEAD")
    return r, v1, v2


def test_end_to_end_matches_answer_key(repo, tmp_path):
    r, v1, v2 = repo
    out = tmp_path / "out"
    run = analyze_versions(r, v1, v2, out)
    diff = json.loads((out / "diff.json").read_text(encoding="utf-8"))
    assert diff["added_nodes"] == [P + "controller.AdminController"]
    assert diff["removed_nodes"] == [P + "service.UserService.Cache"]
    assert run["diff_summary"]["added_edges"] == 2
    assert run["diff_summary"]["removed_edges"] == 2
    assert run["diff_summary"]["unchanged_edges"] == 7
    assert run["before"]["commit"] == v1 and run["after"]["commit"] == v2
    for name in ("before_graph.json", "after_graph.json", "diff.json", "run_metadata.json"):
        assert (out / name).is_file()


def test_test_code_is_excluded_by_default(repo, tmp_path):
    r, v1, v2 = repo
    assert find_source_roots(r, v1) == ["src/main/java"]
    run = analyze_versions(r, v1, v2, tmp_path / "out")
    assert run["before"]["java_files"] == 5


def test_evidence_paths_are_repo_relative(repo, tmp_path):
    r, v1, v2 = repo
    out = tmp_path / "out"
    analyze_versions(r, v1, v2, out)
    diff = json.loads((out / "diff.json").read_text(encoding="utf-8"))
    files = {ev["file"] for e in diff["added_edges"] for ev in e["evidence"]}
    assert files == {"src/main/java/com/example/controller/AdminController.java"}


def test_repository_is_not_modified(repo, tmp_path):
    r, v1, v2 = repo
    head, status = git(r, "rev-parse", "HEAD"), git(r, "status", "--porcelain")
    worktrees = git(r, "worktree", "list")
    analyze_versions(r, v1, v2, tmp_path / "out")
    assert git(r, "rev-parse", "HEAD") == head
    assert git(r, "status", "--porcelain") == status
    assert git(r, "worktree", "list") == worktrees


def test_short_hash_resolves_to_full_hash(repo):
    r, v1, _ = repo
    c = resolve_commit(r, v1[:7])
    assert c["commit"] == v1 and c["subject"] == "v1"


def test_unknown_commit_is_an_error(repo, tmp_path):
    r, v1, _ = repo
    with pytest.raises(IngestionError, match="not found"):
        analyze_versions(r, v1, "does-not-exist", tmp_path / "out")


def test_not_a_repository_is_an_error(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(IngestionError, match="not a Git repository"):
        analyze_versions(plain, "a", "b", tmp_path / "out")


def test_no_java_sources_is_an_error(repo, tmp_path):
    r, v1, v2 = repo
    with pytest.raises(IngestionError, match="No Java files"):
        analyze_versions(r, v1, v2, tmp_path / "out", source_roots=["docs"])


def test_cli(repo, tmp_path):
    r, v1, v2 = repo
    assert main([str(r), v1, v2, "-o", str(tmp_path / "out")]) == 0
    assert main([str(r), v1, "nope", "-o", str(tmp_path / "out2")]) == 2
