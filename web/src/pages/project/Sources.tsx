import * as React from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BookMarked, Download, ExternalLink, Eye, FileArchive, Globe, Search, Upload } from "lucide-react";
import { api, urls, type Project, type SourceRow, type Verdict } from "@/lib/api";
import { cn, displayKey, VERDICTS } from "@/lib/utils";
import { friendlyError } from "@/lib/errors";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton, Tooltip } from "@/components/ui/misc";
import { EmptyState, ErrorState, PageHeader, VerdictDot } from "@/components/common";
import { PdfViewer } from "@/components/PdfViewer";

const STATUS_TONE: Record<string, string> = {
  FULL_TEXT: "text-supported border-supported/40 bg-supported/10",
  ABSTRACT_ONLY: "text-partial border-partial/40 bg-partial/10",
};

function UploadButton({ project, row }: { project: Project; row: SourceRow }) {
  const { t } = useTranslation();
  const ref = React.useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const up = useMutation({
    mutationFn: (f: File) => api.uploadSourcePdf(project.id, row.bib_key, f),
    onSuccess: () => { toast.success(t("sources.uploaded")); qc.invalidateQueries({ queryKey: ["sources", project.id] }); },
    onError: (e: Error) => toast.error(friendlyError(e, t)),
  });
  return (
    <>
      <Tooltip content={row.file_kind === "pdf" ? t("sources.replacePdf") : t("sources.uploadPdf")}>
        <Button variant="ghost" size="icon-sm" onClick={() => ref.current?.click()} aria-label={`${t("sources.uploadPdf")} ${row.bib_key}`} disabled={up.isPending} data-testid={`upload-${row.bib_key}`}><Upload /></Button>
      </Tooltip>
      <input ref={ref} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = ""; }} />
    </>
  );
}

export default function SourcesTab({ project }: { project: Project }) {
  const { t } = useTranslation();
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["sources", project.id], queryFn: () => api.sources(project.id), retry: false });
  const [filter, setFilter] = React.useState("");
  const [view, setView] = React.useState<SourceRow | null>(null);
  const [text, setText] = React.useState<string | null>(null);

  React.useEffect(() => {
    setText(null);
    if (view && view.file_kind !== "pdf") fetch(urls.sourceFile(project.id, view.bib_key)).then((r) => r.text()).then(setText).catch(() => setText(""));
  }, [view, project.id]);

  if (isLoading) return <Skeleton className="h-96" />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data?.length) return <EmptyState icon={<BookMarked />} title={project.summary ? t("sources.noCitations") : t("sources.empty")} />;

  const q = filter.toLowerCase();
  const rows = data.filter((r) => !q || `${r.bib_key} ${r.title ?? ""} ${r.authors.join(" ")}`.toLowerCase().includes(q));
  const statusLabel = (s: string) => t(`sources.statusLabel.${s}`, { defaultValue: s });

  return (
    <div className="space-y-4">
      <PageHeader title={t("sources.title")} description={t("sources.subtitle")}
        actions={<Button variant="outline" asChild><a href={urls.sourcesZip(project.id)} download><FileArchive />{t("sources.downloadAll")}</a></Button>} />
      <div className="relative max-w-sm">
        <Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" />
        <Input className="pl-9" placeholder={t("sources.filter")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={t("sources.filter")} />
      </div>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="sources-table">
            <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2.5 font-medium">{t("sources.work")}</th>
                <th className="px-4 py-2.5 font-medium">{t("sources.status")}</th>
                <th className="hidden px-4 py-2.5 font-medium md:table-cell">{t("sources.results")}</th>
                <th className="px-4 py-2.5 text-right font-medium">{t("sources.file")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => (
                <tr key={r.bib_key} className="hover:bg-muted/30">
                  <td className="max-w-[460px] px-4 py-3">
                    <div className="font-medium leading-snug">{r.title || displayKey(r.bib_key, "")}</div>
                    <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
                      <span className="font-mono">{displayKey(r.bib_key, "")}</span>
                      {r.authors.length > 0 && <span>{r.authors.slice(0, 3).join(", ")}{r.authors.length > 3 ? " et al." : ""}</span>}
                      {r.year && <span>{r.year}</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline" className={cn(STATUS_TONE[r.status])}>{statusLabel(r.status)}</Badge>
                    {r.provider && <div className="mt-1 text-[11px] text-muted-foreground">{t(`sources.provider.${r.provider}`, { defaultValue: r.provider })}{r.version ? ` · ${t(`sources.version.${r.version}`, { defaultValue: r.version })}` : ""}</div>}
                  </td>
                  <td className="hidden px-4 py-3 md:table-cell">
                    <div className="flex flex-wrap gap-2">
                      {VERDICTS.filter((v) => r.verdicts[v]).map((v: Verdict) => (
                        <Tooltip key={v} content={t(`verdict.${v}`)}><span className="flex items-center gap-1 text-xs tabular-nums"><VerdictDot verdict={v} />{r.verdicts[v]}</span></Tooltip>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center justify-end gap-0.5">
                      <span className="mr-2 hidden text-xs text-muted-foreground sm:inline">{t(`sources.kind.${r.file_kind}`)}</span>
                      {r.file_kind !== "none" && (
                        <>
                          <Tooltip content={r.file_kind === "pdf" ? t("sources.viewPdf") : t("sources.viewText")}>
                            <Button variant="ghost" size="icon-sm" onClick={() => setView(r)} aria-label={`${t("sources.viewPdf")} ${r.bib_key}`} data-testid={`view-${r.bib_key}`}><Eye /></Button>
                          </Tooltip>
                          <Tooltip content={t("sources.downloadFile")}>
                            <Button variant="ghost" size="icon-sm" asChild><a href={urls.sourceFile(project.id, r.bib_key, true)} aria-label={`${t("sources.downloadFile")} ${r.bib_key}`}><Download /></a></Button>
                          </Tooltip>
                        </>
                      )}
                      <UploadButton project={project} row={r} />
                      {(r.landing_page || r.doi_url) && (
                        <Tooltip content={r.landing_page ? t("sources.landing") : t("sources.doi")}>
                          <Button variant="ghost" size="icon-sm" asChild><a href={r.landing_page || r.doi_url!} target="_blank" rel="noreferrer" aria-label={t("sources.landing")}>{r.landing_page ? <Globe /> : <ExternalLink />}</a></Button>
                        </Tooltip>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Dialog open={!!view} onOpenChange={(o) => !o && setView(null)}>
        <DialogContent className="flex h-[90vh] max-w-5xl flex-col" closeLabel={t("app.close")}>
          <DialogHeader><DialogTitle className="pr-8 leading-snug">{view?.title || view?.bib_key}</DialogTitle></DialogHeader>
          {view && view.file_kind === "pdf" ? (
            <PdfViewer url={urls.sourceFile(project.id, view.bib_key)} className="min-h-0 flex-1" />
          ) : (
            <pre className="min-h-0 flex-1 overflow-auto rounded-lg bg-muted p-4 text-xs leading-relaxed whitespace-pre-wrap scrollbar-thin">{text ?? t("app.loading")}</pre>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
