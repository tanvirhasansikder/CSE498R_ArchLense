# ArchLens

Explainable architectural drift detection for Java (research prototype).

## Status
Phase 1 — Java source parser implemented and tested (`src/parser.py`).

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
```

## Parser output
For each `.java` file: package, imports, declared types (classes, interfaces,
enums, records, annotations, nested types as `Outer.Inner`), and per-type
references with kind (`extends`, `implements`, `field`, `method_return`,
`method_param`, `local_var`, `object_creation`, `annotation`) and 1-based line.
Syntax errors are recorded per file (`status: parsed_with_errors`).

Type names are recorded **as written** (not resolved). Resolution to project
classes is done later by `dependency_extractor.py`.

## Known limitations (parser)
- No type resolution; `java.lang` / external types are kept and filtered later.
- Annotations on method parameters are not recorded.
- Static method calls (`Foo.bar()`) and static imports are not yet type references.
- Anonymous class bodies are attributed to the enclosing type.
- Generic type parameters are excluded by name within their declaring scope.
