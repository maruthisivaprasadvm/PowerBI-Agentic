#!/usr/bin/env python3
"""In-browser agent bridge (runs inside Pyodide).

The static web app writes the user's Power BI Project (PBIP/TMDL) files into the Pyodide
virtual filesystem under a work dir, then calls `run(agent, workdir, model_name)`. We reuse
the exact same pure-Python parsers the local app uses — nothing is uploaded; everything runs
in the browser.

Only the fully-offline PBIP/TMDL path is supported online: a browser cannot read a binary
.pbix model (that needs the Power BI engine / Desktop). A PBIP project provides both the
model (*.SemanticModel) and the report layer (*.Report) for visual usage.
"""
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # /app in Pyodide
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import load_tmdl                                 # noqa: E402
import build_lineage                             # noqa: E402
import find_unused_artifacts as unused           # noqa: E402
import evaluate_bpa                              # noqa: E402
import render_report                             # noqa: E402

AGENTS = ("lineage", "unused", "bpa")


def _extract_archives(base: Path):
    """Extract any .zip / .pbip archives the user dropped so the TMDL text is on the FS."""
    for z in list(base.rglob("*")):
        if z.is_file() and z.suffix.lower() in (".zip", ".pbip") and zipfile.is_zipfile(z):
            try:
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(base / (z.stem + "_extracted"))
            except Exception:  # noqa: BLE001
                pass


def _model_name(base: Path) -> str:
    # prefer the *.SemanticModel folder name, else the project/top folder
    for p in base.rglob("*.SemanticModel"):
        return p.name.replace(".SemanticModel", "")
    hits = list(base.rglob("model.tmdl"))
    if hits:
        # .../<Name>.SemanticModel/definition/model.tmdl  -> <Name>
        for parent in hits[0].parents:
            if parent.name.endswith(".SemanticModel"):
                return parent.name.replace(".SemanticModel", "")
    return base.name or "model"


def run(agent, workdir, model_name=None):
    """Run one agent against the uploaded PBIP tree. Returns a dict for JS.
    Keys: status, html, filename, stats(optional), message(on error)."""
    base = Path(workdir)
    _extract_archives(base)

    if not list(base.rglob("model.tmdl")):
        return {"status": "error",
                "message": ("No PBIP/TMDL model found. Choose a Power BI Project (PBIP) "
                            "folder — the one containing a '*.SemanticModel' folder — or a "
                            ".zip of it. A binary .pbix cannot be read in the browser; in "
                            "Power BI Desktop use File → Save as → Power BI Project "
                            "(.pbip) once to unlock it.")}

    name = model_name or _model_name(base)
    report = str(base)                    # PBIP *.Report provides the report layer

    try:
        model = load_tmdl.load(str(base))
        jpath = ROOT / "work_model.json"
        jpath.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")

        if agent == "lineage":
            out, _nodes, _edges, stats = build_lineage.run(str(jpath), report, name)
            return {"status": "ok", "agent": agent, "model": name,
                    "html": Path(out).read_text(encoding="utf-8"),
                    "filename": Path(out).name, "stats": stats}

        if agent == "unused":
            out, _records, summary = unused.run(str(jpath), report, name)
            return {"status": "ok", "agent": agent, "model": name,
                    "html": Path(out).read_text(encoding="utf-8"),
                    "filename": Path(out).name, "stats": summary}

        if agent == "bpa":
            m = evaluate_bpa.load_model(str(jpath))
            results = evaluate_bpa.evaluate(m, evaluate_bpa.load_rules("all"))
            out = render_report.render(results, name, "all")
            npass = sum(1 for r in results if r.get("status") == "Pass")
            nfail = sum(1 for r in results if r.get("status") == "Fail")
            return {"status": "ok", "agent": agent, "model": name,
                    "html": Path(out).read_text(encoding="utf-8"),
                    "filename": Path(out).name,
                    "stats": {"total": len(results), "passed": npass, "failed": nfail}}

        return {"status": "error", "message": f"Unknown agent '{agent}'."}
    except Exception as e:  # noqa: BLE001
        import traceback
        return {"status": "error",
                "message": f"{type(e).__name__}: {e}",
                "detail": traceback.format_exc().splitlines()[-3:]}
