"""
Eval runner: run the pipeline against benchmark properties and persist results.

Usage:
    python -m backend.evals.runner [--mode gis|full] [--notes "description"]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime

# Ensure backend/ is on sys.path so bare imports (config, models, pipeline) resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from config import GEMINI_API_KEY, OPENAI_API_KEY  # noqa: E402
from evals.benchmarks import CALIBRATION_PROPERTIES, BenchmarkProperty  # noqa: E402
from models.schemas import FootprintSource, PitchEstimate  # noqa: E402
from pipeline.gis import query_county_gis, query_microsoft_buildings  # noqa: E402
from pipeline.measurements import combine_measurements, compute_pitch_multiplier  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")
HISTORY_PATH = os.path.join(OUTPUT_DIR, "eval_history.jsonl")


def _git_sha() -> str:
    """Get current git short SHA, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _append_jsonl(record: dict) -> None:
    """Append a JSON record to the eval history file."""
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


async def _run_gis_eval(
    prop: BenchmarkProperty,
    run_id: str,
    git_sha: str,
    notes: str,
) -> dict | None:
    """Run GIS-only eval for a single property."""
    ref_avg = prop.ref_avg
    if ref_avg is None:
        logger.warning("Skipping %s: no reference measurements", prop.name)
        return None

    start = time.monotonic()

    # Query GIS + Microsoft Buildings in parallel
    gis_result, msft_result = await asyncio.gather(
        query_county_gis(prop.lat, prop.lng, prop.address),
        query_microsoft_buildings(prop.lat, prop.lng),
    )

    footprint_sources: list[FootprintSource] = []
    sources_used: list[str] = []
    if gis_result:
        footprint_sources.append(gis_result)
        sources_used.append(gis_result.source)
    if msft_result:
        footprint_sources.append(msft_result)
        sources_used.append("microsoft_buildings")

    if not footprint_sources:
        logger.warning("No footprint data for %s", prop.name)
        return None

    # Use known pitch
    assert prop.known_rise is not None
    assert prop.known_pitch is not None
    multiplier = compute_pitch_multiplier(prop.known_rise)
    pitch = PitchEstimate(
        pitch=prop.known_pitch,
        rise=prop.known_rise,
        run=12,
        multiplier=multiplier,
        confidence=0.95,
    )

    measurements = combine_measurements(
        footprint_sources=footprint_sources,
        pitch=pitch,
        aerial_analysis={},
        sunroof_usable_sqft=None,
        sunroof_validation={},
    )

    duration = time.monotonic() - start
    our_sqft = measurements.total_roof_sqft
    error_pct = abs(our_sqft - ref_avg) / ref_avg * 100
    pitch_correct = True  # We used the known pitch

    result = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "notes": notes,
        "property": prop.name,
        "address": prop.address,
        "ref_avg_sqft": ref_avg,
        "measured_sqft": round(our_sqft),
        "error_pct": round(error_pct, 1),
        "pitch_detected": prop.known_pitch,
        "pitch_expected": prop.known_pitch,
        "pitch_correct": pitch_correct,
        "confidence": measurements.confidence,
        "footprint_sqft": round(measurements.footprint_sqft),
        "sources_used": sources_used,
        "duration_seconds": round(duration, 1),
    }

    print(f"  {prop.name:20s}: {our_sqft:.0f} sqft (ref {ref_avg:.0f}), error {error_pct:.1f}%")
    return result


