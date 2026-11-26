import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, Copy, ExternalLink, FileSearch, MapPin, Search, SearchX, Sparkles } from "lucide-react";
import { api, urls, type Project, type Quote, type Unit, type Verdict } from "@/lib/api";
import { cleanClaim, cn, VERDICT_COLOR, VERDICTS } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Alert, Skeleton } from "@/components/ui/misc";
import { EmptyState, ErrorState, VerdictBadge, VerdictDot } from "@/components/common";
import { PdfViewer } from "@/components/PdfViewer";
import { isNotFound, useReport } from "./hooks";

type Origin = "all" | "cited" | "internal" | "conclusions";

function Field({ label, children, tone }: { label: string; children: React.ReactNode; tone?: string }) {
  return (
    <div className="space-y-1">
      <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</h4>
      <div className="text-sm leading-relaxed" style={tone ? { color: tone } : undefined}>{children}</div>
    </div>
  );
}

function QuoteCard({ q, active, onShow, canShow, self = false }: { q: Quote; active: boolean; onShow: () => void; canShow: boolean; self?: boolean }) {
  const { t } = useTranslation();
  return (
    <figure className={cn("rounded-lg border-l-4 bg-muted/40 p-3 transition-colors", active ? "border-l-partial bg-partial/10" : "border-l-primary/40")}>
      <blockquote className="text-sm italic leading-relaxed">“{q.text}”</blockquote>
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {self ? (q.page_label && <span>{q.page_label}</span>) : (<>
          {q.page != null && <span>{t("findings.page", { page: q.page })}{q.page_label && String(q.page_label) !== String(q.page) ? ` (${t("findings.printed", { label: q.page_label })})` : ""}</span>}
          {q.section && <span className="truncate">{q.section}</span>}
        </>)}
        <span>{t("findings.match", { score: q.score })}</span>
        {canShow && <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onShow}><MapPin className="size-3" />{t("findings.showInPdf")}</Button>}
      </figcaption>
    </figure>
  );
}

