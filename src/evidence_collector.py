"""ArchLens evidence collector (Phase 3).

Turns a detected rule violation into a self-contained, reviewable finding.
Everything in a finding is copied from detector inputs (graph evidence, rule
configuration, commit metadata). Nothing is inferred or invented: if a value
is unknown, it is recorded as null.

Finding IDs are stable: the same rule + source + target always gets the same
ID, so a violation can be tracked across versions and runs.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from src.layer_classifier import Classification

LIMITATIONS = (
    "Dependencies come from static analysis of source code (type references). "
    "Runtime-only dependencies (reflection, dependency injection by name, generated code) "
    "are not seen. Layer membership comes from the explicit mapping in the rule file."
)


def finding_id(rule_id: str, source: str, target: str) -> str:
    digest = hashlib.sha1(f"{rule_id}|{source}|{target}".encode("utf-8")).hexdigest()
    return f"F-{digest[:10]}"


def _describe(c: Classification) -> str:
    if c.matched_by == "class_mapping":
        return f"layer '{c.layer}' (explicit class mapping)"
    if c.matched_by == "package_prefix":
        return f"layer '{c.layer}' (package {c.matched_value})"
    return f"layer '{c.layer}'"


def make_finding(*, rule: dict, source: str, target: str,
                 source_cls: Classification, target_cls: Classification,
                 edge: dict, status: str, repo: str | None,
                 before_commit: str | None, after_commit: str | None,
                 evidence_version: str) -> dict:
    """status: present (snapshot) | introduced | persisting | resolved (change analysis)."""
    evidence = [{"file": e.get("file"), "line": e.get("line"), "kind": e.get("kind"),
                 "raw_name": e.get("raw_name")} for e in edge.get("evidence", [])]
    reason = (f"{source} is in {_describe(source_cls)}; {target} is in "
              f"{_describe(target_cls)}. Rule {rule['id']} forbids dependencies from "
              f"{rule['source_layers']} to {rule['forbidden_target_layers']}.")
    return {
        "finding_id": finding_id(rule["id"], source, target),
        "status": status,
        "repo": repo,
        "before_commit": before_commit,
        "after_commit": after_commit,
        "evidence_from": evidence_version,
        "rule_id": rule["id"],
        "rule_description": rule["description"],
        "severity": rule.get("severity"),
        "rule_provenance": rule.get("provenance"),
        "source": source,
        "source_layer": source_cls.layer,
        "target": target,
        "target_layer": target_cls.layer,
        "reference_kinds": sorted({e["kind"] for e in evidence if e["kind"]}),
        "evidence": evidence,
        "reason": reason,
        "detector_outcome": "violation",
        "limitations": LIMITATIONS,
    }


CSV_COLUMNS = ["finding_id", "status", "rule_id", "severity", "source", "source_layer",
               "target", "target_layer", "reference_kinds", "first_evidence",
               "evidence_count", "repo", "before_commit", "after_commit"]


def write_findings_csv(findings: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for f in findings:
            first = f["evidence"][0] if f["evidence"] else None
            w.writerow({
                **{k: f.get(k) for k in CSV_COLUMNS if k in f},
                "reference_kinds": ";".join(f["reference_kinds"]),
                "first_evidence": f"{first['file']}:{first['line']}" if first else "",
                "evidence_count": len(f["evidence"]),
            })
