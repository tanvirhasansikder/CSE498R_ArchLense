# ArchLens

Explainable architectural drift detection for Java (research prototype).

## Status
Phase 1. Parser (`src/parser.py`) and dependency extractor
(`src/dependency_extractor.py`) are implemented and tested.

## Setup (Windows PowerShell)
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run
```powershell
python -m pytest -v
python -m src.parser tests\fixtures\sample_java -o results\sample_parse.json
python -m src.dependency_extractor tests\fixtures\sample_java -o results\sample_deps.json
```

## Parser output
For each `.java` file: package, imports, declared types (classes, interfaces,
enums, records, annotations, nested types as `Outer.Inner`), and per-type
references with kind (`extends`, `implements`, `field`, `method_return`,
`method_param`, `local_var`, `object_creation`, `annotation`, `class_literal`,
`method_reference`, `static_access`) and 1-based line. `static_access` and
identifier-form `method_reference` rely on the Java naming convention
(UpperCamelCase types), so they are kept as separate kinds.
Syntax errors are recorded per file (`status: parsed_with_errors`).

Type names are recorded **as written** (not resolved). Resolution to project
classes is done later by `dependency_extractor.py`.

## Dependency extractor
Resolves each raw type name, in this order: fully qualified project type, nested
type in an enclosing class, single-type import, same package, wildcard import,
implicit `java.lang`, then fully qualified external type. Each reference ends up
in exactly one bucket:
- **internal**: becomes an edge `source -> target`, with all evidence (kind, file, line, how it was resolved).
- **external**: library or JDK type; counted, not an edge.
- **unresolved**: listed with file and line, never dropped.

An import alone never creates an edge. Project imports with no usage are listed
under `import_only`, which helps spot extraction gaps.

## Known limitations
- Annotations on method parameters are not recorded.
- Static imports (`import static a.B.f;` then `f()`) do not create references.
- Anonymous class bodies are attributed to the enclosing type.
- Generic type parameters are excluded by name within their declaring scope.
- Types reached only through a library wildcard import (`import java.util.*`) are
  reported as unresolved, since we cannot prove their origin without a classpath.
- Inherited nested types (an inner class of a superclass used unqualified) are not resolved.
- No reflection, dynamic loading, dependency injection, or generated code.
- Anonymous class bodies are attributed to the enclosing type.
- Generic type parameters are excluded by name within their declaring scope.