async def _run_full_eval(
    prop: BenchmarkProperty,
    run_id: str,
    git_sha: str,
    notes: str,
) -> dict | None:
    """Run full pipeline eval for a single property (GIS + vision + solar)."""
    from openai import AsyncOpenAI

    from pipeline.vision import analyze_aerial, estimate_pitch

    ref_avg = prop.ref_avg
    if ref_avg is None:
        logger.warning("Skipping %s: no reference measurements", prop.name)
        return None

    start = time.monotonic()
    prop_dir = os.path.join(OUTPUT_DIR, prop.name)

    # Find existing images
    streetview_images = []
    sat_image = os.path.join(prop_dir, "satellite_z20.png")
    if os.path.isdir(prop_dir):
        streetview_images = sorted(
            [
                os.path.join(prop_dir, f)
                for f in os.listdir(prop_dir)
                if f.startswith("streetview_") and f.endswith(".jpg")
            ]
        )

    # Query GIS + Microsoft in parallel
    gis_result, msft_result = await asyncio.gather(
        query_county_gis(prop.lat, prop.lng, prop.address),
        query_microsoft_buildings(prop.lat, prop.lng),
    )

    footprint_sources: list[FootprintSource] = []
    sources_used: list[str] = []
    if gis_result:
        footprint_sources.append(gis_result)
        sources_used.append(gis_result.source)
    if msft_result:
        footprint_sources.append(msft_result)
        sources_used.append("microsoft_buildings")

    # Vision pitch estimation
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    if streetview_images:
        detected_pitch = await estimate_pitch(client, streetview_images, gemini_api_key=GEMINI_API_KEY)
    else:
        detected_pitch = PitchEstimate()

    # Aerial analysis
    aerial_analysis = {}
    if os.path.exists(sat_image):
        gsd = 0.075
        aerial_analysis = await analyze_aerial(client, sat_image, gsd, prop.lat, gemini_api_key=GEMINI_API_KEY)

    # Compute measurements
    measurements = combine_measurements(
        footprint_sources=list(footprint_sources),
        pitch=detected_pitch,
        aerial_analysis=aerial_analysis,
        sunroof_usable_sqft=None,
        sunroof_validation={},
    )

    duration = time.monotonic() - start
    our_sqft = measurements.total_roof_sqft
    error_pct = abs(our_sqft - ref_avg) / ref_avg * 100
    pitch_correct = prop.known_rise is not None and detected_pitch.rise == prop.known_rise

    result = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "notes": notes,
        "property": prop.name,
        "address": prop.address,
        "ref_avg_sqft": ref_avg,
        "measured_sqft": round(our_sqft),
        "error_pct": round(error_pct, 1),
        "pitch_detected": detected_pitch.pitch,
        "pitch_expected": prop.known_pitch,
        "pitch_correct": pitch_correct,
        "confidence": measurements.confidence,
        "footprint_sqft": round(measurements.footprint_sqft),
        "sources_used": sources_used,
        "duration_seconds": round(duration, 1),
    }

    pitch_tag = "OK" if pitch_correct else "WRONG"
    print(
        f"  {prop.name:20s}: {our_sqft:.0f} sqft (ref {ref_avg:.0f}), "
        f"error {error_pct:.1f}%, pitch {detected_pitch.pitch} [{pitch_tag}]"
    )
    return result


async def run_eval(mode: str = "gis", notes: str = "") -> None:
    """Run eval suite and persist results."""
    run_id = str(uuid.uuid4())[:8]
    git_sha = _git_sha()
    timestamp = datetime.now(UTC).isoformat()

    print(f"\n{'=' * 60}")
    print(f"Eval run: {run_id} | mode: {mode} | git: {git_sha}")
    if notes:
        print(f"Notes: {notes}")
    print(f"{'=' * 60}")

    eval_fn = _run_full_eval if mode == "full" else _run_gis_eval
    results: list[dict] = []
    total_start = time.monotonic()

    for prop in CALIBRATION_PROPERTIES:
        result = await eval_fn(prop, run_id, git_sha, notes)
        if result:
            results.append(result)
            _append_jsonl(result)

    total_duration = time.monotonic() - total_start

    if not results:
        print("\nNo results to summarize.")
        return

    # Compute summary
    avg_error = sum(r["error_pct"] for r in results) / len(results)
    pitch_accuracy = sum(1 for r in results if r["pitch_correct"]) / len(results)

    summary = {
        "run_id": run_id,
        "timestamp": timestamp,
        "git_sha": git_sha,
        "notes": notes,
        "type": "summary",
        "mode": mode,
        "avg_error_pct": round(avg_error, 1),
        "pitch_accuracy": round(pitch_accuracy, 2),
        "properties_evaluated": len(results),
        "total_duration_seconds": round(total_duration, 1),
    }
    _append_jsonl(summary)

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Average error:    {avg_error:.1f}%")
    print(f"  Pitch accuracy:   {pitch_accuracy:.0%}")
    print(f"  Properties:       {len(results)}")
    print(f"  Duration:         {total_duration:.1f}s")
    print(f"  Results saved to: {HISTORY_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudNimbus eval runner")
    parser.add_argument("--mode", choices=["gis", "full"], default="gis", help="Eval mode (default: gis)")
    parser.add_argument("--notes", default="", help="Optional notes for this eval run")
    args = parser.parse_args()
    asyncio.run(run_eval(mode=args.mode, notes=args.notes))


if __name__ == "__main__":
    main()
