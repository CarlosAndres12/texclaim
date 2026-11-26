"""Markdown rendering of the report dict (PLAN §13), in English or Spanish."""

from __future__ import annotations

from collections import defaultdict

from texclaim.reporting.json_report import FIXES

LABELS: dict[str, dict] = {
    "en": {
        "title": "texclaim report", "findings": "Findings", "none": "No findings.",
        "concl": "Abstract and conclusions consistency",
        "internal": "Internal consistency (uncited statements)",
        "uncheckable": "Uncheckable checks", "integrity": "Bibliography integrity",
        "manifest": "Sources", "suppressed": "Suppressed findings", "nothing": "None.",
        "what_is_wrong": "What is wrong", "what_source_says": "What the source says",
        "analysis": "Analysis", "evidence": "Evidence", "fix": "Suggested fix",
        "confidence": "Confidence", "scope": "evidence", "model": "model", "note": "Note",
        "page": "PDF page", "printed": "printed", "match": "match", "open": "open",
        "needs_review": "needs review", "uncited": "uncited statement",
        "manuscript": "manuscript", "claim": "CLAIM", "run": "run", "models": "model(s)",
        "time": "Run time", "to": "to", "cost": "Cost", "calls": "calls", "claims": "Claims",
        "units": "checks", "verified": "verified this run", "reused": "reused",
        "sources": "Sources", "full": "full text", "abstract_only": "abstract only",
        "nosrc": "none", "n_suppressed": "suppressed",
        "cols": "| key | OpenAlex | provider | version | status | file |",
        "roles": {"abstract": "abstract", "conclusion": "conclusion"},
        "scopes": {"full_text": "full text", "passages": "passages", "abstract": "abstract",
                   "none": "none"},
        "verdicts": {"SUPPORTED": "Supported", "PARTIALLY_SUPPORTED": "Partially supported",
                     "CONTRADICTED": "Contradicted", "NOT_FOUND": "Not found",
                     "UNCHECKABLE": "Uncheckable"},
        "conf": {"low": "low", "medium": "medium", "high": "high"},
    },
    "es": {
        "title": "Informe de texclaim", "findings": "Hallazgos", "none": "Sin hallazgos.",
        "concl": "Coherencia del resumen y las conclusiones",
        "internal": "Coherencia interna (afirmaciones sin cita)",
        "uncheckable": "Verificaciones no concluyentes",
        "integrity": "Integridad de la bibliografía", "manifest": "Fuentes",
        "suppressed": "Hallazgos suprimidos", "nothing": "Ninguno.",
        "what_is_wrong": "Qué está mal", "what_source_says": "Qué dice la fuente",
        "analysis": "Análisis", "evidence": "Evidencia", "fix": "Corrección sugerida",
        "confidence": "Confianza", "scope": "evidencia", "model": "modelo", "note": "Nota",
        "page": "página del PDF", "printed": "impresa", "match": "coincidencia",
        "open": "abrir", "needs_review": "requiere revisión", "uncited": "afirmación sin cita",
        "manuscript": "manuscrito", "claim": "AFIRMACIÓN", "run": "ejecución",
        "models": "modelo(s)", "time": "Ejecución", "to": "a", "cost": "Costo",
        "calls": "llamadas", "claims": "Afirmaciones", "units": "verificaciones",
        "verified": "verificadas en esta ejecución", "reused": "reutilizadas",
        "sources": "Fuentes", "full": "texto completo", "abstract_only": "solo resumen",
        "nosrc": "ninguna", "n_suppressed": "suprimidos",
        "cols": "| clave | OpenAlex | proveedor | versión | estado | archivo |",
        "roles": {"abstract": "resumen", "conclusion": "conclusión"},
        "scopes": {"full_text": "texto completo", "passages": "pasajes", "abstract": "resumen",
                   "none": "ninguna"},
        "verdicts": {"SUPPORTED": "Respaldada", "PARTIALLY_SUPPORTED": "Parcialmente respaldada",
                     "CONTRADICTED": "Contradicha", "NOT_FOUND": "No encontrada",
                     "UNCHECKABLE": "No verificable"},
        "conf": {"low": "baja", "medium": "media", "high": "alta"},
    },
}  # fmt: skip


