"""
Vision analysis for roof measurements.
Multi-model ensemble: Gemini 2.5 Pro + GPT-4o for maximum accuracy.
"""

import asyncio
import base64
import json
import logging
import math
import re
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
    """Parse JSON from LLM response, handling markdown fences and surrounding prose."""
    text = text.strip()

    # Fast path: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences (```json ... ```) with possible surrounding text
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Find outermost { ... } block (handles prose before/after JSON)
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError(f"Could not extract JSON from LLM response: {text[:200]}", text, 0)


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

    # Force JSON output for OpenAI models (requires "JSON" in prompt text)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
        temperature=temperature,
        response_format={"type": "json_object"},
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

_PITCH_PROMPT = """You are a professional roofing estimator. Your task is to MEASURE the roof pitch geometrically from these street-level photos.

## MEASUREMENT METHOD (do this step by step):

1. Find a GABLE END of the roof — the triangular wall section where you can see the roof slope profile.
2. Measure these three things IN PIXELS in the image:
   - **wall_height_px**: The height of the rectangular wall below the eave line (from ground/foundation to where the roof starts)
   - **gable_height_px**: The height of the triangular gable section ABOVE the eave line (from eave to ridge peak)
   - **half_width_px**: The horizontal distance from one side of the building to the ridge (half the building width at the gable end)
3. Compute the ratio: gable_height_px / half_width_px — this IS the rise/run ratio.

## RATIO TO PITCH REFERENCE:
- ratio ≈ 0.33 → 4:12 pitch
- ratio ≈ 0.42 → 5:12 pitch
- ratio ≈ 0.50 → 6:12 pitch
- ratio ≈ 0.58 → 7:12 pitch
- ratio ≈ 0.67 → 8:12 pitch
- ratio ≈ 0.83 → 10:12 pitch
- ratio ≈ 1.00 → 12:12 pitch

## CRITICAL CALIBRATION:
- If gable triangle height is about HALF the half-width → 6:12
- If gable triangle height is about TWO-THIRDS of the half-width → 8:12
- If gable triangle height EQUALS the half-width → 12:12
- Most people UNDERESTIMATE pitch. A gable that looks "moderate" is often 7-8:12, not 6:12.

## IMPORTANT:
- Measure from MULTIPLE photos if possible and average your measurements
- If no gable end is visible, estimate from the roof slope angle seen in profile
- Focus on the MAIN roof, not dormers or small additions

Return ONLY valid JSON:
{"wall_height_px": <number>, "gable_height_px": <number>, "half_width_px": <number>, "ratio": <float>, "rise": <number>, "run": 12, "confidence": <0-1>, "reasoning": "<what you measured and how>"}"""


# ---------------------------------------------------------------------------
# Geographic pitch priors
# ---------------------------------------------------------------------------

# States where snow loads encourage steeper pitches
_SNOW_STATES = frozenset(
    {
        "CO",
        "CT",
        "IA",
        "ID",
        "IL",
        "IN",
        "KS",
        "KY",
        "MA",
        "MD",
        "ME",
        "MI",
        "MN",
        "MO",
        "MT",
        "ND",
        "NE",
        "NH",
        "NJ",
        "NY",
        "OH",
        "OR",
        "PA",
        "RI",
        "SD",
        "UT",
        "VA",
        "VT",
        "WA",
        "WI",
        "WV",
        "WY",
    }
)

# Warm-climate states where lower pitches are common
_WARM_STATES = frozenset(
    {
        "AZ",
        "FL",
        "HI",
        "LA",
        "NM",
        "NV",
    }
)


