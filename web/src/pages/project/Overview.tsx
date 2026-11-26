import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle, ArrowRight, BookOpen, CircleDollarSign, Download, FileArchive, FileCode2, FileJson, FileText, FileType2, Layers, ListChecks, Play, Quote,
} from "lucide-react";
import type { Project, Verdict } from "@/lib/api";
import { urls } from "@/lib/api";
import { cleanClaim, displayKey, formatCost, formatDate, VERDICT_COLOR, VERDICTS } from "@/lib/utils";
import { Alert } from "@/components/ui/misc";
import { Loader2 } from "lucide-react";
import { translateNotice } from "@/lib/errors";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/misc";
import { EmptyState, StatCard, VerdictBadge, VerdictBar, VerdictLegend } from "@/components/common";
import { useRun } from "../Project";
import { isNotFound, useOutline, useReport } from "./hooks";

function Structure({ pid }: { pid: string }) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useOutline(pid);
  if (isLoading) return <Skeleton className="h-40" />;
  if (error || !data) return <p className="text-sm text-destructive">{error instanceof Error ? error.message : ""}</p>;
  const max = Math.max(1, ...data.sections.map((s) => s.cited + s.internal));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge variant="secondary" className="uppercase">{data.kind}</Badge>
        <Badge variant="outline" className="font-mono">{data.main}</Badge>
        <Badge variant="outline">{t("overview.sectionsCount", { count: data.sections.length })}</Badge>
        <Badge variant="outline">{t("overview.citedClaims", { count: data.cited_claims })}</Badge>
        <Badge variant="outline">{t("overview.candidates", { count: data.internal_candidates })}</Badge>
      </div>
      <ul className="space-y-1.5">
        {data.sections.map((s) => (
          <li key={s.title} className="grid grid-cols-[minmax(0,1fr)_120px] items-center gap-3 text-sm">
            <span className="truncate">{s.title}{s.role && !s.title.toLowerCase().startsWith(t(`findings.role.${s.role}`).toLowerCase().slice(0, 6)) && !s.title.toLowerCase().startsWith(s.role.slice(0, 6)) && <span className="ml-1.5 text-xs text-muted-foreground">({t(`findings.role.${s.role}`)})</span>}</span>
            <div className="flex h-2 overflow-hidden rounded-full bg-muted" title={`${s.cited} / ${s.internal}`}>
              <div className="bg-primary" style={{ width: `${(s.cited / max) * 100}%` }} />
              <div className="bg-primary/35" style={{ width: `${(s.internal / max) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
      <div className="flex gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-primary" />{t("overview.citations")}</span>
        <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-primary/35" />{t("overview.internal")}</span>
      </div>
      {data.diagnostics.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{t("overview.diagnostics")} ({data.diagnostics.length})</summary>
          <ul className="mt-2 space-y-1">{data.diagnostics.map((d, i) => <li key={i}><code>{d.code}</code> {d.detail} {d.file && <span className="font-mono">{d.file}:{d.line}</span>}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

export default function OverviewTab({ project }: { project: Project }) {
  const { t, i18n } = useTranslation();
  const run = useRun();
  const { data: report, isLoading, error } = useReport(project.id);
  const s = project.summary;

  if (isLoading) return <div className="grid gap-4 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>;
  if (!report || isNotFound(error) || !s) {
    return (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <EmptyState icon={<ListChecks />} title={t("project.notChecked")} body={t("project.startFirst")}
          action={<div className="flex gap-2"><Button onClick={() => run.start()} disabled={run.running}><Play />{t("project.checkNow")}</Button><Button variant="outline" asChild><Link to={`/projects/${project.id}/settings`}>{t("project.settings")}</Link></Button></div>} />
        <Card><CardHeader><CardTitle>{t("overview.structure")}</CardTitle></CardHeader><CardContent><Structure pid={project.id} /></CardContent></Card>
      </div>
    );
  }

  const cited: Partial<Record<Verdict, number>> = {};
  const internal: Partial<Record<Verdict, number>> = {};
  for (const u of report.units) {
    const bucket = u.claim_origin === "internal" ? internal : cited;
    bucket[u.verdict] = (bucket[u.verdict] ?? 0) + 1;
  }
  const flagged = report.findings.filter((f) => f.kind === "unit" && !f.suppressed).slice(0, 6);
  const cov = report.run.source_coverage;
  const covTotal = cov.full_text + cov.abstract_only + cov.none || 1;
  const downloads = [
    { fmt: "html", label: t("overview.reportHtml"), icon: <FileCode2 /> },
    { fmt: "docx", label: t("overview.reportDocx"), icon: <FileType2 /> },
    { fmt: "md", label: t("overview.reportMd"), icon: <FileText /> },
    { fmt: "json", label: t("overview.reportJson"), icon: <FileJson /> },
  ];

  return (
    <div className="space-y-6">
      {run.running && <Alert variant="info"><Loader2 className="animate-spin" /><p>{t("overview.runningNote")}</p></Alert>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label={t("overview.claims")} value={report.run.counts.claims} icon={<Quote />} hint={`${report.units.length} ${t("overview.units").toLowerCase()}`} />
        <StatCard label={t("overview.findings")} value={s.findings} icon={<AlertTriangle />} accent={s.findings ? VERDICT_COLOR.CONTRADICTED : undefined}
          hint={VERDICTS.filter((v) => (s.finding_verdicts?.[v] ?? 0) > 0).map((v) => t(`verdictCount.${v}`, { count: s.finding_verdicts![v] })).join(" · ") || "—"} />
        <StatCard label={t("overview.coverage")} value={`${Math.round((cov.full_text / covTotal) * 100)}%`} icon={<BookOpen />}
          hint={`${cov.full_text} ${t("overview.fullText").toLowerCase()} · ${cov.abstract_only} ${t("overview.abstractOnly").toLowerCase()} · ${cov.none} ${t("overview.noSource").toLowerCase()}`} />
        <StatCard label={t("overview.cost")} value={formatCost(report.run.llm_cost_usd)} icon={<CircleDollarSign />}
          hint={`${t("overview.model")}: ${report.run.models.join(", ") || "—"}`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("overview.verdicts")}</CardTitle>
              <CardDescription>{t("overview.finished")}: {formatDate(report.run.finished_at, i18n.language)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {[[t("overview.citations"), cited], [t("overview.internal"), internal]].map(([label, counts]) => (
                <div key={label as string} className="space-y-2">
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="font-medium">{label as string}</span>
                    <span className="text-xs text-muted-foreground tabular-nums">{Object.values(counts as object).reduce((a: number, b) => a + (b as number), 0)}</span>
                  </div>
                  <VerdictBar counts={counts as Partial<Record<Verdict, number>>} className="h-3" />
                  <VerdictLegend counts={counts as Partial<Record<Verdict, number>>} />
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>{t("overview.topFindings")}</CardTitle>
              <Button variant="ghost" size="sm" asChild><Link to={`/projects/${project.id}/findings`}>{t("overview.viewAll")}<ArrowRight /></Link></Button>
            </CardHeader>
            <CardContent>
              {flagged.length === 0 ? (
                <p className="rounded-lg bg-supported/10 p-4 text-sm text-supported">{t("overview.noFindings")}</p>
              ) : (
                <ul className="divide-y">
                  {flagged.map((f) => (
                    <li key={f.id}>
                      <Link to={`/projects/${project.id}/findings?f=${f.id}`} className="flex items-start gap-3 rounded-md px-2 py-3 hover:bg-accent/50">
                        {f.verdict && <VerdictBadge verdict={f.verdict} className="mt-0.5" />}
                        <div className="min-w-0 flex-1">
                          <p className="line-clamp-2 text-sm">{cleanClaim(f.claim_text || f.claim_latex)}</p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            <span className="font-mono">{f.file}:{f.line}</span> · {displayKey(f.bib_key, t("findings.selfSource"))}
                            {f.role ? ` · ${t(`findings.role.${f.role}`)}` : ""}
                          </p>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Download className="size-4" />{t("overview.downloads")}</CardTitle></CardHeader>
            <CardContent className="grid gap-2">
              {downloads.map((d) => (
                <Button key={d.fmt} variant="outline" className="justify-start" asChild>
                  <a href={urls.report(project.id, d.fmt)} download data-testid={`download-${d.fmt}`}>{d.icon}{d.label}</a>
                </Button>
              ))}
              <Button variant="outline" className="justify-start" asChild>
                <a href={urls.sourcesZip(project.id)} download><FileArchive />{t("overview.sourcesZip")}</a>
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Layers className="size-4" />{t("overview.structure")}</CardTitle></CardHeader>
            <CardContent><Structure pid={project.id} /></CardContent>
          </Card>
          {report.run.notes.length > 0 && (
            <Card><CardContent className="space-y-1 pt-5 text-xs text-muted-foreground">{report.run.notes.map((n, i) => <p key={i}>• {translateNotice(n, t)}</p>)}</CardContent></Card>
          )}
        </div>
      </div>
    </div>
  );
}
