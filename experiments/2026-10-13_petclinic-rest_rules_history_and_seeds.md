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
*Figures in this subsection use the rule file as committed in `aad0d15`; section 5 supersedes them.*
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

### 5. Unclassified classes: from undecided to fully evaluated (revised 2026-10-13)

**Correction to an earlier claim.** A previous version of this section said the unclassified
root-package classes "cannot affect" ARCH-001/ARCH-002. That argument relied on knowing, from outside
the rule engine, that those classes were entities. Under the configured rules they were simply
unclassified, so the edges touching them were **undecided**, neither compliant nor violating.
ARCH-003 was reported as "not applicable" when it should have been reported as inconclusive.
Himel raised this objection; it was correct.

**Detector change.** Each rule and version now gets a result:
- `applicable`: evaluated, with counts of `evaluated` edges, `violations`, and `undecided` edges.
  An undecided edge has an unclassified endpoint that would break the rule if that endpoint were
  in a source or forbidden layer; these edges are listed in full.
- `not_applicable`: a needed layer has no classes **and every class is classified**.
- `inconclusive`: a needed layer has no classes, but some classes are unclassified, so the layer may
  only look empty. These rules are not evaluated and are never reported as compliant.

The verdict is `compliant` only if there are 0 violations, 0 undecided edges, and 0 unresolved
references that could be project classes. Otherwise it is `violations_found` or
`no_violation_found_but_inconclusive`.

**Classification.** A full-history inventory found **61 distinct classes** that were unclassified in some
commit, all from 2013-01-09 to 2013-02-13. Each was mapped explicitly, using evidence from the repository
(recorded per group in `class_mapping_evidence` in the rule file):

| Group | Layer | Evidence |
|---|---|---|
| Root-package `BaseEntity, NamedEntity, Owner, Person, Pet, PetType, Specialty, Vet, Vets, Visit` | model | `@Entity`/`@MappedSuperclass` (Vets: `@XmlRootElement`); commit `23314c5` "moved all model classes to a dedicated 'model' package" |
| Root-package `Clinic` interface | repository_api | Methods "Retrieve ... from the data store"; replaced by repository interfaces in `c9c8c4e` |
| Root `jdbc`, `jpa`, `hibernate`, `toplink` packages | persistence_impl | `HibernateClinic implements Clinic`, etc.; moved under `repository/` in `c9c8c4e` |
| Root `aspects` package | infrastructure | Commit `0a5ea0b` "moved aspect to util package" |
| Root `validation` package | presentation | Commit `e924e87` "moved Validator to the web package" |
| Early sample modules (`owner`, `pet`, `owners`, `appointments`, `HomeController`; until `87ccf9f`) | per class | `@Controller` = presentation; `@Repository` = persistence_impl; interfaces those implement = repository_api; plain domain classes = model; `*Form` = presentation |

Two assignments are ambiguous: `AppointmentForm` (presentation or model) and `Appointments` (model or
presentation). They were tested both ways (see the table below).

