from typer.testing import CliRunner
from puffdeploy.cli import app

runner = CliRunner()

def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "Puffdeploy CLI" in result.stdout

def test_help_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.stdout
    assert "deploy" in result.stdout
    assert "down" in result.stdout
