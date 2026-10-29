from typer.testing import CliRunner

import texclaim
from texclaim.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == texclaim.__version__


def test_stub_commands_exist() -> None:
    for cmd in ["init", "check", "fetch", "status", "show", "clean", "cache", "doctor"]:
        assert runner.invoke(app, [cmd, "--help"]).exit_code == 0
