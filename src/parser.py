"""ArchLens Java source parser (Phase 1).

Parses Java files with Tree-sitter and produces a *syntactic* description of
each file: package, imports, declared types, and the type references that each
declared type makes. It deliberately does NOT resolve references to fully
qualified project classes - that is the job of dependency_extractor.py.

Usage (from the ArchLens folder):
    python -m src.parser <java_source_dir> [-o results/parse_output.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

log = logging.getLogger("archlens.parser")

JAVA_LANGUAGE = Language(tsjava.language())

TYPE_DECLARATIONS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
}
# Names that look like types to Tree-sitter but are not dependencies.
IGNORED_TYPE_NAMES = {"var"}


@dataclass
class TypeReference:
    """One place where a declared type mentions another type by name."""
    kind: str        # extends | implements | field | method_return | method_param |
                     # local_var | object_creation | annotation | class_literal |
                     # method_reference | static_access (naming heuristic)
    type_name: str   # name exactly as written (generics stripped), e.g. "Repo" or "a.b.Repo"
    line: int        # 1-based line number in the source file


@dataclass
class TypeDeclaration:
    name: str                 # simple name, nested types as Outer.Inner
    qualified_name: str       # package + name (syntactic, not resolved)
    kind: str                 # class | interface | enum | record | annotation
    line: int
    end_line: int
    references: list[TypeReference] = field(default_factory=list)


@dataclass
class ParseError:
    line: int
    column: int
    kind: str                 # "syntax_error" or "missing_token"
    snippet: str


@dataclass
class FileResult:
    path: str                 # relative to the analysed root, '/' separators
    package: str | None = None
    imports: list[dict] = field(default_factory=list)
    types: list[TypeDeclaration] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    status: str = "ok"        # ok | parsed_with_errors | read_failed
    message: str | None = None


def _text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _line(node: Node) -> int:
    return node.start_point[0] + 1


def _type_names(node: Node | None, exclude: set[str]) -> list[str]:
    """Collect every named type inside a type expression.

    `Map<String, List<Repo>>` -> ["Map", "String", "List", "Repo"].
    Primitive types (int, boolean, ...) are separate node kinds and are skipped.
    Type parameters such as `T` are skipped via `exclude`.
    """
    if node is None:
        return []
    if node.type in ("type_identifier", "scoped_type_identifier"):
        name = _text(node)
        # For a.b.Repo, only the outermost scoped node is wanted, so don't recurse.
        if name in IGNORED_TYPE_NAMES or name in exclude:
            return []
        return [name]
    names: list[str] = []
    for child in node.named_children:
        if child.type == "annotation" or child.type == "marker_annotation":
            continue
        names.extend(_type_names(child, exclude))
    return names


def _looks_like_type(name: str) -> bool:
    """Java naming convention: types are UpperCamelCase, constants are UPPER_CASE.

    Used only where the grammar cannot tell a type from a variable (Foo.bar(),
    Foo::bar). It is a heuristic, so those references get their own kinds.
    """
    return name[:1].isupper() and (len(name) == 1 or any(c.islower() for c in name))


def _type_parameter_names(node: Node) -> set[str]:
    params = node.child_by_field_name("type_parameters")
    if params is None:
        return set()
    names = set()
    for p in params.named_children:
        if p.type == "type_parameter":
            for c in p.named_children:
                if c.type in ("type_identifier", "identifier"):
                    names.add(_text(c))
                    break
    return names


class JavaParser:
    def __init__(self) -> None:
        self._parser = Parser(JAVA_LANGUAGE)

    # ---------- public API ----------
    def parse_source(self, source: bytes, rel_path: str = "<memory>") -> FileResult:
        tree = self._parser.parse(source)
        result = FileResult(path=rel_path)
        root = tree.root_node

        for child in root.named_children:
            if child.type == "package_declaration":
                for c in child.named_children:
                    if c.type in ("scoped_identifier", "identifier"):
                        result.package = _text(c)
            elif child.type == "import_declaration":
                result.imports.append(self._import(child))

        self._collect_types(root, result, outer_names=[], inherited_params=set())

        if root.has_error:
            self._collect_errors(root, result.errors)
            result.status = "parsed_with_errors"
        return result

    def parse_file(self, path: Path, root: Path) -> FileResult:
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_bytes()
        except OSError as exc:
            log.warning("Could not read %s: %s", rel, exc)
            return FileResult(path=rel, status="read_failed", message=str(exc))
        return self.parse_source(source, rel)

    def parse_directory(self, root: Path) -> dict:
        root = root.resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")
        files = sorted(p for p in root.rglob("*.java") if p.is_file())
        results = [self.parse_file(p, root) for p in files]
        summary = {
            "root": str(root),
            "files_found": len(files),
            "files_ok": sum(r.status == "ok" for r in results),
            "files_with_errors": sum(r.status == "parsed_with_errors" for r in results),
            "files_unreadable": sum(r.status == "read_failed" for r in results),
            "types_declared": sum(len(r.types) for r in results),
            "type_references": sum(len(t.references) for r in results for t in r.types),
        }
        return {"summary": summary, "files": [asdict(r) for r in results]}

    # ---------- internals ----------
    @staticmethod
    def _import(node: Node) -> dict:
        raw = _text(node)
        is_static = any(c.type == "static" for c in node.children)
        is_wildcard = any(c.type == "asterisk" for c in node.children)
        name = next((_text(c) for c in node.named_children
                     if c.type in ("scoped_identifier", "identifier")), raw)
        return {"name": name, "static": is_static, "wildcard": is_wildcard,
                "line": _line(node)}

    def _collect_types(self, node: Node, result: FileResult,
                       outer_names: list[str], inherited_params: set[str]) -> None:
        for child in node.named_children:
            if child.type in TYPE_DECLARATIONS:
                self._handle_type(child, result, outer_names, inherited_params)
            elif child.type not in ("class_body", "interface_body", "enum_body",
                                    "annotation_type_body", "enum_body_declarations"):
                # Top-level / unexpected wrapper (e.g. ERROR node): keep searching.
                if child.type in ("ERROR", "program"):
                    self._collect_types(child, result, outer_names, inherited_params)

    def _handle_type(self, node: Node, result: FileResult,
                     outer_names: list[str], inherited_params: set[str]) -> None:
        name_node = node.child_by_field_name("name")
        simple = _text(name_node) if name_node else "<anonymous>"
        nested_name = ".".join(outer_names + [simple])
        qualified = f"{result.package}.{nested_name}" if result.package else nested_name
        decl = TypeDeclaration(
            name=nested_name, qualified_name=qualified,
            kind=TYPE_DECLARATIONS[node.type],
            line=_line(node), end_line=node.end_point[0] + 1,
        )
        result.types.append(decl)
        params = inherited_params | _type_parameter_names(node)

        # extends / implements
        for child in node.named_children:
            if child.type == "superclass":
                self._add_refs(decl, "extends", child, params)
            elif child.type in ("super_interfaces", "extends_interfaces"):
                kind = "implements" if child.type == "super_interfaces" else "extends"
                self._add_refs(decl, kind, child, params)
            elif child.type == "modifiers":
                self._add_annotations(decl, child, params)

        body = node.child_by_field_name("body")
        if body is not None:
            self._walk_body(body, decl, result, outer_names + [simple], params)

    def _walk_body(self, node: Node, decl: TypeDeclaration, result: FileResult,
                   outer: list[str], params: set[str]) -> None:
        for child in node.named_children:
            t = child.type
            if t in TYPE_DECLARATIONS:
                # Nested type: recorded as its own declaration.
                self._handle_type(child, result, outer, params)
                continue
            if t == "field_declaration" or t == "constant_declaration":
                self._add_refs(decl, "field", child.child_by_field_name("type"), params)
                self._walk_body(child, decl, result, outer, params)
                continue
            if t in ("method_declaration", "constructor_declaration"):
                mparams = params | _type_parameter_names(child)
                self._add_refs(decl, "method_return", child.child_by_field_name("type"), mparams)
                fps = child.child_by_field_name("parameters")
                if fps is not None:
                    for fp in fps.named_children:
                        if fp.type in ("formal_parameter", "spread_parameter"):
                            tnode = fp.child_by_field_name("type") or next(
                                (c for c in fp.named_children if c.type.endswith("type")
                                 or c.type == "type_identifier"), None)
                            self._add_refs(decl, "method_param", tnode, mparams)
                for c in child.named_children:
                    if c.type == "modifiers":
                        self._add_annotations(decl, c, mparams)
                b = child.child_by_field_name("body")
                if b is not None:
                    self._walk_body(b, decl, result, outer, mparams)
                continue
            if t == "local_variable_declaration":
                self._add_refs(decl, "local_var", child.child_by_field_name("type"), params)
            elif t == "object_creation_expression":
                self._add_refs(decl, "object_creation", child.child_by_field_name("type"), params)
                # Anonymous class bodies belong to the enclosing type here.
            elif t == "modifiers":
                self._add_annotations(decl, child, params)
                continue
            elif t == "class_literal":                       # Foo.class
                self._add_refs(decl, "class_literal", child.named_children[0], params)
                continue
            elif t == "method_reference":                    # Foo::bar
                head = child.named_children[0]
                if head.type == "identifier" and _looks_like_type(_text(head)):
                    decl.references.append(TypeReference("method_reference", _text(head), _line(head)))
                elif head.type not in ("identifier", "this", "super", "field_access",
                                       "method_invocation"):
                    self._add_refs(decl, "method_reference", head, params)
            elif t in ("method_invocation", "field_access"):  # Foo.bar() / Foo.BAR
                obj = child.child_by_field_name("object")
                if obj is not None and obj.type == "identifier" \
                        and _looks_like_type(_text(obj)) and _text(obj) not in params:
                    decl.references.append(TypeReference("static_access", _text(obj), _line(obj)))
            self._walk_body(child, decl, result, outer, params)

    def _add_annotations(self, decl: TypeDeclaration, modifiers: Node, params: set[str]) -> None:
        for c in modifiers.named_children:
            if c.type in ("annotation", "marker_annotation"):
                self._add_refs(decl, "annotation", c.child_by_field_name("name"), params)

    @staticmethod
    def _add_refs(decl: TypeDeclaration, kind: str, node: Node | None, params: set[str]) -> None:
        if node is None:
            return
        if node.type == "identifier":   # annotation names are plain identifiers
            decl.references.append(TypeReference(kind, _text(node), _line(node)))
            return
        if node.type == "scoped_identifier":
            decl.references.append(TypeReference(kind, _text(node), _line(node)))
            return
        for name in _type_names(node, params):
            decl.references.append(TypeReference(kind, name, _line(node)))

    def _collect_errors(self, node: Node, out: list[ParseError]) -> None:
        if node.type == "ERROR" or node.is_missing:
            snippet = _text(node).strip().replace("\n", " ")[:80]
            out.append(ParseError(
                line=_line(node), column=node.start_point[1] + 1,
                kind="missing_token" if node.is_missing else "syntax_error",
                snippet=snippet or f"<missing {node.type}>"))
            if node.type == "ERROR":
                return  # don't report every child of the same broken region
        for child in node.children:
            self._collect_errors(child, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse Java sources with Tree-sitter.")
    ap.add_argument("source_dir", type=Path, help="Directory containing .java files")
    ap.add_argument("-o", "--output", type=Path, help="Write full JSON output to this file")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        report = JavaParser().parse_directory(args.source_dir)
    except NotADirectoryError as exc:
        log.error("%s", exc)
        return 2

    s = report["summary"]
    print(f"Parsed {s['files_found']} Java files under {s['root']}")
    print(f"  ok: {s['files_ok']}  with syntax errors: {s['files_with_errors']}  "
          f"unreadable: {s['files_unreadable']}")
    print(f"  types declared: {s['types_declared']}  type references: {s['type_references']}")
    for f in report["files"]:
        for e in f["errors"]:
            print(f"  ERROR {f['path']}:{e['line']}:{e['column']} {e['kind']}: {e['snippet']}")
        if f["status"] == "read_failed":
            print(f"  UNREADABLE {f['path']}: {f['message']}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Full output written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
