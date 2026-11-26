import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Verdict } from "./api";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const VERDICTS: Verdict[] = [
  "CONTRADICTED",
  "PARTIALLY_SUPPORTED",
  "NOT_FOUND",
  "UNCHECKABLE",
  "SUPPORTED",
];

export const VERDICT_COLOR: Record<Verdict, string> = {
  SUPPORTED: "var(--supported)",
  PARTIALLY_SUPPORTED: "var(--partial)",
  CONTRADICTED: "var(--contradicted)",
  NOT_FOUND: "var(--notfound)",
  UNCHECKABLE: "var(--uncheckable)",
};

/** Concrete colours for canvas/WebGL (CSS variables do not work there). */
export const VERDICT_HEX: Record<Verdict | "PENDING", string> = {
  SUPPORTED: "#16a34a",
  PARTIALLY_SUPPORTED: "#f59e0b",
  CONTRADICTED: "#e11d48",
  NOT_FOUND: "#9333ea",
  UNCHECKABLE: "#94a3b8",
  PENDING: "#cbd5e1",
};

export function formatCost(usd: number | null | undefined) {
  if (usd == null) return "-";
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function formatDate(iso: string | number | null | undefined, lang: string) {
  if (iso == null) return "-";
  const d = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString(lang === "es" ? "es-CO" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Strip pandoc-style citation markers for display. */
export function cleanClaim(text: string) {
  return text.replace(/\s*\[@[^\]]*(\]|$)/g, "").trim();
}

export function displayKey(key: string, selfLabel: string) {
  return key === "@self" ? selfLabel : key;
}
