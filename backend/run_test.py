"""
Run measurements on benchmark properties.

This is a thin wrapper around the eval framework for backward compatibility.
Use `just eval` or `python -m backend.evals.runner --mode full` for the standard workflow.
"""

import asyncio
import sys

from evals.runner import run_eval

if __name__ == "__main__":
    notes = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "run_test.py"
    asyncio.run(run_eval(mode="full", notes=notes))
