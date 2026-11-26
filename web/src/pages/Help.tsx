import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ShieldAlert, Terminal } from "lucide-react";
import type { Verdict } from "@/lib/api";
import { VERDICTS } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { PageHeader, VerdictBadge } from "@/components/common";

export default function HelpPage() {
  const { t } = useTranslation();
  const steps = t("help.steps", { returnObjects: true }) as string[];
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
          <pre className="overflow-auto rounded-lg bg-muted p-4 font-mono text-xs leading-relaxed">{`texclaim check path/to/paper           # LaTeX, Markdown or Word
texclaim check --claim-scope two       # claim length: auto | sentence | two | paragraph
texclaim check --internal-section Results
texclaim export --format docx          # report as Word / HTML
texclaim sources export                # PDFs of the cited works
texclaim graph && texclaim mcp .       # knowledge graph for agents
texclaim serve                         # this web app`}</pre>
        </CardContent>
      </Card>
      <Alert variant="warning"><ShieldAlert /><p>{t("help.privacy")}</p></Alert>
      <Button variant="outline" asChild><Link to="/">{t("app.goHome")}</Link></Button>
    </div>
  );
}
