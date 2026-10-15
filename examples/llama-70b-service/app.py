from fastapi import FastAPI
from vllm import LLM, SamplingParams

app = FastAPI()

llm = LLM(
    model="hugging-quants/Meta-Llama-3.1-70B-Instruct-AWQ-INT4",
    tensor_parallel_size=4,
    max_model_len=4096,
    quantization="awq",
)

@app.get("/health")
def health():
    return {"status": "ready"}

@app.post("/predict")
def predict(req: dict):
    prompt = req.get("prompt")
    messages = req.get("messages") or [{"role": "user", "content": prompt or "Hello"}]
    params = SamplingParams(max_tokens=req.get("max_tokens", 128), temperature=0.7)
    
    outputs = llm.chat(messages, params, use_tqdm=False)
    return {
        "response": outputs[0].outputs[0].text.strip(),
        "tokens": len(outputs[0].outputs[0].token_ids),
    }
