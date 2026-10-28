#!/usr/bin/env python3
"""Power BI Agentic — main dashboard web app.

A local Flask app that is the single entry point for both tools:
  - landing page with tool cards, file upload, agent selection + reorderable sequence, Execute;
  - Performance Analyzer runs fully in-browser (upload export JSON -> report);
  - BPA uses a hybrid bridge (needs the live engine): the app gives the exact @bpa-agent command
    and shows the newest BPA report once the agent has produced it, and can render a BPA
    results JSON the agent output;
  - a Reports page listing every BPA and Performance Analyzer report.

Run:
    python dashboard/app.py          # -> http://127.0.0.1:8000
"""
import json
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from flask import (Flask, abort, jsonify, render_template, request,
                   send_file, url_for)
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.render_perf_report import render as render_perf          # noqa: E402
from scripts.render_report import render as render_bpa                # noqa: E402
from scripts.evaluate_bpa import (load_model as bpa_load_model,       # noqa: E402
                                  load_rules as bpa_load_rules,
                                  evaluate as bpa_evaluate)
from scripts.find_unused_artifacts import run as unused_run           # noqa: E402
from scripts.build_lineage import run as lineage_run                  # noqa: E402
from scripts.load_tmdl import load as tmdl_load                       # noqa: E402

EXTRACT_PS1 = ROOT / "scripts" / "extract_model_dmv.ps1"
LAUNCH_PS1 = ROOT / "scripts" / "launch_and_extract.ps1"
# Performance Analyzer code is kept, but hidden from the dashboard UI.
UI_TOOLS = ("BPA", "UnusedArtifacts", "DataLineage")

OUTPUT = ROOT / "output"
UPLOADS = ROOT / "dashboard" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB (pbix can be large)


# --------------------------------------------------------------------------- helpers
def _rel_output(p: Path) -> str:
    return p.resolve().relative_to(OUTPUT).as_posix()


