"""
Quick calibration: test vision pitch estimation against known values
using existing downloaded images. No scraper needed.

This is a thin wrapper around the eval framework for backward compatibility.
Use `just eval` or `python -m backend.evals.runner` for the full eval suite.
"""

import asyncio
import sys

from evals.runner import run_eval

if __name__ == "__main__":
    notes = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "calibration run"
    asyncio.run(run_eval(mode="full", notes=notes))
