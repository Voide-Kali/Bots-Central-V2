# Bots Central V2

Foundation for a future device-management and automation platform. This repository
currently contains only a modular FastAPI backend, PostgreSQL integration plumbing,
quality checks, and development infrastructure.

## Quick start

1. Copy `.env.example` to `.env` and replace the development-only password.
2. Run `docker compose up --build`.
3. Open `http://localhost:8000/api/v1/health`.

For local Python development, run commands from `backend/`:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

See `docs/CURRENT_STATE.md` for the current state and `docs/ROADMAP.md`
for the delivery plan.
