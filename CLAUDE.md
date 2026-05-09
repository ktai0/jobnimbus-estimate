@AGENTS.md

## Claude Code Specific

- Use `just` commands for all operations
- Always run `just lint` before suggesting a commit
- When modifying Python code, run `just typecheck` to verify
- Backend imports are relative to `backend/` (e.g., `from config import ...`)
- Run `just format` to auto-fix style issues before manual edits
- Eval framework lives in `backend/evals/` — use `just eval-gis` for quick validation
