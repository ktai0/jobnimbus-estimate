"""
End-to-end pipeline orchestrator.
Coordinates scraping, GIS queries, vision analysis, measurements, and estimates.
"""

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime

from openai import AsyncOpenAI

from config import GEMINI_API_KEY, GOOGLE_MAPS_API_KEY, OPENAI_API_KEY, OUTPUT_DIR
from models.schemas import (
    FootprintSource,
    MaterialTier,
    PitchEstimate,
    PropertyReport,
)
from pipeline.estimate import generate_estimate
from pipeline.gis import query_county_gis, query_microsoft_buildings
from pipeline.measurements import combine_measurements, compute_pitch_multiplier
from pipeline.vision import analyze_aerial, estimate_pitch, validate_with_sunroof

logger = logging.getLogger(__name__)


async def run_scraper(address: str) -> dict:
    """Run the Node.js scraper as a subprocess and return its results."""
    scraper_dir = os.path.join(os.path.dirname(__file__), "..", "scraper")
    output_base = os.path.join(os.path.dirname(__file__), "..", "output")

    env = os.environ.copy()
    env["GOOGLE_MAPS_API_KEY"] = GOOGLE_MAPS_API_KEY

    try:
        result = subprocess.run(
            ["npx", "ts-node", "src/index.ts", address],
            cwd=scraper_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.warning("Scraper stderr: %s", result.stderr[:500])

        # Find the output JSON
        safe_name = "".join(c if c.isalnum() else "_" for c in address)[:60]
        result_path = os.path.join(output_base, safe_name, "scrape_result.json")

        if os.path.exists(result_path):
            with open(result_path) as f:
                return json.load(f)
        else:
            logger.warning("Scraper output not found at %s", result_path)
            return {}

    except subprocess.TimeoutExpired:
        logger.error("Scraper timed out for address: %s", address)
        return {}
    except FileNotFoundError:
        logger.error("Node.js/npx not found. Is Node.js installed?")
        return {}


async def _geocode(address: str) -> tuple:
    """Geocode address using Google or Nominatim."""
    import httpx

    if GOOGLE_MAPS_API_KEY:
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {"address": address, "key": GOOGLE_MAPS_API_KEY}
            r = await client.get("https://maps.googleapis.com/maps/api/geocode/json", params=params)
            data = r.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                formatted = data["results"][0].get("formatted_address", address)
                return loc["lat"], loc["lng"], formatted

    # Fallback: Nominatim
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "json", "q": address, "limit": 1},
            headers={"User-Agent": "CloudNimbus/1.0"},
        )
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"]), address

    return 0, 0, address


async def _download_images(lat: float, lng: float, output_dir: str) -> dict:
    """Download satellite and street view images using Google Static APIs."""
    import httpx

    images = {"satellite": [], "streetview": []}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Satellite at zoom 20
        sat_path = os.path.join(output_dir, "satellite_z20.png")
        if not os.path.exists(sat_path):
            url = (
                f"https://maps.googleapis.com/maps/api/staticmap"
                f"?center={lat},{lng}&zoom=20&size=1280x1280&scale=2"
                f"&maptype=satellite&key={GOOGLE_MAPS_API_KEY}"
            )
            r = await client.get(url)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(sat_path, "wb") as f:
                    f.write(r.content)
        if os.path.exists(sat_path):
            images["satellite"].append(sat_path)

        # Street view from 4 headings
        for heading in [0, 90, 180, 270]:
            sv_path = os.path.join(output_dir, f"streetview_{heading}.jpg")
            if not os.path.exists(sv_path):
                url = (
                    f"https://maps.googleapis.com/maps/api/streetview"
                    f"?size=640x480&location={lat},{lng}"
                    f"&heading={heading}&pitch=15&fov=90"
                    f"&key={GOOGLE_MAPS_API_KEY}"
                )
                r = await client.get(url)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(sv_path, "wb") as f:
                        f.write(r.content)
            if os.path.exists(sv_path):
                images["streetview"].append(sv_path)

    return images


