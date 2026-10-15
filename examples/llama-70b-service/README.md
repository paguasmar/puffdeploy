# Llama 3.1 70B Inference Service 🐡

Production-grade deployment of **Meta-Llama-3.1-70B-Instruct** (AWQ 4-bit) running on **AWS EC2 Spot** with **4x NVIDIA A10G GPUs (96 GB VRAM total)** via `vLLM` and **Puffdeploy**.

---

## ⚡ Specifications

- **Model:** `hugging-quants/Meta-Llama-3.1-70B-Instruct-AWQ-INT4` (Un-gated, no HuggingFace token needed).
- **Inference Engine:** `vLLM` with `tensor_parallel_size=4` across 4x A10G GPUs.
- **Instance Type:** AWS EC2 `g5.12xlarge` (48 vCPUs, 192 GB RAM, 4x NVIDIA A10G 24GB).
- **Cost:** **~$1.80 – $2.10/hour** on AWS Spot (~70% discount vs On-Demand ~$5.67/hr, or $0 with AWS Activate credits).
- **Throughput:** ~35–45 tokens/second.

---

## 🚀 One-Command Deployment

From this directory:

```bash
puff deploy
```

Puffdeploy will:
1. Provision a `g5.12xlarge` Spot instance in `us-east-1`.
2. Configure CUDA drivers, PyTorch, and `vLLM`.
3. Distribute the 70B model across all 4 GPUs.
4. Pass the readiness probe (`/health`) and print your live HTTPS/HTTP cURL endpoint.

---

## 🧪 Test Your Endpoint

```bash
curl -X POST http://<ENDPOINT>:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain Quantum Computing in 3 bullet points", "max_tokens": 150}'
```

---

## 🛑 Clean Teardown ($0 Cost)

```bash
puff down --all
```
