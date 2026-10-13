"""Sensitivity check: plant known rule violations into a copy of real code and
confirm the detector reports exactly those (and nothing else).

The repository is not modified: the commit is exported with git archive into a
temporary folder, edited there, and analysed as "after" against the untouched
"before" copy.

Each seed adds one field declaration of a forbidden type to a class:
    "<file relative to repo root>|<fully qualified type to reference>"

Usage (from the ArchLens folder):
    python experiments/seed_check.py <repo> <commit> <rules.json> -o results/<name> \
        --seed "src/main/java/.../ClinicServiceImpl.java|org....repository.jpa.JpaOwnerRepositoryImpl" ...
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.drift_detector import DriftDetector, load_rules, write_report   # noqa: E402
from src.graph_builder import build_from_source, save_graph              # noqa: E402
from src.repo_ingestion import export_sources, find_source_roots, resolve_commit  # noqa: E402


def plant(path: Path, fq_type: str) -> int:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"\b(class|interface)\s+\w+[^{]*\{", text)
    if not m:
        raise ValueError(f"No class declaration found in {path}")
    text = text[:m.end()] + f"\n\n    private {fq_type} archlensSeeded;" + text[m.end():]
    path.write_text(text, encoding="utf-8")
    return text[:m.end()].count("\n") + 3      # line of the planted field


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("commit")
    ap.add_argument("rules", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--seed", action="append", required=True)
    a = ap.parse_args()

    config = load_rules(a.rules)
    c = resolve_commit(a.repo, a.commit)
    planted = []
    with tempfile.TemporaryDirectory() as tmp:
        roots = find_source_roots(a.repo, c["commit"])
        for side in ("before", "after"):
            export_sources(a.repo, c["commit"], roots, Path(tmp) / side)
        for s in a.seed:
            rel, fq_type = s.split("|")
            line = plant(Path(tmp) / "after" / rel, fq_type)
            planted.append({"file": rel, "line": line, "type": fq_type})
        meta = {"repo": config.get("repository"), "commit": c["commit"]}
        before = build_from_source(Path(tmp) / "before", {**meta, "label": "original"})
        after = build_from_source(Path(tmp) / "after", {**meta, "label": "seeded"})
    report = DriftDetector(config).analyze_change(before, after)
    a.output.mkdir(parents=True, exist_ok=True)
    save_graph(before, a.output / "before_graph.json")
    save_graph(after, a.output / "after_graph.json")
    write_report(report, a.output)

    detected = {(f["evidence"][0]["file"], f["evidence"][0]["line"])
                for f in report["findings"] if f["status"] == "introduced" and f["evidence"]}
    hits = sum((p["file"], p["line"]) in detected for p in planted)
    for p in planted:
        ok = (p["file"], p["line"]) in detected
        print(f"{'DETECTED' if ok else 'MISSED  '} {p['file']}:{p['line']} -> {p['type']}")
    extra = len(report["findings"]) - hits
    print(f"=> {hits}/{len(planted)} planted violations detected; "
          f"{extra} other findings (expected 0 on a clean baseline)")
    (a.output / "seeds.json").write_text(json.dumps({"commit": c, "planted": planted},
                                                    indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
