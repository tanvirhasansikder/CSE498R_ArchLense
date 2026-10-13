# Assessment: can TechDebt2023 serve as ground truth for ArchLens? (Phase 4)

**Question.** The blueprint names https://github.com/xjtu-enre/techdebt2023dataset as a candidate
historical data source, and requires its contents and label definitions to be checked before use.
This record reports what the repository actually contains (inspected 2026-10-13 by Claude) and
whether it can provide reference labels for ArchLens detection (RQ2).

**Inspected version:** commit `c81213361a314b6f56ed61a1bebc218f93a83f21` (2023-03-19, "update").

## What the repository contains
The readme describes it as supporting material for an *under-review* paper (at the time of the commit),
"Identifying Code Changes for Architecture Decay via a Metric Forest Structure", and its tool dbMIT/dbMITPlus.

| Item | Content (observed) |
|---|---|
| `Data/Setup/Subjects/Subjects.csv` | 87 projects: name, LOC, #files, #commits, #modules, #classes, #methods, category (61 microservice-based, 17 android-based, 7 others, 2 blank). **No source code and no repository URLs.** |
| `Data/Results/Architecture Decay Detection Results/detection results.csv` | 9 version pairs (apollo, argouml, AxonFramework, bus, junit4, Sentinel, servicecomb-java-chassis, train-ticket, lineage/base), each with **counts** of "problematic" modules/classes/methods under coupling and cohesion rules. **No list of which entities were flagged.** |
| `.../maintenance cost.csv` | Per-version averages of #commit, #change_Loc and #author for flagged vs. unflagged entities (ratio P). These are maintenance-cost proxies, not labels. |
| `Data/Results/Maintainability Evaluation Results/` | A SCORE and DL value per project (64 rows). Per-class (67 columns) and per-method (15 columns) **metric values** for 5 projects (apollo, argouml, LineageOS, servicecomb-java-chassis, piggymetrics). There is no "problematic" flag column. |
| `Knowledge Base/`, `Scripts/`, `Demo Video/` | Metric definitions, a GitHub search script, and a demo video (stored with Git LFS; not downloaded). |

## Compatibility with ArchLens
| ArchLens needs | TechDebt2023 provides | Compatible? |
|---|---|---|
| Labels for **rule violations** (a forbidden dependency between documented layers) | Metric-threshold flags for "architecture decay" (coupling/cohesion), produced by the authors' own tool | **No**: a different construct |
| **Per-dependency or per-class** labels to compute TP/FP/FN | Aggregate **counts** only | **No**: entities cannot be matched |
| **Independent** (human-verified) reference | Tool output (dbMIT), validated indirectly against maintenance-cost proxies | **No**: it is not ground truth for another detector |
| Source code at identifiable versions | Project names and version tags only; no URLs or code | Partially: the projects would have to be located and cloned separately |

## Decision
1. **TechDebt2023 is not used as ground truth.** Computing precision, recall or F1 for ArchLens against it
   would be invalid: different construct, aggregate-only, tool-generated. This follows the blueprint's
   explicit instruction not to compute misleading metrics against misaligned labels.
2. It may be cited in the report as related work on metric-based architecture-decay detection. The
   paper's bibliographic details must first be verified during the literature review; the readme only
   says "under review".
3. Its subject list may be used **only as a source of candidate projects**. That is optional and depends
   on time, because each project would also need a documented architecture to derive rules from.
4. The Phase 4 historical evaluation therefore remains a **documented case study**: spring-petclinic-rest,
   944 commits, 1 developer-confirmed true positive, and 0 findings elsewhere in 808 fully applicable
   commits. Results are reported as counts and verified examples, without precision, recall or F1.

## Limitations of this assessment
- Based on the repository contents and readme only. The associated paper was not read.
- The demo videos (Git LFS) were not downloaded.