def _list_reports():
    items = []
    tool_pats = {"BPA": "BPA/**/*.html",
                 "UnusedArtifacts": "UnusedArtifacts/**/*.html",
                 "DataLineage": "DataLineage/**/*.html",
                 "PerformanceAnalyzer": "PerformanceAnalyzer/**/*.html"}
    for tool in UI_TOOLS:                       # perf excluded from the UI listing (code kept)
        pat = tool_pats[tool]
        for f in OUTPUT.glob(pat):
            st = f.stat()
            items.append({
                "tool": tool,
                "name": f.name,
                "subject": f.parent.name,
                "rel": _rel_output(f),
                "viewUrl": url_for("view_report", f=_rel_output(f)),
                "mtime": st.st_mtime,
                "when": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "sizeKb": round(st.st_size / 1024),
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _latest_bpa_for(model_stem: str):
    from scripts.render_report import _safe
    folder = OUTPUT / "BPA" / _safe(model_stem)
    if not folder.exists():
        return None
    files = sorted(folder.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return None
    f = files[0]
    return {"rel": _rel_output(f), "viewUrl": url_for("view_report", f=_rel_output(f)),
            "name": f.name}


def _bpa_command(model_file: str, rule_set: str) -> str:
    return (f'@bpa-agent run the Best Practice Analyzer on "{model_file}" '
            f'using the {rule_set} rule set')


# --------------------------------------------------------------------------- pages
@app.route("/")
def dashboard():
    return render_template("dashboard.html", reports=_list_reports()[:6])


@app.route("/reports")
def reports():
    return render_template("reports.html", reports=_list_reports())


@app.route("/view")
def view_report():
    rel = request.args.get("f", "")
    target = (OUTPUT / rel).resolve()
    if not str(target).startswith(str(OUTPUT.resolve())) or not target.is_file():
        abort(404)
    return send_file(target)


# --------------------------------------------------------------------------- API
@app.route("/api/reports")
def api_reports():
    return jsonify(_list_reports())


@app.route("/api/latest-bpa")
def api_latest_bpa():
    model = request.args.get("model", "")
    res = _latest_bpa_for(Path(model).stem)
    return jsonify(res or {})


@app.route("/execute", methods=["POST"])
def execute():
    """Run the selected agents in the given order.
    Form: steps = JSON list of {"agent":"perf"|"bpa"}, ruleSet, plus uploaded files."""
    try:
        steps = json.loads(request.form.get("steps", "[]"))
    except json.JSONDecodeError:
        steps = []
    rule_set = request.form.get("ruleSet", "all")
    launch = request.form.get("launch", "0") in ("1", "true", "True")
    tmdl_path_field = (request.form.get("tmdlPath", "") or "").strip().strip('"')

    # Save uploads, routed by extension
    pbix_files, perf_files, zip_files = [], [], []
    for fs in request.files.getlist("files"):
        if not fs or not fs.filename:
            continue
        name = fs.filename
        safe = secure_filename(name) or "upload"
        dest = UPLOADS / safe
        fs.save(dest)
        low = name.lower()
        if low.endswith(".pbix"):
            pbix_files.append({"original": name, "path": dest})
        elif low.endswith(".json"):
            perf_files.append({"original": name, "path": dest})
        elif low.endswith((".zip", ".pbip")):
            zip_files.append({"original": name, "path": dest})

    tmdl_source = _resolve_tmdl_source(tmdl_path_field, zip_files)
    ctx = {"pbix_files": pbix_files, "tmdl_source": tmdl_source, "launch": launch}

    results = []
    for i, step in enumerate(steps, 1):
        agent = step.get("agent")
        if agent == "perf":
            results.append(_run_perf(i, perf_files))
        elif agent == "bpa":
            results.append(_run_bpa(i, ctx, rule_set))
        elif agent == "unused":
            results.append(_run_unused(i, ctx))
        elif agent == "lineage":
            results.append(_run_lineage(i, ctx))
    return jsonify({"results": results})


def _resolve_tmdl_source(path_field, zip_files):
    """Return a folder path containing TMDL (a PBIP project / *.SemanticModel), or None.
    Accepts a local folder path typed into the UI, or an uploaded .zip/.pbip to unpack."""
    import zipfile
    if path_field:
        p = Path(path_field)
        if p.is_dir() and any(p.rglob("*.tmdl")):
            return str(p)
    for zf in zip_files:
        try:
            with zipfile.ZipFile(zf["path"]) as z:
                if not any(n.lower().endswith(".tmdl") for n in z.namelist()):
                    continue
                dest = UPLOADS / ("tmdl_" + Path(secure_filename(zf["original"])).stem)
                if dest.exists():
                    import shutil
                    shutil.rmtree(dest, ignore_errors=True)
                dest.mkdir(parents=True, exist_ok=True)
                z.extractall(dest)
                return str(dest)
        except Exception:  # noqa: BLE001
            continue
    return None


def _acquire_model(ctx):
    """Resolve a model JSON + a report source from the chosen input, trying in order:
      1) PBIP/TMDL folder  -> parse text files, fully offline (no Desktop, no engine)
      2) already-open live model (ADOMD)
      3) .pbix with nothing open -> only if launch=True (opens Desktop, extracts, closes)
    Returns dict: {jsonPath, reportPath, source, modelName} or {error, needsLaunch, modelName}."""
    tmdl_source, pbix_files, launch = ctx["tmdl_source"], ctx["pbix_files"], ctx["launch"]
    # 1) TMDL
    if tmdl_source:
        try:
            model = tmdl_load(tmdl_source)
            tmp = Path(tempfile.gettempdir()) / "pbi_model_tmdl.json"
            tmp.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
            return {"jsonPath": str(tmp), "reportPath": tmdl_source, "source": "tmdl",
                    "modelName": Path(tmdl_source).name}
        except Exception as e:  # noqa: BLE001
            return {"error": f"Couldn't parse the TMDL/PBIP folder: {e}", "needsLaunch": False,
                    "modelName": Path(tmdl_source).name}
    pbix_path = str(pbix_files[0]["path"]) if pbix_files else None
    model_name = pbix_files[0]["original"] if pbix_files else "Live model"
    # 2) live
    json_path, info = _extract_live_model()
    if json_path:
        return {"jsonPath": str(json_path), "reportPath": pbix_path, "source": "live",
                "modelName": model_name}
    # 3) launch
    if launch and pbix_path:
        jp, info2 = _launch_extract_model(pbix_path)
        if jp:
            return {"jsonPath": str(jp), "reportPath": pbix_path, "source": "launched",
                    "modelName": model_name}
        return {"error": f"Launching Power BI Desktop failed: {info2}", "needsLaunch": False,
                "modelName": model_name}
    if pbix_path:
        msg = ("No model is open in Power BI Desktop. Click “Launch Power BI Desktop & run” to "
               "open this .pbix automatically, or upload a PBIP/TMDL folder for a fully offline run.")
    else:
        msg = ("No model available — open the model in Power BI Desktop, upload a .pbix, or point "
               "to a PBIP/TMDL folder.")
    return {"error": msg, "needsLaunch": bool(pbix_path), "modelName": model_name}


def _launch_extract_model(pbix_path):
    tmp = Path(tempfile.gettempdir()) / "pbi_model_launched.json"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(LAUNCH_PS1), "-PbixPath", pbix_path, "-OutFile", str(tmp)],
            capture_output=True, text=True, timeout=300)
    except Exception as e:  # noqa: BLE001
        return None, f"Could not launch Power BI Desktop: {e}"
    if proc.returncode != 0 or not tmp.exists():
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        return None, (msg[-1] if msg else "Power BI Desktop did not produce a model.")
    return tmp, (proc.stdout or "").strip()


def _needs_model(seq, agent, title, acq):
    """Shape a 'no model yet' response; signals the UI to offer the launch button."""
    status = "needs-model" if acq.get("needsLaunch") else "error"
    return {"seq": seq, "agent": agent, "title": title, "status": status,
            "model": acq.get("modelName"),
            "message": acq.get("error") or "No model available.",
            "canLaunch": bool(acq.get("needsLaunch"))}


def _run_lineage(seq, ctx):
    """PBIP/TMDL (offline) or live/launched model + report layer -> data lineage graph."""
    acq = _acquire_model(ctx)
    if "jsonPath" not in acq:
        return _needs_model(seq, "lineage", "Data Lineage", acq)
    try:
        out_path, nodes, edges, stats = lineage_run(
            acq["jsonPath"], acq["reportPath"], acq["modelName"])
        return {
            "seq": seq, "agent": "lineage", "title": "Data Lineage", "status": "ok",
            "model": acq["modelName"], "source": acq["source"],
            "pbixParsed": bool(acq["reportPath"]),
            "viewUrl": url_for("view_report", f=_rel_output(out_path)),
            "nodes": stats["nodes"], "edges": stats["edges"],
            "visuals": stats["visuals"], "pages": stats["pages"],
            "orphans": stats["orphanCount"], "byType": stats["byType"],
        }
    except Exception as e:  # noqa: BLE001
        return {"seq": seq, "agent": "lineage", "title": "Data Lineage",
                "status": "error", "message": f"Lineage build failed: {e}"}


def _run_unused(seq, ctx):
    """PBIP/TMDL (offline) or live/launched model + report layer -> unused artifacts report."""
    acq = _acquire_model(ctx)
    if "jsonPath" not in acq:
        return _needs_model(seq, "unused", "Unused Artifacts", acq)
    try:
        out_path, records, summary = unused_run(
            acq["jsonPath"], acq["reportPath"], acq["modelName"])
        return {
            "seq": seq, "agent": "unused", "title": "Unused Artifacts", "status": "ok",
            "model": acq["modelName"], "source": acq["source"],
            "pbixParsed": bool(acq["reportPath"]),
            "viewUrl": url_for("view_report", f=_rel_output(out_path)),
            "scanned": summary["totalScanned"], "unused": summary["totalUnused"],
            "byType": summary["byType"],
        }
    except Exception as e:  # noqa: BLE001
        return {"seq": seq, "agent": "unused", "title": "Unused Artifacts",
                "status": "error", "message": f"Analysis failed: {e}"}


def _extract_live_model():
    """Run the DMV extractor against the running Power BI Desktop model.
    Returns (json_path, info) on success, or (None, error_message)."""
    tmp = Path(tempfile.gettempdir()) / "pbi_model_dashboard.json"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(EXTRACT_PS1), "-OutFile", str(tmp)],
            capture_output=True, text=True, timeout=120)
    except Exception as e:  # noqa: BLE001
        return None, f"Could not launch the extractor: {e}"
    if proc.returncode != 0 or not tmp.exists():
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        return None, (msg[-1] if msg else "No running Power BI Desktop model found.")
    return tmp, (proc.stdout or "").strip()


