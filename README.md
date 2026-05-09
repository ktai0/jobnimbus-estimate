# CloudNimbus

Aerial roof measurement and auto-estimating platform. Address in, roof measurements + 3-tier cost estimate out.

**Python 3.12 · Next.js 16 · FastAPI · Multi-model Vision Ensemble**

## What it does

CloudNimbus takes a street address and produces:

1. **Roof measurements** — total sqft, footprint, pitch, shape, line items (ridge, hip, valley, rake, eave)
2. **3-tier cost estimates** — Economy, Standard, Premium with itemized materials + labor
3. **Confidence scoring** — cross-validated against county GIS, Microsoft Buildings, and Google Solar API

## Architecture

```
┌──────────┐     ┌──────────────────────────────────────────────┐
│ Frontend │────▶│ Backend (FastAPI)                             │
│ Next.js  │     │                                              │
└──────────┘     │  ┌────────────┐  ┌─────────┐  ┌───────────┐ │
                 │  │ Orchestrator│─▶│ GIS     │  │ Vision    │ │
                 │  └─────┬──────┘  │ County   │  │ GPT-4o    │ │
                 │        │         │ MSFT     │  │ Gemini 2.5│ │
                 │        │         │ OSM      │  └───────────┘ │
                 │        │         └─────────┘                 │
                 │        ▼                                     │
                 │  ┌────────────┐  ┌─────────┐  ┌───────────┐ │
                 │  │Measurements│─▶│ Estimate │  │ Solar API │ │
                 │  └────────────┘  └─────────┘  └───────────┘ │
                 └──────────────────────────────────────────────┘
                          │
                 ┌────────▼───────┐
                 │ Scraper        │
                 │ (Puppeteer)    │
                 │ Satellite +    │
                 │ Street View    │
                 └────────────────┘
```

## Quick start

### Prerequisites

- Python 3.12+
- Node.js 22+
- [pnpm](https://pnpm.io/) — `brew install pnpm`
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [just](https://github.com/casey/just) — `brew install just`

### Setup

```bash
cp .env.example .env   # Add your API keys
just setup             # Install Python + Node deps, set up pre-commit
just dev               # Start backend (port 8000) + frontend in parallel
```

## Project structure

```
cloudNimbus/
├── backend/
│   ├── main.py                 # FastAPI app
│   ├── config.py               # Env var loading
│   ├── models/schemas.py       # Pydantic data models
│   ├── pipeline/
│   │   ├── orchestrator.py     # End-to-end pipeline coordinator
│   │   ├── gis.py              # County GIS + MSFT Buildings + OSM
│   │   ├── vision.py           # Multi-model vision ensemble
│   │   ├── measurements.py     # Measurement engine + cross-validation
│   │   ├── estimate.py         # 3-tier cost estimation
│   │   ├── solar.py            # Solar API processing
│   │   └── sunroof_scraper.py  # Google Solar API scraper
│   ├── scraper/                # Puppeteer scraper (satellite + street view)
│   └── evals/
│       ├── benchmarks.py       # Benchmark property data
│       ├── runner.py           # Eval runner (GIS + full modes)
│       └── dashboard.py        # Streamlit eval dashboard
├── frontend/                   # Next.js 16 + React 19 + Tailwind 4
├── docs/                       # Hackathon materials + developer notes
├── pyproject.toml              # Python project manifest + tool config
├── Justfile                    # Task runner
└── output/                     # Generated reports + eval history
```

## How it works

### Multi-model vision ensemble

Pitch estimation runs **8 parallel inferences** — GPT-4o (4 temperatures) + Gemini 2.5 Pro (4 temperatures) — then takes the median. Aerial analysis uses GPT-4o + GPT-4o-mini + Gemini 2.5 Pro for roof shape and footprint detection.

### GIS cross-validation

Queries up to 3 sources in parallel (county GIS, Microsoft Building Footprints, OpenStreetMap) and weighted-averages the results. Outlier detection discards any source >2x off from others.

### Solar API blending

When Google Solar API data is available, measurements are blended toward it (60% weight for HIGH quality, 40% for MEDIUM). Pitch is refined with 70% solar weight when vision and solar disagree.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/analyze` | Start analysis for an address (returns job_id) |
| `GET` | `/api/jobs/{job_id}` | Check job status |
| `GET` | `/api/reports` | List all completed reports |
| `GET` | `/api/reports/{job_id}` | Get full report with measurements + estimates |
| `POST` | `/api/batch` | Batch analysis for multiple addresses |

## Eval suite

```bash
just eval-gis          # GIS-only eval (fast, free)
just eval              # Full eval with vision + solar
just eval-dashboard    # Launch Streamlit dashboard
```

Eval results are appended to `output/eval_history.jsonl`. The dashboard shows error trends, pitch accuracy, per-property breakdowns, and run-to-run comparisons.

Benchmark properties are defined in `backend/evals/benchmarks.py`.

## Environment variables

See `.env.example`. Required: `OPENAI_API_KEY`. Optional: `GOOGLE_MAPS_API_KEY`, `GEMINI_API_KEY`.

## Development

```bash
just lint              # Lint Python + TypeScript
just format            # Auto-format Python
just typecheck         # Run mypy
just check             # lint + typecheck (run before committing)
just clean             # Remove caches
```
