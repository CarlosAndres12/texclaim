"""Settings resolution (PLAN §5).

Non-secrets: CLI flag -> environment -> paper config -> global config -> default.
Secrets: CLI flag -> environment -> OS keyring -> global config. Never read from the paper config.
"""

from __future__ import annotations

import os
import re
import stat
import tomllib
import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from texclaim import paths

KEYRING_SERVICE = "texclaim"
_SECRET_FIELD = re.compile(r"(api[_-]?key|secret|token|passw(or)?d)", re.I)


class ConfigError(Exception):
    """Usage or configuration problem; the CLI maps it to exit code 2."""


class EvidenceSettings(BaseModel):
    strategy: Literal["auto", "full", "passages"] = "auto"
    full_text_max_tokens: int = 60000
    passage_budget_tokens: int = 8000


class SourceSettings(BaseModel):
    order: list[str] = Field(
        default_factory=lambda: [
            "local",
            "cache",
            "openalex_content",
            "oa_locations",
            "arxiv",
            "abstract",
        ]
    )
    openalex_max_usd_per_run: float = 0.50
    arxiv_max_downloads_per_run: int = 30


class BudgetSettings(BaseModel):
    max_llm_usd_per_run: float = 5.00
    concurrency: int = 4


class Settings(BaseModel):
    main: str | None = None
    model: str | None = None
    report_language: Literal["auto", "en", "es"] = "auto"
    # How much text one citation is checked against: auto lets the model decide from context
    claim_scope: Literal["auto", "sentence", "two", "paragraph"] = "auto"
    fail_on: list[str] = Field(default_factory=lambda: ["contradicted", "missing_bib_entry"])
    extra_cite_commands: list[str] = Field(default_factory=list)
    pdf_dirs: list[str] = Field(default_factory=lambda: ["papers"])
    contact_email: str | None = None
    offline: bool = False
    evidence: EvidenceSettings = Field(default_factory=EvidenceSettings)
    sources: SourceSettings = Field(default_factory=SourceSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)

    def public_dict(self) -> dict[str, Any]:
        """Effective settings, safe to store (contains no secrets by construction)."""
        return self.model_dump(mode="json")


# environment variable -> dotted setting path
ENV_SETTINGS = {
    "TEXCLAIM_MODEL": "model",
    "TEXCLAIM_CONTACT_EMAIL": "contact_email",
    "TEXCLAIM_REPORT_LANGUAGE": "report_language",
    "TEXCLAIM_CLAIM_SCOPE": "claim_scope",
    "TEXCLAIM_MAX_USD": "budget.max_llm_usd_per_run",
}
ENV_SECRETS = {"openalex_api_key": "OPENALEX_API_KEY", "asta_api_key": "ASTA_API_KEY"}


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e


def _find_secret_fields(data: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            name = f"{prefix}{k}"
            if _SECRET_FIELD.search(str(k)):
                found.append(name)
            found.extend(_find_secret_fields(v, f"{name}."))
    return found


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _set_path(data: dict[str, Any], dotted: str, value: Any) -> None:
    *parents, leaf = dotted.split(".")
    for p in parents:
        data = data.setdefault(p, {})
    data[leaf] = value


def read_paper_config(paper: Path) -> dict[str, Any]:
    path = paths.paper_config_path(paper)
    data = _read_toml(path)
    bad = _find_secret_fields(data)
    if bad:
        raise ConfigError(
            f"{path} contains secret-like field(s): {', '.join(bad)}. "
            "Paper configs are committed and shared; put keys in the environment, "
            "the OS keyring or the global config instead."
        )
    return data


def read_global_config() -> dict[str, Any]:
    path = paths.global_config_path()
    if path.exists():
        try:
            if stat.S_IMODE(path.stat().st_mode) & 0o077:
                warnings.warn(
                    f"{path} is readable by other users; run `chmod 600 {path}`.",
                    stacklevel=2,
                )
        except OSError:
            pass
    return _read_toml(path)


def load_settings(
    paper: Path | None = None,
    cli: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> Settings:
    """Resolve non-secret settings. `cli` uses dotted keys and omits unset (None) values."""
    env = os.environ if env is None else env
    glob = read_global_config()
    merged: dict[str, Any] = {}
    merged = _deep_merge(merged, glob.get("defaults", {}))
    if paper is not None:
        merged = _deep_merge(merged, read_paper_config(paper))
    for var, dotted in ENV_SETTINGS.items():
        if env.get(var):
            _set_path(merged, dotted, env[var])
    for dotted, value in (cli or {}).items():
        if value is not None:
            _set_path(merged, dotted, value)
    try:
        return Settings.model_validate(merged)
    except Exception as e:  # pydantic ValidationError
        raise ConfigError(f"invalid settings: {e}") from e


def resolve_secret(
    name: str,
    cli_value: str | None = None,
    env: dict[str, str] | None = None,
) -> str | None:
    """Look up a secret (e.g. 'openalex_api_key'): CLI -> env -> keyring -> global config."""
    env = os.environ if env is None else env
    if cli_value:
        return cli_value
    var = ENV_SECRETS.get(name)
    if var and env.get(var):
        return env[var]
    try:
        import keyring  # optional extra

        value = keyring.get_password(KEYRING_SERVICE, name)
        if value:
            return value
    except Exception:  # noqa: BLE001 - keyring missing or backend unavailable
        pass
    return read_global_config().get("secrets", {}).get(name)


def require_model(settings: Settings) -> str:
    if not settings.model:
        raise ConfigError(
            "No model configured. Set TEXCLAIM_MODEL, pass --model, or add "
            'model = "<provider>/<model>" to .texclaim/config.toml.'
        )
    return settings.model
