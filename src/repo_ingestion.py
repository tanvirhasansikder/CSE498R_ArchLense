"""ArchLens repository ingestion (Phase 2).

Analyses two commits of a local Git repository end to end:
  commit -> Java source snapshot -> graph -> comparison

Each snapshot is read with `git archive` into a temporary folder, so the
repository is only *read*: no checkout, no worktree, no change to its
branches, index, working files or history.

By default only production code is analysed: every `src/main/java` folder in
the commit (multi-module projects are supported). Test code is excluded
because it is not part of the deployed architecture. Use --source-root to
choose other folders explicitly.

Outputs in the chosen folder:
  before_graph.json, after_graph.json, diff.json  (deterministic analysis results)
  run_metadata.json                               (commits, environment, settings)

Usage (from the ArchLens folder):
    python -m src.repo_ingestion <repo_path> <before_commit> <after_commit> -o <output_dir>
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path

from src.graph_builder import build_from_source, save_graph
from src.graph_comparator import compare_graphs

DEFAULT_SOURCE_MARKER = "src/main/java"


class IngestionError(Exception):
    """A problem with the repository, commits or sources. Reported, never ignored."""


def _git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              check=False)
    except FileNotFoundError as exc:
        raise IngestionError("git was not found on PATH") from exc
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", errors="replace").strip()
        raise IngestionError(f"git {' '.join(args)} failed: {msg}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", errors="replace").strip()


def resolve_commit(repo: Path, ref: str) -> dict:
    """Turn a branch, tag or short hash into a full commit record."""
    try:
        full = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except IngestionError as exc:
        raise IngestionError(f"Commit {ref!r} not found in {repo}") from exc
    info = _git(repo, "show", "-s", "--format=%cI%x00%s", full).split("\x00", 1)
    return {"ref": ref, "commit": full, "date": info[0],
            "subject": info[1] if len(info) > 1 else ""}


def find_source_roots(repo: Path, commit: str, marker: str = DEFAULT_SOURCE_MARKER) -> list[str]:
    """All folders in the commit ending in `marker` that contain .java files."""
    files = _git(repo, "ls-tree", "-r", "--name-only", commit).splitlines()
    roots = set()
    needle = f"/{marker}/"
    for f in files:
        if not f.endswith(".java"):
            continue
        padded = f"/{f}"
        idx = padded.find(needle)
        if idx >= 0:
            roots.add(padded[1:idx + len(needle) - 1])
    return sorted(roots)


def export_sources(repo: Path, commit: str, roots: list[str], dest: Path) -> int:
    """Extract the .java files under `roots` at `commit` into `dest`. Returns file count."""
    if not roots:
        return 0
    try:
        data = _git(repo, "archive", "--format=tar", commit, "--", *roots, binary=True)
    except IngestionError as exc:
        if "did not match any files" in str(exc):
            raise IngestionError(f"No Java files: source root(s) {roots} do not exist "
                                 f"at commit {commit[:10]}") from exc
        raise
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".java")]
        # filter="data" blocks absolute paths, '..' and links (safe extraction).
        tar.extractall(dest, members=members, filter="data")
        count = len(members)
    return count


def _package_versions() -> dict:
    out = {}
    for pkg in ("tree-sitter", "tree-sitter-java", "networkx"):
        try:
            out[pkg] = importlib_metadata.version(pkg)
        except importlib_metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def analyze_versions(repo: Path, before_ref: str, after_ref: str, out_dir: Path,
                     source_roots: list[str] | None = None, repo_name: str | None = None) -> dict:
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise IngestionError(f"Repository folder not found: {repo}")
    try:
        toplevel = Path(_git(repo, "rev-parse", "--show-toplevel"))
    except IngestionError as exc:
        raise IngestionError(f"{repo} is not a Git repository") from exc
    # samefile, not ==, so Windows short names (HIMEL~1) and drive-letter case don't matter.
    if not os.path.samefile(toplevel, repo):
        raise IngestionError(f"{repo} is inside a Git repository but is not its root ({toplevel})")

    try:
        remote = _git(repo, "config", "--get", "remote.origin.url")
    except IngestionError:
        remote = None   # local-only repository: allowed, recorded as null
    name = repo_name or repo.name
    before, after = resolve_commit(repo, before_ref), resolve_commit(repo, after_ref)

    out_dir.mkdir(parents=True, exist_ok=True)
    graphs, versions = {}, {}
    with tempfile.TemporaryDirectory(prefix="archlens_") as tmp:
        for label, c in (("before", before), ("after", after)):
            roots = source_roots or find_source_roots(repo, c["commit"])
            dest = Path(tmp) / label
            dest.mkdir()
            n_files = export_sources(repo, c["commit"], roots, dest)
            if n_files == 0:
                raise IngestionError(
                    f"No Java files found at {label} commit {c['commit'][:10]} "
                    f"under {roots or DEFAULT_SOURCE_MARKER!r}")
            meta = {"repo": name, "repo_url": remote, "commit": c["commit"],
                    "label": label, "source_roots": roots}
            g = build_from_source(dest, meta)
            # The temp path is meaningless later; file paths in evidence are repo-relative.
            g.graph["metadata"]["source_dir"] = "<repo root>"
            save_graph(g, out_dir / f"{label}_graph.json")
            graphs[label] = g
            versions[label] = {**c, "source_roots": roots, "java_files": n_files,
                               **g.graph["analysis"]["summary"]}

    diff = compare_graphs(graphs["before"], graphs["after"])
    (out_dir / "diff.json").write_text(json.dumps(diff, indent=2) + "\n", encoding="utf-8")

    run = {
        "repo": name, "repo_path": str(repo), "repo_url": remote,
        "before": versions["before"], "after": versions["after"],
        "diff_summary": diff["summary"],
        "settings": {"source_roots": source_roots or f"auto: every {DEFAULT_SOURCE_MARKER}"},
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "packages": _package_versions()},
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    return run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Analyse and compare two commits of a Git repository.")
    ap.add_argument("repo", type=Path, help="Path to the local Git repository (its root folder)")
    ap.add_argument("before", help="Earlier commit, tag or branch")
    ap.add_argument("after", help="Later commit, tag or branch")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output folder")
    ap.add_argument("--source-root", action="append", dest="source_roots",
                    help="Folder to analyse, relative to the repo root (repeatable). "
                         "Default: every src/main/java folder.")
    ap.add_argument("--name", help="Repository name to record (default: folder name)")
    args = ap.parse_args(argv)

    try:
        run = analyze_versions(args.repo, args.before, args.after, args.output,
                               args.source_roots, args.name)
    except IngestionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for label in ("before", "after"):
        v = run[label]
        print(f"{label:6} {v['commit'][:10]} {v['date'][:10]} {v['subject'][:60]}")
        print(f"       {v['java_files']} Java files, {v['project_types']} types, "
              f"{v['dependency_edges']} edges, {v['references_unresolved']} unresolved "
              f"({v['unresolved_could_be_internal']} could be project types), "
              f"{v['files_with_parse_errors']} files with parse errors")
    s = run["diff_summary"]
    print(f"diff   nodes +{s['added_nodes']} / -{s['removed_nodes']}   "
          f"edges +{s['added_edges']} / -{s['removed_edges']} / ={s['unchanged_edges']}")
    print(f"Written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
