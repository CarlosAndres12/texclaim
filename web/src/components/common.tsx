import * as React from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, FolderUp, Upload, X } from "lucide-react";
import type { Verdict } from "@/lib/api";
import { cn, VERDICT_COLOR, VERDICTS } from "@/lib/utils";
import { friendlyError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/misc";

export function VerdictDot({ verdict, className }: { verdict: Verdict | "PENDING"; className?: string }) {
  const color = verdict === "PENDING" ? "var(--muted-foreground)" : VERDICT_COLOR[verdict];
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full", className)} style={{ background: color }} />;
}

export function VerdictBadge({ verdict, className, withHelp = false }: { verdict: Verdict; className?: string; withHelp?: boolean }) {
  const { t } = useTranslation();
  const color = VERDICT_COLOR[verdict];
  const badge = (
    <span
      className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap", className)}
      style={{ color, borderColor: `color-mix(in oklch, ${color} 35%, transparent)`, background: `color-mix(in oklch, ${color} 10%, transparent)` }}
      data-verdict={verdict}
    >
      <VerdictDot verdict={verdict} />
      {t(`verdict.${verdict}`)}
    </span>
  );
  return withHelp ? <Tooltip content={t(`verdict.help.${verdict}`)}>{badge}</Tooltip> : badge;
}

export function VerdictBar({ counts, className }: { counts: Partial<Record<Verdict, number>>; className?: string }) {
  const { t } = useTranslation();
  const total = VERDICTS.reduce((s, v) => s + (counts[v] ?? 0), 0);
  if (!total) return <div className={cn("h-2.5 rounded-full bg-muted", className)} />;
  return (
    <div className={cn("flex h-2.5 w-full overflow-hidden rounded-full bg-muted", className)} role="img"
      aria-label={VERDICTS.filter((v) => counts[v]).map((v) => `${t(`verdict.${v}`)}: ${counts[v]}`).join(", ")}>
      {[...VERDICTS].reverse().map((v) =>
        counts[v] ? (
          <Tooltip key={v} content={`${t(`verdict.${v}`)}: ${counts[v]}`}>
            <div style={{ width: `${((counts[v] ?? 0) / total) * 100}%`, background: VERDICT_COLOR[v] }} className="h-full transition-all first:rounded-l-full last:rounded-r-full" />
          </Tooltip>
        ) : null,
      )}
    </div>
  );
}

export function VerdictLegend({ counts }: { counts?: Partial<Record<Verdict, number>> }) {
  const { t } = useTranslation();
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
      {VERDICTS.map((v) => (
        <li key={v} className="flex items-center gap-1.5">
          <VerdictDot verdict={v} />
          {t(`verdict.${v}`)}
          {counts && <span className="font-medium text-foreground tabular-nums">{counts[v] ?? 0}</span>}
        </li>
      ))}
    </ul>
  );
}