def _geographic_pitch_adjustment(median_rise: int, estimates: list[int], state: str | None) -> int:
    """Nudge pitch when the ensemble vote is close and geographic priors apply.

    Only activates when the ensemble is genuinely split (not overriding strong
    consensus). A "split" means the median sits right at the boundary between
    two pitch values and votes are distributed across both.
    """
    if state is None or len(estimates) < 3:
        return median_rise

    # Count how many votes are above vs below the median
    above = sum(1 for e in estimates if e > median_rise)
    below = sum(1 for e in estimates if e < median_rise)
    total = len(estimates)

    # Only nudge if the vote is genuinely split: significant minority disagrees
    # (at least 30% of votes are not at the median)
    minority_pct = (above + below) / total
    if minority_pct < 0.30:
        return median_rise  # Strong consensus, don't override

    if state in _SNOW_STATES and above > below and median_rise < 10:
        logger.info("Geographic prior: snow state %s, nudging pitch %d→%d", state, median_rise, median_rise + 1)
        return median_rise + 1

    if state in _WARM_STATES and below > above and median_rise > 4:
        logger.info("Geographic prior: warm state %s, nudging pitch %d→%d", state, median_rise, median_rise - 1)
        return median_rise - 1

    return median_rise


def _ratio_to_rise(ratio: float) -> int:
    """Convert a gable_height/half_width ratio to the nearest standard pitch rise."""
    # Standard pitch ratios: rise/12
    standard_pitches = [
        (4, 4 / 12),
        (5, 5 / 12),
        (6, 6 / 12),
        (7, 7 / 12),
        (8, 8 / 12),
        (9, 9 / 12),
        (10, 10 / 12),
        (12, 12 / 12),
    ]
    best_rise = 6
    best_diff = float("inf")
    for rise, std_ratio in standard_pitches:
        diff = abs(ratio - std_ratio)
        if diff < best_diff:
            best_diff = diff
            best_rise = rise
    return best_rise


async def estimate_pitch(
    openai_client: Any,
    streetview_images: list[str],
    gemini_api_key: str = "",
    state: str | None = None,
) -> PitchEstimate:
    """
    Two-pass multi-model ensemble pitch estimation.
    Pass 1: LLMs measure gable geometry (pixel measurements → ratio).
    Pass 2: Python converts ratios to pitch deterministically.
    Geographic priors nudge borderline cases based on state.
    Prefers roof-focused images (*_roof.jpg) for clearer slope visibility.
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

    # Prefer roof-focused images (pitch=35) for pitch estimation — they show
    # the roof slope much more clearly, especially for steep roofs
    roof_images = [p for p in valid_images if "_roof" in Path(p).stem]
    standard_images = [p for p in valid_images if "_roof" not in Path(p).stem]

    # Use roof images if available, fall back to standard
    if roof_images:
        images = roof_images[:4]
        logger.info("Using %d roof-focused images for pitch estimation", len(images))
    else:
        images = standard_images[:4]
        logger.info("No roof-focused images, using %d standard images", len(images))

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
                # Two-pass: use ratio for deterministic conversion if available
                ratio = data.get("ratio")
                if ratio and isinstance(ratio, (int, float)) and ratio > 0:
                    rise = _ratio_to_rise(float(ratio))
                else:
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
                    # Two-pass: use ratio for deterministic conversion if available
                    ratio = data.get("ratio")
                    if ratio and isinstance(ratio, (int, float)) and ratio > 0:
                        rise = _ratio_to_rise(float(ratio))
                    else:
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

    # Use upper-median of ALL estimates. For even-length lists, take the upper
    # middle value rather than averaging. This corrects for the known systematic
    # underestimation bias in vision models (they default to 6:12 "most common").
    filtered = sorted(estimates)
    n = len(filtered)
    median_rise = filtered[n // 2] if n % 2 == 0 else filtered[n // 2]

    # Clamp to residential range
    if median_rise <= 1:
        median_rise = 6  # couldn't determine, default
    median_rise = max(4, min(median_rise, 12))

    # Apply geographic pitch adjustment for borderline cases, but only when
    # the split is wide (not adjacent values, which indicates genuine ambiguity)
    tight_split = n % 2 == 0 and (filtered[n // 2] - filtered[n // 2 - 1] <= 1)
    if not tight_split:
        median_rise = _geographic_pitch_adjustment(median_rise, estimates, state)

    logger.info(
        "Pitch ensemble: %d estimates, sorted=%s, median=%d:12, state=%s",
        len(estimates),
        filtered,
        median_rise,
        state,
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
            response_format={"type": "json_object"},
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
