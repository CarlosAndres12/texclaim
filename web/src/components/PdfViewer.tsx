import * as React from "react";
import { useTranslation } from "react-i18next";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ChevronLeft, ChevronRight, ExternalLink, Loader2, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/misc";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const norm = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]+/gu, "");

/** Mark the text-layer spans that contain `quote`; returns the first marked span. */
function highlight(container: HTMLElement, quote: string): HTMLElement | null {
  const spans = Array.from(container.querySelectorAll<HTMLElement>("span"));
  spans.forEach((s) => s.classList.remove("tc-hl"));
  const target = norm(quote);
  if (!target) return null;
  let flat = "";
  const owner: number[] = [];
  spans.forEach((s, i) => {
    const n = norm(s.textContent || "");
    flat += n;
    for (let k = 0; k < n.length; k++) owner.push(i);
  });
  for (const size of [target.length, 120, 80, 50, 30]) {
    if (size > target.length) continue;
    const probe = target.slice(0, size);
    const at = flat.indexOf(probe);
    if (at < 0) continue;
    const end = Math.min(flat.length - 1, at + target.length - 1);
    const first = owner[at], last = owner[end];
    for (let i = first; i <= last; i++) spans[i].classList.add("tc-hl");
    return spans[first];
  }
  return null;
}

export function PdfViewer({ url, page = 1, quote, className }: { url: string; page?: number | null; quote?: string | null; className?: string }) {
  const { t } = useTranslation();
  const [doc, setDoc] = React.useState<pdfjs.PDFDocumentProxy | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [current, setCurrent] = React.useState(page || 1);
  const [zoom, setZoom] = React.useState(1);
  const [rendering, setRendering] = React.useState(false);
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const textRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => setCurrent(page || 1), [page, url, quote]);

  React.useEffect(() => {
    let cancelled = false;
    setDoc(null);
    setError(null);
    const task = pdfjs.getDocument({ url });
    task.promise.then((d) => !cancelled && setDoc(d), (e) => !cancelled && setError(String(e?.message || e)));
    return () => { cancelled = true; task.destroy(); };
  }, [url]);

  React.useEffect(() => {
    if (!doc || !wrapRef.current || !canvasRef.current || !textRef.current) return;
    let cancelled = false;
    let renderTask: pdfjs.RenderTask | null = null;
    const n = Math.min(Math.max(1, current), doc.numPages);
    setRendering(true);
    (async () => {
      const p = await doc.getPage(n);
      if (cancelled) return;
      const base = p.getViewport({ scale: 1 });
      const width = Math.max(320, wrapRef.current!.clientWidth - 24);
      const scale = (width / base.width) * zoom;
      const viewport = p.getViewport({ scale });
      const ratio = window.devicePixelRatio || 1;
      const canvas = canvasRef.current!;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      const ctx = canvas.getContext("2d")!;
      renderTask = p.render({ canvasContext: ctx, viewport, canvas, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined });
      await renderTask.promise.catch(() => undefined);
      if (cancelled) return;
      const layer = textRef.current!;
      layer.innerHTML = "";
      layer.style.width = `${viewport.width}px`;
      layer.style.height = `${viewport.height}px`;
      layer.style.setProperty("--scale-factor", String(scale));
      const tl = new pdfjs.TextLayer({ textContentSource: p.streamTextContent(), container: layer, viewport });
      await tl.render();
      if (cancelled) return;
      if (quote) {
        const hit = highlight(layer, quote);
        hit?.scrollIntoView({ block: "center", behavior: "smooth" });
      }
      setRendering(false);
    })().catch((e) => !cancelled && setError(String(e?.message || e)));
    return () => { cancelled = true; renderTask?.cancel(); };
  }, [doc, current, zoom, quote]);

  const total = doc?.numPages ?? 0;
  return (
    <div className={`flex min-h-0 flex-col overflow-hidden rounded-xl border bg-muted/40 ${className ?? ""}`} data-testid="pdf-viewer">
      <div className="flex items-center gap-1 border-b bg-card px-2 py-1.5">
        <Tooltip content={t("pdf.prev")}>
          <Button variant="ghost" size="icon-sm" aria-label={t("pdf.prev")} disabled={current <= 1} onClick={() => setCurrent((c) => c - 1)}><ChevronLeft /></Button>
        </Tooltip>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <span className="sr-only">{t("pdf.page")}</span>
          <input
            type="number" min={1} max={total || 1} value={current}
            onChange={(e) => setCurrent(Number(e.target.value) || 1)}
            className="h-7 w-12 rounded-md border bg-background px-1 text-center text-xs tabular-nums"
            aria-label={t("pdf.page")}
          />
          {t("pdf.of", { total: total || "…" })}
        </label>
        <Tooltip content={t("pdf.next")}>
          <Button variant="ghost" size="icon-sm" aria-label={t("pdf.next")} disabled={current >= total} onClick={() => setCurrent((c) => c + 1)}><ChevronRight /></Button>
        </Tooltip>
        <div className="mx-1 h-5 w-px bg-border" />
        <Tooltip content={t("pdf.zoomOut")}><Button variant="ghost" size="icon-sm" aria-label={t("pdf.zoomOut")} onClick={() => setZoom((z) => Math.max(0.5, z - 0.2))}><ZoomOut /></Button></Tooltip>
        <button className="min-w-12 text-xs tabular-nums text-muted-foreground hover:text-foreground cursor-pointer" onClick={() => setZoom(1)} title={t("pdf.fit")}>{Math.round(zoom * 100)}%</button>
        <Tooltip content={t("pdf.zoomIn")}><Button variant="ghost" size="icon-sm" aria-label={t("pdf.zoomIn")} onClick={() => setZoom((z) => Math.min(3, z + 0.2))}><ZoomIn /></Button></Tooltip>
        {rendering && <Loader2 className="ml-1 size-4 animate-spin text-muted-foreground" />}
        <div className="ml-auto flex items-center gap-2">
          {quote && <span className="hidden items-center gap-1.5 text-xs text-muted-foreground lg:flex"><span className="size-2.5 rounded-sm bg-partial/60" />{t("pdf.highlight")}</span>}
          <Tooltip content={t("pdf.openNew")}>
            <Button variant="ghost" size="icon-sm" asChild><a href={`${url}#page=${current}`} target="_blank" rel="noreferrer" aria-label={t("pdf.openNew")}><ExternalLink /></a></Button>
          </Tooltip>
        </div>
      </div>
      <div ref={wrapRef} className="relative min-h-0 flex-1 overflow-auto p-3 scrollbar-thin">
        {error ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">{t("pdf.error")} <span className="sr-only">{error}</span></div>
        ) : !doc ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />{t("pdf.loading")}</div>
        ) : null}
        <div className="relative mx-auto w-fit shadow-lg" style={{ display: doc && !error ? "block" : "none" }}>
          <canvas ref={canvasRef} className="block bg-white" />
          <div ref={textRef} className="textLayer" />
        </div>
      </div>
    </div>
  );
}
