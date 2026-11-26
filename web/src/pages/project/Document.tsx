import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, FileText } from "lucide-react";
import { api, type Project, type Unit, type Verdict } from "@/lib/api";
import { cleanClaim, cn, VERDICT_COLOR, VERDICTS } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/misc";
import { EmptyState, ErrorState, VerdictBadge, VerdictLegend } from "@/components/common";
import { useReport } from "./hooks";

const worst = (vs: Verdict[]) => VERDICTS.find((v) => vs.includes(v));
const FLAGGED = new Set<Verdict>(["CONTRADICTED", "PARTIALLY_SUPPORTED", "NOT_FOUND"]);

export default function DocumentTab({ project }: { project: Project }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const { data: doc, isLoading, error, refetch } = useQuery({ queryKey: ["document", project.id], queryFn: () => api.document(project.id), retry: false });
  const { data: report } = useReport(project.id);
  const [onlyFlagged, setOnlyFlagged] = React.useState(false);
  const [openLine, setOpenLine] = React.useState<number | null>(null);
  const files = doc?.files ?? [];
  const file = files.find((f) => f.path === params.get("file")) ?? files[0];
  const targetLine = Number(params.get("line") || 0);
  const lineRefs = React.useRef<Record<number, HTMLDivElement | null>>({});

  const byLine = React.useMemo(() => {
    const m = new Map<number, Unit[]>();
    if (!report || !file) return m;
    for (const u of report.units) {
      if (u.file !== file.path || u.suppressed) continue;
      if (onlyFlagged && !FLAGGED.has(u.verdict)) continue;
      for (let l = u.line; l <= Math.max(u.line, u.line_end); l++) {
        const arr = m.get(l) ?? [];
        arr.push(u);
        m.set(l, arr);
      }
    }
    return m;
  }, [report, file, onlyFlagged]);

  React.useEffect(() => {
    if (targetLine && lineRefs.current[targetLine]) {
      lineRefs.current[targetLine]!.scrollIntoView({ block: "center" });
      setOpenLine(targetLine);
    }
  }, [targetLine, file?.path, doc]);

  if (isLoading) return <Skeleton className="h-[600px]" />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!file) return <EmptyState icon={<FileText />} title={t("document.empty")} />;

  const flaggedLines = [...byLine.entries()].filter(([, us]) => us.some((u) => FLAGGED.has(u.verdict))).map(([l]) => l).sort((a, b) => a - b);
  const jump = () => {
    const next = flaggedLines.find((l) => l > (openLine ?? 0)) ?? flaggedLines[0];
    if (next) { lineRefs.current[next]?.scrollIntoView({ block: "center", behavior: "smooth" }); setOpenLine(next); }
  };
  const fileCounts: Partial<Record<Verdict, number>> = {};
  report?.units.filter((u) => u.file === file.path).forEach((u) => (fileCounts[u.verdict] = (fileCounts[u.verdict] ?? 0) + 1));
  const opened = openLine != null ? byLine.get(openLine) : undefined;
  const seen = new Set<string>();

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          {files.length > 1 && (
            <div className="w-full sm:w-64"><Select ariaLabel={t("document.file")} value={file.path} onValueChange={(v) => setParams({ file: v })} options={files.map((f) => ({ value: f.path, label: f.path }))} /></div>
          )}
          <Label className="text-sm font-normal"><Switch checked={onlyFlagged} onCheckedChange={setOnlyFlagged} />{t("document.onlyFlagged")}</Label>
          <Button variant="outline" size="sm" onClick={jump} disabled={!flaggedLines.length}><ArrowDown />{t("document.jump")}</Button>
        </div>
        <VerdictLegend counts={fileCounts} />
      </div>
      <p className="text-xs text-muted-foreground">{t("document.legend")}</p>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <Card className="min-w-0 overflow-hidden">
          <div className="border-b bg-muted/40 px-4 py-2 font-mono text-xs text-muted-foreground">{file.path}</div>
          <div className="max-h-[calc(100vh-300px)] overflow-auto font-mono text-[13px] leading-6 scrollbar-thin" data-testid="document-view">
            {file.lines.map((text, i) => {
              const n = i + 1;
              const us = byLine.get(n);
              const w = us ? worst(us.map((u) => u.verdict)) : undefined;
              return (
                <div key={n} ref={(el) => { lineRefs.current[n] = el; }}
                  className={cn("group grid grid-cols-[56px_1fr]", w && "cursor-pointer", openLine === n && "ring-2 ring-inset ring-primary/50")}
                  style={w ? { background: `color-mix(in oklch, ${VERDICT_COLOR[w]} ${openLine === n ? 22 : 11}%, transparent)` } : undefined}
                  onClick={() => w && setOpenLine(n)} data-line={n} data-verdict={w}>
                  <span className="sticky left-0 border-r bg-card/90 pr-3 text-right text-xs leading-6 text-muted-foreground select-none" style={w ? { boxShadow: `inset 3px 0 0 ${VERDICT_COLOR[w]}` } : undefined}>
                    {file.unit === "paragraph" ? `¶${n}` : n}
                  </span>
                  <span className={cn("px-3 break-words whitespace-pre-wrap", file.unit === "paragraph" && "py-1.5 font-sans")}>{text || " "}</span>
                </div>
              );
            })}
          </div>
        </Card>
        <div className="xl:sticky xl:top-20 xl:self-start">
          {opened?.length ? (
            <Card><CardContent className="space-y-4 pt-5">
              <p className="font-mono text-xs text-muted-foreground">{file.path}:{openLine}</p>
              {opened.filter((u) => !seen.has(u.unit_key) && seen.add(u.unit_key)).map((u) => (
                <div key={u.unit_key} className="space-y-2 rounded-lg border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <VerdictBadge verdict={u.verdict} />
                    <span className="font-mono text-xs text-muted-foreground">{u.bib_key === "@self" ? t("findings.selfSource") : u.bib_key}</span>
                  </div>
                  <p className="text-sm">{cleanClaim(u.claim_text)}</p>
                  {(u.what_is_wrong || u.analysis) && <p className="text-xs text-muted-foreground">{u.what_is_wrong || u.analysis}</p>}
                  <Button variant="link" size="sm" className="h-auto p-0" asChild><Link to={`/projects/${project.id}/findings?f=${u.id}&all=1`}>{t("findings.detail")} →</Link></Button>
                </div>
              ))}
            </CardContent></Card>
          ) : (
            <Card><CardContent className="pt-5 text-sm text-muted-foreground">{byLine.size ? t("document.legend") : report ? t("document.noClaims") : t("document.empty")}</CardContent></Card>
          )}
        </div>
      </div>
    </div>
  );
}