STATUS_ES = {
    "completed": "completada", "interrupted": "interrumpida",
    "budget_exhausted": "presupuesto agotado",
    "FULL_TEXT": "texto completo", "ABSTRACT_ONLY": "solo resumen", "NO_SOURCE": "no encontrada",
    "MISSING_BIB_ENTRY": "falta la entrada .bib", "MALFORMED_BIB_ENTRY": "entrada mal formada",
    "SOURCE_IDENTITY_MISMATCH": "documento equivocado", "SCANNED_PDF": "PDF escaneado",
    "EXTRACTION_FAILED": "PDF ilegible",
}  # fmt: skip
STATUS_EN = {
    "FULL_TEXT": "full text", "ABSTRACT_ONLY": "abstract only", "NO_SOURCE": "not found",
    "MISSING_BIB_ENTRY": "missing .bib entry", "MALFORMED_BIB_ENTRY": "malformed entry",
    "SOURCE_IDENTITY_MISMATCH": "wrong document", "SCANNED_PDF": "scanned PDF",
    "EXTRACTION_FAILED": "unreadable PDF", "budget_exhausted": "budget exhausted",
}  # fmt: skip
PROVIDERS = {
    "local": ("your PDF", "su PDF"), "cache": ("cached copy", "copia en caché"),
    "openalex_content": ("OpenAlex", "OpenAlex"), "oa_locations": ("open-access copy",
    "copia de acceso abierto"), "arxiv": ("arXiv", "arXiv"), "asta": ("Asta", "Asta"),
    "abstract": ("abstract", "resumen"),
}  # fmt: skip
VERSIONS = {
    "publishedVersion": ("published", "publicada"), "acceptedVersion": ("accepted", "aceptada"),
    "submittedVersion": ("preprint", "preprint"),
}  # fmt: skip


def _status(code: str | None, es: bool) -> str:
    if not code:
        return ""
    return (STATUS_ES if es else STATUS_EN).get(code, code)


def _note(text: str, es: bool) -> str:
    import re

    if not es:
        return text
    m = re.match(r"internal checks: (\d+) of (\d+) uncited statements selected", text)
    if m:
        return f"verificaciones internas: se seleccionaron {m[1]} de {m[2]} afirmaciones sin cita"
    m = re.match(r"(\d+) unit\(s\) were verified with another model", text)
    if m:
        return f"{m[1]} resultado(s) se verificaron con otro modelo y se conservaron"
    return text


def labels(lang: str | None) -> dict:
    return LABELS.get((lang or "en")[:2], LABELS["en"])


def _when(iso: str | None) -> str:
    return (iso.replace("T", " ")[:16] + " UTC") if iso else "-"


def _quote(q: dict, key: str, version: str | None, L: dict) -> str:
    text = q["text"].replace("\n", " ")
    if key == L["manuscript"]:  # internal evidence: pages are the manuscript's sections
        where = f"{key}" + (f" · {q['page_label']}" if q.get("page_label") else "")
        return f'**{L["evidence"]}:** "{text}"  \n{where}'
    where = f"{key} · {L['page']} {q['page']}"
    if q.get("page_label") and str(q["page_label"]) != str(q["page"]):
        where += f" ({L['printed']} {q['page_label']})"
    if q.get("section"):
        where += f" · {q['section']}"
    where += f" · {L['match']} {q['score']:g}"
    if version:
        where += f" · {version}"
    if q.get("link"):
        where += f" · [{L['open']}]({q['link']})"
    return f'**{L["evidence"]}:** "{text}"  \n{where}'


def _finding(f: dict, L: dict) -> str:
    if f["kind"] == "claim":
        return (
            f"### {f['id']} · {L['claim']} · {f['file']}:{f['line']}\n\n> {f['claim_latex']}\n\n"
            f"**{L['note']}:** {f['detail']}\n"
        )
    title = L["verdicts"].get(f["verdict"], f["verdict"])
    if f["needs_review"]:
        title += f" · {L['needs_review']}"
    if f.get("claim_origin") == "internal":
        title += " · " + (L["roles"].get(f["role"], f["role"]) if f["role"] else L["uncited"])
    out = [f"### {f['id']} · {title} · {f['file']}:{f['line']}", "", f"> {f['claim_latex']}"]
    for label, k in (
        (L["what_is_wrong"], "what_is_wrong"),
        (L["what_source_says"], "what_source_says"),
    ):
        if f[k]:
            out += ["", f"**{label}:** {f[k]}"]
    if f["analysis"] and not (f["what_is_wrong"] or f["what_source_says"]):
        out += ["", f"**{L['analysis']}:** {f['analysis']}"]
    for q in f["quotes"]:
        key = L["manuscript"] if f["bib_key"] == "@self" else f["bib_key"]
        out += ["", _quote(q, key, None if f["bib_key"] == "@self" else f["source_version"], L)]
    if f["suggested_fix"]:
        out += ["", f"**{L['fix']}:** {f['suggested_fix']}"]
    scope = L["scopes"].get(f["evidence_scope"], f["evidence_scope"])
    conf = L["conf"].get(f["confidence"] or "", f["confidence"] or "-")
    out += ["", f"*{L['confidence']}: {conf} · {L['scope']}: {scope} · {L['model']}: {f['model']}*"]
    return "\n".join(out) + "\n"


