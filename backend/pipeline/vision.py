"""
Vision analysis for roof measurements.
Multi-model ensemble: Gemini 2.5 Pro + GPT-4o for maximum accuracy.
"""

import asyncio
import base64
import json
import logging
import math
from pathlib import Path
from typing import Any

from models.schemas import PitchEstimate

logger = logging.getLogger(__name__)


def _encode_image_b64(image_path: str) -> tuple[str, str]:
    """Read image file and return (base64_string, mime_type)."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    ext = Path(image_path).suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return b64, mime


def _openai_image(image_path: str) -> dict:
    """Create an OpenAI image_url message part."""
    b64, mime = _encode_image_b64(image_path)
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
    }


def _parse_json(text: str) -> dict:
    """Parse JSON from LLM response, stripping markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Gemini backend helpers
# ---------------------------------------------------------------------------


def _init_gemini(api_key: str):
    """Lazily initialize Gemini client."""
    from google import genai

    return genai.Client(api_key=api_key)


async def _gemini_vision_call(
    gemini_client,
    model: str,
    prompt: str,
    image_paths: list[str],
    temperature: float = 0.1,
    max_tokens: int = 1000,
) -> dict:
    """Call Gemini vision model and return parsed JSON."""
    from google.genai import types

    parts = [{"text": prompt}]
    for img_path in image_paths:
        b64, mime = _encode_image_b64(img_path)
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})

    # Gemini 2.5 Pro uses thinking mode by default — thinking tokens count
    # against max_output_tokens. Need 8192+ to leave room for actual response.
    effective_max = max(max_tokens, 8192)
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=effective_max,
    )

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: gemini_client.models.generate_content(
            model=model,
            contents=[{"parts": parts}],
            config=config,
        ),
    )
    text = response.text or "{}"
    return _parse_json(text)


async def _openai_vision_call(
    client: Any,
    model: str,
    prompt: str,
    image_paths: list[str],
    temperature: float = 0.1,
    max_tokens: int = 1000,
) -> dict:
    """Call OpenAI vision model and return parsed JSON."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for img_path in image_paths:
        content.append(_openai_image(img_path))

    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    text = response.choices[0].message.content or "{}"
    return _parse_json(text)


# ---------------------------------------------------------------------------
# Aerial footprint analysis (multi-model ensemble)
# ---------------------------------------------------------------------------

_AERIAL_PROMPT_TEMPLATE = """This is a satellite/aerial image showing residential buildings. Analyze the main building's roof near the center.

CRITICAL MEASUREMENT INFO:
- This image is 1280x1280 pixels
- Each pixel = approximately {gsd_ft:.3f} feet
- Total image coverage: approximately {image_ft:.0f} x {image_ft:.0f} feet
- A typical US residential house is 30-60 feet wide and 30-80 feet deep

TO MEASURE THE ROOF FOOTPRINT:
1. Identify the roof outline of the MAIN building near center
2. Estimate the roof's width in pixels, then multiply by {gsd_ft:.3f} ft/pixel to get width in feet
3. Estimate the roof's depth in pixels, then multiply by {gsd_ft:.3f} ft/pixel to get depth in feet
4. Footprint = width x depth (adjust for non-rectangular shapes)
5. Typical residential footprints range from 1000-4000 sqft. If your estimate is below 800, you are likely measuring wrong.

Also identify:
- Roof type (gable, hip, cross-gable, cross-hip, etc.)
- Number of roof planes/facets
- Approximate lengths of ridge, hip, valley, rake, and eave edges in feet
- Building width and depth in feet (for aspect ratio)

