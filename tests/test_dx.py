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
    def mock_get_logs(name, tail=100, follow=False, replica="1"):
        logs_called.append((name, tail, follow, replica))
    monkeypatch.setattr(SkyPilotOrchestrator, "get_service_logs", mock_get_logs)
    
    result = runner.invoke(app, ["logs", "my-test-service", "--tail", "50"])
    assert result.exit_code == 0
    assert "Fetching logs for service 'my-test-service'" in result.stdout
    assert logs_called == [("my-test-service", 50, False, "1")]

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


def test_capacity_bottleneck_box():
    from puffdeploy.ui.console import print_capacity_bottleneck_box, console
    # Test rendering without errors
    print_capacity_bottleneck_box("us-east-1", ["puff deploy --gpu L4:4", "puff deploy --region eu-north-1"])


def test_check_capacity_bottleneck_explicit_error():
    from puffdeploy.config import PuffConfig
    orchestrator = SkyPilotOrchestrator(PuffConfig())
    # Status with explicit AWS capacity error
    mock_status = '''
Services
NAME               VERSION  UPTIME  STATUS      REPLICAS
my-service         -        -       NO_REPLICA  0/1
Service Replicas
my-service  1  1  -  10s  AWS (us-east-1a)  InsufficientInstanceCapacity: We currently do not have sufficient capacity
'''
    assert orchestrator.check_capacity_bottleneck("my-service", status_output=mock_status, elapsed=30) is True


def test_check_capacity_bottleneck_2min_timeout():
    from puffdeploy.config import PuffConfig
    orchestrator = SkyPilotOrchestrator(PuffConfig())
    # Status stuck in NO_REPLICA without instances
    mock_status = '''
Services
NAME               VERSION  UPTIME  STATUS      REPLICAS
my-service         -        -       NO_REPLICA  0/1
Service Replicas
my-service  1  1  -  125s  AWS (us-east-1a)  FAILED
'''
    # Under 2 minutes (e.g. 60s) -> should NOT trigger timeout yet
    assert orchestrator.check_capacity_bottleneck("my-service", status_output=mock_status, elapsed=60) is False

    # At or over 2 minutes (120s) with no active replica -> MUST trigger fail-fast!
    assert orchestrator.check_capacity_bottleneck("my-service", status_output=mock_status, elapsed=120) is True

def test_check_capacity_bottleneck_provisioning_not_killed():
    from puffdeploy.config import PuffConfig
    orchestrator = SkyPilotOrchestrator(PuffConfig())
    # Replica is actively bootstrapping in AWS (PROVISIONING)
    mock_status = '''
Services
NAME               VERSION  UPTIME  STATUS      REPLICAS
my-service         -        -       NO_REPLICA  0/1
Service Replicas
my-service  1  1  -  140s  AWS (eu-central-1a)  PROVISIONING
'''
    # Even past 120s, a PROVISIONING node must NOT be killed as a capacity bottleneck
    assert orchestrator.check_capacity_bottleneck("my-service", status_output=mock_status, elapsed=140) is False


def test_check_capacity_bottleneck_healthy_ready():
    from puffdeploy.config import PuffConfig
    orchestrator = SkyPilotOrchestrator(PuffConfig())
    mock_status = '''
Services
NAME               VERSION  UPTIME  STATUS      REPLICAS
my-service         1        5m      READY       1/1
Service Replicas
my-service  1  1  http://1.2.3.4:8000  5m  AWS  READY
'''
    # Even past 120s, if it is READY, it must NOT trigger bottleneck!
    assert orchestrator.check_capacity_bottleneck("my-service", status_output=mock_status, elapsed=150) is False
