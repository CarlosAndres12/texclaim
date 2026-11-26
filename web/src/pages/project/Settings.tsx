import * as React from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, FileText, KeyRound, Loader2, Upload } from "lucide-react";
import { registerFlusher, trackSave } from "@/lib/pending";
import { friendlyError } from "@/lib/errors";
import { api, type Project, type WebSettings } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Select } from "@/components/ui/select";
import { Alert, Skeleton } from "@/components/ui/misc";
import { Dropzone } from "@/components/common";
import { useOutline } from "./hooks";

const SCOPES = ["auto", "sentence", "two", "paragraph"] as const;
const AGENT_NAMES: Record<string, string> = { claude: "Claude Code", pi: "pi", agy: "Antigravity" };

function Row({ label, hint, htmlFor, children }: { label: string; hint?: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 py-4 md:grid-cols-[260px_1fr] md:gap-6">
      <div>
        <Label htmlFor={htmlFor}>{label}</Label>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function FilesCard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["files", project.id], queryFn: () => api.files(project.id) });
  const [files, setFiles] = React.useState<File[]>([]);
  const up = useMutation({
    mutationFn: () => api.uploadFiles(project.id, files),
    onSuccess: (r) => {
      toast.success(t("settings.filesAdded", { count: r.files.length }));
      setFiles([]);
      qc.invalidateQueries({ queryKey: ["files", project.id] });
      qc.invalidateQueries({ queryKey: ["outline", project.id] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><FileText className="size-4" />{t("settings.files")}</CardTitle>
        <CardDescription className="font-mono text-xs break-all">{project.folder}</CardDescription></CardHeader>
      <CardContent className="space-y-3">
        <ul className="max-h-56 divide-y overflow-auto rounded-lg border text-sm scrollbar-thin" data-testid="file-list">
          {(data ?? []).map((f) => (
            <li key={f.path} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span className="truncate font-mono text-xs">{f.path}</span>
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{(f.size / 1024).toFixed(1)} KB</span>
            </li>
          ))}
        </ul>
        {!project.external && (
          <>
            <Dropzone files={files} onFiles={setFiles} compact />
            {files.length > 0 && <Button onClick={() => up.mutate()} disabled={up.isPending}>{up.isPending ? <Loader2 className="animate-spin" /> : <Upload />}{t("settings.addFiles")}</Button>}
          </>
        )}
      </CardContent>
    </Card>
  );
}

const PROVIDERS = ["local", "cache", "openalex_content", "oa_locations", "arxiv", "asta", "abstract"];

function NumberField({ value, placeholder, onChange, min = 0, max, step = 1, label }: {
  value: number | null | undefined; placeholder: number | string; onChange: (v: number | null) => void;
  min?: number; max?: number; step?: number; label: string;
}) {
  return (
    <Input type="number" className="w-40" min={min} max={max} step={step} aria-label={label}
      value={value ?? ""} placeholder={String(placeholder)}
      onChange={(e) => onChange(e.target.value === "" ? null : Math.max(min, Math.min(max ?? Infinity, Number(e.target.value))))} />
  );
}

function ListField({ value, placeholder, onChange, label }: {
  value: string[] | null | undefined; placeholder: string; onChange: (v: string[] | null) => void; label: string;
}) {
  const [text, setText] = React.useState((value ?? []).join(", "));
  React.useEffect(() => setText((value ?? []).join(", ")), [value]);
  return (
    <Input className="font-mono" aria-label={label} value={text} placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => { const items = text.split(",").map((x) => x.trim()).filter(Boolean); onChange(items.length ? items : null); }} />
  );
}

function Advanced({ s, set }: { s: WebSettings; set: <K extends keyof WebSettings>(k: K, v: WebSettings[K]) => void }) {
  const { t } = useTranslation();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: 60_000 });
  const d = cfg?.defaults;
  const order = s.source_order ?? d?.source_order ?? PROVIDERS;
  const move = (i: number, dir: -1 | 1) => {
    const next = [...order];
    const j = i + dir;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    set("source_order", next);
  };
  const toggle = (p: string) =>
    set("source_order", order.includes(p) ? order.filter((x) => x !== p) : [...order, p]);
  const off = PROVIDERS.filter((p) => !order.includes(p));
  return (
    <details className="group rounded-lg border" data-testid="advanced">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium select-none">
        <span className="mr-2 inline-block transition-transform group-open:rotate-90">›</span>{t("advanced.title")}
        <span className="ml-2 text-xs font-normal text-muted-foreground">{t("advanced.hint")}</span>
      </summary>
      <div className="divide-y border-t px-4">
        <Row label={t("advanced.evidence")} hint={t("advanced.evidenceHint")}>
          <div className="w-64"><Select ariaLabel={t("advanced.evidence")} value={s.evidence_strategy ?? "__default"}
            onValueChange={(v) => set("evidence_strategy", v === "__default" ? null : v)}
            options={[{ value: "__default", label: t("advanced.default", { value: d?.evidence_strategy ?? "auto" }) },
              ...["auto", "full", "passages"].map((v) => ({ value: v, label: t(`advanced.strategy.${v}`) }))]} /></div>
        </Row>
        <Row label={t("advanced.fullMax")} hint={t("advanced.fullMaxHint")}>
          <NumberField label={t("advanced.fullMax")} value={s.full_text_max_tokens} placeholder={d?.full_text_max_tokens ?? 60000} step={1000} min={2000} onChange={(v) => set("full_text_max_tokens", v)} />
        </Row>
        <Row label={t("advanced.passages")} hint={t("advanced.passagesHint")}>
          <NumberField label={t("advanced.passages")} value={s.passage_budget_tokens} placeholder={d?.passage_budget_tokens ?? 8000} step={500} min={500} onChange={(v) => set("passage_budget_tokens", v)} />
        </Row>
        <Row label={t("advanced.concurrency")} hint={t("advanced.concurrencyHint")}>
          <NumberField label={t("advanced.concurrency")} value={s.concurrency} placeholder={d?.concurrency ?? 4} min={1} max={16} onChange={(v) => set("concurrency", v)} />
        </Row>
        <Row label={t("advanced.sources")} hint={t("advanced.sourcesHint")}>
          <ol className="space-y-1" data-testid="source-order">
            {order.map((p, i) => (
              <li key={p} className="flex items-center gap-2 rounded-md border bg-card px-2 py-1 text-sm">
                <Checkbox checked onCheckedChange={() => toggle(p)} aria-label={`${t("advanced.disable")} ${p}`} />
                <span className="flex-1">{t(`sources.provider.${p}`, { defaultValue: p })}</span>
                <Button variant="ghost" size="icon-sm" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("advanced.up")}>↑</Button>
                <Button variant="ghost" size="icon-sm" disabled={i === order.length - 1} onClick={() => move(i, 1)} aria-label={t("advanced.down")}>↓</Button>
              </li>
            ))}
            {off.map((p) => (
              <li key={p} className="flex items-center gap-2 rounded-md border border-dashed px-2 py-1 text-sm text-muted-foreground">
                <Checkbox checked={false} onCheckedChange={() => toggle(p)} aria-label={`${t("advanced.enable")} ${p}`} />
                <span className="flex-1 line-through">{t(`sources.provider.${p}`, { defaultValue: p })}</span>
              </li>
            ))}
          </ol>
          {s.source_order && <Button variant="link" size="sm" className="px-0" onClick={() => set("source_order", null)}>{t("advanced.reset")}</Button>}
        </Row>
        <Row label={t("advanced.openalexBudget")} hint={t("advanced.openalexBudgetHint")}>
          <NumberField label={t("advanced.openalexBudget")} value={s.openalex_max_usd} placeholder={d?.openalex_max_usd ?? 0.5} step={0.1} onChange={(v) => set("openalex_max_usd", v)} />
        </Row>
        <Row label={t("advanced.arxivMax")} hint={t("advanced.arxivMaxHint")}>
          <NumberField label={t("advanced.arxivMax")} value={s.arxiv_max_downloads} placeholder={d?.arxiv_max_downloads ?? 30} onChange={(v) => set("arxiv_max_downloads", v)} />
        </Row>
        <Row label={t("advanced.pdfDirs")} hint={t("advanced.pdfDirsHint")}>
          <ListField label={t("advanced.pdfDirs")} value={s.pdf_dirs} placeholder={(d?.pdf_dirs ?? ["papers"]).join(", ")} onChange={(v) => set("pdf_dirs", v)} />
        </Row>
        <Row label={t("advanced.citeCommands")} hint={t("advanced.citeCommandsHint")}>
          <ListField label={t("advanced.citeCommands")} value={s.extra_cite_commands} placeholder="mycite, citeauthoryear" onChange={(v) => set("extra_cite_commands", v)} />
        </Row>
        <Row label={t("advanced.screening")} hint={t("advanced.screeningHint")}>
          <div className="w-64"><Select ariaLabel={t("advanced.screening")} value={s.screening ?? "__default"}
            onValueChange={(v) => set("screening", v === "__default" ? null : v)}
            options={[{ value: "__default", label: t("advanced.default", { value: d?.screening ?? "auto" }) },
              ...["auto", "llm", "heuristic", "none"].map((v) => ({ value: v, label: t(`advanced.screen.${v}`) }))]} /></div>
        </Row>
        <Row label={t("advanced.maxInternal")} hint={t("advanced.maxInternalHint")}>
          <NumberField label={t("advanced.maxInternal")} value={s.internal_max_claims} placeholder={d?.internal_max_claims ?? 150} onChange={(v) => set("internal_max_claims", v)} />
        </Row>
      </div>
    </details>
  );
}

