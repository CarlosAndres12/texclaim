import * as React from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeft, BookMarked, FileSearch, FileText, LayoutDashboard, Loader2, Network, Pencil, Play, Settings2, Square, Zap,
} from "lucide-react";
import { api, ApiError, urls, type RunEvent } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { flushSaves } from "@/lib/pending";
import NotFound from "./NotFound";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ErrorState } from "@/components/common";
import OverviewTab from "./project/Overview";
import RunTab from "./project/Run";
import FindingsTab from "./project/Findings";
import DocumentTab from "./project/Document";
import SourcesTab from "./project/Sources";
import GraphTab from "./project/Graph";
import SettingsTab from "./project/Settings";

const TABS = ["overview", "run", "findings", "document", "sources", "graph", "settings"] as const;
export type TabName = (typeof TABS)[number];

export interface RunState {
  events: RunEvent[];
  running: boolean;
  start: (opts?: { force?: boolean; dry_run?: boolean }) => void;
  cancel: () => void;
  starting: boolean;
}

export const RunContext = React.createContext<RunState | null>(null);
export const useRun = () => React.useContext(RunContext)!;

function useRunEvents(pid: string): RunState {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const [events, setEvents] = React.useState<RunEvent[]>([]);
  const [running, setRunning] = React.useState(false);
  const esRef = React.useRef<EventSource | null>(null);

  const follow = React.useCallback(() => {
    esRef.current?.close();
    const es = new EventSource(urls.events(pid));
    esRef.current = es;
    setEvents([]);
    setRunning(true);
    es.onmessage = (m) => {
      const e = JSON.parse(m.data) as RunEvent;
      setEvents((prev) => (prev.some((x) => x.seq === e.seq) ? prev : [...prev, e]));
      if (e.type === "done" || e.type === "error") {
        qc.invalidateQueries({ queryKey: ["project", pid] });
        qc.invalidateQueries({ queryKey: ["report", pid] });
        qc.invalidateQueries({ queryKey: ["sources", pid] });
        qc.invalidateQueries({ queryKey: ["graph", pid] });
        qc.invalidateQueries({ queryKey: ["projects"] });
      }
      if (e.type === "done") toast.success(t("run.done"));
      if (e.type === "error") toast.error(friendlyError(e.message ?? t("run.failed"), t));
    };
    const end = () => { setRunning(false); es.close(); };
    es.addEventListener("end", end);
    es.addEventListener("idle", end);
    es.onerror = () => { if (es.readyState === EventSource.CLOSED) setRunning(false); };
  }, [pid, qc, t]);

  // Pick up a run that is already in progress (page reload) or replay the last one's log
  React.useEffect(() => {
    let alive = true;
    api.currentRun(pid).then((r) => {
      if (!alive) return;
      if (r.state === "running") follow();
      else if (r.log) setEvents(r.log);
    }).catch(() => undefined);
    return () => { alive = false; esRef.current?.close(); };
  }, [pid, follow]);

  const startM = useMutation({
    mutationFn: async (opts: { force?: boolean; dry_run?: boolean }) => {
      await flushSaves(); // unsaved settings are saved before the run starts
      return api.startRun(pid, opts);
    },
    onSuccess: () => follow(),
    onError: (e: Error) => toast.error(friendlyError(e, t)),
  });
  const cancelM = useMutation({ mutationFn: () => api.cancelRun(pid) });
  return {
    events, running,
    start: (opts = {}) => startM.mutate(opts),
    cancel: () => cancelM.mutate(),
    starting: startM.isPending,
  };
}

