import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bot, Settings, ShieldAlert, Terminal, Wrench } from "lucide-react";
import type { Verdict } from "@/lib/api";
import { VERDICTS } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { PageHeader, VerdictBadge } from "@/components/common";

export default function HelpPage() {
  const { t } = useTranslation();
  const steps = t("help.steps", { returnObjects: true }) as string[];
  const c = t("help.cliComments", { returnObjects: true }) as string[];
  const cli: [string, string][] = [
    ["texclaim check path/to/paper", c[0]],
    ["texclaim check --claim-scope two", c[1]],
    ["texclaim check --internal-section Results", c[2]],
    ["texclaim export --format docx", c[3]],
    ["texclaim sources export", c[4]],
    ["texclaim graph && texclaim mcp .", c[5]],
    ["texclaim serve", c[6]],
  ];
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title={t("help.title")} description={t("app.tagline")} />
      <Card>
        <CardContent className="pt-5">
          <ol className="space-y-4">
            {steps.map((s, i) => (
              <li key={i} className="flex gap-4">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">{i + 1}</span>
                <p className="pt-0.5 text-sm leading-relaxed">{s}</p>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
      <Card id="setup" className="scroll-mt-20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Wrench className="size-4" />{t("help.setupTitle")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("help.setupIntro")}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed">
            {(t("help.setupSteps", { returnObjects: true }) as string[]).map((s, i) => <li key={i}>{s}</li>)}
          </ol>
          <Button asChild><Link to="/settings"><Settings />{t("config.title")}</Link></Button>
          <div className="rounded-lg border bg-muted/40 p-3">
            <p className="flex items-center gap-2 text-sm font-medium"><Bot className="size-4" />{t("help.agentsTitle")}</p>
            <p className="mt-1 text-xs text-muted-foreground">{t("help.agentsBody")}</p>
            <pre className="mt-2 overflow-auto rounded-md bg-background p-3 font-mono text-xs leading-relaxed">{`texclaim config show --json          # what is configured (no secret values)
texclaim config set TEXCLAIM_MODEL=cli:claude
texclaim config set ANTHROPIC_API_KEY  # prompts without echo
texclaim config test                   # tiny request to the model
curl -s localhost:8765/api/config      # same over HTTP (GET / PUT)`}</pre>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>{t("help.verdictsTitle")}</CardTitle></CardHeader>
        <CardContent>
          <dl className="space-y-3">
            {VERDICTS.map((v: Verdict) => (
              <div key={v} className="grid gap-1 sm:grid-cols-[220px_1fr] sm:items-center">
                <dt><VerdictBadge verdict={v} /></dt>
                <dd className="text-sm text-muted-foreground">{t(`verdict.help.${v}`)}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Terminal className="size-4" />{t("help.cli")}</CardTitle></CardHeader>
        <CardContent>
          <pre className="overflow-auto rounded-lg bg-muted p-4 font-mono text-xs leading-relaxed">{cli.map(([cmd, note]) => `${cmd.padEnd(42)}# ${note}`).join("\n")}</pre>
        </CardContent>
      </Card>
      <Alert variant="warning"><ShieldAlert /><p>{t("help.privacy")}</p></Alert>
      <Button variant="outline" asChild><Link to="/">{t("app.goHome")}</Link></Button>
    </div>
  );
}
