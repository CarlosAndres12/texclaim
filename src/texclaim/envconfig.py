"""Read and write texclaim's keys and global defaults (the `.env` file), safely.

Used by `texclaim config`, the web app's Settings page and `/api/config`. Secret values are never
returned: callers only learn whether a key is set. The file keeps its comments and order, is
written atomically with mode 0600, and changes apply to the running process immediately.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from texclaim import dotenv, paths

PROVIDER_KEYS = {
    "ANTHROPIC_API_KEY": "Anthropic",
    "OPENAI_API_KEY": "OpenAI",
    "GEMINI_API_KEY": "Google Gemini",
    "MISTRAL_API_KEY": "Mistral",
    "DEEPSEEK_API_KEY": "DeepSeek",
    "GROQ_API_KEY": "Groq",
    "OPENROUTER_API_KEY": "OpenRouter",
    "AZURE_API_KEY": "Azure OpenAI",
}
SOURCE_KEYS = {"OPENALEX_API_KEY": "OpenAlex", "ASTA_API_KEY": "Asta / Semantic Scholar"}
SECRETS = {**PROVIDER_KEYS, **SOURCE_KEYS}
PLAIN = {
    "TEXCLAIM_MODEL": "Default model",
    "TEXCLAIM_CONTACT_EMAIL": "Contact email for OpenAlex/arXiv",
    "TEXCLAIM_REPORT_LANGUAGE": "Default explanation language (auto|en|es)",
    "TEXCLAIM_CLAIM_SCOPE": "Default claim length (auto|sentence|two|paragraph)",
    "TEXCLAIM_MAX_USD": "Default maximum LLM cost per run (USD)",
    "AZURE_API_BASE": "Azure OpenAI endpoint",
    "AZURE_API_VERSION": "Azure OpenAI API version",
    "OLLAMA_API_BASE": "Ollama server URL",
}
KNOWN = {**SECRETS, **PLAIN}
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_CHOICES = {
    "TEXCLAIM_REPORT_LANGUAGE": {"auto", "en", "es"},
    "TEXCLAIM_CLAIM_SCOPE": {"auto", "sentence", "two", "paragraph"},
}


class ConfigValueError(ValueError):
    pass


def env_file() -> Path:
    """The file texclaim writes: $TEXCLAIM_ENV_FILE, the source checkout's .env, or the
    global config folder's .env (for regular installs)."""
    if os.environ.get("TEXCLAIM_ENV_FILE"):
        return Path(os.environ["TEXCLAIM_ENV_FILE"])
    repo = dotenv.REPO_ROOT
    if (repo / ".env").exists() or (repo / "pyproject.toml").exists():
        return repo / ".env"
    return paths.global_config_dir() / ".env"


def read_file(path: Path | None = None) -> dict[str, str]:
    path = path or env_file()
    try:
        return dotenv.parse(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def validate(name: str, value: str) -> str:
    if name not in KNOWN:
        raise ConfigValueError(f"unknown setting: {name}")
    value = value.strip()
    if "\n" in value or "\r" in value:
        raise ConfigValueError(f"{name}: value must be a single line")
    if name in _CHOICES and value and value not in _CHOICES[name]:
        raise ConfigValueError(f"{name}: use one of {', '.join(sorted(_CHOICES[name]))}")
    if name == "TEXCLAIM_MAX_USD" and value:
        try:
            v = float(value)
        except ValueError as e:
            raise ConfigValueError("TEXCLAIM_MAX_USD must be a number") from e
        if not 0 <= v <= 1000:
            raise ConfigValueError("TEXCLAIM_MAX_USD must be between 0 and 1000")
    if name == "TEXCLAIM_CONTACT_EMAIL" and value and "@" not in value:
        raise ConfigValueError("TEXCLAIM_CONTACT_EMAIL must be an email address")
    return value


def _quote(value: str) -> str:
    return f'"{value}"' if (" " in value or "#" in value) else value


def write(updates: dict[str, str | None], path: Path | None = None) -> Path:
    """Set (str) or remove (None or "") values; keeps every other line. Returns the file."""
    path = path or env_file()
    clean = {k: (validate(k, v) if v else "") for k, v in updates.items()}
    for k in updates:
        if k not in KNOWN:
            raise ConfigValueError(f"unknown setting: {k}")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done: set[str] = set()
    out = []
    for line in lines:
        m = _LINE.match(line)
        if m and m.group(1) in clean:
            name = m.group(1)
            if name not in done:
                out.append(f"{name}={_quote(clean[name])}")
                done.add(name)
            continue  # drop duplicates
        out.append(line)
    missing = [k for k in clean if k not in done]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out += [f"{k}={_quote(clean[k])}" for k in missing]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    for k, v in clean.items():  # apply now, for this process
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    return path


def describe() -> dict:
    """What a UI may show: secrets as booleans, plain settings as values."""
    file_values = read_file()
    out_secrets = {}
    for k, label in SECRETS.items():
        out_secrets[k] = {
            "label": label,
            "set": bool(os.environ.get(k) or file_values.get(k)),
            "from_environment": bool(os.environ.get(k)) and not file_values.get(k),
        }
    out_plain = {
        k: {"label": label, "value": os.environ.get(k) or file_values.get(k) or ""}
        for k, label in PLAIN.items()
    }
    return {"file": str(env_file()), "secrets": out_secrets, "settings": out_plain}
