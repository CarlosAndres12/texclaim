"""Markdown rendering of the report dict (PLAN §13)."""

from __future__ import annotations

from collections import defaultdict

from texclaim.reporting.json_report import FIXES

SCOPE = {"full_text": "full text", "passages": "passages", "abstract": "abstract", "none": "none"}


def _quote(q: dict, key: str, version: str | None) -> str:
    where = f"{key} · PDF page {q['page']}"
    if q.get("page_label") and str(q["page_label"]) != str(q["page"]):
        where += f" (printed {q['page_label']})"
    if q.get("section"):
        where += f" · {q['section']}"
    where += f" · match {q['score']:g}"
    if version:
        where += f" · {version}"
    if q.get("link"):
        where += f" · [open]({q['link']})"
    text = q["text"].replace("\n", " ")
    return f'**Evidence:** "{text}"\n  {where}'


def _finding(f: dict) -> str:
    if f["kind"] == "claim":
        return (
            f"### {f['id']} · CLAIM · {f['file']}:{f['line']}\n> {f['claim_latex']}\n\n"
            f"**Note:** {f['detail']}\n"
        )
    title = f["verdict"] + (" · needs review" if f["needs_review"] else "")
    if f.get("claim_origin") == "internal":
        title += " · " + (f["role"] or "uncited statement")
    out = [f"### {f['id']} · {title} · {f['file']}:{f['line']}", f"> {f['claim_latex']}", ""]
    for label, k in (
        ("What is wrong", "what_is_wrong"),
        ("What the source says", "what_source_says"),
    ):
        if f[k]:
            out.append(f"**{label}:** {f[k]}")
    if f["analysis"] and not (f["what_is_wrong"] or f["what_source_says"]):
        out.append(f"**Analysis:** {f['analysis']}")
    for q in f["quotes"]:
        key = "manuscript" if f["bib_key"] == "@self" else f["bib_key"]
        out.append(_quote(q, key, None if key == "manuscript" else f["source_version"]))
    if f["suggested_fix"]:
        out.append(f"**Suggested fix:** {f['suggested_fix']}")
    scope = SCOPE.get(f["evidence_scope"], f["evidence_scope"])
    out.append(f"**Confidence:** {f['confidence'] or '-'} · scope: {scope} · model: {f['model']}")
    return "\n".join(out) + "\n"


def render_markdown(rep: dict) -> str:
    run, c = rep["run"], rep["run"]["counts"]
    cov = run["source_coverage"]
    lines = [
        "# texclaim report",
        "",
        f"- texclaim {run['tool_version']} · prompt {run['prompt_version']} · "
        f"model(s): {', '.join(run['models']) or '-'} · run {run['run_id']} ({run['status']})",
        f"- Run time: {run['started_at']} to {run['finished_at']}",
        f"- Cost: LLM ${run['llm_cost_usd']:.4f} ({run['llm_calls']} calls) · "
        f"OpenAlex ${run['openalex_cost_usd']:.2f}",
        f"- Claims: {c['claims']} · units: {c['units']} · verified this run: "
        f"{c['verified_this_run']} · reused: {c['reused']}",
        f"- Sources: {cov['full_text']} full text · {cov['abstract_only']} abstract only · "
        f"{cov['none']} none",
    ]
    lines += [f"- Note: {n}" for n in run["notes"]]
    shown = [f for f in rep["findings"] if not f["suppressed"]]
    cited = [f for f in shown if f.get("claim_origin") != "internal"]
    concl = [f for f in shown if f.get("claim_origin") == "internal" and f.get("role")]
    other = [f for f in shown if f.get("claim_origin") == "internal" and not f.get("role")]
    lines += ["", "## Findings", ""]
    lines += [_finding(f) for f in cited] or ["No findings.\n"]
    if concl or other or any(u.get("claim_origin") == "internal" for u in rep["units"]):
        lines += ["## Abstract and conclusions consistency", ""]
        lines += [_finding(f) for f in concl] or ["No findings.\n"]
        lines += ["## Internal consistency (uncited statements)", ""]
        lines += [_finding(f) for f in other] or ["No findings.\n"]

    lines += ["## Uncheckable units", ""]
    groups: dict[str, list[dict]] = defaultdict(list)
    for u in rep["units"]:
        if (
            u["verdict"] == "UNCHECKABLE"
            and not u["suppressed"]
            and u.get("claim_origin") != "internal"
        ):
            groups[u["reason_code"]].append(u)
    for reason in sorted(groups):
        fix = FIXES.get(reason, "")
        lines.append(f"### {reason} ({len(groups[reason])})")
        for u in groups[reason]:
            hint = fix.format(key=u["bib_key"], pdf_dir=rep["pdf_dir"])
            lines.append(
                f"- `{u['file']}:{u['line']}` `{u['bib_key']}`" + (f": {hint}" if hint else "")
            )
        lines.append("")
    if not groups:
        lines += ["None.", ""]

    lines += ["## Bibliography integrity", ""]
    active = [i for i in rep["integrity"] if not i["suppressed"]]
    for i in active:
        loc = (
            f"`{i['file']}:{i['line']}` "
            if i["file"] and i["line"]
            else (f"`{i['file']}` " if i["file"] else "")
        )
        key = f"`{i['bib_key']}` " if i["bib_key"] else ""
        lines.append(f"- **{i['severity']}** {i['code']} {loc}{key}{i['detail']} ({i['id']})")
    if not active:
        lines.append("None.")
    header = "| key | OpenAlex | provider | version | status | file |"
    lines += ["", "## Source manifest", "", header, "| --- | --- | --- | --- | --- | --- |"]
    for s in rep["sources"]:
        link = f"[open]({s['link']})" if s["link"] else ""
        lines.append(
            f"| {s['bib_key']} | {s['openalex_id'] or ''} | {s['provider'] or ''} | "
            f"{s['version'] or ''} | {s['status']} | {link} |"
        )
    hidden = [f for f in rep["findings"] if f["suppressed"]] + [
        i for i in rep["integrity"] if i["suppressed"]
    ]
    lines += ["", "## Suppressed findings", "", f"{len(hidden)} suppressed."]
    for h in hidden:
        why = h.get("suppression_reason") or "suppressed"
        lines.append(f"- {h['id']}: {why}")
    return "\n".join(lines) + "\n"
