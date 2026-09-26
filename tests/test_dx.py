from typer.testing import CliRunner
from puffdeploy.cli import app
from puffdeploy.orchestrator.skypilot import SkyPilotOrchestrator

runner = CliRunner()

def test_cli_status_clean_output(monkeypatch):
    monkeypatch.setattr(SkyPilotOrchestrator, "list_services", lambda: [])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No active Puffdeploy services" in result.stdout

def test_cli_status_with_services(monkeypatch):
    mock_services = [{
        "name": "smollm-test",
        "version": "1",
        "uptime": "5m",
        "status": "READY",
        "replicas": "1/1",
        "endpoint": "http://1.2.3.4:8000",
    }]
    monkeypatch.setattr(SkyPilotOrchestrator, "list_services", lambda: mock_services)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "smollm-test" in result.stdout
    assert "READY" in result.stdout

def test_cli_down_all_flag(monkeypatch):
    calls = []
    def mock_teardown(self, purge_all=False):
        calls.append(purge_all)
    monkeypatch.setattr(SkyPilotOrchestrator, "teardown", mock_teardown)
    
    result = runner.invoke(app, ["down", "--name", "test-svc", "--all"])
    assert result.exit_code == 0
    assert calls == [True]

def test_cli_check_success(monkeypatch):
    monkeypatch.setattr(SkyPilotOrchestrator, "check_cloud", lambda: True)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "AWS Connected & Verified" in result.stdout
    assert "All systems operational" in result.stdout

def test_cli_check_failure(monkeypatch):
    monkeypatch.setattr(SkyPilotOrchestrator, "check_cloud", lambda: False)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "Cloud Credentials Not Found" in result.stdout
    assert "aws configure" in result.stdout

def test_cli_logs_command(monkeypatch):
    logs_called = []
    def mock_get_logs(name, tail=100, follow=False):
        logs_called.append((name, tail, follow))
    monkeypatch.setattr(SkyPilotOrchestrator, "get_service_logs", mock_get_logs)
    
    result = runner.invoke(app, ["logs", "my-test-service", "--tail", "50"])
    assert result.exit_code == 0
    assert "Fetching logs for service 'my-test-service'" in result.stdout
    assert logs_called == [("my-test-service", 50, False)]

def test_cli_status_warming_up(monkeypatch):
    mock_services = [{
        "name": "smollm-test",
        "version": "1",
        "uptime": "1m",
        "status": "WARMING_UP",
        "replicas": "0/1",
        "endpoint": "http://1.2.3.4:30001",
    }]
    monkeypatch.setattr(SkyPilotOrchestrator, "list_services", lambda: mock_services)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "smollm-test" in result.stdout
    assert "WARMING_UP" in result.stdout
