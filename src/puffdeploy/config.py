from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field

class ComputeConfig(BaseModel):
    cloud: str = "aws"
    region: str = "us-east-1"
    accelerator: Optional[str] = None  # e.g. "T4:1", "A10G:1", "L4:1"
    cpus: str = "2+"
    memory: str = "4+"
    use_spot: bool = False

class ServiceConfig(BaseModel):
    port: int = 8000
    readiness_probe: str = "/health"
    predict_path: str = "/predict"
    min_replicas: int = 1
    max_replicas: int = 1
    target_qps: Optional[int] = 10
    auto_restart: bool = True

class RuntimeConfig(BaseModel):
    app_entrypoint: str = "app:app"
    command: str = "uvicorn app:app --host 0.0.0.0 --port 8000"
    setup: Optional[str] = None

class PuffConfig(BaseModel):
    pass

# Alias for backward compatibility
VeloxConfig = PuffConfig
PuffdeployConfig = PuffConfig

class PuffConfig(BaseModel):
    name: str = Field(default="my-model-service")
    version: str = "0.1.1"
    compute: ComputeConfig = Field(default_factory=ComputeConfig)
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    @classmethod
    def load_or_default(cls, path: Path = Path("puffdeploy.yaml")) -> "VeloxConfig":
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return cls(**data)
        return cls()

    def save(self, path: Path = Path("puffdeploy.yaml")):
        data = self.model_dump(exclude_none=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, sort_keys=False, default_flow_style=False)
