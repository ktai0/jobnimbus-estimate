"""
Test the pipeline against benchmark properties.
Can run with or without scraper (GIS-only mode for quick validation).

This is a thin wrapper around the eval framework for backward compatibility.
Use `just eval-gis` or `just eval` for the standard eval workflow.
"""

import asyncio
import sys

from evals.runner import run_eval

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "gis"

    if mode in ("gis", "full"):
        asyncio.run(run_eval(mode=mode, notes=f"test_pipeline.py {mode}"))
    elif mode == "test":
        asyncio.run(run_eval(mode="full", notes="test_pipeline.py test"))
    else:
        print("Usage: python test_pipeline.py [gis|full|test]")
        print("  gis  - Test GIS queries only (no API keys needed)")
        print("  full - Full pipeline on calibration properties")
        print("  test - Full pipeline on calibration properties")