def _run_bpa(seq, ctx, rule_set):
    """PBIP/TMDL (offline) or live/launched model -> BPA. Falls back to the agent bridge."""
    acq = _acquire_model(ctx)
    model_file = acq.get("modelName", "Live model")
    if "jsonPath" in acq:
        try:
            model = bpa_load_model(acq["jsonPath"])
            results = bpa_evaluate(model, bpa_load_rules(rule_set))
            out_path = render_bpa(results, model_file, rule_set)
            passed = sum(1 for r in results if str(r["status"]).startswith("Pass"))
            failed = sum(1 for r in results if r["status"] == "Fail")
            return {
                "seq": seq, "agent": "bpa", "title": "Best Practice Analyzer",
                "status": "ok", "mode": acq["source"], "model": model_file, "ruleSet": rule_set,
                "source": acq["source"],
                "viewUrl": url_for("view_report", f=_rel_output(out_path)),
                "total": len(results), "passed": passed, "failed": failed,
                "counts": {"tables": len(model["tables"]), "columns": len(model["columns"]),
                           "measures": len(model["measures"]),
                           "relationships": len(model["relationships"])},
            }
        except Exception as e:  # noqa: BLE001
            acq["error"] = f"Extracted the model but evaluation failed: {e}"
    # Fallback: engine not available -> bridge (offer launch too)
    latest = _latest_bpa_for(Path(model_file).stem) if ctx["pbix_files"] else None
    return {
        "seq": seq, "agent": "bpa", "title": "Best Practice Analyzer",
        "status": "bridge", "model": model_file, "ruleSet": rule_set,
        "canLaunch": bool(acq.get("needsLaunch")),
        "command": _bpa_command(model_file, rule_set), "latest": latest,
        "message": ((acq.get("error") or "No model open.") + " Use “Launch Power BI Desktop & "
                    "run”, open the .pbix yourself and Execute again, or upload a PBIP/TMDL "
                    "folder for a fully offline run."),
    }


