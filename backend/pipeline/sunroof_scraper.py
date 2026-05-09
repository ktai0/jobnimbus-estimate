"""
Scrape Google Project Sunroof for roof data using Playwright.
Replaces the Solar API — no API key needed, just browser automation.

Navigates directly to https://sunroof.withgoogle.com/building/{lat}/{lng}/
and extracts usable sqft, hours, and screenshots the roof overlay.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)


async def scrape_sunroof(
    lat: float,
    lng: float,
    output_dir: str = "",
) -> dict | None:
    """
    Scrape Project Sunroof for a building at the given lat/lng.

    Returns dict compatible with get_solar_insights() format:
      - whole_roof_sqft: estimated total roof area (derived from usable sqft)
      - usable_sqft: solar-viable area scraped from page
      - avg_pitch_rise: not available from scraping (returns 0)
      - avg_pitch_degrees: not available from scraping (returns 0)
      - segment_count: 0 (not available)
      - segments: []
      - quality: "SUNROOF_SCRAPE"
      - screenshot: path to roof overlay screenshot
      - sunlight_hours: hours of usable sunlight per year
      - panel_sqft: recommended panel area in sqft
      - kw_size: recommended installation size in kW
    """
    from playwright.async_api import async_playwright

    url = f"https://sunroof.withgoogle.com/building/{lat}/{lng}/"
    logger.info("Scraping Project Sunroof: %s", url)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, timeout=30000)
            # Wait for the analysis to complete
            await page.wait_for_timeout(6000)

            text = await page.inner_text("body")

            # Parse usable sqft: "2,114 sq feet available for solar panels"
            usable_sqft = 0
            sqft_match = re.search(r"([\d,]+)\s*sq\s*feet?\s*available", text, re.IGNORECASE)
            if sqft_match:
                usable_sqft = int(sqft_match.group(1).replace(",", ""))

            # Parse sunlight hours: "1,874 hours of usable sunlight"
            sunlight_hours = 0
            hours_match = re.search(r"([\d,]+)\s*hours\s*of\s*usable\s*sunlight", text, re.IGNORECASE)
            if hours_match:
                sunlight_hours = int(hours_match.group(1).replace(",", ""))

            # Parse recommended kW size: "11.2 kW"
            kw_size = 0.0
            kw_match = re.search(r"([\d.]+)\s*kW", text)
            if kw_match:
                kw_size = float(kw_match.group(1))

            # Parse panel area in sqft: "(592 ft2)" or "(592 ft²)"
            panel_sqft = 0
            panel_match = re.search(r"\(([\d,]+)\s*ft", text)
            if panel_match:
                panel_sqft = int(panel_match.group(1).replace(",", ""))

            if usable_sqft == 0 and sunlight_hours == 0:
                logger.warning(
                    "Sunroof scrape: no data found for (%.6f, %.6f). Page may show 'roof not ideal' or no coverage.",
                    lat,
                    lng,
                )
                # Check if there's at least sunlight hours (roof not ideal case)
                basic_hours = re.search(r"([\d,]+)\s*hours", text)
                if basic_hours:
                    sunlight_hours = int(basic_hours.group(1).replace(",", ""))

                if sunlight_hours == 0:
                    await browser.close()
                    return None

            # Estimate total roof area from usable sqft.
            # Sunroof "usable sqft" is typically 70-85% of total roof area
            # (excludes shaded areas, vents, chimneys, etc.)
            usable_ratio = 0.80
            whole_roof_sqft = round(usable_sqft / usable_ratio) if usable_sqft > 0 else 0

            # Take a screenshot of the roof overlay
            screenshot_path = ""
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                screenshot_path = os.path.join(output_dir, "sunroof_overlay.png")
                await page.screenshot(path=screenshot_path)
                logger.info("Sunroof screenshot saved: %s", screenshot_path)

            await browser.close()

            result = {
                "whole_roof_sqft": whole_roof_sqft,
                "usable_sqft": usable_sqft,
                "segments": [],
                "segment_count": 0,
                "avg_pitch_degrees": 0,
                "avg_pitch_rise": 0,
                "quality": "SUNROOF_SCRAPE",
                "screenshot": screenshot_path,
                "sunlight_hours": sunlight_hours,
                "panel_sqft": panel_sqft,
                "kw_size": kw_size,
            }

            logger.info(
                "Sunroof scrape: usable=%d sqft, estimated total=%d sqft, hours=%d, kW=%.1f",
                usable_sqft,
                whole_roof_sqft,
                sunlight_hours,
                kw_size,
            )

            return result

    except Exception as e:
        logger.error("Sunroof scraping failed: %s", e)
        return None