Return ONLY valid JSON:
{{"footprint_sqft": <number>, "width_ft": <number>, "depth_ft": <number>, "roof_shape": "<type>", "facet_count": <n>, "ridge_length_ft": <n>, "hip_length_ft": <n>, "valley_length_ft": <n>, "rake_length_ft": <n>, "eave_length_ft": <n>, "flashing_length_ft": <n>, "step_flashing_length_ft": <n>, "confidence": <0-1>, "notes": "<brief>"}}"""


async def analyze_aerial(
    openai_client: Any,
    satellite_image: str,
    gsd_meters_per_pixel: float,
    lat: float,
    gemini_api_key: str = "",
) -> dict:
    """
    Analyze satellite/aerial image for roof geometry using multi-model ensemble.
    Runs Gemini 2.5 Pro and GPT-4o in parallel, takes median footprint.
    """
    gsd_ft = gsd_meters_per_pixel * 3.28084
    image_ft = 1280 * gsd_ft
    prompt = _AERIAL_PROMPT_TEMPLATE.format(gsd_ft=gsd_ft, image_ft=image_ft)

    tasks = []
    task_labels = []

    # GPT-4o
    async def _run_openai():
        try:
            return await _openai_vision_call(
                openai_client,
                "gpt-4o",
                prompt,
                [satellite_image],
                temperature=0.1,
                max_tokens=1000,
            )
        except Exception as e:
            logger.warning("GPT-4o aerial analysis failed: %s", e)
            return None

    # GPT-4o-mini (cheap second opinion)
    async def _run_openai_mini():
        try:
            return await _openai_vision_call(
                openai_client,
                "gpt-4o-mini",
                prompt,
                [satellite_image],
                temperature=0.1,
                max_tokens=1000,
            )
        except Exception as e:
            logger.warning("GPT-4o-mini aerial analysis failed: %s", e)
            return None

    tasks.append(_run_openai())
    task_labels.append("gpt-4o")
    tasks.append(_run_openai_mini())
    task_labels.append("gpt-4o-mini")

    # Gemini 2.5 Pro (run twice for more votes)
    if gemini_api_key:
        for i in range(2):

            async def _run_gemini(_i=i):
                try:
                    gemini = _init_gemini(gemini_api_key)
                    return await _gemini_vision_call(
                        gemini,
                        "gemini-2.5-pro",
                        prompt,
                        [satellite_image],
                        temperature=0.1,
                        max_tokens=1000,
                    )
                except Exception as e:
                    logger.warning("Gemini 2.5 Pro aerial analysis (run %d) failed: %s", _i, e)
                    return None

            tasks.append(_run_gemini())
            task_labels.append(f"gemini-2.5-pro-{i}")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect valid results
    valid_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("Aerial task %s raised exception: %s", task_labels[i], r)
            continue
        if r is None:
            continue
        sqft = r.get("footprint_sqft", 0)
        if sqft and sqft > 0:
            valid_results.append(r)
            logger.info("Aerial estimate (%s): %.0f sqft, shape=%s", task_labels[i], sqft, r.get("roof_shape", "?"))

    if not valid_results:
        logger.error("All aerial analysis models failed")
        return {}

    # Take median footprint and use the result closest to median for line items
    footprints = sorted([r["footprint_sqft"] for r in valid_results])
    median_sqft = footprints[len(footprints) // 2]

    best = min(valid_results, key=lambda r: abs(r["footprint_sqft"] - median_sqft))
    best["footprint_sqft"] = median_sqft
    best["ensemble_count"] = len(valid_results)
    best["ensemble_footprints"] = footprints

    logger.info(
        "Aerial ensemble: %d models, footprints=%s, median=%.0f sqft",
        len(valid_results),
        footprints,
        median_sqft,
    )

    return best


# ---------------------------------------------------------------------------
# Pitch estimation (multi-model ensemble)
# ---------------------------------------------------------------------------

_PITCH_PROMPT = """You are a professional roofing estimator analyzing a residential building from street-level photos to determine the roof pitch.

CRITICAL: Measure the ANGLE of the roof slope carefully. Most people underestimate pitch.

## How to visually estimate pitch:
1. Find where the roof meets the wall (eave line) and trace up to the ridge
2. The RISE is the vertical height from eave to ridge
3. The RUN is the horizontal distance from the wall to the ridge (roughly half the building width for a gable)
4. Pitch = rise:run (normalized to 12 run)

## Visual calibration guide:
- 4:12 = 18.4 deg — Almost flat-looking. Ranch-style homes. Roof barely slopes. You can almost see the roof surface from ground level.
- 5:12 = 22.6 deg — Slight slope. Still a gentle angle. Common in warm climates (FL, TX coast).
- 6:12 = 26.6 deg — Moderate slope. MOST COMMON in US residential. The triangle of the gable end is noticeable but not dramatic.
- 7:12 = 30.3 deg — Steeper. Gable triangle is clearly visible and prominent.
- 8:12 = 33.7 deg — Steep. The roof takes up a significant portion of the building's visual profile. Common in areas with snow (CO, IL, MO, VA). The gable triangle is tall.
- 9:12 = 36.9 deg — Very steep. Roof dominates the view. Colonial/traditional style.
- 10:12 = 39.8 deg — Near 40 degrees. Dramatic steep roof.
- 12:12 = 45.0 deg — Equal rise and run. Very steep, A-frame look.

## Key indicators of STEEPER pitch (7:12+):
- Gable end triangle is tall relative to wall height
- You can barely see the roof surface from ground level
- Building looks "top-heavy" with a lot of roof
- Snow-prone regions (Midwest, Mountain states, Northeast)
- Traditional/colonial architectural style

## Key indicators of LOWER pitch (4-5:12):
- Roof appears nearly flat from ground level
- You can see a large area of the roof surface
- Modern/ranch/Mediterranean style
- Warm climate region

Examine ALL provided photos carefully. Look at the roof from multiple angles.

