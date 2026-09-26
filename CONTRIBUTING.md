# Contributing to Puffdeploy ⚡

Thank you for your interest in contributing to Puffdeploy! We welcome contributions from the community to help make LLM and SLM deployments seamless.

---

## 🛠️ Development Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/puffdeploy.git
   cd puffdeploy
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies in editable mode with dev tools:**
   ```bash
   pip install -e ".[dev]"
   ```

---

## 🧪 Running Tests

All unit and integration tests use `pytest` and mock cloud provider APIs so you do **not** need an active AWS/GCP account to run test suites:

```bash
pytest tests/ -v
```

---

## 📝 Pull Request Guidelines

1. Create a descriptive feature branch (`git checkout -b feature/your-feature-name`).
2. Ensure all tests pass before submitting.
3. Add unit tests for any new features or bug fixes.
4. Keep PR descriptions clear and concise.
