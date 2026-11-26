import * as React from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { BookOpenCheck, CircleHelp, KeyRound, Languages, Monitor, Moon, Sun } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown";
import { Tooltip } from "@/components/ui/misc";

type Theme = "light" | "dark" | "system";

function applyTheme(t: Theme) {
  const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function useTheme() {
  const [theme, setTheme] = React.useState<Theme>(() => (localStorage.getItem("texclaim-theme") as Theme) || "system");
  React.useEffect(() => {
    if (theme === "system") localStorage.removeItem("texclaim-theme");
    else localStorage.setItem("texclaim-theme", theme);
    applyTheme(theme);
  }, [theme]);
  return [theme, setTheme] as const;
}

function LanguageSwitch() {
  const { t, i18n } = useTranslation();
  const lang = i18n.resolvedLanguage === "es" ? "es" : "en";
  return (
    <div className="flex items-center rounded-lg border bg-card p-0.5" role="group" aria-label={t("app.language")}>
      <Languages className="mx-1.5 size-4 text-muted-foreground" aria-hidden />
      {(["en", "es"] as const).map((l) => (
        <button
          key={l}
          onClick={() => i18n.changeLanguage(l)}
          aria-pressed={lang === l}
          data-testid={`lang-${l}`}
          className={cn(
            "rounded-md px-2 py-1 text-xs font-semibold uppercase transition-colors cursor-pointer",
            lang === l ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

function ThemeMenu() {
  const { t } = useTranslation();
  const [theme, setTheme] = useTheme();
  const Icon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t("app.theme")}><Icon /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => setTheme("light")}><Sun />{t("app.light")}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTheme("dark")}><Moon />{t("app.dark")}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTheme("system")}><Monitor />{t("app.system")}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function HealthMenu() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000 });
  if (!data) return null;
  const configured = Object.entries(data.keys).filter(([, v]) => v);
  return (
    <DropdownMenu>
      <Tooltip content={t("status.keys")}>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="hidden md:inline-flex" data-testid="health">
            <span className={cn("size-2 rounded-full", data.model_configured ? "bg-supported" : "bg-partial")} />
            <span className="max-w-48 truncate text-xs font-normal text-muted-foreground">
              {data.default_model ? t("status.modelReady", { model: data.default_model }) : t("status.noModel")}
            </span>
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="flex items-center gap-2"><KeyRound className="size-3.5" />{t("status.keys")}</DropdownMenuLabel>
        {[...configured.map(([k]) => [k, true] as const), ["OpenAlex", data.openalex_key] as const, ["Asta", data.asta_key] as const].map(([k, ok]) => (
          <div key={k} className="flex items-center justify-between px-2 py-1 text-sm">
            <span className="capitalize">{k}</span>
            <span className={cn("text-xs", ok ? "text-supported" : "text-muted-foreground")}>{ok ? t("status.keyOk") : t("status.keyMissing")}</span>
          </div>
        ))}
        {!data.pandoc && (<><DropdownMenuSeparator /><p className="px-2 py-1 text-xs text-partial">{t("status.pandocMissing")}</p></>)}
        <DropdownMenuSeparator />
        <p className="px-2 py-1 text-[11px] text-muted-foreground">texclaim {data.version}</p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Layout() {
  const { t } = useTranslation();
  const nav = ({ isActive }: { isActive: boolean }) =>
    cn("rounded-md px-3 py-1.5 text-sm font-medium transition-colors", isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground");
  return (
    <div className="flex min-h-full flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground">{t("app.skipToContent")}</a>
      <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight" aria-label="texclaim">
            <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm"><BookOpenCheck className="size-4" /></span>
            <span>texclaim</span>
          </Link>
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={nav}>{t("app.projects")}</NavLink>
            <NavLink to="/help" className={nav}><span className="flex items-center gap-1.5"><CircleHelp className="size-4" />{t("app.help")}</span></NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <HealthMenu />
            <LanguageSwitch />
            <ThemeMenu />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