Return ONLY valid JSON:
{"pitch": "<rise>:<run>", "rise": <number>, "run": 12, "confidence": <0-1>, "reasoning": "<brief explanation of what you see>"}"""


async def estimate_pitch(
    openai_client: Any,
    streetview_images: list[str],
    gemini_api_key: str = "",
) -> PitchEstimate:
    """
    Multi-model ensemble pitch estimation.
    Runs GPT-4o (4 temps) + Gemini 2.5 Pro (4 temps), takes median of all.
    """
    if not streetview_images:
        logger.info("No street view images, defaulting to 6:12 pitch")
        return PitchEstimate()

    # Filter out blank/invalid street view images (< 15KB is likely "no imagery")
    valid_images = []
    for img_path in streetview_images:
        try:
            size = Path(img_path).stat().st_size
            if size > 15000:
                valid_images.append(img_path)
            else:
                logger.info("Skipping small/blank street view image: %s (%d bytes)", img_path, size)
        except OSError:
            pass

    if not valid_images:
        logger.info("No valid street view images, defaulting to 6:12 pitch")
        return PitchEstimate()

    images = valid_images[:4]

    # Build ensemble of calls across models and temperatures
    tasks = []
    task_labels = []

    # GPT-4o at multiple temperatures
    openai_temps = [0.1, 0.3, 0.5, 0.7]
    for temp in openai_temps:

        async def _run_openai(t=temp):
            try:
                data = await _openai_vision_call(
                    openai_client,
                    "gpt-4o",
                    _PITCH_PROMPT,
                    images,
                    temperature=t,
                    max_tokens=500,
                )
                rise = int(data.get("rise", 0))
                return rise, data.get("reasoning", "")
            except Exception as e:
                logger.warning("GPT-4o pitch (temp=%.1f) failed: %s", t, e)
                return None, ""

        tasks.append(_run_openai())
        task_labels.append(f"gpt-4o(t={temp})")

    # Gemini 2.5 Pro at multiple temperatures
    if gemini_api_key:
        gemini_temps = [0.1, 0.3, 0.5, 0.7]
        for temp in gemini_temps:

            async def _run_gemini(t=temp):
                try:
                    gemini = _init_gemini(gemini_api_key)
                    data = await _gemini_vision_call(
                        gemini,
                        "gemini-2.5-pro",
                        _PITCH_PROMPT,
                        images,
                        temperature=t,
                        max_tokens=500,
                    )
                    rise = int(data.get("rise", 0))
                    return rise, data.get("reasoning", "")
                except Exception as e:
                    logger.warning("Gemini pitch (temp=%.1f) failed: %s", t, e)
                    return None, ""

            tasks.append(_run_gemini())
            task_labels.append(f"gemini-2.5-pro(t={temp})")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect valid estimates
    estimates = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("Pitch task %s raised exception: %s", task_labels[i], r)
            continue
        rise, reasoning = r if isinstance(r, tuple) else (None, "")
        if rise and rise > 0:
            estimates.append(rise)
            logger.info("Pitch estimate (%s): %d:12 — %s", task_labels[i], rise, reasoning[:80])

    if not estimates:
        logger.warning("All pitch estimation models failed, defaulting to 6:12")
        return PitchEstimate()

    # Use proper median of ALL estimates (no outlier filtering).
    # Previous mode-based filtering discarded one model's votes entirely when
    # GPT-4o and Gemini disagreed, losing valuable signal from Gemini.
    # The proper median of all estimates naturally balances biases between models.
    filtered = sorted(estimates)
    n = len(filtered)
    # Average the two middle values for even-length lists, otherwise take middle
    median_rise = round((filtered[n // 2 - 1] + filtered[n // 2]) / 2) if n % 2 == 0 else filtered[n // 2]

    # Clamp to residential range. No blunt +1 correction — the larger
    # multi-model ensemble handles bias naturally.
    if median_rise <= 1:
        median_rise = 6  # couldn't determine, default
    median_rise = max(4, min(median_rise, 12))

    logger.info(
        "Pitch ensemble: %d estimates, sorted=%s, median=%d:12",
        len(estimates),
        filtered,
        median_rise,
    )

    run = 12
    multiplier = _pitch_multiplier(median_rise, run)
    confidence = min(0.85, 0.4 + 0.05 * len(filtered))

    return PitchEstimate(
        pitch=f"{median_rise}:{run}",
        rise=median_rise,
        run=run,
        multiplier=multiplier,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Sunroof validation (unchanged — low impact)
# ---------------------------------------------------------------------------


async def validate_with_sunroof(
    client: Any,
    sunroof_image: str,
) -> dict:
    """Analyze sunroof overlay for segment validation."""
    prompt = """This image shows a roof visualization with colored segments representing different roof planes.

Identify:
1. Number of distinct roof segments
2. Overall roof shape
3. Relative sizes of segments
4. Whether the visualization covers the full roof

Return ONLY JSON:
{"segment_count": <number>, "roof_shape": "<description>", "coverage_notes": "<notes>", "confidence": <0-1>}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        _openai_image(sunroof_image),
                    ],
                }
            ],
            max_tokens=500,
            temperature=0.1,
        )
        text = response.choices[0].message.content or "{}"
        return _parse_json(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse sunroof validation: %s", text[:200])
        return {}
    except Exception as e:
        logger.error("Sunroof validation failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _pitch_multiplier(rise: int, run: int = 12) -> float:
    """Calculate the pitch multiplier (roof area / footprint area)."""
    slope = rise / run
    return math.sqrt(1 + slope**2)


PITCH_MULTIPLIERS = {
    (4, 12): 1.054,
    (5, 12): 1.083,
    (6, 12): 1.118,
    (7, 12): 1.158,
    (8, 12): 1.202,
    (9, 12): 1.250,
    (10, 12): 1.302,
    (12, 12): 1.414,
}