async def analyze_property(address: str) -> PropertyReport:
    """
    Full pipeline: address → measurements → estimate → report.
    """
    logger.info("=== Starting analysis for: %s ===", address)

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    # Step 1: Geocode and download images
    logger.info("Step 1: Geocoding and downloading images...")
    lat, lng, formatted_address = await _geocode(address)
    if lat == 0 and lng == 0:
        logger.error("Failed to geocode address: %s", address)

    # Create output directory
    safe_name = "".join(c if c.isalnum() else "_" for c in address)[:60]
    report_dir = os.path.join(OUTPUT_DIR, safe_name)
    os.makedirs(report_dir, exist_ok=True)

    # Try scraper first, fall back to direct API
    scrape_data = await run_scraper(address)

    if scrape_data.get("lat"):
        lat = scrape_data["lat"]
        lng = scrape_data["lng"]
        formatted_address = scrape_data.get("formattedAddress", formatted_address)

    satellite_images = scrape_data.get("satellite", {}).get("screenshots", [])
    streetview_images = scrape_data.get("streetView", {}).get("screenshots", [])
    sunroof_data = scrape_data.get("sunroof", {})
    sunroof_sqft = sunroof_data.get("sqft")
    sunroof_image = sunroof_data.get("screenshot")
    gsd = scrape_data.get("satellite", {}).get("gsdMetersPerPixel", 0.075)

    # If scraper didn't produce images, download directly
    if not satellite_images and GOOGLE_MAPS_API_KEY and lat != 0:
        logger.info("Scraper didn't produce images, downloading directly...")
        images = await _download_images(lat, lng, report_dir)
        satellite_images = images["satellite"]
        streetview_images = images["streetview"]

    # Step 2: Query GIS for building footprint (run in parallel with vision)
    logger.info("Step 2: Querying GIS + running vision analysis...")

    footprint_sources: list[FootprintSource] = []

    # Run GIS, aerial analysis, and pitch estimation in parallel
    gis_task = query_county_gis(lat, lng, address)
    msft_task = query_microsoft_buildings(lat, lng)

    async def _empty_dict() -> dict:
        return {}

    aerial_task = (
        analyze_aerial(client, satellite_images[0], gsd, lat, gemini_api_key=GEMINI_API_KEY)
        if satellite_images
        else _empty_dict()
    )

    pitch_task = estimate_pitch(client, streetview_images, gemini_api_key=GEMINI_API_KEY)

    sunroof_task = validate_with_sunroof(client, sunroof_image) if sunroof_image else _empty_dict()

    results = await asyncio.gather(
        gis_task,
        msft_task,
        aerial_task,
        pitch_task,
        sunroof_task,
        return_exceptions=True,
    )

    gis_result = results[0] if not isinstance(results[0], Exception) else None
    msft_result = results[1] if not isinstance(results[1], Exception) else None
    aerial_analysis = results[2] if not isinstance(results[2], Exception) else {}
    pitch = results[3] if not isinstance(results[3], Exception) else None
    sunroof_validation = results[4] if not isinstance(results[4], Exception) else {}

    # Handle exceptions
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("Task %d failed: %s", i, r)

    if gis_result:
        footprint_sources.append(gis_result)
    if msft_result:
        footprint_sources.append(msft_result)

    if pitch is None:
        pitch = PitchEstimate()

    # Step 3: Combine into measurements
    logger.info("Step 3: Computing measurements...")
    measurements = combine_measurements(
        footprint_sources=footprint_sources,
        pitch=pitch,
        aerial_analysis=aerial_analysis if isinstance(aerial_analysis, dict) else {},
        sunroof_usable_sqft=sunroof_sqft,
        sunroof_validation=sunroof_validation if isinstance(sunroof_validation, dict) else {},
    )

    logger.info(
        "Measurements: %.0f sqft roof area (%.0f footprint × %.3f pitch multiplier)",
        measurements.total_roof_sqft,
        measurements.footprint_sqft,
        measurements.pitch.multiplier,
    )

    # Step 4: Generate estimates for all tiers
    logger.info("Step 4: Generating estimates...")
    estimates = {}
    for tier in MaterialTier:
        estimates[tier.value] = generate_estimate(measurements, tier)

    standard = estimates["standard"]
    logger.info(
        "Standard estimate: $%.2f (materials $%.2f + labor $%.2f + other $%.2f)",
        standard.grand_total,
        standard.materials_subtotal,
        standard.labor_subtotal,
        standard.other_subtotal,
    )

    # Step 5: Build report
    report = PropertyReport(
        address=address,
        formatted_address=formatted_address,
        lat=lat,
        lng=lng,
        measurements=measurements,
        estimates=estimates,
        satellite_images=satellite_images,
        streetview_images=streetview_images,
        sunroof_image=sunroof_image,
        sunroof_usable_sqft=sunroof_sqft,
        solar_validation=None,
        report_date=datetime.now().isoformat(),
    )

    # Save report
    safe_name = "".join(c if c.isalnum() else "_" for c in address)[:60]
    report_dir = os.path.join(OUTPUT_DIR, safe_name)
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "report.json")
    with open(report_path, "w") as f:
        f.write(report.model_dump_json(indent=2))
    logger.info("Report saved to %s", report_path)

    return report


async def run_batch(addresses: list[str]) -> list[PropertyReport]:
    """Run pipeline on multiple addresses sequentially."""
    reports = []
    for addr in addresses:
        try:
            report = await analyze_property(addr)
            reports.append(report)
        except Exception as e:
            logger.error("Failed to analyze %s: %s", addr, e)
    return reports
