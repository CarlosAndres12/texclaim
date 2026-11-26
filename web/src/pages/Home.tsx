import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileText, Folder, FolderOpen, Loader2, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react";
import { api, type Project } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown";
import { Dropzone, EmptyState, ErrorState, PageHeader, VerdictBar } from "@/components/common";

function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [files, setFiles] = React.useState<File[]>([]);
  const [name, setName] = React.useState("");
  const [path, setPath] = React.useState("");
  const [tab, setTab] = React.useState("upload");

  const create = useMutation({
    mutationFn: () => (tab === "upload" ? api.createProject(files, name) : api.openLocal(path, name)),
    onSuccess: (p) => {
      toast.success(t("newProject.created"));
      qc.invalidateQueries({ queryKey: ["projects"] });
      onOpenChange(false);
      setFiles([]); setName(""); setPath("");
      nav(`/projects/${p.id}/settings`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const canSubmit = tab === "upload" ? files.length > 0 : path.trim().startsWith("/") || /^[A-Za-z]:\\/.test(path.trim());
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" closeLabel={t("app.close")}>
        <DialogHeader>
          <DialogTitle>{t("newProject.title")}</DialogTitle>
          <DialogDescription>{t("newProject.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (canSubmit) create.mutate(); }}>
          <div className="space-y-1.5">
            <Label htmlFor="pname">{t("newProject.name")}</Label>
            <Input id="pname" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("newProject.namePlaceholder")} />
          </div>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="w-full">
              <TabsTrigger value="upload" className="flex-1">{t("newProject.tabUpload")}</TabsTrigger>
              <TabsTrigger value="local" className="flex-1">{t("newProject.tabLocal")}</TabsTrigger>
            </TabsList>
            <TabsContent value="upload" className="mt-3 space-y-2">
              <Dropzone files={files} onFiles={setFiles} />
              <p className="text-xs text-muted-foreground">{t("newProject.supported")}</p>
            </TabsContent>
            <TabsContent value="local" className="mt-3 space-y-1.5">
              <Label htmlFor="ppath">{t("newProject.localPath")}</Label>
              <Input id="ppath" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/home/me/papers/my-paper" className="font-mono" />
              <p className="text-xs text-muted-foreground">{t("newProject.localHint")}</p>
            </TabsContent>
          </Tabs>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{t("app.cancel")}</Button>
            <Button type="submit" disabled={!canSubmit || create.isPending} data-testid="create-project">
              {create.isPending ? <><Loader2 className="animate-spin" />{t("newProject.creating")}</> : tab === "upload" ? t("newProject.create") : t("newProject.open")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ProjectCard({ p, onDelete }: { p: Project; onDelete: () => void }) {
  const { t, i18n } = useTranslation();
  const s = p.summary;
  return (
    <div className="group relative flex flex-col gap-4 rounded-xl border bg-card p-5 shadow-xs transition-all hover:-translate-y-0.5 hover:shadow-md focus-within:ring-2 focus-within:ring-ring/40" data-testid="project-card">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            {p.external ? <FolderOpen className="size-5" /> : <FileText className="size-5" />}
          </div>
          <div className="min-w-0">
            <Link to={`/projects/${p.id}`} className="block truncate font-semibold after:absolute after:inset-0 after:content-[''] focus:outline-none">{p.name}</Link>
            <p className="truncate text-xs text-muted-foreground">
              {p.running ? <span className="inline-flex items-center gap-1 text-primary"><Loader2 className="size-3 animate-spin" />{t("home.running")}</span>
                : s?.finished ? t("home.lastCheck", { date: formatDate(s.finished, i18n.language) }) : t("home.notChecked")}
            </p>
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="relative z-10" aria-label={`${p.name}: ${t("app.delete")}`}><MoreHorizontal /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onDelete} className="text-destructive data-[highlighted]:text-destructive"><Trash2 />{t("app.delete")}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {s ? (
        <div className="space-y-2">
          <VerdictBar counts={s.verdicts} />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{t("home.claims", { count: s.claims })}</span>
            <span className={s.findings ? "font-medium text-contradicted" : ""}>{t("home.findings", { count: s.findings })}</span>
          </div>
        </div>
      ) : (
        <div className="h-[38px] rounded-lg border border-dashed" />
      )}
      {p.external && <p className="flex items-center gap-1 truncate font-mono text-[11px] text-muted-foreground"><Folder className="size-3" />{p.folder}</p>}
    </div>
  );
}

export default function HomePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [filter, setFilter] = React.useState("");
  const [toDelete, setToDelete] = React.useState<Project | null>(null);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["projects"],
    queryFn: api.projects,
    refetchInterval: (q) => (q.state.data?.some((p) => p.running) ? 2000 : false),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => { toast.success(t("home.deleted")); qc.invalidateQueries({ queryKey: ["projects"] }); setToDelete(null); },
    onError: (e: Error) => toast.error(e.message),
  });
  const shown = (data ?? []).filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("home.title")}
        description={t("home.subtitle")}
        actions={<Button onClick={() => setOpen(true)} data-testid="new-project"><Plus />{t("home.newProject")}</Button>}
      />
      {data && data.length > 3 && (
        <div className="relative max-w-sm">
          <Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" />
          <Input className="pl-9" placeholder={t("home.filter")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={t("home.filter")} />
        </div>
      )}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}</div>
      ) : error ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : !data?.length ? (
        <EmptyState icon={<FileText />} title={t("home.empty")} body={t("home.emptyBody")}
          action={<Button onClick={() => setOpen(true)}><Plus />{t("home.newProject")}</Button>} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((p) => <ProjectCard key={p.id} p={p} onDelete={() => setToDelete(p)} />)}
        </div>
      )}
      <NewProjectDialog open={open} onOpenChange={setOpen} />
      <Dialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)}>
        <DialogContent closeLabel={t("app.close")}>
          <DialogHeader>
            <DialogTitle>{t("home.deleteConfirm", { name: toDelete?.name })}</DialogTitle>
            <DialogDescription>{t("home.deleteBody")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>{t("app.cancel")}</Button>
            <Button variant="destructive" disabled={del.isPending} onClick={() => toDelete && del.mutate(toDelete.id)} data-testid="confirm-delete">{t("app.delete")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
