<<<<<<< HEAD
# ArchLens

Explainable architectural drift detection for Java (research prototype).

## Status
- Phase 1 (done): parser (`src/parser.py`) and dependency extractor (`src/dependency_extractor.py`).
- Phase 2 (done): graph builder (`src/graph_builder.py`), comparator
  (`src/graph_comparator.py`) and repository ingestion (`src/repo_ingestion.py`).
  It has been verified on one real commit pair; see
  `experiments/2026-10-13_petclinic_c953442_diff_verification.md`.

- Phase 3 (done): layer classifier (`src/layer_classifier.py`), drift detector
  (`src/drift_detector.py`) and evidence collector (`src/evidence_collector.py`), with
  rules for spring-petclinic-rest (`rules/spring-petclinic-rest.json`). See
  `experiments/2026-10-13_petclinic-rest_rules_history_and_seeds.md`.

Requires Python 3.12+ (safe tar extraction) and Git on PATH.

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
python -m src.graph_builder tests\fixtures\sample_java -o results\v1.json --label v1
python -m src.graph_builder tests\fixtures\sample_java_v2 -o results\v2.json --label v2
python -m src.graph_comparator results\v1.json results\v2.json -o results\diff_v1_v2.json
```

## Analyse two commits of a real repository
```powershell
python -m src.repo_ingestion <repo_root> <before_commit> <after_commit> -o results\<run_name>
python experiments\verify_diff.py <repo_root> results\<run_name>
```
Each commit's Java sources are read with `git archive` into a temporary folder,
so the repository is never modified: no checkout and no worktree. By default
every `src/main/java` folder is analysed and test code is excluded; use
`--source-root` to override. The output folder holds `before_graph.json`,
`after_graph.json`, `diff.json` and `run_metadata.json` (commit hashes, dates and
subjects, source roots, Python and package versions, run time). Evidence file paths are
relative to the repository root.

## Rule-based drift detection
```powershell
python -m src.drift_detector rules\spring-petclinic-rest.json --run results\<run_name>     # two versions
python -m src.drift_detector rules\spring-petclinic-rest.json --graph <graph.json> -o <dir>  # one version
python experiments\scan_history.py <repo> rules\spring-petclinic-rest.json -o results\history.csv
python experiments\seed_check.py <repo> <commit> <rules.json> -o results\seeds --seed "<file>|<type>"
```
**Rule file (`archlens-rules/1`).** Defines layers (package prefixes; the longest match wins),
explicit class-to-layer mappings, and rules (`source_layers` must not depend on
`forbidden_target_layers`). Each rule records its `provenance` and `rationale`. Rule files
are per repository: a rule is applied only to the repository it was written for.

**Definitions.** A *violation* is an edge from a class in a rule's source layer to a class in a
forbidden target layer. *Drift* means a violation present after a change but not before (status
`introduced`). Violations present before and after are `persisting`; violations only before are
`resolved`. A structural change that breaks no rule is never a finding.

**Rule status per version.**
- `applicable`: the rule file is for this repository, and every layer the rule needs (source,
  forbidden target, and any `requires_layers`) contains classes.
- `not_applicable`: a needed layer has no classes and every class is classified.
- `inconclusive`: a needed layer has no classes, but some classes are unclassified, so the layer may only
  look empty. These rules are not evaluated, and the result is never treated as compliant.

**Per-rule accounting** (`rule_results` in `findings.json`), for each applicable rule:
- `evaluated`: edges actually checked.
- `violations`: evaluated edges that break the rule.
- `undecided`: edges with an unclassified endpoint that would break the rule if that endpoint were
  in a source or forbidden layer. Listed in full.
- `unresolved_references_could_be_internal`: references the extractor could not resolve that could be
  project classes.

The verdict is `compliant` only when violations, undecided edges and those unresolved references are all
0. Otherwise it is `violations_found` or `no_violation_found_but_inconclusive`. Unclassified dependencies are
never silently treated as compliant.

**Findings** (`findings.json`, `findings.csv`): a stable ID (the same rule, source and target always give
the same ID), status, rule, layers, every evidence location (file, line, kind), the reason the
rule applies, commits, and limitations.

## Architecture graph (`archlens-graph/1`)
Nodes are project types, identified by fully qualified name, with path, line and
kind. Edges are dependencies, with reference kinds, evidence (file, line, kind,
resolved_by) and weight (the number of references). The file also stores the
version metadata (repo, commit, label, source_dir) and the extractor's
analysis: summary, external refs, unresolved refs and import-only imports.
Output is sorted and has no timestamps, so identical input gives an identical file.

## Graph comparison (`archlens-diff/1`)
Reports added, removed and unchanged nodes and edges between two graphs, with
both versions' metadata. Added edges carry evidence from the new version, and
removed edges carry evidence from the old one. It reports structural change
only and makes no judgement about whether a change is good or bad. Renamed or
moved classes appear as a removal plus an addition.

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
- **unresolved**: listed with file and line, never dropped. `could_be_internal` is
  true only if some project type has that simple name; if it is false, the
  reference cannot be a missed project dependency.

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
=======
# CSE498R_ArchLense
>>>>>>> origin/main
