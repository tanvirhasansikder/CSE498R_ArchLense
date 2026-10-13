"""Run the drift detector on every commit of a repository's history (snapshot mode).

For each commit: read the Java sources with git archive (read-only), build the
graph, check rule applicability, and count violations. Writes one CSV row per
commit, so you can see when rules apply and whether any violation ever existed.

Usage (from the ArchLens folder):
    python experiments/scan_history.py <repo_path> <rules.json> -o results/<name>_history.csv
        [--branch master] [--first-parent] [--name REPO_NAME]
"""
import argparse
import csv
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.drift_detector import DriftDetector, load_rules            # noqa: E402
from src.graph_builder import build_from_source                      # noqa: E402
from src.repo_ingestion import export_sources, find_source_roots     # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("rules", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--branch", default="HEAD")
    ap.add_argument("--first-parent", action="store_true")
    ap.add_argument("--name", help="Repository name (default: the rule file's repository)")
    a = ap.parse_args()

    config = load_rules(a.rules)
    det = DriftDetector(config)
    name = a.name or config.get("repository")
    log_args = ["git", "-C", str(a.repo), "log", "--reverse", "--format=%H %cs"]
    if a.first_parent:
        log_args.append("--first-parent")
    commits = [l.split() for l in subprocess.run(log_args + [a.branch], capture_output=True,
                                                  text=True, check=True).stdout.splitlines()]
    rule_ids = [r["id"] for r in config["rules"]]
    per_rule_cols = ["status", "evaluated", "violations", "undecided"]
    a.output.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    totals = {"commits": 0, "all_rules_applicable": 0, "with_findings": 0,
              "with_unclassified": 0}
    per_rule_tot = {r: {"applicable": 0, "not_applicable": 0, "inconclusive": 0,
                        "evaluated": 0, "violations": 0, "undecided": 0,
                        "commits_with_undecided": 0} for r in rule_ids}
    with a.output.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["index", "commit", "date", "java_files", "types", "edges", "unclassified",
                    "edges_with_unclassified_endpoint", "unresolved_could_be_internal"]
                   + [f"{r}_{c}" for r in rule_ids for c in per_rule_cols] + ["error"])
        blank = [""] * (len(rule_ids) * len(per_rule_cols))
        for i, (h, date) in enumerate(commits):
            row = [i, h, date]
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    roots = find_source_roots(a.repo, h)
                    n = export_sources(a.repo, h, roots, Path(tmp)) if roots else 0
                    if n == 0:
                        w.writerow(row + [0, "", "", "", "", ""] + blank + ["no java sources"])
                        continue
                    g = build_from_source(Path(tmp), {"repo": name, "commit": h})
                    r = det.analyze_snapshot(g)
                    res = r["rule_results"]["snapshot"]
                    cells = []
                    for x in rule_ids:
                        rr = res[x]
                        cells += [rr["status"], rr.get("evaluated", ""), rr.get("violations", ""),
                                  rr.get("undecided", "")]
                        t = per_rule_tot[x]
                        t[rr["status"]] += 1
                        if rr["status"] == "applicable":
                            t["evaluated"] += rr["evaluated"]
                            t["violations"] += rr["violations"]
                            t["undecided"] += rr["undecided"]
                            t["commits_with_undecided"] += rr["undecided"] > 0
                    unc = len(r["classification"]["snapshot"]["unclassified"])
                    w.writerow(row + [n, g.number_of_nodes(), g.number_of_edges(), unc,
                                      r["edges_not_evaluated_unclassified"]["snapshot"],
                                      g.graph["analysis"]["summary"]["unresolved_could_be_internal"]]
                               + cells + [""])
                    totals["commits"] += 1
                    totals["with_unclassified"] += unc > 0
                    totals["all_rules_applicable"] += all(res[x]["status"] == "applicable"
                                                          for x in rule_ids)
                    totals["with_findings"] += bool(r["findings"])
            except Exception as exc:            # record and continue; never silently skip
                w.writerow(row + [""] * 6 + blank + [f"{type(exc).__name__}: {exc}"])
    print(f"Commits listed: {len(commits)}   analysed: {totals['commits']}   "
          f"all rules applicable: {totals['all_rules_applicable']}   "
          f"commits with any violation: {totals['with_findings']}   "
          f"commits with unclassified classes: {totals['with_unclassified']}   "
          f"time: {time.time() - start:.0f}s")
    for x, t in per_rule_tot.items():
        print(f"  {x}: commits applicable {t['applicable']}, not applicable {t['not_applicable']}, "
              f"inconclusive {t['inconclusive']} | edge checks (summed over applicable commits): "
              f"evaluated {t['evaluated']}, violations {t['violations']}, undecided {t['undecided']} "
              f"(in {t['commits_with_undecided']} commits)")
    print(f"Written to {a.output}")


if __name__ == "__main__":
    main()