export default function SettingsTab({ project }: { project: Project }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000 });
  const { data: outline } = useOutline(project.id);
  const [s, setS] = React.useState<WebSettings>(project.settings);
  const [custom, setCustom] = React.useState(false);
  const [saved, setSaved] = React.useState<WebSettings>(project.settings);
  const latest = React.useRef(s);
  latest.current = s;
  React.useEffect(() => { setS(project.settings); setSaved(project.settings); }, [project.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = JSON.stringify(s) !== JSON.stringify(saved);

  const save = useMutation({
    mutationFn: (value: WebSettings) => trackSave(api.saveSettings(project.id, value)),
    onSuccess: (value) => {
      setSaved(value);
      qc.setQueryData(["project", project.id], (p: Project | undefined) => (p ? { ...p, settings: value } : p));
      qc.invalidateQueries({ queryKey: ["outline", project.id] });
    },
    onError: (e: Error) => toast.error(friendlyError(e, t)),
  });

  // Auto-save shortly after each change; a run started meanwhile waits for it (flushSaves)
  React.useEffect(() => {
    if (!dirty) return;
    const id = setTimeout(() => save.mutate(latest.current), 500);
    return () => clearTimeout(id);
  }, [s]); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    registerFlusher(() =>
      JSON.stringify(latest.current) !== JSON.stringify(saved) ? save.mutateAsync(latest.current) : undefined,
    );
    return () => registerFlusher(null);
  }, [saved]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = <K extends keyof WebSettings>(k: K, v: WebSettings[K]) => setS((p) => ({ ...p, [k]: v }));

  const models = health?.suggested_models ?? ["demo"];
  const isCustom = custom || (!!s.model && !models.includes(s.model));
  const modelOptions = [
    { value: "__default", label: health?.default_model ? t("settings.modelDefault", { model: health.default_model }) : t("settings.modelNone") },
    ...models.map((m) => ({
      value: m,
      label: m,
      hint: m.startsWith("cli:")
        ? t("settings.cliHint", { agent: AGENT_NAMES[m.slice(4)] ?? m.slice(4) })
        : m === "demo" ? t("settings.demoHint") : undefined,
    })),
    { value: "__custom", label: t("settings.custom") },
  ];
  const sections = outline?.sections ?? [];
  const toggleSection = (title: string) =>
    set("internal_sections", s.internal_sections.includes(title) ? s.internal_sections.filter((x) => x !== title) : [...s.internal_sections, title]);

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_400px]">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>{t("settings.title")}</CardTitle>
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground" data-testid="save-settings" aria-live="polite">
            {save.isPending || dirty ? <><Loader2 className="size-4 animate-spin" />{t("settings.saving")}</> : <><Check className="size-4 text-supported" />{t("app.saved")}</>}
          </span>
        </CardHeader>
        <CardContent className="divide-y">
          <Row label={t("settings.model")} hint={t("settings.modelHint")} htmlFor="model">
            <div className="space-y-2">
              <Select id="model" ariaLabel={t("settings.model")} value={isCustom ? "__custom" : s.model ?? "__default"} options={modelOptions}
                onValueChange={(v) => { if (v === "__custom") { setCustom(true); } else { setCustom(false); set("model", v === "__default" ? null : v); } }} />
              {isCustom && <Input aria-label={t("settings.customModel")} placeholder="provider/model" className="font-mono" value={s.model ?? ""} onChange={(e) => set("model", e.target.value || null)} />}
            </div>
          </Row>
          <Row label={t("settings.claimScope")} hint={t("settings.claimScopeHint")}>
            <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t("settings.claimScope")}>
              {SCOPES.map((sc) => (
                <button key={sc} role="radio" aria-checked={s.claim_scope === sc} onClick={() => set("claim_scope", sc)} data-testid={`scope-${sc}`}
                  className={cn("rounded-lg border p-3 text-left transition-colors cursor-pointer", s.claim_scope === sc ? "border-primary bg-accent ring-1 ring-primary/40" : "hover:bg-muted/50")}>
                  <div className="text-sm font-medium">{t(`settings.scope.${sc}`)}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{t(`settings.scopeHint.${sc}`)}</div>
                </button>
              ))}
            </div>
          </Row>
          <Row label={t("settings.internal")} hint={t("settings.internalHint")}>
            <div className="space-y-3">
              <Switch checked={s.internal_enabled} onCheckedChange={(v) => set("internal_enabled", v)} aria-label={t("settings.internal")} data-testid="internal-switch" />
              {s.internal_enabled && (
                <div className="space-y-2 rounded-lg border p-3">
                  <p className="text-sm font-medium">{t("settings.sections")}</p>
                  <p className="text-xs text-muted-foreground">{t("settings.sectionsHint")}</p>
                  {outline ? (
                    <div className="grid gap-2 pt-1 sm:grid-cols-2">
                      {sections.map((sec) => (
                        <Label key={sec.title} className="font-normal">
                          <Checkbox checked={s.internal_sections.includes(sec.title)} onCheckedChange={() => toggleSection(sec.title)} />
                          <span className="truncate">{sec.title}</span>
                          <span className="text-xs text-muted-foreground tabular-nums" title={t("settings.sectionCount", { count: sec.internal })}>{t("settings.sectionCount", { count: sec.internal })}</span>
                        </Label>
                      ))}
                    </div>
                  ) : <Skeleton className="h-16" />}
                  <p className="pt-1 text-xs text-primary">{s.internal_sections.length ? s.internal_sections.join(", ") : t("settings.wholeDocument")}</p>
                </div>
              )}
            </div>
          </Row>
          <Row label={t("settings.reportLanguage")} htmlFor="lang">
            <Select id="lang" ariaLabel={t("settings.reportLanguage")} value={s.report_language} onValueChange={(v) => set("report_language", v as WebSettings["report_language"])}
              options={(["auto", "en", "es"] as const).map((l) => ({ value: l, label: t(`settings.lang.${l}`) }))} />
          </Row>
          <Row label={t("settings.budget")} htmlFor="budget">
            <Input id="budget" type="number" min={0} max={1000} step={0.5} className="w-40" value={s.max_usd} onChange={(e) => { if (e.target.value !== "") set("max_usd", Math.min(1000, Math.max(0, Number(e.target.value)))); }} />
            <p className="mt-1 text-xs text-muted-foreground">{t("settings.budgetHint")}</p>
          </Row>
          <Row label={t("settings.offline")}>
            <Switch checked={s.offline} onCheckedChange={(v) => set("offline", v)} aria-label={t("settings.offline")} />
          </Row>
          <div className="py-4"><Advanced s={s} set={set} /></div>
          {outline && (
            <Row label={t("settings.mainFile")} htmlFor="main">
              <Input id="main" className="font-mono" placeholder={`${t("settings.mainAuto")} (${outline.main})`} value={s.main ?? ""} onChange={(e) => set("main", e.target.value || null)} />
            </Row>
          )}
        </CardContent>
      </Card>
      <div className="space-y-6">
        <FilesCard project={project} />
        <Alert variant="info"><KeyRound /><div><p className="font-medium">{t("settings.keysTitle")}</p><p className="mt-1 text-xs">{t("settings.keysBody")}</p><Link to="/settings" className="mt-2 inline-block text-xs font-medium underline">{t("config.manage")}</Link></div></Alert>
      </div>
    </div>
  );
}
