import * as React from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { circular } from "graphology-layout";
import Sigma from "sigma";
import {
  Download, Image as ImageIcon, Maximize, Minus, Network, Plus, RefreshCw, Search, Terminal, X,
} from "lucide-react";
import { api, type GraphData, type GraphNode, type Project, type Verdict } from "@/lib/api";
import { cleanClaim, cn, VERDICT_HEX } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton, Tooltip } from "@/components/ui/misc";
import { Switch } from "@/components/ui/switch";
import { EmptyState, ErrorState, VerdictBadge } from "@/components/common";
import { useReport } from "./hooks";

type Kind = GraphNode["kind"];
type ColorMode = "verdict" | "kind" | "community";
type LayoutMode = "force" | "circular" | "section";

const KIND_HEX: Record<Kind, string> = {
  document: "#312e81",
  section: "#6366f1",
  claim: "#64748b",
  work: "#0891b2",
  entity: "#d97706",
};
// Entity colours avoid the verdict hues (green, amber, red, purple, slate)
const ETYPE_HEX: Record<string, string> = {
  method: "#2563eb", dataset: "#0d9488", metric: "#a16207", task: "#0369a1", result: "#db2777", concept: "#78716c",
};
const ENTITY_IN_VERDICT_MODE = "#14b8a6";
const COMMUNITY = ["#6366f1", "#0891b2", "#16a34a", "#d97706", "#db2777", "#7c3aed", "#0d9488", "#dc2626", "#4f46e5", "#65a30d"];

function nodeColor(n: GraphNode, mode: ColorMode): string {
  if (mode === "community") return COMMUNITY[n.community % COMMUNITY.length];
  if (mode === "kind") return n.kind === "entity" ? ETYPE_HEX[n.etype || "concept"] ?? KIND_HEX.entity : KIND_HEX[n.kind];
  if (n.kind === "claim") return n.verdict ? VERDICT_HEX[n.verdict] : VERDICT_HEX.PENDING;
  if (n.kind === "work") {
    return n.status === "FULL_TEXT" ? KIND_HEX.work : n.status === "ABSTRACT_ONLY" ? "#67e8f9" : "#cbd5e1";
  }
  if (n.kind === "entity") return ENTITY_IN_VERDICT_MODE;
  return KIND_HEX[n.kind];
}

function buildGraph(data: GraphData, kinds: Set<Kind>, mode: ColorMode, layout: LayoutMode, dark: boolean): Graph {
  const g = new Graph({ multi: true, type: "directed" });
  const sections = data.stats.sections;
  const maxDeg = Math.max(1, ...data.nodes.map((n) => n.degree));
  for (const n of data.nodes) {
    if (!kinds.has(n.kind)) continue;
    const base = n.kind === "document" ? 16 : n.kind === "section" ? 11 : n.kind === "work" ? 8 : n.kind === "claim" ? 6 : 5;
    g.addNode(n.id, {
      label: n.kind === "claim" ? cleanClaim(n.label).slice(0, 60) + (n.label.length > 60 ? "…" : "") : n.label,
      size: base + 8 * Math.sqrt(n.degree / maxDeg),
      color: nodeColor(n, mode),
      x: Math.random(), y: Math.random(),
      kind: n.kind,
    });
  }
  for (const e of data.edges) {
    if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
    const color = e.verdict && e.verdict in VERDICT_HEX ? VERDICT_HEX[e.verdict as Verdict] + "cc" : dark ? "#94a3b880" : "#47556999";
    g.addDirectedEdgeWithKey(e.id, e.source, e.target, {
      size: e.kind === "cites" || e.kind === "evidence" ? 1.6 : 0.8,
      color, kind: e.kind, type: "arrow",
    });
  }
  if (layout === "circular") {
    circular.assign(g, { scale: 100 });
  } else if (layout === "section") {
    // Columns by section; claims under their section, works/entities to the right
    const col = new Map<string, number>(sections.map((s, i) => [`sec:${s}`, i]));
    const counts = new Map<number, number>();
    g.forEachNode((id, a) => {
      let c = a.kind === "document" ? -1 : a.kind === "section" ? col.get(id) ?? 0 : -2;
      if (a.kind === "claim") g.forEachInNeighbor(id, (nb) => { if (col.has(nb)) c = col.get(nb)!; });
      if (c === -2) c = sections.length + (a.kind === "work" ? 0 : 1);
      const k = counts.get(c) ?? 0;
      counts.set(c, k + 1);
      g.mergeNodeAttributes(id, { x: c * 120, y: a.kind === "section" ? 0 : -(k + 1) * 14 });
    });
  } else {
    circular.assign(g, { scale: 100 });
    if (g.order > 1) {
      const settings = forceAtlas2.inferSettings(g);
      forceAtlas2.assign(g, { iterations: g.order > 800 ? 120 : 300, settings: { ...settings, gravity: 1.2, scalingRatio: 8, barnesHutOptimize: g.order > 400 } });
    }
  }
  return g;
}

