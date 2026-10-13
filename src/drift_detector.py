"""ArchLens drift detector (Phase 3).

Applies explicit architectural rules to architecture graphs. Deterministic: the
same graphs and rule file always give the same findings.

Operational definition used throughout ArchLens:
  - rule violation: a dependency edge from a class in one of a rule's source layers
    to a class in one of its forbidden target layers.
  - architectural drift: a violation that exists in the AFTER version but not in the
    BEFORE version (status "introduced"). Violations in both versions are
    "persisting" (pre-existing, not new drift); violations only in BEFORE are
    "resolved". A structural change that breaks no rule is never a finding.

Before evaluating anything it checks applicability: the rule file must be for
this repository, and every layer a rule needs must contain at least one class.
Rules that fail the check are reported as not applicable and are not evaluated.

Usage (from the ArchLens folder):
    python -m src.drift_detector <rules.json> --run <repo_ingestion_output_dir>
    python -m src.drift_detector <rules.json> --graph <graph.json> -o <output_dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import networkx as nx

from src.evidence_collector import make_finding, write_findings_csv
from src.graph_builder import load_graph
from src.layer_classifier import UNCLASSIFIED, LayerClassifier

SCHEMA = "archlens-findings/1"
REQUIRED_RULE_KEYS = ("id", "description", "source_layers", "forbidden_target_layers")


def load_rules(path: Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_rules(config)
    return config


def validate_rules(config: dict) -> None:
    if config.get("schema") != "archlens-rules/1":
        raise ValueError(f"Unsupported rules schema {config.get('schema')!r}")
    layers = {layer["name"] for layer in config.get("layers", [])}
    ids = set()
    for rule in config.get("rules", []):
        missing = [k for k in REQUIRED_RULE_KEYS if k not in rule]
        if missing:
            raise ValueError(f"Rule {rule.get('id', '?')} is missing {missing}")
        if rule["id"] in ids:
            raise ValueError(f"Duplicate rule id {rule['id']}")
        ids.add(rule["id"])
        for layer in rule["source_layers"] + rule["forbidden_target_layers"]:
            if layer not in layers:
                raise ValueError(f"Rule {rule['id']} uses undefined layer {layer!r}")
    LayerClassifier(config)   # raises on inconsistent layer/class mappings


class DriftDetector:
    def __init__(self, config: dict) -> None:
        validate_rules(config)
        self.config = config
        self.classifier = LayerClassifier(config)

    # ---------- applicability ----------
    def applicability(self, g: nx.DiGraph) -> dict:
        repo = g.graph.get("metadata", {}).get("repo")
        expected = self.config.get("repository")
        layer_sizes = Counter(self.classifier.classify(n).layer for n in g.nodes)
        result = {}
        for rule in self.config["rules"]:
            if expected and repo and repo != expected:
                result[rule["id"]] = {"applicable": False,
                                      "reason": f"rule file is for {expected!r}, graph is {repo!r}"}
                continue
            empty_src = [l for l in rule["source_layers"] if layer_sizes[l] == 0]
            empty_tgt = [l for l in rule["forbidden_target_layers"] if layer_sizes[l] == 0]
            if len(empty_src) == len(rule["source_layers"]):
                result[rule["id"]] = {"applicable": False,
                                      "reason": f"no classes in source layers {empty_src}"}
            elif len(empty_tgt) == len(rule["forbidden_target_layers"]):
                result[rule["id"]] = {"applicable": False,
                                      "reason": f"no classes in target layers {empty_tgt}"}
            else:
                note = None
                if not repo:
                    note = "graph has no repository name; applicability assumed from layer contents"
                result[rule["id"]] = {"applicable": True, "reason": note}
        return result

    # ---------- core check ----------
    def violations(self, g: nx.DiGraph, applicable: set[str]) -> tuple[dict, int]:
        """Return ({(rule_id, source, target): rule}, edges_not_evaluated)."""
        found, not_evaluated = {}, 0
        rules = [r for r in self.config["rules"] if r["id"] in applicable]
        for s, t in sorted(g.edges):
            ls, lt = self.classifier.classify(s).layer, self.classifier.classify(t).layer
            if UNCLASSIFIED in (ls, lt):
                not_evaluated += 1
                continue
            for rule in rules:
                if ls in rule["source_layers"] and lt in rule["forbidden_target_layers"]:
                    found[(rule["id"], s, t)] = rule
        return found, not_evaluated

    def _classification_summary(self, g: nx.DiGraph) -> dict:
        cls = self.classifier.classify_all(g.nodes)
        return {"per_layer": dict(sorted(Counter(c.layer for c in cls.values()).items())),
                "unclassified": [n for n, c in cls.items() if c.layer == UNCLASSIFIED]}

    def _finding(self, key, rule, g, status, before_meta, after_meta, version):
        _, s, t = key
        return make_finding(
            rule=rule, source=s, target=t,
            source_cls=self.classifier.classify(s), target_cls=self.classifier.classify(t),
            edge=g.edges[s, t], status=status,
            repo=(after_meta or before_meta).get("repo"),
            before_commit=before_meta.get("commit") if before_meta else None,
            after_commit=after_meta.get("commit") if after_meta else None,
            evidence_version=version)

    # ---------- public analyses ----------
    def analyze_snapshot(self, g: nx.DiGraph) -> dict:
        app = self.applicability(g)
        ok = {r for r, a in app.items() if a["applicable"]}
        found, not_eval = self.violations(g, ok)
        meta = g.graph.get("metadata", {})
        findings = [self._finding(k, rule, g, "present", {}, meta, "snapshot")
                    for k, rule in sorted(found.items())]
        return self._report("snapshot", {}, meta, app, {"snapshot": not_eval},
                            {"snapshot": self._classification_summary(g)}, findings)

    def analyze_change(self, before: nx.DiGraph, after: nx.DiGraph) -> dict:
        app_b, app_a = self.applicability(before), self.applicability(after)
        ok_b = {r for r, a in app_b.items() if a["applicable"]}
        ok_a = {r for r, a in app_a.items() if a["applicable"]}
        # Each version is checked against the rules that apply to IT. If a rule only
        # becomes applicable in AFTER (e.g. the layers it needs were just created),
        # violations in AFTER are new and count as introduced; they are flagged so
        # they can be analysed separately.
        app = {}
        for r in app_a:
            reason = app_a[r]["reason"] if app_a[r]["applicable"] else app_b[r]["reason"]
            if r in ok_a and r not in ok_b:
                reason = f"applicable only after the change (before: {app_b[r]['reason']})"
            elif r in ok_b and r not in ok_a:
                reason = f"applicable only before the change (after: {app_a[r]['reason']})"
            app[r] = {"applicable": r in ok_a or r in ok_b, "reason": reason,
                      "before": app_b[r]["applicable"], "after": app_a[r]["applicable"]}
        vb, ne_b = self.violations(before, ok_b)
        va, ne_a = self.violations(after, ok_a)
        mb, ma = before.graph.get("metadata", {}), after.graph.get("metadata", {})
        findings = []
        for k in sorted(va.keys() - vb.keys()):
            f = self._finding(k, va[k], after, "introduced", mb, ma, "after")
            f["rule_newly_applicable"] = k[0] not in ok_b
            findings.append(f)
        for k in sorted(va.keys() & vb.keys()):
            findings.append(self._finding(k, va[k], after, "persisting", mb, ma, "after"))
        for k in sorted(vb.keys() - va.keys()):
            f = self._finding(k, vb[k], before, "resolved", mb, ma, "before")
            f["rule_no_longer_applicable"] = k[0] not in ok_a
            findings.append(f)
        return self._report("change", mb, ma, app, {"before": ne_b, "after": ne_a},
                            {"before": self._classification_summary(before),
                             "after": self._classification_summary(after)}, findings)

    def _report(self, mode, before_meta, after_meta, app, not_eval, classification, findings):
        status = Counter(f["status"] for f in findings)
        return {
            "schema": SCHEMA, "mode": mode,
            "rules_file": {"repository": self.config.get("repository"),
                           "baseline": self.config.get("baseline")},
            "before": before_meta, "after": after_meta,
            "rule_applicability": app,
            "classification": classification,
            "edges_not_evaluated_unclassified": not_eval,
            "summary": {"findings": len(findings),
                        "introduced (drift)": status["introduced"],
                        "persisting": status["persisting"],
                        "resolved": status["resolved"],
                        "present": status["present"],
                        "by_rule": dict(sorted(Counter(f["rule_id"] for f in findings).items()))},
            "findings": findings,
        }


def write_report(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "findings.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_findings_csv(report["findings"], out_dir / "findings.csv")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detect architectural-rule violations and drift.")
    ap.add_argument("rules", type=Path, help="Rule configuration (archlens-rules/1 JSON)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", type=Path, help="repo_ingestion output folder (before/after)")
    src.add_argument("--graph", type=Path, help="A single graph JSON (snapshot check)")
    ap.add_argument("-o", "--output", type=Path,
                    help="Output folder (default: the --run folder, or the graph's folder)")
    args = ap.parse_args(argv)

    try:
        detector = DriftDetector(load_rules(args.rules))
        if args.run:
            report = detector.analyze_change(load_graph(args.run / "before_graph.json"),
                                             load_graph(args.run / "after_graph.json"))
            out = args.output or args.run
        else:
            report = detector.analyze_snapshot(load_graph(args.graph))
            out = args.output or args.graph.parent
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    write_report(report, out)
    print(f"Mode: {report['mode']}")
    for rid, a in report["rule_applicability"].items():
        state = "applicable" if a["applicable"] else "NOT applicable"
        print(f"  {rid}: {state}" + (f" ({a['reason']})" if a["reason"] else ""))
    for version, c in report["classification"].items():
        print(f"  classes per layer ({version}): {c['per_layer']}")
        for n in c["unclassified"][:10]:
            print(f"    unclassified: {n}")
    print(f"  edges not evaluated (unclassified endpoint): "
          f"{report['edges_not_evaluated_unclassified']}")
    s = report["summary"]
    print(f"Findings: {s['findings']}  | introduced (drift): {s['introduced (drift)']}  "
          f"persisting: {s['persisting']}  resolved: {s['resolved']}  present: {s['present']}")
    for f in report["findings"]:
        ev = f["evidence"][0] if f["evidence"] else {}
        print(f"  [{f['status']}] {f['rule_id']} {f['source']} -> {f['target']}  "
              f"({ev.get('file')}:{ev.get('line')})")
    print(f"Written to {out / 'findings.json'} and {out / 'findings.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
