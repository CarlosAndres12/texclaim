import pytest

from texclaim import paths
from texclaim.config import ConfigError, load_settings, require_model, resolve_secret


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o600)


def test_defaults(tmp_path):
    s = load_settings(tmp_path)
    assert s.model is None
    assert s.budget.max_llm_usd_per_run == 5.0
    assert s.report_language == "auto"


def test_precedence_matrix(tmp_path):
    # default < global < paper < env < cli
    write(paths.global_config_path(), '[defaults]\nmodel = "g/model"\nreport_language = "es"\n')
    assert load_settings(tmp_path).model == "g/model"
    write(paths.paper_config_path(tmp_path), 'model = "p/model"\n')
    s = load_settings(tmp_path)
    assert s.model == "p/model"
    assert s.report_language == "es"  # global still applies where paper is silent
    assert load_settings(tmp_path, env={"TEXCLAIM_MODEL": "e/model"}).model == "e/model"
    s = load_settings(tmp_path, cli={"model": "c/model"}, env={"TEXCLAIM_MODEL": "e/model"})
    assert s.model == "c/model"


def test_cli_none_does_not_override(tmp_path):
    write(paths.paper_config_path(tmp_path), 'model = "p/model"\n')
    assert load_settings(tmp_path, cli={"model": None}).model == "p/model"


def test_nested_merge(tmp_path):
    write(paths.paper_config_path(tmp_path), "[budget]\nconcurrency = 8\n")
    s = load_settings(tmp_path, cli={"budget.max_llm_usd_per_run": 1.0})
    assert s.budget.concurrency == 8
    assert s.budget.max_llm_usd_per_run == 1.0


@pytest.mark.parametrize("field", ["openalex_api_key", "api_key", "[secrets]\nx = 1\n# "])
def test_secret_in_paper_config_refused(tmp_path, field):
    text = f'{field} = "sk-123"\n' if not field.startswith("[") else "[sk]\ntoken = 'x'\n"
    write(paths.paper_config_path(tmp_path), text)
    with pytest.raises(ConfigError, match="secret"):
        load_settings(tmp_path)


def test_secret_order(tmp_path):
    write(paths.global_config_path(), '[secrets]\nopenalex_api_key = "global"\n')
    assert resolve_secret("openalex_api_key", env={}) == "global"
    assert resolve_secret("openalex_api_key", env={"OPENALEX_API_KEY": "env"}) == "env"
    assert resolve_secret("openalex_api_key", "cli", env={"OPENALEX_API_KEY": "env"}) == "cli"


def test_require_model(tmp_path):
    with pytest.raises(ConfigError, match="TEXCLAIM_MODEL"):
        require_model(load_settings(tmp_path))


def test_invalid_toml(tmp_path):
    write(paths.paper_config_path(tmp_path), "model = ")
    with pytest.raises(ConfigError):
        load_settings(tmp_path)
