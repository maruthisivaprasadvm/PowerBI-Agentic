#!/usr/bin/env python3
"""Fill the BPA HTML dashboard template with a results JSON.

Usage:
    python scripts/render_report.py <results.json> <model_name> <rule_set> [out.html]

<results.json> is an array of objects:
    { "id","name","category","severity","status","violationCount","violations":[...],"description" }

The BPA agent produces <results.json> from the live model (via the powerbi-modeling MCP
server) and calls this script to write the self-contained report.

Output layout (per-pbix subfolder + timestamp, so each model keeps its own history):
    output/BPA/<model_name>/<model_name>_<rule_set>_<YYYYMMDD-HHMMSS>.html
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fonts  # noqa: E402  (embeds the iA Writer webfonts)
TEMPLATE = ROOT / "templates" / "bpa-report-template.html"


def _safe(name: str) -> str:
    """Make a string safe for use as a file/folder name."""
    stem = re.sub(r"\.pbix$", "", str(name), flags=re.IGNORECASE)
    stem = re.sub(r'[<>:"/\\|?*]+', "_", stem).strip().strip(".")
    return stem or "model"


def render(results, model_name, rule_set, out_path=None):
    html = fonts.apply(TEMPLATE.read_text(encoding="utf-8"))
    total = len(results)
    passed = sum(1 for r in results if str(r.get("status", "")).startswith("Pass"))
    failed = sum(1 for r in results if r.get("status") == "Fail")
    not_eval = sum(1 for r in results if r.get("status") == "Not Evaluated")
    timestamp = datetime.now()
    repl = {
        "{{MODEL_NAME}}": model_name,
        "{{RULE_SET}}": rule_set,
        "{{RUN_TIMESTAMP}}": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "{{TOTAL}}": str(total),
        "{{PASSED}}": str(passed),
        "{{FAILED}}": str(failed),
        "{{NOT_EVALUATED}}": str(not_eval),
        "{{RESULTS_JSON}}": json.dumps(results, ensure_ascii=False),
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    if out_path is None:
        stem = _safe(model_name)
        rs = _safe(rule_set)
        stamp = timestamp.strftime("%Y%m%d-%H%M%S")
        out_dir = ROOT / "output" / "BPA" / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{stem}_{rs}_{stamp}.html"
    Path(out_path).write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    results = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = render(results, sys.argv[2], sys.argv[3],
                 sys.argv[4] if len(sys.argv) > 4 else None)
    print(f"Report written: {out}")
