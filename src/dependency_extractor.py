"""ArchLens dependency extractor (Phase 1, step 2).

Takes the parser's output and turns raw type names ("UserRepository") into
directed dependencies between fully qualified *project* classes
("com.example.service.UserService" -> "com.example.repository.UserRepository").

Each reference ends up in exactly one bucket:
  internal   - resolved to a type declared in the analysed project (becomes an edge)
  external   - resolved to a library / JDK type (kept as a count, not an edge)
  unresolved - could not be resolved; recorded with file and line, never dropped

Imports alone never create an edge. A project import with no matching usage
is reported separately as "import_only".

Usage (from the ArchLens folder):
    python -m src.dependency_extractor <java_source_dir> -o results/dependencies.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from src.parser import JavaParser

log = logging.getLogger("archlens.dependency_extractor")

# Common java.lang types, which Java imports implicitly. Anything not here and not
# otherwise resolvable is reported as unresolved rather than guessed.
JAVA_LANG = {
    "Object", "String", "StringBuilder", "StringBuffer", "CharSequence", "Class",
    "Integer", "Long", "Short", "Byte", "Double", "Float", "Boolean", "Character",
    "Number", "Math", "System", "Thread", "Runnable", "Iterable", "Comparable",
    "AutoCloseable", "Enum", "Record", "Void", "Throwable", "Exception", "Error",
    "RuntimeException", "IllegalArgumentException", "IllegalStateException",
    "NullPointerException", "UnsupportedOperationException", "IndexOutOfBoundsException",
    "ArithmeticException", "ClassCastException", "NumberFormatException",
    "InterruptedException", "CloneNotSupportedException", "Override", "Deprecated",
    "SuppressWarnings", "FunctionalInterface", "SafeVarargs", "ClassLoader",
    "Cloneable", "Appendable", "Runtime", "Process", "ProcessBuilder", "StrictMath",
    "ThreadLocal", "AssertionError", "OutOfMemoryError", "StackOverflowError",
    "SecurityException", "ReflectiveOperationException", "ClassNotFoundException",
    "NoSuchMethodException", "NoSuchFieldException", "IllegalAccessException",
    "ArrayIndexOutOfBoundsException", "StringIndexOutOfBoundsException",
}


class ProjectIndex:
    """Index of every type declared in the analysed project."""

    def __init__(self, parse_report: dict) -> None:
        self.types: dict[str, dict] = {}          # qualified name -> {path, line, kind}
        for f in parse_report["files"]:
            for t in f["types"]:
                qn = t["qualified_name"]
                if qn in self.types:
                    log.warning("Duplicate type %s in %s and %s",
                                qn, self.types[qn]["path"], f["path"])
                    continue
                self.types[qn] = {"path": f["path"], "line": t["line"], "kind": t["kind"]}

    def __contains__(self, qn: str) -> bool:
        return qn in self.types


def _resolve(raw: str, file: dict, decl: dict, index: ProjectIndex) -> tuple[str, str | None, str]:
    """Return (bucket, qualified_target, how) for one raw type name."""
    package = file["package"]
    head, _, tail = raw.partition(".")

    def with_tail(qn: str) -> str:
        return f"{qn}.{tail}" if tail else qn

    # 1. Already fully qualified project type, e.g. com.example.model.User
    if "." in raw and raw in index:
        return "internal", raw, "fully_qualified"

    # 2. Nested type visible from the current type or one of its enclosing types
    # Walk outwards through enclosing *types* only (stop at the package).
    prefix = f"{package}." if package else ""
    enclosing = decl["qualified_name"][len(prefix):].split(".")   # e.g. ["Outer", "Inner"]
    while enclosing:
        candidate = with_tail(prefix + ".".join(enclosing) + "." + head)
        if candidate in index:
            return "internal", candidate, "nested_scope"
        enclosing.pop()

    # 3. Single-type import whose last segment matches the head
    for imp in file["imports"]:
        if imp["static"] or imp["wildcard"]:
            continue
        if imp["name"].rpartition(".")[2] == head:
            target = with_tail(imp["name"])
            if target in index:
                return "internal", target, "single_import"
            return "external", target, "single_import"

    # 4. Same package (no import needed in Java)
    candidate = with_tail(f"{package}.{head}" if package else head)
    if candidate in index:
        return "internal", candidate, "same_package"

    # 5. Wildcard imports, e.g. import com.example.model.*;
    for imp in file["imports"]:
        if imp["wildcard"] and not imp["static"]:
            candidate = with_tail(f"{imp['name']}.{head}")
            if candidate in index:
                return "internal", candidate, "wildcard_import"

    # 6. Implicit java.lang
    if not tail and head in JAVA_LANG:
        return "external", f"java.lang.{head}", "java_lang"

    # 7. Fully qualified but not in the project, e.g. java.util.List written in full
    if "." in raw and head[:1].islower():
        return "external", raw, "fully_qualified_external"

    # Unknown: could be a wildcard-imported library type, or something we missed.
    return "unresolved", None, "no_match"


def extract_dependencies(parse_report: dict) -> dict:
    index = ProjectIndex(parse_report)
    edges: dict[tuple[str, str], list[dict]] = defaultdict(list)
    external: dict[str, int] = defaultdict(int)
    unresolved: list[dict] = []
    used_targets: dict[str, set[str]] = defaultdict(set)   # file path -> internal targets
    counts = {"internal": 0, "external": 0, "unresolved": 0, "self": 0}

    for f in parse_report["files"]:
        for decl in f["types"]:
            source = decl["qualified_name"]
            for ref in decl["references"]:
                bucket, target, how = _resolve(ref["type_name"], f, decl, index)
                if bucket == "internal" and target == source:
                    counts["self"] += 1        # a class mentioning itself is not a dependency
                    continue
                counts[bucket] += 1
                if bucket == "internal":
                    edges[(source, target)].append({
                        "kind": ref["kind"], "file": f["path"], "line": ref["line"],
                        "raw_name": ref["type_name"], "resolved_by": how,
                    })
                    used_targets[f["path"]].add(target)
                elif bucket == "external":
                    external[target] += 1
                else:
                    unresolved.append({
                        "source": source, "raw_name": ref["type_name"],
                        "kind": ref["kind"], "file": f["path"], "line": ref["line"],
                    })

    # An unresolved name can only be a missed *project* dependency if some project
    # type has that simple name. Everything else is necessarily a library type.
    simple_names = {qn.rpartition(".")[2] for qn in index.types}
    for u in unresolved:
        u["could_be_internal"] = u["raw_name"].partition(".")[0] in simple_names

    # Imports of project types that are never actually used in the file.
    import_only = []
    for f in parse_report["files"]:
        for imp in f["imports"]:
            if not imp["static"] and not imp["wildcard"] and imp["name"] in index \
                    and imp["name"] not in used_targets[f["path"]]:
                import_only.append({"file": f["path"], "import": imp["name"],
                                    "line": imp["line"]})

    dependencies = [
        {"source": s, "target": t, "kinds": sorted({e["kind"] for e in ev}),
         "evidence": sorted(ev, key=lambda e: (e["file"], e["line"]))}
        for (s, t), ev in sorted(edges.items())
    ]
    total = counts["internal"] + counts["external"] + counts["unresolved"]
    summary = {
        "project_types": len(index.types),
        "references_total": total,
        "references_internal": counts["internal"],
        "references_external": counts["external"],
        "references_unresolved": counts["unresolved"],
        "references_self_skipped": counts["self"],
        "unresolved_could_be_internal": sum(u["could_be_internal"] for u in unresolved),
        "resolution_rate": round((total - counts["unresolved"]) / total, 4) if total else None,
        "dependency_edges": len(dependencies),
        "import_only": len(import_only),
        "files_with_parse_errors": parse_report["summary"]["files_with_errors"],
    }
    return {
        "summary": summary,
        "nodes": [{"id": qn, **meta} for qn, meta in sorted(index.types.items())],
        "dependencies": dependencies,
        "external_references": dict(sorted(external.items())),
        "unresolved_references": unresolved,
        "import_only": import_only,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract class dependencies from Java sources.")
    ap.add_argument("source_dir", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--show-unresolved", type=int, default=10,
                    help="How many unresolved references to print (default 10)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        report = extract_dependencies(JavaParser().parse_directory(args.source_dir))
    except NotADirectoryError as exc:
        log.error("%s", exc)
        return 2

    s = report["summary"]
    print(f"Project types: {s['project_types']}   dependency edges: {s['dependency_edges']}")
    print(f"References: {s['references_total']} total | internal {s['references_internal']} | "
          f"external {s['references_external']} | unresolved {s['references_unresolved']} | "
          f"resolution rate {s['resolution_rate']}")
    print(f"Unresolved that could be project types: {s['unresolved_could_be_internal']}")
    print(f"Import-only project imports: {s['import_only']}   "
          f"files with parse errors: {s['files_with_parse_errors']}")
    for d in report["dependencies"]:
        print(f"  {d['source']} -> {d['target']}  {d['kinds']}")
    for u in report["unresolved_references"][:args.show_unresolved]:
        print(f"  UNRESOLVED {u['file']}:{u['line']} {u['raw_name']} ({u['kind']})")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Full output written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
