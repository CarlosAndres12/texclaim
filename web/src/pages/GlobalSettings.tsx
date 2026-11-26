import * as React from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  BookOpen, Bot, CheckCircle2, CircleSlash, FlaskConical, KeyRound, Loader2, Lock, Save, Server, SlidersHorizontal, Trash2, XCircle,
} from "lucide-react";
import { api, type GlobalConfig, type TestResult } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { Alert, Skeleton } from "@/components/ui/misc";
import { ErrorState, PageHeader } from "@/components/common";

const AGENT_NAMES: Record<string, string> = { claude: "Claude Code", pi: "pi", agy: "Antigravity" };
const PROVIDER_FOR_KEY: Record<string, string> = {
  ANTHROPIC_API_KEY: "anthropic/claude-haiku-5-5",
  OPENAI_API_KEY: "openai/gpt-5-mini",
  GEMINI_API_KEY: "gemini/gemini-2.5-flash",
  MISTRAL_API_KEY: "mistral/mistral-small-latest",
  DEEPSEEK_API_KEY: "deepseek/deepseek-chat",
  GROQ_API_KEY: "groq/llama-3.3-70b-versatile",
  OPENROUTER_API_KEY: "openrouter/anthropic/claude-haiku-5-5",
};

function TestBadge({ r }: { r?: TestResult | null }) {
  const { t } = useTranslation();
  if (!r) return null;
  return (
    <p className={cn("flex items-start gap-1.5 text-xs", r.ok ? "text-supported" : "text-destructive")} role="status" data-testid="test-result">
      {r.ok ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" /> : <XCircle className="mt-0.5 size-3.5 shrink-0" />}
      <span className="break-words">{r.ok ? t("config.testOk", { s: r.seconds, reply: r.reply }) : friendlyError(r.error, t)}</span>
    </p>
  );
}

function useSave() {
  const qc = useQueryClient();
  const { t } = useTranslation();
  return useMutation({
    mutationFn: (values: Record<string, string | null>) => api.saveConfig(values),
    onSuccess: (cfg) => {
      qc.setQueryData(["config"], cfg);
      qc.invalidateQueries({ queryKey: ["health"] });
      toast.success(t("config.saved"));
    },
    onError: (e: Error) => toast.error(friendlyError(e, t)),
  });
}

function SecretRow({ name, info, testTarget, testModel }: {
  name: string; info: GlobalConfig["secrets"][string]; testTarget?: "model" | "openalex" | "asta"; testModel?: string;
}) {
  const { t } = useTranslation();
  const save = useSave();
  const [value, setValue] = React.useState("");
  const [result, setResult] = React.useState<TestResult | null>(null);
  const test = useMutation({
    mutationFn: () => api.testConfig({ target: testTarget ?? "model", model: testModel }),
    onSuccess: setResult,
  });
  return (
    <div className="grid gap-2 border-b py-3 last:border-0 md:grid-cols-[220px_1fr] md:items-start" data-testid={`secret-${name}`}>
      <div>
        <p className="text-sm font-medium">{info.label}</p>
        <p className="font-mono text-[11px] text-muted-foreground">{name}</p>
      </div>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          {info.set ? (
            <Badge variant="outline" className="border-supported/40 text-supported"><Lock />{info.from_environment ? t("config.setInEnv") : t("config.set")}</Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground"><CircleSlash />{t("config.notSet")}</Badge>
          )}
          <form className="flex min-w-0 flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); if (value.trim()) save.mutate({ [name]: value.trim() }, { onSuccess: () => setValue("") }); }}>
            <Input type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)}
              placeholder={info.set ? t("config.replacePlaceholder") : t("config.pastePlaceholder")} aria-label={`${info.label} ${name}`} className="min-w-0 font-mono" />
            <Button type="submit" size="sm" disabled={!value.trim() || save.isPending}><Save />{t("app.save")}</Button>
          </form>
          {info.set && !info.from_environment && (
            <Button variant="ghost" size="sm" onClick={() => save.mutate({ [name]: null })} aria-label={`${t("config.remove")} ${name}`}><Trash2 />{t("config.remove")}</Button>
          )}
          {info.set && (testTarget || testModel) && (
            <Button variant="outline" size="sm" onClick={() => test.mutate()} disabled={test.isPending}>
              {test.isPending ? <Loader2 className="animate-spin" /> : <FlaskConical />}{t("config.test")}
            </Button>
          )}
        </div>
        <TestBadge r={result} />
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 border-b py-3 last:border-0 md:grid-cols-[220px_1fr] md:items-center">
      <div><Label>{label}</Label>{hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export default function GlobalSettingsPage() {
  const { t } = useTranslation();
  const { data: cfg, isLoading, error, refetch } = useQuery({ queryKey: ["config"], queryFn: api.config });
  const save = useSave();
  const [model, setModel] = React.useState<string>("");
  const [custom, setCustom] = React.useState(false);
  const [email, setEmail] = React.useState("");
  const [result, setResult] = React.useState<TestResult | null>(null);
  const [agentResults, setAgentResults] = React.useState<Record<string, TestResult>>({});
  React.useEffect(() => {
    if (!cfg) return;
    setModel(cfg.settings.TEXCLAIM_MODEL?.value ?? "");
    setEmail(cfg.settings.TEXCLAIM_CONTACT_EMAIL?.value ?? "");
  }, [cfg]);
  const test = useMutation({ mutationFn: (m: string) => api.testConfig({ target: "model", model: m }), onSuccess: setResult });
  const testAgent = useMutation({
    mutationFn: (a: string) => api.testConfig({ target: "model", model: `cli:${a}` }),
    onSuccess: (r, a) => setAgentResults((p) => ({ ...p, [a]: r })),
  });

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-64" /><Skeleton className="h-96" /></div>;
  if (error || !cfg) return <ErrorState error={error} onRetry={() => refetch()} />;

  const saved = cfg.settings.TEXCLAIM_MODEL?.value ?? "";
  const isCustom = custom || (!!model && !cfg.suggested_models.includes(model));
  const providers = Object.entries(cfg.secrets).filter(([k]) => !["OPENALEX_API_KEY", "ASTA_API_KEY"].includes(k));
  const plain = (k: string) => cfg.settings[k]?.value ?? "";

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title={t("config.title")} description={t("config.subtitle")}
        actions={<Button variant="outline" asChild><Link to="/help#setup"><BookOpen />{t("config.guide")}</Link></Button>} />
      <Alert variant="info"><Lock /><p>{t("config.secrecy", { file: cfg.file })}</p></Alert>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Server className="size-4" />{t("config.modelTitle")}</CardTitle>
          <CardDescription>{t("config.modelBody")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <div className="md:w-96">
              <Select ariaLabel={t("config.defaultModel")} value={isCustom ? "__custom" : model || "__none"}
                onValueChange={(v) => { if (v === "__custom") setCustom(true); else { setCustom(false); setModel(v === "__none" ? "" : v); } }}
                options={[
                  { value: "__none", label: t("config.noDefault") },
                  ...cfg.suggested_models.map((m) => ({
                    value: m, label: m,
                    hint: m.startsWith("cli:") ? t("settings.cliHint", { agent: AGENT_NAMES[m.slice(4)] ?? m }) : m === "demo" ? t("settings.demoHint") : undefined,
                  })),
                  { value: "__custom", label: t("settings.custom") },
                ]} />
            </div>
            {isCustom && <Input className="font-mono md:w-80" placeholder="provider/model or cli:claude/haiku" value={model} onChange={(e) => setModel(e.target.value)} aria-label={t("settings.customModel")} />}
            <div className="flex gap-2">
              <Button onClick={() => save.mutate({ TEXCLAIM_MODEL: model || null })} disabled={model === saved || save.isPending} data-testid="save-default-model"><Save />{t("app.save")}</Button>
              <Button variant="outline" onClick={() => model && test.mutate(model)} disabled={!model || test.isPending} data-testid="test-default-model">
                {test.isPending ? <Loader2 className="animate-spin" /> : <FlaskConical />}{t("config.test")}
              </Button>
            </div>
          </div>
          <TestBadge r={result} />
          <p className="text-xs text-muted-foreground">{t("config.modelFormats")}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Bot className="size-4" />{t("config.agentsTitle")}</CardTitle>
          <CardDescription>{t("config.agentsBody")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          {cfg.cli_agents.map((a) => (
            <div key={a.name} className="space-y-2 rounded-lg border p-3" data-testid={`agent-${a.name}`}>
              <div className="flex items-center justify-between">
                <p className="font-medium">{AGENT_NAMES[a.name]}</p>
                <Badge variant="outline" className={a.installed ? "border-supported/40 text-supported" : "text-muted-foreground"}>
                  {a.installed ? t("config.installed") : t("config.notInstalled")}
                </Badge>
              </div>
              <p className="font-mono text-xs text-muted-foreground">cli:{a.name}</p>
              {a.installed && (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => testAgent.mutate(a.name)} disabled={testAgent.isPending && testAgent.variables === a.name}>
                    {testAgent.isPending && testAgent.variables === a.name ? <Loader2 className="animate-spin" /> : <FlaskConical />}{t("config.test")}
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => { setModel(`cli:${a.name}`); save.mutate({ TEXCLAIM_MODEL: `cli:${a.name}` }); }} disabled={saved === `cli:${a.name}`}>
                    {saved === `cli:${a.name}` ? t("config.isDefault") : t("config.useDefault")}
                  </Button>
                </div>
              )}
              <TestBadge r={agentResults[a.name]} />
            </div>
          ))}
          <p className="text-xs text-muted-foreground md:col-span-3">{t("config.agentsSafety")}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><KeyRound className="size-4" />{t("config.keysTitle")}</CardTitle>
          <CardDescription>{t("config.keysBody")}</CardDescription>
        </CardHeader>
        <CardContent>
          {providers.map(([k, info]) => <SecretRow key={k} name={k} info={info} testModel={PROVIDER_FOR_KEY[k]} />)}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><BookOpen className="size-4" />{t("config.sourcesTitle")}</CardTitle>
          <CardDescription>{t("config.sourcesBody")}</CardDescription>
        </CardHeader>
        <CardContent>
          <SecretRow name="OPENALEX_API_KEY" info={cfg.secrets.OPENALEX_API_KEY} testTarget="openalex" />
          <SecretRow name="ASTA_API_KEY" info={cfg.secrets.ASTA_API_KEY} testTarget="asta" />
          <Field label={t("config.email")} hint={t("config.emailHint")}>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate({ TEXCLAIM_CONTACT_EMAIL: email || null }); }}>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@university.edu" aria-label={t("config.email")} />
              <Button type="submit" size="sm" disabled={email === plain("TEXCLAIM_CONTACT_EMAIL") || save.isPending}><Save />{t("app.save")}</Button>
            </form>
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><SlidersHorizontal className="size-4" />{t("config.defaultsTitle")}</CardTitle>
          <CardDescription>{t("config.defaultsBody")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Field label={t("settings.reportLanguage")}>
            <div className="md:w-72"><Select ariaLabel={t("settings.reportLanguage")} value={plain("TEXCLAIM_REPORT_LANGUAGE") || "auto"}
              onValueChange={(v) => save.mutate({ TEXCLAIM_REPORT_LANGUAGE: v === "auto" ? null : v })}
              options={(["auto", "en", "es"] as const).map((l) => ({ value: l, label: t(`settings.lang.${l}`) }))} /></div>
          </Field>
          <Field label={t("settings.claimScope")} hint={t("settings.claimScopeHint")}>
            <div className="md:w-72"><Select ariaLabel={t("settings.claimScope")} value={plain("TEXCLAIM_CLAIM_SCOPE") || "auto"}
              onValueChange={(v) => save.mutate({ TEXCLAIM_CLAIM_SCOPE: v === "auto" ? null : v })}
              options={(["auto", "sentence", "two", "paragraph"] as const).map((sc) => ({ value: sc, label: t(`settings.scope.${sc}`) }))} /></div>
          </Field>
          <Field label={t("settings.budget")} hint={t("config.budgetDefaultHint")}>
            <BudgetInput value={plain("TEXCLAIM_MAX_USD")} onSave={(v) => save.mutate({ TEXCLAIM_MAX_USD: v || null })} />
          </Field>
          <p className="pt-3 text-xs text-muted-foreground">{t("config.projectOverride")}</p>
        </CardContent>
      </Card>
    </div>
  );
}

function BudgetInput({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const { t } = useTranslation();
  const [v, setV] = React.useState(value);
  React.useEffect(() => setV(value), [value]);
  return (
    <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); onSave(v); }}>
      <Input type="number" min={0} max={1000} step={0.5} className="w-40" value={v} placeholder="5" onChange={(e) => setV(e.target.value)} aria-label={t("settings.budget")} />
      <Button type="submit" size="sm" disabled={v === value}><Save />{t("app.save")}</Button>
    </form>
  );
}