def _run_perf(seq, perf_files):
    if not perf_files:
        return {"seq": seq, "agent": "perf", "title": "Performance Analyzer",
                "status": "error",
                "message": "No Performance Analyzer export (.json) was uploaded. "
                           "Export one from Power BI Desktop > Optimize > Performance Analyzer."}
    out = []
    for pf in perf_files:
        try:
            report_path, visuals, summary, rule_results = render_perf(str(pf["path"]))
            failed = sum(1 for r in rule_results if r["status"] == "Fail")
            out.append({
                "export": pf["original"],
                "viewUrl": url_for("view_report", f=_rel_output(report_path)),
                "summary": summary, "rulesFailed": failed,
            })
        except Exception as e:  # noqa: BLE001
            out.append({"export": pf["original"], "error": str(e)})
    ok = any("viewUrl" in o for o in out)
    return {"seq": seq, "agent": "perf", "title": "Performance Analyzer",
            "status": "ok" if ok else "error", "runs": out}


@app.route("/render-bpa-json", methods=["POST"])
def render_bpa_json():
    """Render a BPA report from a results JSON produced by @bpa-agent."""
    model = request.form.get("model", "model.pbix")
    rule_set = request.form.get("ruleSet", "all")
    payload = request.form.get("resultsJson", "").strip()
    fs = request.files.get("resultsFile")
    try:
        if fs and fs.filename:
            results = json.loads(fs.read().decode("utf-8-sig"))
        else:
            results = json.loads(payload)
        if not isinstance(results, list):
            raise ValueError("Results JSON must be an array of rule objects.")
        out_path = render_bpa(results, model, rule_set)
        return jsonify({"status": "ok",
                        "viewUrl": url_for("view_report", f=_rel_output(out_path)),
                        "count": len(results)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e),
                        "detail": traceback.format_exc().splitlines()[-1]})


def _serve(host="127.0.0.1", port=8000):
    """Serve the dashboard on a production WSGI server (waitress) so there is no
    'development server' warning. Falls back to Flask's built-in server only if
    waitress isn't installed, or when PBIA_DEV=1 is set (auto-reload for coding)."""
    url = f"http://{host}:{port}"
    if os.environ.get("PBIA_DEV") == "1":
        print(f"Power BI Agentic dashboard (DEV / auto-reload) -> {url}  (Ctrl+C to stop)")
        app.run(host=host, port=port, debug=True)
        return
    try:
        from waitress import serve
    except ImportError:
        print(f"Power BI Agentic dashboard -> {url}  (Ctrl+C to stop)")
        print("  (install 'waitress' for the production server: python -m pip install waitress)")
        app.run(host=host, port=port, debug=False)
        return
    print(f"Power BI Agentic dashboard -> {url}  (Ctrl+C to stop)")
    print("  Serving with waitress (production WSGI server).")
    serve(app, host=host, port=port, threads=8, ident="PowerBI-Agentic")


if __name__ == "__main__":
    _serve(host=os.environ.get("PBIA_HOST", "127.0.0.1"),
           port=int(os.environ.get("PBIA_PORT", "8000")))