function Detail({ u, project, fileKind, index, total, onPrev, onNext }: {
  u: Unit; project: Project; fileKind?: string; index: number; total: number; onPrev: () => void; onNext: () => void;
}) {
  const { t } = useTranslation();
  const [quoteIdx, setQuoteIdx] = React.useState(0);
  React.useEffect(() => setQuoteIdx(0), [u.unit_key]);
  const isSelf = u.bib_key === "@self";
  const hasPdf = fileKind === "pdf" && !isSelf;
  const q = u.quotes[quoteIdx];
  const copy = async (text: string) => { await navigator.clipboard.writeText(text); toast.success(t("findings.copied")); };

  return (
    <div className="grid min-h-0 min-w-0 gap-4 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="finding-detail">
      <Card className="min-h-0 min-w-0 overflow-hidden">
        <div className="flex items-center justify-between gap-2 border-b px-4 py-2.5">
          <div className="flex items-center gap-2">
            <VerdictBadge verdict={u.verdict} withHelp className="text-sm" />
            {u.needs_review && <Badge variant="outline" className="border-partial/50 text-partial">{t("findings.needsReview")}</Badge>}
            {u.claim_origin === "internal" && <Badge variant="secondary">{u.role ? t(`findings.role.${u.role}`) : t("findings.internal")}</Badge>}
          </div>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <span className="tabular-nums">{index + 1} / {total}</span>
            <Button variant="ghost" size="icon-sm" onClick={onPrev} disabled={index <= 0} aria-label={t("findings.prev")}><ChevronLeft /></Button>
            <Button variant="ghost" size="icon-sm" onClick={onNext} disabled={index >= total - 1} aria-label={t("findings.next")}><ChevronRight /></Button>
          </div>
        </div>
        <CardContent className="max-h-[calc(100vh-280px)] space-y-5 overflow-auto pt-4 scrollbar-thin">
          <div className="space-y-2">
            <p className="text-[15px] leading-relaxed font-medium">{cleanClaim(u.claim_text)}</p>
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <Link to={`/projects/${project.id}/document?line=${u.line}&file=${encodeURIComponent(u.file)}`} className="font-mono hover:underline">{u.file}:{u.line}</Link>
              {u.section && <span>{u.section}</span>}
              <span>{t("findings.key")}: <span className="font-mono">{isSelf ? t("findings.selfSource") : u.bib_key}</span></span>
            </p>
          </div>
          {u.what_is_wrong && <Field label={t("findings.whatIsWrong")} tone={VERDICT_COLOR[u.verdict]}>{u.what_is_wrong}</Field>}
          {u.what_source_says && <Field label={t("findings.whatSourceSays")}>{u.what_source_says}</Field>}
          {u.analysis && <Field label={t("findings.analysis")}>{u.analysis}</Field>}
          {u.suggested_fix && (
            <Field label={t("findings.suggestedFix")}>
              <div className="relative rounded-lg border bg-supported/5 p-3 pr-10 font-mono text-xs leading-relaxed">
                {u.suggested_fix}
                <Button variant="ghost" size="icon-sm" className="absolute top-1.5 right-1.5" onClick={() => copy(u.suggested_fix!)} aria-label={t("findings.copyFix")}><Copy /></Button>
              </div>
            </Field>
          )}
          <Field label={t("findings.evidence")}>
            {u.quotes.length ? (
              <div className="space-y-2">
                {u.quotes.map((qq, i) => <QuoteCard key={i} q={qq} self={isSelf} active={i === quoteIdx && hasPdf} canShow={hasPdf} onShow={() => setQuoteIdx(i)} />)}
              </div>
            ) : <p className="text-muted-foreground">{t("findings.noQuotes")}</p>}
          </Field>
          <dl className="grid grid-cols-2 gap-3 rounded-lg bg-muted/40 p-3 text-xs">
            <div><dt className="text-muted-foreground">{t("findings.confidence")}</dt><dd className="font-medium">{u.confidence ? t(`values.confidence.${u.confidence}`, { defaultValue: u.confidence }) : "—"}</dd></div>
            <div><dt className="text-muted-foreground">{t("findings.scope")}</dt><dd className="font-medium">{t(`values.scope.${u.evidence_scope}`, { defaultValue: u.evidence_scope })}</dd></div>
            {!isSelf && <div><dt className="text-muted-foreground">{t("findings.citationFunction")}</dt><dd className="font-medium">{u.citation_function ? t(`values.citationFunction.${u.citation_function}`, { defaultValue: u.citation_function }) : "—"}</dd></div>}
            {u.reason_code !== "NONE" && <div><dt className="text-muted-foreground">{t("findings.reason")}</dt><dd className="font-medium">{t(`values.reason.${u.reason_code}`, { defaultValue: u.reason_code })}</dd></div>}
            <div className="col-span-2"><dt className="text-muted-foreground">{t("overview.model")}</dt><dd className="font-medium">{u.model ?? "—"}</dd></div>
          </dl>
          {!isSelf && fileKind && fileKind !== "none" && (
            <Button variant="outline" size="sm" asChild>
              <a href={urls.sourceFile(project.id, u.bib_key)} target="_blank" rel="noreferrer"><ExternalLink />{t("findings.openSource")}</a>
            </Button>
          )}
        </CardContent>
      </Card>
      <div className="min-h-[520px] min-w-0 2xl:h-[calc(100vh-230px)]">
        {hasPdf ? (
          <PdfViewer url={urls.sourceFile(project.id, u.bib_key)} page={q?.page ?? 1} quote={q?.text} className="h-full min-h-[520px]" />
        ) : isSelf ? (
          <Card className="h-full"><CardContent className="space-y-3 pt-5 text-sm">
            <p className="text-muted-foreground">{t("findings.selfSource")}: {u.quotes.length ? "" : t("findings.noQuotes")}</p>
            {u.quotes.map((qq, i) => <blockquote key={i} className="rounded-lg border-l-4 border-l-partial bg-partial/10 p-3 italic">“{qq.text}”</blockquote>)}
          </CardContent></Card>
        ) : (
          <EmptyState icon={<FileSearch />} title={t("sources.kind.none")} body={t("findings.noPdf")} className="h-full"
            action={<Button variant="outline" asChild><Link to={`/projects/${project.id}/sources`}>{t("project.sources")}</Link></Button>} />
        )}
      </div>
    </div>
  );
}