def render_markdown(rep: dict, lang: str | None = None) -> str:
    run, c = rep["run"], rep["run"]["counts"]
    L = labels(lang or run.get("report_language"))
    es = L is LABELS["es"]
    cov = run["source_coverage"]
    lines = [
        f"# {L['title']}",
        "",
        f"- texclaim {run['tool_version']} · prompt {run['prompt_version']} · "
        f"{L['models']}: {', '.join(run['models']) or '-'} · {L['run']} {run['run_id']} "
        f"({_status(run['status'], es)})",
        f"- {L['time']}: {_when(run['started_at'])} {L['to']} {_when(run['finished_at'])}",
        f"- {L['cost']}: LLM ${run['llm_cost_usd']:.4f} ({run['llm_calls']} {L['calls']}) · "
        f"OpenAlex ${run['openalex_cost_usd']:.2f}",
        f"- {L['claims']}: {c['claims']} · {L['units']}: {c['units']} · {L['verified']}: "
        f"{c['verified_this_run']} · {L['reused']}: {c['reused']}",
        f"- {L['sources']}: {cov['full_text']} {L['full']} · {cov['abstract_only']} "
        f"{L['abstract_only']} · {cov['none']} {L['nosrc']}",
    ]
    lines += [f"- {L['note']}: {_note(n, es)}" for n in run["notes"]]
    shown = [f for f in rep["findings"] if not f["suppressed"]]
    cited = [f for f in shown if f.get("claim_origin") != "internal"]
    concl = [f for f in shown if f.get("claim_origin") == "internal" and f.get("role")]
    other = [f for f in shown if f.get("claim_origin") == "internal" and not f.get("role")]
    lines += ["", f"## {L['findings']}", ""]
    lines += [_finding(f, L) for f in cited] or [L["none"] + "\n"]
    if concl or other or any(u.get("claim_origin") == "internal" for u in rep["units"]):
        lines += [f"## {L['concl']}", ""]
        lines += [_finding(f, L) for f in concl] or [L["none"] + "\n"]
        lines += [f"## {L['internal']}", ""]
        lines += [_finding(f, L) for f in other] or [L["none"] + "\n"]

    lines += [f"## {L['uncheckable']}", ""]
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
        lines += [L["nothing"], ""]

    lines += [f"## {L['integrity']}", ""]
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
        lines.append(L["nothing"])
    lines += ["", f"## {L['manifest']}", "", L["cols"], "| --- | --- | --- | --- | --- | --- |"]
    for s in rep["sources"]:
        link = f"[{L['open']}]({s['link']})" if s["link"] else ""
        prov = PROVIDERS.get(s["provider"] or "", (s["provider"] or "",) * 2)[1 if es else 0]
        ver = VERSIONS.get(s["version"] or "", (s["version"] or "",) * 2)[1 if es else 0]
        lines.append(
            f"| {s['bib_key']} | {s['openalex_id'] or ''} | {prov} | "
            f"{ver} | {_status(s['status'], es)} | {link} |"
        )
    hidden = [f for f in rep["findings"] if f["suppressed"]] + [
        i for i in rep["integrity"] if i["suppressed"]
    ]
    lines += ["", f"## {L['suppressed']}", "", f"{len(hidden)} {L['n_suppressed']}."]
    for h in hidden:
        why = h.get("suppression_reason") or L["n_suppressed"]
        lines.append(f"- {h['id']}: {why}")
    return "\n".join(lines) + "\n"
