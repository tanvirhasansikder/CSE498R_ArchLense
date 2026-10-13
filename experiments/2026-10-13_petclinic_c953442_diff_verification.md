# Verification record: graph comparison on spring-petclinic c953442

**Purpose:** Phase 2 checkpoint. This checks that ArchLens reports the correct
structural changes between two real commits (supports RQ1). It is a check of the
comparator and extractor, **not** an architectural-rule evaluation. No change
here is classified as drift.

## Inputs
| Item | Value |
|---|---|
| Repository | https://github.com/spring-projects/spring-petclinic.git |
| Before | `778161f0183d44df8f58b6eaee64fc085b64b69c` (2021-12-24, "Update to Boot 2.6.2") |
| After | `c9534421c8d4f29b7d2d78636bb42f58b7cdebaa` (2022-01-05, "Remove PetRepository and use Owner as aggregate") |
| Analysed code | `src/main/java` (production code only; tests excluded) |
| Why this pair | A real refactoring that removes a class and reroutes its dependencies, so it exercises added, removed and unchanged edges |

## Command
```
python -m src.repo_ingestion <path-to>/spring-petclinic 778161f c953442 -o results/petclinic_c953442
python experiments/verify_diff.py <path-to>/spring-petclinic results/petclinic_c953442
```

## ArchLens output
- Before: 25 Java files, 24 types, 38 edges, 25 unresolved refs (0 could be project types), 0 parse errors.
- After: 24 Java files, 23 types, 36 edges, 13 unresolved refs (0 could be project types), 0 parse errors.
- Diff: nodes +0 / −1 (`owner.PetRepository` removed); edges +4 / −6 / =32.
- The same numbers were produced on Linux (Python 3.13.16, Claude's workspace) and Windows
  (Python 3.13.3, Himel's machine, using a manual worktree run on 2026-10-13).

## Verification method
1. **Every reported change is real.** For each of the 10 changed edges, the evidence
   lines were read from the version where the edge exists. The target class was
   confirmed absent from the source class's file in the other version.
2. **No change was missed.** An independent text-based method was used. For each of
   the 12 `.java` files changed by the commit, the project class names mentioned
   before and after were compared, outside imports, package lines and comments.
   Those differences were then compared with the graph diff. A class's
   dependencies can only change if its own file changes, so checking every
   changed file covers all possible edge changes.

## Result (observed 2026-10-13)
- Check 1: **10/10** reported changes confirmed.
- Check 2: the methods agree, with **0** disagreements in either direction.

| Change | Edge (`org.springframework.samples.petclinic.` omitted) | Evidence |
|---|---|---|
| added | owner.OwnerRepository → owner.PetType | OwnerRepository.java:46 `List<PetType> findPetTypes();` |
| added | owner.PetTypeFormatter → owner.OwnerRepository | PetTypeFormatter.java:39, 42 |
| added | owner.VisitController → owner.Owner | VisitController.java:62 |
| added | owner.VisitController → owner.OwnerRepository | VisitController.java:40, 42 |
| removed | owner.Pet → owner.Owner | Pet.java:61, 82, 86 (field, getter, setter) |
| removed | owner.PetController → owner.PetRepository | PetController.java:39, 43 |
| removed | owner.PetRepository → owner.Pet | PetRepository.java:35, 51, 57 (file deleted) |
| removed | owner.PetRepository → owner.PetType | PetRepository.java:43 (file deleted) |
| removed | owner.PetTypeFormatter → owner.PetRepository | PetTypeFormatter.java:39, 42 |
| removed | owner.VisitController → owner.PetRepository | VisitController.java:40, 42 |

## Who verified
- Checks 1 and 2 were run by script and read by Claude (the AI assistant).
- Human spot-check: on 2026-10-13 Himel ran `git show c953442` on Pet.java, PetTypeFormatter.java and
  VisitController.java (3 of the 10 changed edges) and confirmed them. His reply was "okay done", and Claude
  recorded it as agreement with all three. The diff output he pasted shows the expected `-`/`+` lines.
- Status: 3/10 edges checked by a human, 10/10 checked by script.

## Limitations
- This is one commit pair in one small project, so it shows correctness on this case, not in general.
- Check 2 matches simple names in text. It would not detect two different classes
  with the same simple name, and that did not occur in this project.
- Both checks share the same definition of "dependency" (a type mentioned in code). They do not test
  runtime-only dependencies (reflection, dependency injection by name).
- 25 / 13 references were unresolved because of library wildcard imports. None of them could be
  project classes, so they cannot hide a project-level edge.
