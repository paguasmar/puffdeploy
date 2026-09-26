from pathlib import Path
from typing import Dict, Any

class Packager:
    @staticmethod
    def detect_project_type(workdir: Path = Path(".")) -> str:
        if (workdir / "config.yaml").exists() and (workdir / "model").exists():
            return "truss"
        if (workdir / "app.py").exists() or (workdir / "main.py").exists():
            return "fastapi"
        return "generic"

    @staticmethod
    def scaffold_starter_project(target_dir: Path, name: str):
        target_dir.mkdir(parents=True, exist_ok=True)
        
        app_py = target_dir / "app.py"
        if not app_py.exists():
            app_py.write_text("""from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Puffdeploy Model Service")

class PredictRequest(BaseModel):
    prompt: str

class PredictResponse(BaseModel):
    response: str
    tokens: int

@app.get("/health")
def health():
    return {"status": "ok", "service": "live"}

@app.post("/predict")
def predict(req: PredictRequest):
    # Model inference logic goes here
    return {
        "response": f"Echo: {req.prompt} (Processed by Puffdeploy in AWS VPC)",
        "tokens": len(req.prompt.split())
    }
""")

        reqs = target_dir / "requirements.txt"
        if not reqs.exists():
            reqs.write_text("fastapi>=0.110.0\nuvicorn>=0.29.0\npydantic>=2.7.0\n")
