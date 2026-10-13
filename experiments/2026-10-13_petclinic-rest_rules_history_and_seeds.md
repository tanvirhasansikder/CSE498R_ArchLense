# Experiment record: rule applicability, history scan and seeded violations on spring-petclinic-rest

**Phase 3 checkpoint, plus a preliminary result for Phase 4 (historical evaluation).**
It supports RQ2: can explicit rules identify verified violations in historical code changes?

## Repository and rules
| Item | Value |
|---|---|
| Repository | https://github.com/spring-petclinic/spring-petclinic-rest |
| Baseline commit | `afc8fc1d3b8ec8de69414482b3bd70a1da78cb95` (2026-10-04) |
| Rule file | `rules/spring-petclinic-rest.json` (3 rules, 8 layers) |
| Code analysed | every `src/main/java` folder; tests excluded |

### Why this repository (and not spring-petclinic) for rule detection
- spring-petclinic (HEAD `500158f`) is organised by feature (`owner`, `vet`, `system`, `model`).
  It has no service layer, its controllers use repositories directly, and its README documents
  no layered architecture. ARCH-001 has no source layer there, and a controller-to-repository rule
  would contradict the project's intended design. spring-petclinic is therefore used only
  for the extraction and comparison checks.
- spring-petclinic-rest has a layer table in `readme.md`: REST API controllers, Service,
  and the JDBC / JPA / Spring Data JPA persistence implementations, which are switched by
  Spring profile.

### Rules and where they come from
| Rule | Forbids | Provenance |
|---|---|---|
| ARCH-001 | service → persistence_impl | **derived** from the readme's interchangeable persistence implementations |
| ARCH-002 | presentation → repository_api, persistence_impl | **documented**: readme layer table, plus commit `a994785` "made sure the ClinicService facade is used by all Controllers" |
| ARCH-003 | model → presentation, service, repository_api, persistence_impl | **derived** (prevents layer cycles) |

## Results (observed 2026-10-13, Claude's Linux workspace)

### 1. Baseline check (snapshot at `afc8fc1`)
85 classes: all classified, 0 unclassified. All 3 rules applicable. **0 violations.**

### 2. Sensitivity: seeded violations (`experiments/seed_check.py`)
One forbidden field was planted per rule into a copy of the baseline (the repository was not modified):

| Planted in | Forbidden type | Rule | Result |
|---|---|---|---|
| service/ClinicServiceImpl.java:43 | repository.jpa.JpaOwnerRepositoryImpl | ARCH-001 | DETECTED |
| rest/controller/v1/OwnerRestControllerV1.java:56 | repository.OwnerRepository | ARCH-002 | DETECTED |
| model/Owner.java:39 | service.ClinicService | ARCH-003 | DETECTED |

**3/3 detected, 0 other findings.** This shows the detector can find each rule's violations
in real code. It is a seeded check, not a measure of recall on naturally occurring violations.

### 3. Full history scan (`experiments/scan_history.py`, all 944 reachable commits)
- 943 commits analysed (the first commit has no Java sources); 0 analysis errors.
- Rule applicability: ARCH-001 and ARCH-002 apply in 849 commits, ARCH-003 in 808 commits,
  and all three in 808. Early commits (2013) use a different package layout, so the rules are
  correctly reported as not applicable there instead of being judged.
- In the 808 commits where all rules apply: **0 unclassified classes and 0 unevaluated edges.**
- **Violations: 35 commits, all the same ARCH-002 edge.** ARCH-001: 0. ARCH-003: 0.

### 4. The one historical violation, a drift case confirmed by the developers
| | Commit | Date | ArchLens result |
|---|---|---|---|
| Introduced | `c9c8c4e` "moved the ClinicRepository into some separate repos" | 2013-01-17 | `introduced` ARCH-002: `web.OwnerController → repository.OwnerRepository` (OwnerController.java:35, field), flagged `rule_newly_applicable` because the repository layer was created in the same commit |
| Present | 35 consecutive commits (scan index 95–129) | to 2013-02-11 | `present` in each snapshot |
| Resolved | `a994785` "made sure the ClinicService facade is used by all Controllers" | 2013-02-12 | `resolved` ARCH-002, same edge |

The source at `c9c8c4e` shows `private final OwnerRepository ownerRepository;` in
`OwnerController`, while `service/ClinicService.java` and `ClinicServiceImpl.java` already existed.
The developer's later commit message states the rule that was being broken.
This is external evidence that the finding is a true positive, not an artefact of our rules.

Reproduce:
```
python -m src.repo_ingestion <repo> 16b1476 c9c8c4e -o results/rest_c9c8c4e --name spring-petclinic-rest
python -m src.drift_detector rules/spring-petclinic-rest.json --run results/rest_c9c8c4e
python -m src.repo_ingestion <repo> a994785^ a994785 -o results/rest_a994785 --name spring-petclinic-rest
python -m src.drift_detector rules/spring-petclinic-rest.json --run results/rest_a994785
```

## How the rule file evolved (disclosed as a researcher degree of freedom)
1. The first rule file mapped only the `rest` package to the controller layer. The history scan found
   **0 violations**, but 86 commits had up to 8 unclassified classes (an older `web` MVC package),
   with up to 15 edges not evaluated.
2. A sensitivity rescan with `web` treated as presentation found the 35-commit ARCH-002 case.
3. Inspection showed commit `a994785` explicitly requires all controllers, including `web`, to use the
   service facade. On that documented basis, `web` was added to the `presentation` layer in the
   official rule file, and ARCH-002's provenance became "documented".
4. Two root-package bootstrapping classes (`PetclinicInitializer`, `ServletInitializer`) were
   mapped to `application`, alongside `PetClinicApplication`. This removed the last unclassified classes.

The rules were changed after looking at the data. The change is justified by project
documentation (a commit message), not by the number of findings, but it must be reported.

## Detector design change made during this experiment
The first version evaluated a rule in a commit comparison only if it applied to **both** versions.
That missed the introduction at `c9c8c4e`, because the target layer did not exist before that commit.
Now each version is checked against the rules that apply to it, and such findings are flagged
`rule_newly_applicable`. A regression test covers this case
(`test_violation_created_together_with_its_layers_is_introduced`).

## Interpretation and limits
- On this project the rules almost never fire: there is 1 distinct violation in 944 commits. The
  historical evaluation therefore mainly measures **false-alarm behaviour** (0 findings in all other
  commits where the rules apply), plus one confirmed true positive. It **cannot** support precision,
  recall or F1. There are no independent reference labels for this repository, and n = 1 positive.
- The absence of findings is only as good as dependency extraction. Unclassified edges were 0 in the
  applicable range, and the seeded check shows sensitivity, but runtime-only dependencies are not seen.
- One repository and three rules; no generalisation.
- **Verification:** all checks so far were run and read by Claude (the AI assistant). The introducing and
  resolving commits should be inspected by a human (Himel) before this is reported as verified.
