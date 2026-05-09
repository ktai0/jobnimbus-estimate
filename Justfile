# CloudNimbus task runner
# Install: brew install just

set dotenv-load

# Start backend + frontend in parallel
dev:
    #!/usr/bin/env bash
    trap 'kill 0' EXIT
    just backend &
    just frontend &
    wait

# Start FastAPI backend with hot reload
backend:
    uv run uvicorn backend.main:app --reload --port 8000

# Start Next.js frontend dev server
frontend:
    cd frontend && pnpm dev

# Run the Puppeteer scraper for one address
scrape address:
    cd backend/scraper && npx ts-node src/index.ts "{{address}}"

# Lint Python + TypeScript
lint:
    uv run ruff check backend/
    cd frontend && pnpm lint

# Auto-format Python code
format:
    uv run ruff format backend/
    uv run ruff check --fix backend/

# Run mypy type checking
typecheck:
    uv run mypy backend/

# Run all checks (lint + typecheck) — gate before committing
check: lint typecheck

# Run eval suite against benchmark properties
eval:
    uv run python -m backend.evals.runner --mode full

# Run GIS-only eval (fast, no vision API keys needed)
eval-gis:
    uv run python -m backend.evals.runner --mode gis

# Launch the eval dashboard
eval-dashboard:
    uv run streamlit run backend/evals/dashboard.py

# Install all dependencies
setup:
    uv sync --extra dev
    cd frontend && pnpm install
    cd backend/scraper && npm install
    uv run pre-commit install

# Remove generated caches
clean:
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    rm -rf .mypy_cache .ruff_cache .pytest_cache
    rm -rf frontend/.next
