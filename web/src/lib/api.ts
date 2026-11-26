export type Verdict =
  | "SUPPORTED"
  | "PARTIALLY_SUPPORTED"
  | "CONTRADICTED"
  | "NOT_FOUND"
  | "UNCHECKABLE";

export interface Health {
  version: string;
  default_model: string | null;
  model_configured: boolean;
  keys: Record<string, boolean>;
  openalex_key: boolean;
  asta_key: boolean;
  pandoc: boolean;
  suggested_models: string[];
  cli_agents?: string[];
}

export interface GlobalConfig {
  file: string;
  secrets: Record<string, { label: string; set: boolean; from_environment: boolean }>;
  settings: Record<string, { label: string; value: string }>;
  cli_agents: { name: string; installed: boolean }[];
  suggested_models: string[];
  defaults: {
    source_order: string[];
    evidence_strategy: string;
    full_text_max_tokens: number;
    passage_budget_tokens: number;
    concurrency: number;
    openalex_max_usd: number;
    arxiv_max_downloads: number;
    pdf_dirs: string[];
    internal_max_claims: number;
    screening: string;
  };
}

export interface TestResult {
  ok: boolean;
  seconds: number;
  reply?: string;
  error?: string;
}

export interface WebSettings {
  model: string | null;
  claim_scope: "auto" | "sentence" | "two" | "paragraph";
  report_language: "auto" | "en" | "es";
  internal_enabled: boolean;
  internal_sections: string[];
  max_usd: number;
  main: string | null;
  offline: boolean;
  evidence_strategy?: string | null;
  full_text_max_tokens?: number | null;
  passage_budget_tokens?: number | null;
  concurrency?: number | null;
  source_order?: string[] | null;
  openalex_max_usd?: number | null;
  arxiv_max_downloads?: number | null;
  pdf_dirs?: string[] | null;
  extra_cite_commands?: string[] | null;
  internal_max_claims?: number | null;
  screening?: string | null;
}

export interface Summary {
  verdicts: Partial<Record<Verdict, number>>;
  finding_verdicts?: Partial<Record<Verdict, number>>;
  internal: Partial<Record<Verdict, number>>;
  findings: number;
  units: number;
  claims: number;
  cost: number;
  models: string[];
  finished: string | null;
  sources: { full_text: number; abstract_only: number; none: number };
}

export interface JobSnapshot {
  project_id: string;
  kind: string;
  state: "running" | "done" | "failed" | "cancelled" | "idle";
  total: number;
  done: number;
  cost: number;
  error: string | null;
  started: number;
  events: number;
}

export interface Project {
  id: string;
  name: string;
  created: string;
  folder: string;
  external: boolean;
  settings: WebSettings;
  last_run: (Record<string, unknown> & { status?: string; finished?: number }) | null;
  summary: Summary | null;
  running?: boolean;
  job?: JobSnapshot | null;
  has_graph?: boolean;
}

export interface Quote {
  block_id: string;
  page: number | null;
  page_label?: string | null;
  text: string;
  score: number;
  section?: string | null;
  char_start: number;
  char_end: number;
}

export interface Unit {
  id: string;
  unit_key: string;
  file: string;
  line: number;
  line_end: number;
  section: string | null;
  unit_kind: string;
  bib_key: string;
  cite_command: string;
  claim_latex: string;
  claim_text: string;
  claim_origin: "cited" | "internal";
  role: "" | "abstract" | "conclusion";
  verdict: Verdict;
  reason_code: string;
  origin: string;
  evidence_scope: string;
  citation_function: string | null;
  claim_scope: string | null;
  analysis: string | null;
  what_is_wrong: string | null;
  what_source_says: string | null;
  suggested_fix: string | null;
  confidence: string | null;
  needs_review: boolean;
  model: string | null;
  source_provider: string | null;
  source_version: string | null;
  quotes: Quote[];
  suppressed: boolean;
}

export interface Finding extends Partial<Unit> {
  id: string;
  kind: "unit" | "claim";
  file: string;
  line: number;
  claim_latex: string;
  detail?: string;
  flag?: string;
}

export interface IntegrityIssue {
  id: string;
  code: string;
  severity: string;
  bib_key: string | null;
  file: string | null;
  line: number | null;
  detail: string;
  suppressed: boolean;
}

export interface Report {
  schema_version: number;
  run: {
    run_id: string;
    status: string;
    models: string[];
    llm_cost_usd: number;
    llm_calls: number;
    started_at: string;
    finished_at: string;
    counts: { claims: number; units: number; verified_this_run: number; reused: number };
    source_coverage: { full_text: number; abstract_only: number; none: number };
    notes: string[];
    report_language?: string;
  };
  findings: Finding[];
  units: Unit[];
  integrity: IntegrityIssue[];
  sources: { bib_key: string; status: string; provider: string | null; link: string | null }[];
}

