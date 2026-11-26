"""Web projects: an uploaded manuscript folder (or a local folder) plus its web settings."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import platformdirs

ALLOWED_EXT = {
    ".tex", ".bib", ".bbl", ".sty", ".cls", ".bst", ".md", ".markdown", ".docx", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".eps", ".txt", ".csv", ".json", ".yaml", ".yml",
    ".toml", ".latexmkrc",
}  # fmt: skip
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_FILES = 2000


class ProjectError(Exception):
    pass


def data_dir() -> Path:
    env = os.environ.get("TEXCLAIM_DATA_DIR")
    d = Path(env) if env else platformdirs.user_data_path("texclaim") / "web"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class WebSettings:
    """Per-project choices made in the web UI; passed to the pipeline as top-priority overrides."""

    model: str | None = None
    claim_scope: str = "auto"
    report_language: str = "auto"
    internal_enabled: bool = True
    internal_sections: list[str] = field(default_factory=list)
    max_usd: float = 5.0
    main: str | None = None
    offline: bool = False

    def overrides(self) -> dict:
        out = {
            "claim_scope": self.claim_scope,
            "report_language": self.report_language,
            "internal.enabled": self.internal_enabled,
            "internal.sections": self.internal_sections,
            "budget.max_llm_usd_per_run": self.max_usd,
            "offline": self.offline or None,
        }
        if self.model:
            out["model"] = self.model
        if self.main:
            out["main"] = self.main
        return out


@dataclass
class Project:
    id: str
    name: str
    created: str
    folder: str  # absolute paper folder
    external: bool = False  # a local folder opened in place (never deleted)
    settings: WebSettings = field(default_factory=WebSettings)
    last_run: dict | None = None

    @property
    def path(self) -> Path:
        return Path(self.folder)

    def to_json(self) -> dict:
        d = asdict(self)
        return d


class ProjectStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or data_dir()) / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def _meta(self, pid: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", pid):
            raise ProjectError("invalid project id")
        return self.root / pid / "project.json"

    def list(self) -> list[Project]:
        out = []
        for d in sorted(self.root.iterdir()):
            try:
                out.append(self.get(d.name))
            except (ProjectError, OSError, ValueError):
                continue
        out.sort(key=lambda p: p.created, reverse=True)
        return out

    def get(self, pid: str) -> Project:
        meta = self._meta(pid)
        if not meta.exists():
            raise ProjectError("project not found")
        d = json.loads(meta.read_text(encoding="utf-8"))
        d["settings"] = WebSettings(**d.get("settings", {}))
        return Project(**d)

    def save(self, p: Project) -> None:
        meta = self._meta(p.id)
        meta.parent.mkdir(parents=True, exist_ok=True)
        tmp = meta.with_suffix(".tmp")
        tmp.write_text(json.dumps(p.to_json(), indent=2), encoding="utf-8")
        tmp.replace(meta)

    def create(self, name: str, folder: Path | None = None) -> Project:
        pid = uuid.uuid4().hex[:12]
        external = folder is not None
        if folder is None:
            folder = self.root / pid / "paper"
            folder.mkdir(parents=True)
        p = Project(pid, name.strip() or "Untitled", _now(), str(folder.resolve()), external)
        self.save(p)
        return p

    def delete(self, pid: str) -> None:
        self.get(pid)
        shutil.rmtree(self.root / pid, ignore_errors=True)  # external folders live elsewhere


def safe_relpath(name: str) -> Path:
    """A relative path inside the project; rejects absolute paths and '..'."""
    name = name.replace("\\", "/").lstrip("/")
    parts = [x for x in name.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." for x in parts) or any(x.startswith(".texclaim") for x in parts):
        raise ProjectError(f"invalid file name: {name}")
    return Path(*parts)


def _allowed(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_EXT or path.name in (".latexmkrc", "latexmkrc")


def add_file(folder: Path, name: str, data: bytes) -> list[str]:
    """Store an uploaded file (a .zip is extracted). Returns the stored relative paths."""
    rel = safe_relpath(name)
    if rel.suffix.lower() == ".zip":
        return extract_zip(folder, data)
    if not _allowed(rel):
        raise ProjectError(f"file type not supported: {rel.name}")
    dest = folder / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return [rel.as_posix()]


def extract_zip(folder: Path, data: bytes) -> list[str]:
    import io

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ProjectError("not a valid .zip file") from e
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise ProjectError("too many files in the archive")
    if sum(i.file_size for i in infos) > MAX_UPLOAD_BYTES:
        raise ProjectError("archive too large when extracted")
    names = [i.filename for i in infos if not i.filename.startswith("__MACOSX/")]
    # Strip a single top-level folder ("paper/main.tex" -> "main.tex")
    tops = {n.split("/", 1)[0] for n in names}
    strip = len(tops) == 1 and all("/" in n for n in names)
    stored = []
    for i in infos:
        n = i.filename
        if n.startswith("__MACOSX/") or Path(n).name.startswith("._"):
            continue
        if strip:
            n = n.split("/", 1)[1]
        try:
            rel = safe_relpath(n)
        except ProjectError:
            continue
        if not _allowed(rel):
            continue
        dest = folder / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(i) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)
        stored.append(rel.as_posix())
    if not stored:
        raise ProjectError("the archive has no supported files")
    return stored


def list_files(folder: Path) -> list[dict]:
    from texclaim.parser.root_finder import SKIP_DIRS

    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if f.startswith(".") or f.startswith("texclaim_report"):
                continue
            rel = p.relative_to(folder).as_posix()
            out.append({"path": rel, "size": p.stat().st_size, "kind": p.suffix.lower()[1:]})
        if len(out) > MAX_FILES:
            break
    return out
