#!/usr/bin/env python3
"""Generate manifest.json — the list of pure-Python parser/template/rule files the
static browser app (Pyodide) fetches at runtime and writes into its in-memory FS.

The app is served from the repo root (zero-config GitHub Pages: main / root), so it
fetches these files directly at their real repo paths — there is no vendored copy.
Re-run this only when the set of parser files / templates / rules changes.

Usage:  python build_web.py
Output: manifest.json (a sorted JSON array of repo-root-relative paths)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent              # repo root (also the site root)

# files the in-browser Python needs (all pure-stdlib; no Desktop / no network)
SCRIPTS = [
    "load_tmdl.py", "mquery.py", "build_lineage.py",
    "find_unused_artifacts.py", "evaluate_bpa.py",
    "render_report.py", "fonts.py",
]
TEMPLATES = [
    "bpa-report-template.html", "unused-report-template.html",
    "lineage-report-template.html",
]
RULES = [
    "BPARules-custom-extended.json", "BPARules-measurekiller.json",
    "BPARules-PowerBI.json", "BPARules-standard.json",
]


def build():
    manifest = ["pyagent.py", "scripts/assets/ia-fonts.css"]
    manifest += [f"scripts/{n}" for n in SCRIPTS]
    manifest += [f"templates/{n}" for n in TEMPLATES]
    manifest += [f"rules/{n}" for n in RULES]

    missing = [m for m in manifest if not (ROOT / m).is_file()]
    if missing:
        raise SystemExit("manifest references missing files:\n  " + "\n  ".join(missing))

    (ROOT / "manifest.json").write_text(
        json.dumps(sorted(manifest), indent=0), encoding="utf-8")
    print(f"Wrote manifest.json with {len(manifest)} files:")
    for m in sorted(manifest):
        print("  ", m)


if __name__ == "__main__":
    build()
