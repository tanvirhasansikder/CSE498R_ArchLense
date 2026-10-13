"""Verify a repo_ingestion diff against the real Git history.

Check 1 (each reported change is real): for every added/removed edge, print the
evidence lines from the version where the edge exists, and confirm that the
target class is NOT mentioned by the source class's file in the other version.

Check 2 (no change was missed): independent text-based method. For every .java
file the commit changed, compare which project class names it mentions before vs
after, and compare those differences with the graph diff. Names are matched as
whole words outside imports, package lines and comments.

A class's dependencies can only change if its own file changes, so checking
every changed file covers all possible edge changes.

Usage (from the ArchLens folder):
    python experiments/verify_diff.py <repo_path> <ingestion_output_dir>
"""
import json
import re
import subprocess
import sys
from pathlib import Path

SKIP = ("import", "package", "//", "*", "/*")


def git_show(repo, commit, path):
    r = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.splitlines() if r.returncode == 0 else None


def code_lines(lines):
    return [(i + 1, l) for i, l in enumerate(lines) if not l.strip().startswith(SKIP)]


def uses(lines, name):
    pat = re.compile(rf"\b{re.escape(name)}\b")
    return [n for n, l in code_lines(lines) if pat.search(l)]


def simple(qn):
    return qn.rsplit(".", 1)[1]


def main(repo, out):
    out = Path(out)
    d = json.loads((out / "diff.json").read_text(encoding="utf-8"))
    before, after = d["before"]["commit"], d["after"]["commit"]
    print(f"Verifying {before[:10]} -> {after[:10]}\n")

    print("CHECK 1: every reported change is real")
    ok = total = 0
    for kind, edges, here, there in (("ADDED", d["added_edges"], after, before),
                                     ("REMOVED", d["removed_edges"], before, after)):
        for e in edges:
            total += 1
            path = e["evidence"][0]["file"]
            lines = git_show(repo, here, path)
            tgt = simple(e["target"])
            in_here = all(re.search(rf"\b{tgt}\b", lines[ev["line"] - 1]) for ev in e["evidence"])
            other = git_show(repo, there, path)
            absent = other is None or not uses(other, tgt)
            ok += in_here and absent
            print(f"[{kind}] {e['source']} -> {e['target']}  "
                  f"{'CONFIRMED' if in_here and absent else 'CHECK MANUALLY'}")
            for ev in e["evidence"]:
                print(f"    {here[:7]} {path.rsplit('/', 1)[1]}:{ev['line']} ({ev['kind']}): "
                      f"{lines[ev['line'] - 1].strip()[:100]}")
            print(f"    {there[:7]}: " + ("file does not exist" if other is None else
                  f"'{tgt}' used on lines {uses(other, tgt) or 'none'}"))
    print(f"=> {ok}/{total} reported changes confirmed\n")

    print("CHECK 2: no change was missed (independent text-based comparison)")
    names = set()
    for side in ("before", "after"):
        doc = json.loads((out / f"{side}_graph.json").read_text(encoding="utf-8"))
        names |= {simple(n["id"]) for n in doc["nodes"]}
    changed = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", before, after],
                             capture_output=True, text=True).stdout.split()
    roots = d["before"].get("source_roots") or ["src/main/java"]
    changed = [f for f in changed if f.endswith(".java") and any(f.startswith(r + "/") for r in roots)]
    text_add, text_rem = set(), set()
    for f in changed:
        cls = f.rsplit("/", 1)[1][:-5]
        b = {n for n in names if uses(git_show(repo, before, f) or [], n)} - {cls}
        a = {n for n in names if uses(git_show(repo, after, f) or [], n)} - {cls}
        text_add |= {(cls, t) for t in a - b}
        text_rem |= {(cls, t) for t in b - a}
    g_add = {(simple(e["source"]), simple(e["target"])) for e in d["added_edges"]}
    g_rem = {(simple(e["source"]), simple(e["target"])) for e in d["removed_edges"]}
    print(f"changed .java files checked: {len(changed)}")
    problems = 0
    for label, diffset in (("added in text, missing from graph", text_add - g_add),
                           ("added in graph, missing from text", g_add - text_add),
                           ("removed in text, missing from graph", text_rem - g_rem),
                           ("removed in graph, missing from text", g_rem - text_rem)):
        problems += len(diffset)
        print(f"  {label}: {sorted(diffset) or 'none'}")
    print(f"=> {'methods agree' if problems == 0 else f'{problems} disagreements to inspect'}")
    return 0 if ok == total and problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
