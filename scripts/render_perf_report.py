#!/usr/bin/env python3
"""Parse a Power BI Desktop Performance Analyzer export, evaluate performance rules,
and render a self-contained HTML dashboard.

Usage:
    python scripts/render_perf_report.py <export.json> [rules.json] [out.html]

<export.json>  A Performance Analyzer export (Power BI Desktop > Optimize ribbon >
               Performance Analyzer > Export). Conforms to performanceAnalyzerExport.schema.json
               (microsoft/powerbi-desktop-samples): { version, events:[{id,parentId,name,
               component,start,end,metrics}] }.

Output (per-export subfolder + timestamp, so each export keeps its own history):
    output/PerformanceAnalyzer/<export>/<export>_<YYYYMMDD-HHMMSS>.html

The parser aggregates each visual's event subtree into the three categories Power BI itself
reports — DAX query, Visual display, Other — plus DirectQuery counts, row counts and query text.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fonts  # noqa: E402  (embeds the iA Writer webfonts)
TEMPLATE = ROOT / "templates" / "perf-report-template.html"
DEFAULT_RULES = ROOT / "rules" / "performance" / "PerfRules.json"


# --------------------------------------------------------------------------- helpers
def _safe(name: str) -> str:
    stem = re.sub(r"\.json$", "", str(name), flags=re.IGNORECASE)
    stem = re.sub(r'[<>:"/\\|?*]+', "_", stem).strip().strip(".")
    return stem or "export"


def _parse_ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_ms(ev):
    """Prefer an explicit duration metric; fall back to end - start."""
    m = ev.get("metrics") or {}
    for k in ("durationMs", "DurationMs", "duration", "totalMs"):
        if isinstance(m.get(k), (int, float)):
            return float(m[k])
    s, e = _parse_ts(ev.get("start")), _parse_ts(ev.get("end"))
    if s and e:
        return max(0.0, (e - s).total_seconds() * 1000.0)
    return 0.0


def _text(ev):
    return f"{ev.get('name', '')} {ev.get('component', '')}".lower()


def _matches(ev, keywords):
    t = _text(ev)
    return any(k.lower() in t for k in keywords)


def _metric_any(ev, keys):
    m = ev.get("metrics") or {}
    for k in keys:
        for mk, mv in m.items():
            if mk.lower() == k.lower():
                return mv
    return None


# --------------------------------------------------------------------------- parse
def parse_export(export, cat_kw):
    events = export.get("events", []) or []
    by_id = {str(e.get("id")): e for e in events if e.get("id") is not None}
    children = {}
    for e in events:
        pid = e.get("parentId")
        if pid is not None:
            children.setdefault(str(pid), []).append(e)

    dax_kw = cat_kw.get("DAX Query", [])
    rnd_kw = cat_kw.get("Visual Display", [])
    dq_kw = cat_kw.get("DirectQuery", [])

    def subtree(ev):
        out = [ev]
        for c in children.get(str(ev.get("id")), []):
            out.extend(subtree(c))
        return out

    def category_root_sum(nodes, root_ev, keywords):
        """Sum durations of events matching `keywords` that have no matching ancestor
        within the visual subtree (avoids double-counting nested lifecycle events)."""
        ids = {str(n.get("id")) for n in nodes}
        total, count = 0.0, 0
        for n in nodes:
            if not _matches(n, keywords):
                continue
            # walk up to the visual root; skip if an ancestor also matches
            anc = n.get("parentId")
            has_match_anc = False
            while anc is not None and str(anc) in ids and str(anc) != str(root_ev.get("id")):
                p = by_id.get(str(anc))
                if p is None:
                    break
                if _matches(p, keywords):
                    has_match_anc = True
                    break
                anc = p.get("parentId")
            if not has_match_anc:
                total += _duration_ms(n)
                count += 1
        return total, count

    # Identify visual containers. Match the container component exactly — child lifecycle
    # events ("Visual Container Lifecycle · Query · ...") also contain the phrase and must NOT
    # be treated as separate visuals.
    containers = [e for e in events
                  if (e.get("component", "") or "").strip().lower() == "visual container"]
    if not containers:
        # Fallback: treat root events (no parent) that own a DAX or render descendant as visuals
        for e in events:
            if e.get("parentId") is None:
                st = subtree(e)
                if any(_matches(n, dax_kw) or _matches(n, rnd_kw) for n in st):
                    containers.append(e)

    visuals = []
    for i, c in enumerate(containers):
        nodes = subtree(c)
        dax_ms, q_count = category_root_sum(nodes, c, dax_kw)
        rnd_ms, _ = category_root_sum(nodes, c, rnd_kw)
        dq_count = sum(1 for n in nodes if _matches(n, dq_kw))
        total_ms = _duration_ms(c)
        if total_ms <= 0:
            total_ms = dax_ms + rnd_ms
        other_ms = max(0.0, total_ms - dax_ms - rnd_ms)

        row_count = None
        query_text = None
        for n in nodes:
            if _matches(n, dax_kw):
                rc = _metric_any(n, ["rowCount", "rows"])
                if isinstance(rc, (int, float)) and row_count is None:
                    row_count = rc
                qt = _metric_any(n, ["QueryText", "queryText", "query", "QueryProcessingText"])
                if qt and not query_text:
                    query_text = str(qt)

        m = c.get("metrics") or {}
        title = (m.get("title") or m.get("name") or m.get("visualTitle")
                 or c.get("name") or f"Visual {i + 1}")
        vtype = (m.get("visualType") or m.get("visualContainerType")
                 or m.get("type") or "")
        visuals.append({
            "id": str(c.get("id")),
            "title": str(title),
            "visualType": str(vtype),
            "daxMs": round(dax_ms, 1),
            "renderMs": round(rnd_ms, 1),
            "otherMs": round(other_ms, 1),
            "totalMs": round(total_ms, 1),
            "directQueryCount": dq_count,
            "queryCount": q_count,
            "rowCount": row_count,
            "queryText": query_text,
        })

    summary = {
        "visualCount": len(visuals),
        "totalDaxMs": round(sum(v["daxMs"] for v in visuals), 1),
        "totalRenderMs": round(sum(v["renderMs"] for v in visuals), 1),
        "slowestMs": round(max((v["totalMs"] for v in visuals), default=0), 1),
    }
    return visuals, summary


# --------------------------------------------------------------------------- rules
_OPS = {
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    "=": lambda a, b: a == b, "==": lambda a, b: a == b,
}


def _visual_metric(v, metric):
    if metric == "daxShareOfSlow":
        return (v["daxMs"] / v["totalMs"]) if v["totalMs"] > 1000 else 0.0
    return v.get(metric)


def evaluate_rules(rules, visuals, summary):
    results = []
    for r in rules:
        op = _OPS.get(r.get("operator", ">"))
        thr = r.get("threshold")
        metric = r.get("metric")
        unit = " ms" if str(metric).endswith("Ms") else ""
        offenders = []
        if r.get("scope") == "report":
            val = summary.get(metric)
            if val is None and metric == "visualCount":
                val = summary["visualCount"]
            status = "Fail" if (val is not None and op and op(val, thr)) else "Pass"
            if status == "Fail":
                offenders.append({"visual": "(report total)", "value": round(val, 2), "unit": unit})
        else:  # visual scope
            for v in visuals:
                val = _visual_metric(v, metric)
                if val is not None and op and op(val, thr):
                    show = round(val, 2)
                    offenders.append({"visual": v["title"], "value": show,
                                      "unit": "" if metric == "daxShareOfSlow" else unit})
            status = "Fail" if offenders else "Pass"
        results.append({
            "id": r["id"], "name": r["name"], "category": r.get("category", ""),
            "severity": r.get("severity", 1), "scope": r.get("scope", "visual"),
            "metric": metric, "operator": r.get("operator", ">"), "threshold": thr,
            "unit": "" if metric == "daxShareOfSlow" else unit,
            "status": status, "offenders": offenders,
            "description": r.get("description", ""), "remediation": r.get("remediation", ""),
        })
    return results


# --------------------------------------------------------------------------- render
def render(export_path, rules_path=None, out_path=None):
    export = json.loads(Path(export_path).read_text(encoding="utf-8-sig"))
    rules_doc = json.loads(Path(rules_path or DEFAULT_RULES).read_text(encoding="utf-8-sig"))
    cat_kw = rules_doc.get("categoryKeywords", {})
    rules = rules_doc.get("rules", [])

    visuals, summary = parse_export(export, cat_kw)
    results = evaluate_rules(rules, visuals, summary)

    html = fonts.apply(TEMPLATE.read_text(encoding="utf-8"))
    ts = datetime.now()
    name = Path(export_path).stem
    repl = {
        "{{EXPORT_NAME}}": name,
        "{{VERSION}}": str(export.get("version", "?")),
        "{{RUN_TIMESTAMP}}": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "{{VISUALS_JSON}}": json.dumps(visuals, ensure_ascii=False),
        "{{RESULTS_JSON}}": json.dumps(results, ensure_ascii=False),
        "{{SUMMARY_JSON}}": json.dumps(summary, ensure_ascii=False),
    }
    for k, v in repl.items():
        html = html.replace(k, v)

    if out_path is None:
        stem = _safe(name)
        out_dir = ROOT / "output" / "PerformanceAnalyzer" / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{stem}_{ts.strftime('%Y%m%d-%H%M%S')}.html"
    Path(out_path).write_text(html, encoding="utf-8")
    return out_path, visuals, summary, results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    rules_arg = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].lower().endswith(".json") else None
    out_arg = next((a for a in sys.argv[2:] if a.lower().endswith(".html")), None)
    out, visuals, summary, results = render(sys.argv[1], rules_arg, out_arg)
    failed = sum(1 for r in results if r["status"] == "Fail")
    print(f"Report written: {out}")
    print(f"  visuals: {summary['visualCount']}  slowest: {summary['slowestMs']} ms  "
          f"total DAX: {summary['totalDaxMs']} ms  rules failed: {failed}")