function Title({ pid, name }: { pid: string; name: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [edit, setEdit] = React.useState(false);
  const [value, setValue] = React.useState(name);
  React.useEffect(() => setValue(name), [name]);
  const save = useMutation({
    mutationFn: () => api.rename(pid, value),
    onSuccess: () => { setEdit(false); qc.invalidateQueries({ queryKey: ["project", pid] }); },
  });
  if (edit)
    return (
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="flex items-center gap-2">
        <Input autoFocus value={value} onChange={(e) => setValue(e.target.value)} className="h-9 w-72 text-lg font-semibold" aria-label={t("project.rename")} onBlur={() => save.mutate()} />
      </form>
    );
  return (
    <button className="group flex min-w-0 items-center gap-2 text-left cursor-pointer" onClick={() => setEdit(true)} title={t("project.rename")}>
      <h1 className="truncate text-2xl font-semibold tracking-tight">{name}</h1>
      <Pencil className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
    </button>
  );
}

export default function ProjectPage() {
  const { id = "", tab = "overview" } = useParams();
  const { t } = useTranslation();
  const nav = useNavigate();
  const run = useRunEvents(id);
  const { data: project, isLoading, error, refetch } = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.project(id),
    refetchInterval: run.running ? 3000 : false,
  });
  const active: TabName = (TABS as readonly string[]).includes(tab) ? (tab as TabName) : "overview";

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-80" /><Skeleton className="h-10 w-full" /><Skeleton className="h-96" /></div>;
  if (error instanceof ApiError && (error.status === 404 || error.status === 400)) return <NotFound />;
  if (error || !project) return <ErrorState error={error ?? "not found"} onRetry={() => refetch()} />;
  if (tab !== "overview" && !(TABS as readonly string[]).includes(tab)) return <Navigate to={`/projects/${id}`} replace />;

  const icons: Record<TabName, React.ReactNode> = {
    overview: <LayoutDashboard />, run: <Zap />, findings: <FileSearch />, document: <FileText />,
    sources: <BookMarked />, graph: <Network />, settings: <Settings2 />,
  };
  return (
    <RunContext.Provider value={run}>
      <div className="space-y-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-center gap-2">
            <Button variant="ghost" size="icon" asChild><Link to="/" aria-label={t("app.back")}><ArrowLeft /></Link></Button>
            <Title pid={id} name={project.name} />
            {project.external && <span className="hidden truncate rounded-md bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground md:inline" title={project.folder}>{project.folder.split("/").slice(-2).join("/")}</span>}
          </div>
          <div className="flex items-center gap-2">
            {run.running ? (
              <Button variant="outline" onClick={run.cancel} data-testid="stop-run"><Square />{t("run.cancel")}</Button>
            ) : (
              <Button onClick={() => { run.start(); nav(`/projects/${id}/run`); }} disabled={run.starting} data-testid="start-run">
                {run.starting ? <Loader2 className="animate-spin" /> : <Play />}{t("project.checkNow")}
              </Button>
            )}
          </div>
        </div>
        <Tabs value={active} onValueChange={(v) => nav(`/projects/${id}/${v === "overview" ? "" : v}`)}>
          <div className="-mx-1 overflow-x-auto px-1 pb-1 scrollbar-thin">
            <TabsList>
              {TABS.map((k) => (
                <TabsTrigger key={k} value={k} data-testid={`tab-${k}`}>
                  {icons[k]}
                  {t(`project.${k}`)}
                  {k === "run" && run.running && <Loader2 className="animate-spin text-primary" />}
                  {k === "findings" && project.summary?.findings ? (
                    <span className="ml-0.5 rounded-full bg-contradicted/15 px-1.5 text-[10px] font-semibold text-contradicted tabular-nums">{project.summary.findings}</span>
                  ) : null}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
        </Tabs>
        <div>
          {active === "overview" && <OverviewTab project={project} />}
          {active === "run" && <RunTab project={project} />}
          {active === "findings" && <FindingsTab project={project} />}
          {active === "document" && <DocumentTab project={project} />}
          {active === "sources" && <SourcesTab project={project} />}
          {active === "graph" && <GraphTab project={project} />}
          {active === "settings" && <SettingsTab project={project} />}
        </div>
      </div>
    </RunContext.Provider>
  );
}
