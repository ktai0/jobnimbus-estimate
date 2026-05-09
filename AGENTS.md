# AGENTS.md — CloudNimbus

Instructions for AI coding agents (Claude Code, Codex, Cursor).

## Architecture

Three components, one repo:

| Component | Language | Entry point |
|-----------|----------|-------------|
| **Backend** | Python 3.12 / FastAPI | `backend/main.py` |
| **Frontend** | TypeScript / Next.js 16 | `frontend/app/` |
| **Scraper** | TypeScript / Puppeteer | `scraper/src/index.ts` |

Data flow: Frontend → Backend API → (Scraper + GIS + Vision LLMs + Solar API) → Measurements → Cost Estimate → Report

## Before you code

1. Run `just format` to auto-fix formatting
2. Run `just check` (lint + typecheck) before committing
3. Commit frequently with descriptive messages
4. Never commit `.env`, API keys, or large binaries

## Python style

- **Python 3.12+** syntax: `list[X]` not `List[X]`, `X | None` not `Optional[X]`
- **Import order**: stdlib → third-party → local (enforced by ruff isort)
- **Local imports**: bare `from config import ...`, `from models.schemas import ...`, `from pipeline.gis import ...` (backend/ is the import root)
- **Async/await** for all I/O operations (HTTP calls, file I/O in pipeline)
- **Structured logging**: `logger = logging.getLogger(__name__)`, use `logger.info/warning/error`
- **Pydantic models** live in `backend/models/schemas.py`
- **Line length**: 120 chars (ruff enforced)
- **Linter rules**: E, F, W, I, UP, B, SIM, N (ruff)

## TypeScript style

- **Strict mode** enabled in both frontend and scraper
- **Next.js App Router** (frontend/app/ directory)
- **ESLint** for linting: `cd frontend && npx eslint .`
- **Tailwind CSS 4** for styling

## Environment variables

- `.env` at project root, loaded by `python-dotenv` in `backend/config.py`
- Required: `OPENAI_API_KEY`
- Optional: `GOOGLE_MAPS_API_KEY`, `GEMINI_API_KEY`
- Reference `.env.example` for all available vars
- Never commit `.env`

## Testing / Evals

- `just eval-gis` — fast GIS-only eval, no API keys needed for vision
- `just eval` — full eval with vision + solar (costs API credits)
- `just eval-dashboard` — Streamlit dashboard for eval history visualization
- Benchmark data: `backend/evals/benchmarks.py` (single source of truth)
- Eval results: `output/eval_history.jsonl` (append-only)

## Common tasks

### Add a new pipeline step
1. Create module in `backend/pipeline/`
2. Wire into `backend/pipeline/orchestrator.py` `analyze_property()`
3. Add to the parallel `asyncio.gather` block if independent

### Add a new API endpoint
1. Add route in `backend/main.py`
2. Add Pydantic request/response models if needed

### Add a new measurement source
1. Add `FootprintSource` in the relevant pipeline module
2. Measurements engine (`backend/pipeline/measurements.py`) handles weighting automatically

### Update cost estimates
1. Edit pricing tables in `backend/pipeline/estimate.py`

### Add a benchmark property
1. Add to `CALIBRATION_PROPERTIES` or `TEST_PROPERTIES` in `backend/evals/benchmarks.py`
2. Run `just eval-gis` to verify
