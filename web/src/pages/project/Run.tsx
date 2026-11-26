import * as React from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, CheckCircle2, Circle, Loader2, Play, RefreshCw, Square, Calculator } from "lucide-react";
import { api, type Project, type RunEvent, type Verdict } from "@/lib/api";
import { cleanClaim, cn, displayKey, formatCost } from "@/lib/utils";
import { friendlyError, translateNotice } from "@/lib/errors";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, Progress } from "@/components/ui/misc";
import { useElapsed, VerdictBadge } from "@/components/common";
import { useRun } from "../Project";

const STAGES = ["parse", "resolve, download and extract", "verify", "report", "graph"];

export default function RunTab({ project }: { project: Project }) {
  const { t } = useTranslation();
  const run = useRun();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000 });
  const ev = run.events;
  const startEv = ev.find((e) => e.type === "start");
  const plan = [...ev].reverse().find((e) => e.type === "plan");
  const units = ev.filter((e) => e.type === "unit");
  const done = ev.find((e) => e.type === "done");
  const err = ev.find((e) => e.type === "error");
  const stages = ev.filter((e) => e.type === "stage").map((e) => String(e.name));
  const current = stages[stages.length - 1];
  const total = Number(plan?.queued ?? 0);
  const pct = total ? (units.length / total) * 100 : done ? 100 : 0;
  const lastCost = Number(units[units.length - 1]?.cost ?? done?.cost ?? 0);
  const endEv = ev.find((e) => e.type === "done" || e.type === "error");
  const elapsed = useElapsed(startEv?.t ?? null, run.running, endEv?.t ?? ev[ev.length - 1]?.t);
  const noModel = !project.settings.model && !health?.default_model;
  const logRef = React.useRef<HTMLOListElement>(null);
  React.useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" }); }, [units.length]);

  const state = run.running ? "running" : err ? "failed" : done ? (done.status === "interrupted" ? "cancelled" : "done") : "idle";
  const isDry = Boolean(startEv?.dry_run);
  const title = { idle: t("run.idle"), running: t("run.running"), done: isDry ? t("run.estimateDone") : t("run.done"), failed: t("run.failed"), cancelled: t("run.cancelled") }[state];

  return (
    <div className="grid gap-6 lg:grid-cols-[400px_minmax(0,1fr)]">
      <div className="min-w-0 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2" data-testid="run-state" data-state={state}>
              {state === "running" ? <Loader2 className="size-5 animate-spin text-primary" /> : state === "done" ? <CheckCircle2 className="size-5 text-supported" /> : state === "failed" ? <AlertCircle className="size-5 text-destructive" /> : <Circle className="size-5 text-muted-foreground" />}
              {title}
            </CardTitle>
            <CardDescription>{state === "idle" ? t("run.idleBody") : startEv?.model ? `${t("overview.model")}: ${startEv.model}` : null}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {noModel && state === "idle" && <Alert variant="warning"><AlertCircle /><p>{t("run.noModel")} <Link className="underline" to={`/projects/${project.id}/settings`}>{t("project.settings")}</Link></p></Alert>}
            {(state !== "idle") && (
              <div className="space-y-2">
                <Progress value={pct} indicatorClassName={state === "failed" ? "bg-destructive" : undefined} />
                <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
                  <span>{total ? t("run.progress", { done: units.length, total }) : current ? t(`run.stage.${current}`, { defaultValue: current }) : ""}</span>
                  <span>{t("run.elapsed", { time: elapsed })}</span>
                </div>
                {plan && <p className="text-xs text-muted-foreground">{t("run.queued", { queued: plan.queued, reused: plan.reused })}</p>}
                <p className="text-xs text-muted-foreground">{t("run.cost", { cost: formatCost(lastCost) })}</p>
              </div>
            )}
            {done && !isDry && Number(done.units) === 0 && <Alert variant="warning"><AlertCircle /><p>{t("run.noClaims")}</p></Alert>}
            {err && <Alert variant="destructive"><AlertCircle /><p className="break-words">{friendlyError(err.message, t)}</p></Alert>}
            {done && (
              <p className="rounded-lg bg-muted p-3 text-sm">
                {isDry ? t("run.estimateSummary", { queued: done.queued, reused: done.reused })
                  : t("run.summary", { verified: done.verified, reused: done.reused, errors: done.errors, cost: formatCost(Number(done.cost)) })}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {run.running ? (
                <Button variant="outline" onClick={run.cancel}><Square />{t("run.cancel")}</Button>
              ) : (
                <>
                  <Button onClick={() => run.start()} disabled={run.starting || noModel} data-testid="run-start"><Play />{t("run.start")}</Button>
                  <Button variant="outline" onClick={() => run.start({ force: true })} disabled={run.starting || noModel}><RefreshCw />{t("project.recheckAll")}</Button>
                  <Button variant="ghost" onClick={() => run.start({ dry_run: true })} disabled={run.starting}><Calculator />{t("project.estimate")}</Button>
                </>
              )}
              {done && !done.dry_run && <Button variant="secondary" asChild><Link to={`/projects/${project.id}/findings`} data-testid="view-results">{t("run.viewResults")}<ArrowRight /></Link></Button>}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <ol className="space-y-3">
              {STAGES.filter((s) => !isDry || s === "parse" || s === "resolve, download and extract").map((s) => {
                const idx = stages.lastIndexOf(s);
                const reached = idx >= 0;
                const isCurrent = run.running && current === s;
                const finished = reached && (!isCurrent || !run.running);
                return (
                  <li key={s} className="flex items-center gap-3 text-sm">
                    {isCurrent ? <Loader2 className="size-4 animate-spin text-primary" /> : finished ? <CheckCircle2 className="size-4 text-supported" /> : <Circle className="size-4 text-muted-foreground/50" />}
                    <span className={cn(!reached && "text-muted-foreground")}>{t(`run.stage.${s}`)}</span>
                  </li>
                );
              })}
            </ol>
          </CardContent>
        </Card>
      </div>
      <Card className="flex min-h-[420px] min-w-0 flex-col">
        <CardHeader><CardTitle>{t("run.log")}</CardTitle></CardHeader>
        <CardContent className="min-h-0 flex-1">
          <ol ref={logRef} className="max-h-[560px] space-y-1 overflow-auto pr-1 scrollbar-thin" aria-live="polite" data-testid="run-log">
            {ev.map((e: RunEvent) => (
              <li key={e.seq} className="flex min-w-0 items-start gap-3 rounded-md px-2 py-1.5 text-sm odd:bg-muted/40">
                <span className="w-12 shrink-0 pt-0.5 text-[11px] text-muted-foreground tabular-nums">{startEv ? `+${Math.max(0, Math.round(e.t - startEv.t))}s` : ""}</span>
                {e.type === "unit" ? (
                  <div className="flex min-w-0 flex-1 items-start gap-2">
                    <VerdictBadge verdict={e.verdict as Verdict} />
                    <span className="min-w-0 flex-1 truncate">{cleanClaim(String(e.text))}</span>
                    <span className="hidden max-w-40 shrink-0 truncate font-mono text-[11px] text-muted-foreground sm:inline">{displayKey(String(e.bib_key), t("findings.selfSource"))}</span>
                  </div>
                ) : e.type === "stage" ? (
                  <span className="font-medium">{t(`run.stage.${e.name}`, { defaultValue: String(e.name) })}</span>
                ) : e.type === "notice" ? (
                  <span className="text-muted-foreground">{translateNotice(String(e.message), t)}</span>
                ) : e.type === "plan" ? (
                  <span className="text-muted-foreground">{t("run.queued", { queued: e.queued, reused: e.reused })}</span>
                ) : e.type === "error" ? (
                  <span className="text-destructive">{friendlyError(e.message, t)}</span>
                ) : e.type === "done" ? (
                  <span className="font-medium text-supported">{isDry ? t("run.estimateDone") : t("run.done")}</span>
                ) : e.type === "start" ? (
                  <span className="text-muted-foreground">{e.dry_run ? t("run.startedDry") : t("run.started", { model: String(e.model ?? "—") })}</span>
                ) : null}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}
