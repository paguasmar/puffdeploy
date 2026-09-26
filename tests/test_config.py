import tempfile
from pathlib import Path
from puffdeploy.config import PuffConfig
VeloxConfig = PuffConfig

def test_default_config():
    config = VeloxConfig()
    assert config.name == "my-model-service"
    assert config.compute.cloud == "aws"
    assert config.compute.region == "us-east-1"
    assert config.service.port == 8000

def test_save_and_load_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "puffdeploy.yaml"
        cfg = VeloxConfig(name="custom-model")
        cfg.compute.accelerator = "T4:1"
        cfg.save(config_path)

        loaded = VeloxConfig.load_or_default(config_path)
        assert loaded.name == "custom-model"
        assert loaded.compute.accelerator == "T4:1"

def test_orchestrator_generate_spec():
    from puffdeploy.orchestrator.skypilot import SkyPilotOrchestrator
    cfg = VeloxConfig(name="test-spec")
    cfg.runtime.setup = "pip install fastapi"
    orch = SkyPilotOrchestrator(cfg)
    spec = orch.generate_skyserve_spec()
    assert spec["resources"]["cloud"] == "aws"
    assert spec["service"]["replica_policy"]["min_replicas"] == 1
    assert "pip install fastapi" in spec["setup"]
    assert spec["run"] == "uvicorn app:app --host 0.0.0.0 --port 8000"
