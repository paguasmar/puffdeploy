from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Puffdeploy AWS Live Test")

class PromptRequest(BaseModel):
    prompt: str

@app.get("/health")
def health():
    return {"status": "ok", "cloud": "AWS", "provider": "Puffdeploy"}

@app.post("/predict")
def predict(req: PromptRequest):
    return {
        "output": f"Live response from AWS VPC: '{req.prompt}'",
        "processed_by": "Puffdeploy CLI MVP",
        "status": "success"
    }