export default function FindingsTab({ project }: { project: Project }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const { data: report, isLoading, error, refetch } = useReport(project.id);
  const { data: sources } = useQuery({ queryKey: ["sources", project.id], queryFn: () => api.sources(project.id), enabled: !!report });
  const [query, setQuery] = React.useState("");
  const [verdicts, setVerdicts] = React.useState<Set<Verdict>>(new Set());
  const [origin, setOrigin] = React.useState<Origin>((params.get("origin") as Origin) || "all");
  const [flaggedOnly, setFlaggedOnly] = React.useState(params.get("all") !== "1");

  const kinds = React.useMemo(() => Object.fromEntries((sources ?? []).map((s) => [s.bib_key, s.file_kind])), [sources]);
  const flaggedIds = React.useMemo(() => new Set((report?.findings ?? []).filter((f) => f.kind === "unit").map((f) => f.id)), [report]);

  const list = React.useMemo(() => {
    if (!report) return [];
    const q = query.trim().toLowerCase();
    const order = (v: Verdict) => VERDICTS.indexOf(v);
    return report.units
      .filter((u) => !u.suppressed)
      .filter((u) => !flaggedOnly || flaggedIds.has(u.id))
      .filter((u) => !verdicts.size || verdicts.has(u.verdict))
      .filter((u) => origin === "all" || (origin === "cited" ? u.claim_origin !== "internal" : origin === "internal" ? u.claim_origin === "internal" && !u.role : u.claim_origin === "internal" && !!u.role))
      .filter((u) => !q || `${u.claim_text} ${u.bib_key} ${u.file} ${u.section ?? ""}`.toLowerCase().includes(q))
      .sort((a, b) => order(a.verdict) - order(b.verdict) || a.file.localeCompare(b.file) || a.line - b.line);
  }, [report, query, verdicts, origin, flaggedOnly, flaggedIds]);

  const selectedId = params.get("f");
  const idx = Math.max(0, list.findIndex((u) => u.id === selectedId));
  const selected = list[idx];
  const select = (id: string) => setParams((p) => { p.set("f", id); return p; }, { replace: true });

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "j" || e.key === "ArrowDown") { if (list[idx + 1]) { e.preventDefault(); select(list[idx + 1].id); } }
      if (e.key === "k" || e.key === "ArrowUp") { if (list[idx - 1]) { e.preventDefault(); select(list[idx - 1].id); } }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (isLoading) return <div className="grid gap-4 lg:grid-cols-[400px_1fr]"><Skeleton className="h-[600px]" /><Skeleton className="h-[600px]" /></div>;
  if (isNotFound(error) || !report) return error && !isNotFound(error) ? <ErrorState error={error} onRetry={() => refetch()} /> : <EmptyState icon={<FileSearch />} title={t("project.notChecked")} body={t("project.startFirst")} />;

  const counts: Partial<Record<Verdict, number>> = {};
  for (const u of report.units) counts[u.verdict] = (counts[u.verdict] ?? 0) + 1;
  const toggle = (v: Verdict) => setVerdicts((s) => { const n = new Set(s); if (n.has(v)) n.delete(v); else n.add(v); return n; });

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)]">
      <Card className="flex min-h-0 flex-col lg:h-[calc(100vh-230px)]">
        <div className="space-y-3 border-b p-3">
          <div className="relative">
            <Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" />
            <Input placeholder={t("findings.search")} value={query} onChange={(e) => setQuery(e.target.value)} className="pl-9" aria-label={t("findings.search")} data-testid="findings-search" />
          </div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("findings.origin")}>
            {(["all", "cited", "internal", "conclusions"] as Origin[]).map((o) => (
              <button key={o} onClick={() => setOrigin(o)} aria-pressed={origin === o} data-testid={`origin-${o}`}
                className={cn("rounded-full border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer", origin === o ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
                {o === "all" ? t("app.all") : t(`findings.${o}`)}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("findings.verdict")}>
            {VERDICTS.map((v) => (
              <button key={v} onClick={() => toggle(v)} aria-pressed={verdicts.has(v)} disabled={!counts[v]}
                className={cn("flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition-colors disabled:opacity-40 cursor-pointer", verdicts.has(v) ? "bg-accent font-medium ring-1 ring-primary/40" : "hover:bg-accent/60")}>
                <VerdictDot verdict={v} />{t(`verdict.${v}`)}<span className="tabular-nums text-muted-foreground">{counts[v] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between">
            <Label className="text-xs font-normal text-muted-foreground"><Switch checked={flaggedOnly} onCheckedChange={setFlaggedOnly} data-testid="flagged-only" />{t("findings.flagged")}</Label>
            <span className="text-xs text-muted-foreground tabular-nums">{t("findings.count", { count: list.length })}</span>
          </div>
        </div>
        <ul className="min-h-0 flex-1 overflow-auto p-1.5 scrollbar-thin" data-testid="findings-list" aria-label={t("findings.title")}>
          {list.length === 0 && <li className="flex flex-col items-center gap-2 p-8 text-center text-sm text-muted-foreground"><SearchX className="size-6" />{t("findings.empty")}</li>}
          {list.map((u, i) => (
            <li key={u.unit_key}>
              <button onClick={() => select(u.id)} aria-current={i === idx}
                className={cn("w-full rounded-lg px-3 py-2.5 text-left transition-colors cursor-pointer", i === idx ? "bg-accent ring-1 ring-primary/30" : "hover:bg-muted/60")}>
                <div className="flex items-center gap-2">
                  <VerdictDot verdict={u.verdict} className="size-2.5" />
                  <span className="text-xs font-medium" style={{ color: VERDICT_COLOR[u.verdict] }}>{t(`verdict.${u.verdict}`)}</span>
                  {u.claim_origin === "internal" && <Sparkles className="size-3 text-muted-foreground" aria-label={t("findings.internal")} />}
                  <span className="ml-auto truncate font-mono text-[11px] text-muted-foreground">{u.bib_key === "@self" ? t("findings.selfSource") : u.bib_key}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-sm">{cleanClaim(u.claim_text)}</p>
                <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{u.file}:{u.line}</p>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {selected ? (
        <Detail u={selected} project={project} fileKind={kinds[selected.bib_key]} index={idx} total={list.length}
          onPrev={() => list[idx - 1] && select(list[idx - 1].id)} onNext={() => list[idx + 1] && select(list[idx + 1].id)} />
      ) : (
        <Alert variant="info"><FileSearch /><p>{t("findings.noSelection")}</p></Alert>
      )}
    </div>
  );
}