**Rule precondition.** ARCH-002 now has `requires_layers: ["service"]`. Its text ("must go through the
service layer") presupposes that a service layer exists. Before `c9c8c4e`, there was none.

**Full-history results (943 analysed commits; Claude's workspace, 2026-10-13):**

| Configuration | Commits with unclassified classes | ARCH-001 applicable / n.a. / inconclusive | ARCH-001 evaluated · violations · undecided | ARCH-002 applicable / n.a. / inconclusive | ARCH-002 evaluated · violations · undecided | ARCH-003 applicable / n.a. / inconclusive | ARCH-003 evaluated · violations · undecided |
|---|---|---|---|---|---|---|---|
| Old rule file (commit `aad0d15`) | 135 | 849 / 0 / 94 | 16,345 · 0 · **1,064** (41 commits) | 849 / 0 / 94 | 20,080 · 35 · **1,064** (41 commits) | 808 / 0 / **135** | 12,899 · 0 · 0 |
| **New rule file (official)** | **0** | 849 / 94 / 0 | 16,755 · 0 · **0** | 849 / 94 / 0 | 20,529 · 35 · **0** | **943** / 0 / 0 | 14,858 · 0 · **0** |
| New, ambiguous classes swapped | 0 | same | same | same | same | 943 / 0 / 0 | 14,805 · 0 · 0 |
| New, **without** `requires_layers` | 0 | same | same | 943 / 0 / 0 | 23,632 · **971** · 0 (129 commits) | same | same |

"Evaluated, violations, undecided" are summed over all commits where the rule is applicable, so one
edge present in many commits is counted once per commit.

**Interpretation.**
- With the new mappings, every edge in every commit is classified. The result "ARCH-003: 0 violations"
  now rests on 14,858 actual edge checks across all 943 commits, not on "not applicable".
- The single historical violation (ARCH-002, `c9c8c4e` → `a994785`, 35 commits) is unchanged.
- The two ambiguous classes do not affect any verdict.
- `requires_layers` is consequential. Without it, ARCH-002 also flags 94 commits (2013-01-09..16). **None
  of those commits contains any service-layer class.** Every extra edge is a controller using the only
  data-access interface that existed (`web.* -> Clinic`, `owners.*Controller -> owners.*Repository`, ...).
  That was the original design, so flagging it as drift would be a false positive under the rule's own
  wording. Both numbers are reported so the choice can be judged.
- Undecided edge counts are 0 in the official configuration. Unresolved references that could be project
  classes are also 0 for every commit; they are reported per commit in `results/rest_history.csv`.

### 6. Reproduction on Himel's machine (Windows, Python 3.13.3, 2026-10-13)
- `python -m pytest -q`: **78 passed**.
- Baseline `afc8fc1`: 85 classes, 0 unclassified, all 3 rules applicable, **0 findings**. Identical to Claude's run.
- `16b1476 -> c9c8c4e`: `introduced` ARCH-002 `web.OwnerController -> repository.OwnerRepository` (OwnerController.java:35). Identical.
- `a994785^ -> a994785`: `resolved`, same edge. Identical.
- `scan_history.py`: 944 listed, 943 analysed, 808 all-applicable, **35** commits with violations. Identical (250 s on Windows vs 78 s on Linux).
- Committed as `aad0d15`.
- Himel displayed the `a994785` diff for `web/OwnerController.java`. It shows the `OwnerRepository`
  import, field, constructor parameter and 5 call sites replaced by `ClinicService`.
  **Himel's judgement (2026-10-13): "Agree".**

## How the rule file evolved (disclosed as a researcher degree of freedom)
(Steps 1–4 below happened before section 5's revision; step 5 is section 5.)
1. The first rule file mapped only the `rest` package to the controller layer. The history scan found
   **0 violations**, but 86 commits had up to 8 unclassified classes (an older `web` MVC package),
   with up to 15 edges not evaluated.
2. A sensitivity rescan with `web` treated as presentation found the 35-commit ARCH-002 case.
3. Inspection showed commit `a994785` explicitly requires all controllers, including `web`, to use the
   service facade. On that documented basis, `web` was added to the `presentation` layer in the
   official rule file, and ARCH-002's provenance became "documented".
4. Two root-package bootstrapping classes (`PetclinicInitializer`, `ServletInitializer`) were
   mapped to `application`, alongside `PetClinicApplication`. This removed the last unclassified classes.

5. Explicit mappings for the 61 early-history classes, plus `requires_layers` for ARCH-002 (section 5).

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
- **Verification:** the scans and seeds were run by script on two machines with identical results (before the
  section 5 revision; the revised scans have so far been run only in Claude's workspace). Himel inspected the
  resolving commit `a994785` and agreed. The introducing commit `c9c8c4e` has been inspected only by Claude.
