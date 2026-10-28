#!/usr/bin/env python3
"""Vendor the pure-Python parsers + templates + rules + fonts into web/vendor/ so the
static browser app (Pyodide) can load them. Re-run this whenever the parsers change.

Usage:  python web/build_web.py
Output: web/vendor/** (mirrors the Pyodide /app layout) + web/vendor/manifest.json
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # project root
WEB = ROOT / "web"
VENDOR = WEB / "vendor"

# files the in-browser Python needs (all pure-stdlib; no Desktop / no network)
SCRIPTS = [
    "load_tmdl.py", "mquery.py", "build_lineage.py",
    "find_unused_artifacts.py", "evaluate_bpa.py",
    "render_report.py", "render_perf_report.py", "fonts.py",
]
TEMPLATES = [
    "bpa-report-template.html", "unused-report-template.html",
    "lineage-report-template.html", "perf-report-template.html",
]
RULES = [
    "BPARules-custom-extended.json", "BPARules-measurekiller.json",
    "BPARules-PowerBI.json", "BPARules-standard.json",
    "performance/PerfRules.json",
]


def _copy(src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def main():
    # Copy/overwrite in place (don't wipe the tree first — OneDrive may hold a transient
    # lock on a synced subfolder). Stale files are pruned best-effort at the end.
    VENDOR.mkdir(parents=True, exist_ok=True)
    manifest = []

    for name in SCRIPTS:
        _copy(ROOT / "scripts" / name, VENDOR / "scripts" / name)
        manifest.append(f"scripts/{name}")

    # embedded iA Writer fonts CSS used by fonts.apply()
    _copy(ROOT / "scripts" / "assets" / "ia-fonts.css",
          VENDOR / "scripts" / "assets" / "ia-fonts.css")
    manifest.append("scripts/assets/ia-fonts.css")

    for name in TEMPLATES:
        _copy(ROOT / "templates" / name, VENDOR / "templates" / name)
        manifest.append(f"templates/{name}")

    for rel in RULES:
        _copy(ROOT / "rules" / rel, VENDOR / "rules" / rel)
        manifest.append(f"rules/{rel}")

    # the browser-side bridge (sits at the Pyodide /app root)
    _copy(WEB / "pyagent.py", VENDOR / "pyagent.py")
    manifest.append("pyagent.py")

    (VENDOR / "manifest.json").write_text(
        json.dumps(sorted(manifest), indent=0), encoding="utf-8")

    # prune any orphaned files no longer in the manifest (best-effort; ignore OneDrive locks)
    keep = {str((VENDOR / m).resolve()) for m in manifest} | {str((VENDOR / "manifest.json").resolve())}
    for f in VENDOR.rglob("*"):
        if f.is_file() and str(f.resolve()) not in keep:
            try:
                f.unlink()
            except OSError:
                pass

    print(f"Vendored {len(manifest)} files into {VENDOR}")
    for m in sorted(manifest):
        print("  ", m)


if __name__ == "__main__":
    main()