export interface Outline {
  kind: "latex" | "markdown" | "docx";
  main: string;
  unit_label: "line" | "paragraph";
  sections: { title: string; cited: number; internal: number; role: string }[];
  roles: Record<string, number>;
  cited_claims: number;
  internal_candidates: number;
  keys: string[];
  diagnostics: { code: string; detail: string; file: string | null; line: number | null }[];
}

export interface SourceRow {
  bib_key: string;
  status: string;
  provider: string | null;
  version: string | null;
  link: string | null;
  openalex_id: string | null;
  file_kind: "pdf" | "text" | "abstract" | "none";
  landing_page: string | null;
  doi_url: string | null;
  title: string | null;
  year: string | null;
  authors: string[];
  verdicts: Partial<Record<Verdict, number>>;
}

export interface DocFile {
  path: string;
  unit: "line" | "paragraph";
  lines: string[];
}

export interface GraphNode {
  id: string;
  kind: "document" | "section" | "claim" | "work" | "entity";
  label: string;
  text?: string;
  verdict?: Verdict | null;
  role?: string;
  origin?: string;
  etype?: string;
  file?: string;
  line?: number;
  section?: string;
  status?: string;
  bib_key?: string;
  year?: string | null;
  degree: number;
  pagerank: number;
  community: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  verdict?: string;
  quote?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: {
    counts: Record<string, number>;
    edges: number;
    extraction_cost: number;
    top_entities: { id: string; label: string; etype: string }[];
    sections: string[];
  };
}

export interface RunEvent {
  seq: number;
  type: "start" | "stage" | "plan" | "unit" | "notice" | "done" | "error";
  t: number;
  [k: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => req<Health>("/api/health"),
  config: () => req<GlobalConfig>("/api/config"),
  saveConfig: (values: Record<string, string | null>) =>
    req<GlobalConfig>("/api/config", json("PUT", { values })),
  testConfig: (body: { target: "model" | "openalex" | "asta"; model?: string }) =>
    req<TestResult>("/api/config/test", json("POST", body)),
  projects: () => req<Project[]>("/api/projects"),
  project: (id: string) => req<Project>(`/api/projects/${id}`),
  createProject: (files: File[], name: string) => {
    const fd = new FormData();
    if (name) fd.append("name", name);
    for (const f of files) fd.append("files", f, (f as File & { relPath?: string }).relPath || f.name);
    return req<Project & { files: string[] }>("/api/projects", { method: "POST", body: fd });
  },
  openLocal: (path: string, name: string) =>
    req<Project>("/api/projects/local", json("POST", { path, name })),
  rename: (id: string, name: string) => req<Project>(`/api/projects/${id}`, json("PATCH", { name })),
  deleteProject: (id: string) => req<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  files: (id: string) => req<{ path: string; size: number; kind: string }[]>(`/api/projects/${id}/files`),
  uploadFiles: (id: string, files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f, (f as File & { relPath?: string }).relPath || f.name);
    return req<{ files: string[] }>(`/api/projects/${id}/files`, { method: "POST", body: fd });
  },
  settings: (id: string) => req<WebSettings>(`/api/projects/${id}/settings`),
  saveSettings: (id: string, s: Partial<WebSettings>) =>
    req<WebSettings>(`/api/projects/${id}/settings`, json("PUT", s)),
  outline: (id: string) => req<Outline>(`/api/projects/${id}/outline`),
  startRun: (id: string, opts: { force?: boolean; dry_run?: boolean } = {}) =>
    req<JobSnapshot>(`/api/projects/${id}/runs`, json("POST", opts)),
  currentRun: (id: string) =>
    req<JobSnapshot & { log?: RunEvent[] }>(`/api/projects/${id}/runs/current`),
  cancelRun: (id: string) => req<{ cancelled: boolean }>(`/api/projects/${id}/runs/cancel`, { method: "POST" }),
  report: (id: string) => req<Report>(`/api/projects/${id}/report`),
  document: (id: string) => req<{ kind: string; files: DocFile[] }>(`/api/projects/${id}/document`),
  sources: (id: string) => req<SourceRow[]>(`/api/projects/${id}/sources`),
  uploadSourcePdf: (id: string, key: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ saved: string }>(`/api/projects/${id}/sources/${encodeURIComponent(key)}/pdf`, {
      method: "POST",
      body: fd,
    });
  },
  graph: (id: string, rebuild = false) =>
    req<GraphData>(`/api/projects/${id}/graph${rebuild ? "?rebuild=true" : ""}`),
};

export const urls = {
  report: (id: string, fmt: string) => `/api/projects/${id}/report.${fmt}`,
  sourceFile: (id: string, key: string, download = false) =>
    `/api/projects/${id}/sources/${encodeURIComponent(key)}/file${download ? "?download=true" : ""}`,
  sourcesZip: (id: string) => `/api/projects/${id}/sources.zip`,
  rawFile: (id: string, path: string) => `/api/projects/${id}/files/raw?path=${encodeURIComponent(path)}`,
  events: (id: string, after = -1) => `/api/projects/${id}/events?after=${after}`,
};