export function EmptyState({ icon, title, body, action, className }: { icon?: React.ReactNode; title: string; body?: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-card/50 px-6 py-14 text-center", className)}>
      {icon && <div className="flex size-12 items-center justify-center rounded-full bg-accent text-accent-foreground [&_svg]:size-6">{icon}</div>}
      <h3 className="text-base font-semibold">{title}</h3>
      {body && <p className="max-w-md text-sm text-muted-foreground">{body}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <EmptyState
      icon={<AlertTriangle />}
      title={t("app.error")}
      body={friendlyError(error, t)}
      action={onRetry && <Button variant="outline" onClick={onRetry}>{t("app.retry")}</Button>}
    />
  );
}

export function StatCard({ label, value, hint, icon, accent }: { label: string; value: React.ReactNode; hint?: React.ReactNode; icon?: React.ReactNode; accent?: string }) {
  return (
    <div className="relative overflow-hidden rounded-xl border bg-card p-4 shadow-xs">
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>{label}</span>
        {icon && <span className="[&_svg]:size-4" style={accent ? { color: accent } : undefined}>{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="truncate text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

type FileWithPath = File & { relPath?: string };

async function readEntry(entry: FileSystemEntry, prefix = ""): Promise<FileWithPath[]> {
  if (entry.isFile) {
    const f = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
    const out = f as FileWithPath;
    out.relPath = prefix + f.name;
    return [out];
  }
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const all: FileSystemEntry[] = [];
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
    if (!batch.length) break;
    all.push(...batch);
  }
  const nested = await Promise.all(all.map((e) => readEntry(e, `${prefix}${entry.name}/`)));
  return nested.flat();
}

export function Dropzone({ files, onFiles, compact = false }: { files: File[]; onFiles: (f: File[]) => void; compact?: boolean }) {
  const { t } = useTranslation();
  const [active, setActive] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const dirRef = React.useRef<HTMLInputElement>(null);

  const add = (more: FileWithPath[]) => {
    const visible = more.filter((f) => !(f.relPath || f.name).split("/").some((p) => p.startsWith(".")));
    onFiles([...files, ...visible]);
  };

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setActive(false);
    const items = Array.from(e.dataTransfer.items || []);
    const entries = items.map((i) => i.webkitGetAsEntry?.()).filter(Boolean) as FileSystemEntry[];
    if (entries.length) {
      const nested = await Promise.all(entries.map((en) => readEntry(en)));
      // A single dropped folder: strip its name so main.tex lands at the root
      let flat = nested.flat();
      if (entries.length === 1 && entries[0].isDirectory) {
        const root = entries[0].name + "/";
        flat = flat.map((f) => { f.relPath = f.relPath?.startsWith(root) ? f.relPath.slice(root.length) : f.relPath; return f; });
      }
      add(flat);
    } else {
      add(Array.from(e.dataTransfer.files));
    }
  };

  const onDir = (list: FileList | null) => {
    if (!list) return;
    const arr = Array.from(list) as FileWithPath[];
    for (const f of arr) {
      const rp = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      f.relPath = rp.includes("/") ? rp.split("/").slice(1).join("/") : rp;
    }
    add(arr);
  };

  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => { e.preventDefault(); setActive(true); }}
        onDragLeave={() => setActive(false)}
        onDrop={onDrop}
        data-testid="dropzone"
        className={cn(
          "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-4 text-center transition-colors",
          compact ? "py-5" : "py-9",
          active ? "border-primary bg-accent/60" : "border-border bg-muted/30",
        )}
      >
        <div className="flex size-10 items-center justify-center rounded-full bg-accent text-accent-foreground"><Upload className="size-5" /></div>
        <p className="text-sm font-medium">{active ? t("newProject.dropActive") : t("newProject.drop")}</p>
        <div className="flex flex-wrap justify-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}><Upload />{t("newProject.browseFiles")}</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => dirRef.current?.click()}><FolderUp />{t("newProject.browseFolder")}</Button>
        </div>
        <input ref={fileRef} type="file" multiple hidden data-testid="file-input"
          accept=".tex,.bib,.md,.markdown,.docx,.pdf,.zip,.sty,.cls,.bst,.png,.jpg,.jpeg,.svg,.eps"
          onChange={(e) => { add(Array.from(e.target.files || [])); e.target.value = ""; }} />
        <input ref={dirRef} type="file" multiple hidden
          {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          onChange={(e) => { onDir(e.target.files); e.target.value = ""; }} />
      </div>
      {files.length > 0 && (
        <div className="rounded-lg border bg-card">
          <div className="flex items-center justify-between border-b px-3 py-2 text-xs text-muted-foreground">
            <span>{t("newProject.selected", { count: files.length })}</span>
            <Button variant="ghost" size="sm" onClick={() => onFiles([])}>{t("newProject.clear")}</Button>
          </div>
          <ul className="max-h-36 overflow-auto px-3 py-2 text-xs scrollbar-thin">
            {files.map((f, i) => (
              <li key={i} className="flex items-center justify-between gap-2 py-0.5">
                <span className="truncate font-mono">{(f as FileWithPath).relPath || f.name}</span>
                <button aria-label={t("app.delete")} className="text-muted-foreground hover:text-foreground cursor-pointer" onClick={() => onFiles(files.filter((_, j) => j !== i))}><X className="size-3.5" /></button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function useElapsed(start: number | null | undefined, running: boolean, end?: number | null) {
  const [now, setNow] = React.useState(Date.now());
  React.useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);
  if (!start) return "0:00";
  const stop = running ? now / 1000 : end ?? start;
  const s = Math.max(0, Math.floor(stop - start));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