export default function GraphTab({ project }: { project: Project }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data, isLoading, error, refetch, isFetching } = useQuery({ queryKey: ["graph", project.id], queryFn: () => api.graph(project.id), retry: false });
  const { data: report } = useReport(project.id);
  const container = React.useRef<HTMLDivElement>(null);
  const sigmaRef = React.useRef<Sigma | null>(null);
  const [kinds, setKinds] = React.useState<Set<Kind>>(new Set(["document", "section", "claim", "work", "entity"]));
  const [mode, setMode] = React.useState<ColorMode>("verdict");
  const [layout, setLayout] = React.useState<LayoutMode>("force");
  const [labels, setLabels] = React.useState(true);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [hovered, setHovered] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const graphRef = React.useRef<Graph | null>(null);
  const stateRef = React.useRef({ selected, hovered, query });
  stateRef.current = { selected, hovered, query };

  const nodesById = React.useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);

  React.useEffect(() => {
    if (!data || !container.current) return;
    const dark = document.documentElement.classList.contains("dark");
    const g = buildGraph(data, kinds, mode, layout, dark);
    graphRef.current = g;
    const sigma = new Sigma(g, container.current, {
      renderLabels: labels,
      labelDensity: 0.7,
      labelRenderedSizeThreshold: layout === "section" ? 12 : 7,
      labelColor: { color: dark ? "#e2e8f0" : "#1e293b" },
      labelFont: "Inter, ui-sans-serif, system-ui, sans-serif",
      labelSize: 12,
      defaultEdgeType: "arrow",
      zIndex: true,
      minCameraRatio: 0.05,
      maxCameraRatio: 8,
      nodeReducer: (node, attrs) => {
        const { selected: sel, hovered: hov, query: q } = stateRef.current;
        const focus = hov || sel;
        const res: Record<string, unknown> = { ...attrs };
        if (q && !String(attrs.label).toLowerCase().includes(q.toLowerCase())) {
          res.color = dark ? "#334155" : "#e2e8f0";
          res.label = "";
        }
        if (focus && node !== focus && !g.areNeighbors(node, focus)) {
          res.color = dark ? "#1e293b" : "#e5e7eb";
          res.label = "";
          res.zIndex = 0;
        } else if (focus) {
          res.zIndex = 1;
          res.forceLabel = true;
        }
        if (node === sel) { res.highlighted = true; res.size = (attrs.size as number) * 1.3; }
        return res;
      },
      edgeReducer: (edge, attrs) => {
        const { selected: sel, hovered: hov } = stateRef.current;
        const focus = hov || sel;
        if (focus && !g.extremities(edge).includes(focus)) return { ...attrs, hidden: true };
        return attrs;
      },
    });
    sigma.on("clickNode", ({ node }) => setSelected(node));
    sigma.on("clickStage", () => setSelected(null));
    sigma.on("enterNode", ({ node }) => { setHovered(node); container.current!.style.cursor = "pointer"; });
    sigma.on("leaveNode", () => { setHovered(null); container.current!.style.cursor = "default"; });
    sigmaRef.current = sigma;
    return () => { sigma.kill(); sigmaRef.current = null; };
  }, [data, kinds, mode, layout, labels]);

  React.useEffect(() => { sigmaRef.current?.refresh(); }, [selected, hovered, query]);

  const focusNode = (id: string) => {
    setSelected(id);
    const s = sigmaRef.current, g = graphRef.current;
    if (!s || !g?.hasNode(id)) return;
    const pos = s.getNodeDisplayData(id);
    if (pos) s.getCamera().animate({ x: pos.x, y: pos.y, ratio: 0.35 }, { duration: 500 });
  };

  const exportPng = () => {
    const s = sigmaRef.current;
    if (!s) return;
    // WebGL buffers are cleared after each frame: re-render and copy in the same task
    s.refresh();
    const { width, height } = s.getDimensions();
    const ratio = window.devicePixelRatio || 1;
    const out = document.createElement("canvas");
    out.width = width * ratio; out.height = height * ratio;
    const ctx = out.getContext("2d")!;
    ctx.fillStyle = document.documentElement.classList.contains("dark") ? "#0f172a" : "#ffffff";
    ctx.fillRect(0, 0, out.width, out.height);
    const canvases = s.getCanvases();
    for (const key of ["edges", "nodes", "labels", "hovers", "hoverNodes"]) if (canvases[key]) ctx.drawImage(canvases[key], 0, 0, out.width, out.height);
    const a = document.createElement("a");
    a.href = out.toDataURL("image/png");
    a.download = `${project.name}-graph.png`;
    a.click();
  };
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${project.name}-graph.json`;
    a.click();
  };

  if (isLoading) return <Skeleton className="h-[640px]" />;
  if (error) return error instanceof Error && error.message.includes("run a check") ? <EmptyState icon={<Network />} title={t("graph.empty")} /> : <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  const sel = selected ? nodesById.get(selected) : undefined;
  const neighbours = sel
    ? data.edges.filter((e) => e.source === sel.id || e.target === sel.id).map((e) => ({ e, other: nodesById.get(e.source === sel.id ? e.target : e.source)! })).filter((x) => x.other)
    : [];
  const unitFor = (n: GraphNode) => report?.units.find((u) => u.file === n.file && u.line === n.line && u.claim_text === n.text);
  const matches = query ? data.nodes.filter((n) => n.label.toLowerCase().includes(query.toLowerCase())).slice(0, 8) : [];
  const toggleKind = (k: Kind) => setKinds((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <Card className="relative min-w-0 overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b p-3">
          <div className="relative w-full sm:w-64">
            <Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" />
            <Input className="pl-9" placeholder={t("graph.search")} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t("graph.search")} data-testid="graph-search" />
            {matches.length > 0 && (
              <ul className="absolute top-10 z-20 w-80 rounded-lg border bg-popover p-1 shadow-lg">
                {matches.map((n) => (
                  <li key={n.id}><button className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent cursor-pointer" onClick={() => { focusNode(n.id); setQuery(""); }}>
                    <span className="size-2 shrink-0 rounded-full" style={{ background: nodeColor(n, mode) }} /><span className="truncate">{cleanClaim(n.label)}</span><span className="ml-auto text-[10px] text-muted-foreground">{t(`graph.kindOne.${n.kind}`)}</span>
                  </button></li>
                ))}
              </ul>
            )}
          </div>
          <div className="w-[calc(50%-4px)] sm:w-40"><Select ariaLabel={t("graph.layout")} value={layout} onValueChange={(v) => setLayout(v as LayoutMode)} options={[{ value: "force", label: t("graph.force") }, { value: "section", label: t("graph.bySection") }, { value: "circular", label: t("graph.circular") }]} /></div>
          <div className="w-[calc(50%-4px)] sm:w-40"><Select ariaLabel={t("graph.colorBy")} value={mode} onValueChange={(v) => setMode(v as ColorMode)} options={[{ value: "verdict", label: t("graph.byVerdict") }, { value: "kind", label: t("graph.byKind") }, { value: "community", label: t("graph.byCommunity") }]} /></div>
          <Label className="text-xs font-normal"><Switch checked={labels} onCheckedChange={setLabels} />{t("graph.labels")}</Label>
          <div className="ml-auto flex items-center gap-1">
            <span className="mr-2 text-xs text-muted-foreground tabular-nums">{t("graph.stats", { nodes: data.nodes.length, edges: data.edges.length })}</span>
            <Tooltip content={t("graph.rebuild")}><Button variant="ghost" size="icon-sm" aria-label={t("graph.rebuild")} disabled={isFetching} onClick={async () => { await qc.fetchQuery({ queryKey: ["graph", project.id], queryFn: () => api.graph(project.id, true) }); }}><RefreshCw className={cn(isFetching && "animate-spin")} /></Button></Tooltip>
            <Tooltip content={t("graph.exportPng")}><Button variant="ghost" size="icon-sm" aria-label={t("graph.exportPng")} onClick={exportPng}><ImageIcon /></Button></Tooltip>
            <Tooltip content={t("graph.exportJson")}><Button variant="ghost" size="icon-sm" aria-label={t("graph.exportJson")} onClick={exportJson}><Download /></Button></Tooltip>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4 border-b px-3 py-2 text-xs" role="group" aria-label={t("graph.show")}>
          <span className="text-muted-foreground">{t("graph.show")}:</span>
          {(["section", "claim", "work", "entity"] as Kind[]).map((k) => (
            <Label key={k} className="text-xs font-normal"><Checkbox checked={kinds.has(k)} onCheckedChange={() => toggleKind(k)} />
              <span className="size-2 rounded-full" style={{ background: KIND_HEX[k] }} />{t(`graph.kinds.${k}`)} <span className="text-muted-foreground tabular-nums">{data.stats.counts[k] ?? 0}</span>
            </Label>
          ))}
        </div>
        <div className="relative">
          <div ref={container} className="h-[calc(100vh-330px)] min-h-[520px] w-full bg-[radial-gradient(circle_at_1px_1px,var(--border)_1px,transparent_0)] [background-size:22px_22px]" data-testid="graph-canvas" />
          <div className="absolute right-3 bottom-3 flex flex-col gap-1 rounded-lg border bg-card/90 p-1 shadow-sm backdrop-blur">
            <Tooltip side="left" content={t("graph.zoomIn")}><Button variant="ghost" size="icon-sm" aria-label={t("graph.zoomIn")} onClick={() => sigmaRef.current?.getCamera().animatedZoom({ duration: 250 })}><Plus /></Button></Tooltip>
            <Tooltip side="left" content={t("graph.zoomOut")}><Button variant="ghost" size="icon-sm" aria-label={t("graph.zoomOut")} onClick={() => sigmaRef.current?.getCamera().animatedUnzoom({ duration: 250 })}><Minus /></Button></Tooltip>
            <Tooltip side="left" content={t("graph.reset")}><Button variant="ghost" size="icon-sm" aria-label={t("graph.reset")} onClick={() => { setSelected(null); sigmaRef.current?.getCamera().animatedReset({ duration: 300 }); }}><Maximize /></Button></Tooltip>
          </div>
          <div className="pointer-events-none absolute bottom-3 left-3 max-w-xs rounded-lg border bg-card/90 p-3 text-xs shadow-sm backdrop-blur">
            <p className="mb-1.5 font-medium">{t("graph.legend")}</p>
            {mode === "verdict" ? (
              <ul className="grid grid-cols-2 gap-x-3 gap-y-1">
                {(Object.keys(VERDICT_HEX) as (Verdict | "PENDING")[]).filter((v) => v !== "PENDING").map((v) => <li key={v} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: VERDICT_HEX[v] }} />{t(`verdict.${v}`)}</li>)}
                <li className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: KIND_HEX.section }} />{t("graph.kinds.section")}</li>
                <li className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: KIND_HEX.work }} />{t("graph.kinds.work")}</li>
                <li className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: ENTITY_IN_VERDICT_MODE }} />{t("graph.entitiesLegend")}</li>
              </ul>
            ) : mode === "kind" ? (
              <ul className="grid grid-cols-2 gap-x-3 gap-y-1">
                {(["section", "claim", "work"] as Kind[]).map((k) => <li key={k} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: KIND_HEX[k] }} />{t(`graph.kinds.${k}`)}</li>)}
                {Object.entries(ETYPE_HEX).map(([k, c]) => <li key={k} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: c }} />{t(`graph.etypes.${k}`)}</li>)}
              </ul>
            ) : (
              <ul className="grid grid-cols-2 gap-x-3 gap-y-1">
                {[...new Set(data.nodes.map((n) => n.community))].sort((a, b) => a - b).slice(0, 10).map((c) => (
                  <li key={c} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: COMMUNITY[c % COMMUNITY.length] }} />{t("graph.community", { n: c + 1 })}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </Card>

      <div className="space-y-4">
        <Card data-testid="graph-panel">
          {sel ? (
            <>
              <CardHeader className="flex-row items-start justify-between gap-2">
                <div className="min-w-0 space-y-1">
                  <p className="text-xs text-muted-foreground">{sel.kind === "entity" ? t(`graph.etypes.${sel.etype}`) : t(`graph.kindOne.${sel.kind}`)} · {t("graph.degree", { count: sel.degree })}</p>
                  <CardTitle className="text-base leading-snug break-words">{cleanClaim(sel.text || sel.label)}</CardTitle>
                </div>
                <Button variant="ghost" size="icon-sm" onClick={() => setSelected(null)} aria-label={t("app.close")}><X /></Button>
              </CardHeader>
              <CardContent className="space-y-4">
                {sel.kind === "claim" && (
                  <div className="space-y-2 text-sm">
                    {sel.verdict && <VerdictBadge verdict={sel.verdict} />}
                    <p className="font-mono text-xs text-muted-foreground">{sel.file}:{sel.line}{sel.role ? ` · ${t(`findings.role.${sel.role}`)}` : ""}</p>
                    {unitFor(sel) && <Button size="sm" variant="outline" asChild><Link to={`/projects/${project.id}/findings?f=${unitFor(sel)!.id}&all=1`}>{t("graph.openDetail")}</Link></Button>}
                  </div>
                )}
                {sel.kind === "work" && <p className="text-xs text-muted-foreground"><span className="font-mono">{sel.bib_key}</span>{sel.year ? ` · ${sel.year}` : ""} · {t(`sources.statusLabel.${sel.status}`, { defaultValue: sel.status })}</p>}
                <div>
                  <h4 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t("graph.neighbours")}</h4>
                  <ul className="max-h-80 space-y-1 overflow-auto scrollbar-thin">
                    {neighbours.map(({ e, other }) => (
                      <li key={e.id}>
                        <button onClick={() => focusNode(other.id)} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent cursor-pointer">
                          <span className="size-2 shrink-0 rounded-full" style={{ background: nodeColor(other, mode) }} />
                          <span className="min-w-0 flex-1 truncate">{cleanClaim(other.label)}</span>
                          <span className="shrink-0 text-[10px] text-muted-foreground">{t(`graph.edges.${e.kind}`, { defaultValue: e.kind })}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </CardContent>
            </>
          ) : (
            <CardContent className="space-y-4 pt-5">
              <p className="text-sm text-muted-foreground">{t("graph.selectHint")}</p>
              {data.stats.top_entities.length > 0 && (
                <div>
                  <h4 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t("graph.topEntities")}</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {data.stats.top_entities.map((e) => (
                      <button key={e.id} onClick={() => focusNode(e.id)} className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs hover:bg-accent cursor-pointer">
                        <span className="size-2 rounded-full" style={{ background: ETYPE_HEX[e.etype] ?? KIND_HEX.entity }} />{e.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          )}
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><Terminal className="size-4" />{t("graph.mcpTitle")}</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">{t("graph.mcpBody")}</p>
            <pre className="overflow-x-auto rounded-md bg-muted p-2.5 font-mono text-[11px] whitespace-pre-wrap break-all">{`claude mcp add texclaim -- \\\n  texclaim mcp "${project.folder}"`}</pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
