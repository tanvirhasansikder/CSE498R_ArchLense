# ArchLens

**An Explainable Framework for Continuous Architectural Governance and Drift Detection in AI-Driven Software Development**

ArchLens is a research prototype for analyzing Java software repositories, representing dependencies as architecture graphs, detecting rule-based architectural violations, and collecting evidence to support explainable findings.

## Research objectives

- Extract dependencies from Java source code.
- Build and compare architecture graphs across Git revisions.
- Detect violations of explicitly configured architectural rules.
- Collect evidence for reproducible analysis.
- Evaluate the approach using repository history and controlled experiments.

## Research status

The current implementation includes Java parsing, dependency extraction, graph construction and comparison, repository ingestion, layer classification, rule-based drift detection, evidence collection, and historical scanning.

AI-assisted experiments and systematic evaluation of explanation quality remain future work. Results should be interpreted within the scope of the repositories, rules, and experiments actually evaluated.

## Project structure

- `src/` — analysis pipeline modules
- `rules/` — architecture rule configurations
- `tests/` — automated tests and fixtures
- `experiments/` — verification and research scripts
- `data/` — project fixtures and experimental data
- `results/` — selected generated outputs

## Setup

Python 3.13 is the current development environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run tests

```powershell
python -m pytest -q
```

## Research integrity

A structural dependency change is not automatically architectural drift. Findings depend on the configured rules and available static evidence. Undecided dependencies should not be treated as confirmed violations or proof of compliance.

## License

A license has not yet been selected.
