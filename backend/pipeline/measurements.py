"""
Measurement engine: combine data from GIS, SAM2, vision LLM, and Sunroof
into final roof measurements with confidence scoring.
"""

from __future__ import annotations

import logging
import math

from models.schemas import (
    FootprintSource,
    LineItems,
    PitchEstimate,
    RoofMeasurements,
    RoofShape,
)

logger = logging.getLogger(__name__)

# Sunroof "usable sqft" is typically 75-85% of total roof area
SUNROOF_USABLE_RATIO_LOW = 0.70
SUNROOF_USABLE_RATIO_HIGH = 0.90
SUNROOF_USABLE_RATIO_MID = 0.80

# Eave overhang correction: GIS/MSFT capture building outlines (wall-to-wall),
# but roof measurements need the drip-line area (including overhang).
# Standard residential eave overhang: 6-18 inches. We estimate the added area
# as overhang x perimeter. For a rectangular building with aspect ratio ~1.3:1,
# perimeter ~ 4.6 x sqrt(area). With ~1 ft overhang:
#   added_area = 1.0 x 4.6 x sqrt(area) ~ 5-8% of footprint for typical homes.
# We apply a conservative 4% correction to building-outline sources.
EAVE_OVERHANG_FACTOR = 1.04


def compute_pitch_multiplier(rise: int, run: int = 12) -> float:
    """Compute pitch multiplier = sqrt(1 + (rise/run)^2)."""
    slope = rise / run
    return math.sqrt(1 + slope**2)


def combine_measurements(
    footprint_sources: list[FootprintSource],
    pitch: PitchEstimate,
    aerial_analysis: dict,
    sunroof_usable_sqft: float | None,
    sunroof_validation: dict,
) -> RoofMeasurements:
    """
    Combine all data sources into final roof measurements.

    Strategy:
    1. Pick the best footprint estimate (highest confidence weighted by source reliability)
    2. Apply pitch multiplier to get roof area
    3. Cross-validate against Sunroof — ADJUST numbers when Sunroof disagrees significantly
    4. Use aerial vision analysis for line items (with aspect-ratio-based fallback)
    """

    # --- Step 1: Determine best footprint ---
    # Remove outlier footprint sources: if two sources disagree by >2x, discard the larger
    if len(footprint_sources) >= 2:
        footprint_sources.sort(key=lambda x: x.footprint_sqft)
        smallest = footprint_sources[0].footprint_sqft
        largest = footprint_sources[-1].footprint_sqft
        if smallest > 0 and largest / smallest > 2.0:
            outlier = footprint_sources[-1]
            logger.warning(
                "Discarding outlier footprint: %s %.0f sqft (>2x vs %.0f sqft)",
                outlier.source,
                outlier.footprint_sqft,
                smallest,
            )
            footprint_sources = footprint_sources[:-1]

    # Apply eave overhang correction to building-outline sources.
    # EXCEPTION: when 2+ independent sources agree within 3%, they're both measuring
    # the same physical boundary (roof drip line from aerial imagery). Applying
    # eave correction would double-count the overhang that's already captured.
    _building_outline_prefixes = ("county_gis", "osm", "microsoft")
    outline_sources = [s for s in footprint_sources if any(s.source.startswith(p) for p in _building_outline_prefixes)]

    skip_eave = False
    if len(outline_sources) >= 2:
        sorted_areas = sorted(s.footprint_sqft for s in outline_sources)
        spread_pct = (sorted_areas[-1] - sorted_areas[0]) / sorted_areas[0] if sorted_areas[0] > 0 else 1.0
        if spread_pct <= 0.03:
            skip_eave = True
            logger.info(
                "Skipping eave correction: %d sources agree within %.1f%%",
                len(outline_sources),
                spread_pct * 100,
            )

    if not skip_eave:
        for i, src in enumerate(footprint_sources):
            if any(src.source.startswith(p) for p in _building_outline_prefixes):
                corrected = src.footprint_sqft * EAVE_OVERHANG_FACTOR
                logger.debug(
                    "Eave overhang correction: %s %.0f -> %.0f sqft",
                    src.source,
                    src.footprint_sqft,
                    corrected,
                )
                footprint_sources[i] = FootprintSource(
                    source=src.source,
                    footprint_sqft=corrected,
                    confidence=src.confidence,
                )

    # Only use vision LLM footprint as fallback when no reliable footprint data
    has_gis = any(
        s.source.startswith("county_gis") or s.source.startswith("osm") or s.source.startswith("microsoft")
        for s in footprint_sources
    )
    if not has_gis and aerial_analysis.get("footprint_sqft"):
        footprint_sources.append(
            FootprintSource(
                source="vision_llm",
                footprint_sqft=float(aerial_analysis["footprint_sqft"]),
                confidence=float(aerial_analysis.get("confidence", 0.5)) * 0.6,
            )
        )

    # Sort by confidence
    footprint_sources.sort(key=lambda x: x.confidence, reverse=True)

    if not footprint_sources:
        logger.warning("No footprint sources available!")
        # Last resort: try to derive from sunroof
        if sunroof_usable_sqft:
            estimated_total_roof = sunroof_usable_sqft / SUNROOF_USABLE_RATIO_MID
            estimated_footprint = estimated_total_roof / pitch.multiplier
            footprint_sources.append(
                FootprintSource(
                    source="sunroof_derived",
                    footprint_sqft=estimated_footprint,
                    confidence=0.4,
                )
            )

    if not footprint_sources:
        return RoofMeasurements(
            total_roof_sqft=0,
            footprint_sqft=0,
            pitch=pitch,
            confidence=0,
        )

    # Sanity check: residential buildings are typically 800-8000 sqft footprint.
    min_residential_sqft = 800
    if (
        len(footprint_sources) == 1
        and footprint_sources[0].source == "vision_llm"
        and footprint_sources[0].footprint_sqft < min_residential_sqft
    ):
        logger.warning(
            "Vision-only footprint %.0f sqft is below residential minimum, clamping to %d",
            footprint_sources[0].footprint_sqft,
            min_residential_sqft,
        )
        footprint_sources[0] = FootprintSource(
            source="vision_llm",
            footprint_sqft=min_residential_sqft,
            confidence=footprint_sources[0].confidence * 0.5,
        )

    # Weighted average of footprint estimates
    best_footprint = _weighted_footprint(footprint_sources)
    logger.info("Best footprint estimate: %.1f sqft", best_footprint)

    # --- Step 2: Apply pitch multiplier ---
    total_roof_sqft = best_footprint * pitch.multiplier
    logger.info(
        "Roof area: %.1f sqft (footprint %.1f x multiplier %.3f for %s pitch)",
        total_roof_sqft,
        best_footprint,
        pitch.multiplier,
        pitch.pitch,
    )

    # --- Step 3: Cross-validate AND CORRECT using Sunroof ---
    if sunroof_usable_sqft and sunroof_usable_sqft > 0:
        estimated_total_from_sunroof = sunroof_usable_sqft / SUNROOF_USABLE_RATIO_MID
        ratio = total_roof_sqft / estimated_total_from_sunroof
        if 0.80 <= ratio <= 1.25:
            logger.info(
                "Sunroof cross-validation PASS: our %.0f vs sunroof-derived %.0f (ratio %.2f)",
                total_roof_sqft,
                estimated_total_from_sunroof,
                ratio,
            )
        else:
            sunroof_weight = 0.30
            our_weight = 1.0 - sunroof_weight
            corrected_sqft = total_roof_sqft * our_weight + estimated_total_from_sunroof * sunroof_weight
            logger.warning(
                "Sunroof CORRECTION: our %.0f vs sunroof-derived %.0f (ratio %.2f). "
                "Blending %.0f%% sunroof -> corrected %.0f sqft",
                total_roof_sqft,
                estimated_total_from_sunroof,
                ratio,
                sunroof_weight * 100,
                corrected_sqft,
            )
            total_roof_sqft = corrected_sqft
            best_footprint = total_roof_sqft / pitch.multiplier

    # --- Step 4: Extract line items from aerial analysis ---
    # Use actual building dimensions for perimeter estimation when available
    width_ft = float(aerial_analysis.get("width_ft", 0))
    depth_ft = float(aerial_analysis.get("depth_ft", 0))

    line_items = _extract_line_items(
        aerial_analysis,
        best_footprint,
        width_ft,
        depth_ft,
    )

    # Parse roof shape
    shape_str = aerial_analysis.get("roof_shape", "unknown")
    try:
        roof_shape = RoofShape(shape_str.lower().replace(" ", "-"))
    except ValueError:
        roof_shape = RoofShape.UNKNOWN

    # Compute overall confidence
    confidence = _compute_confidence(
        footprint_sources,
        pitch,
        sunroof_usable_sqft,
        total_roof_sqft,
    )

    return RoofMeasurements(
        total_roof_sqft=round(total_roof_sqft),
        footprint_sqft=round(best_footprint),
        pitch=pitch,
        roof_shape=roof_shape,
        facet_count=int(aerial_analysis.get("facet_count", 0)),
        line_items=line_items,
        footprint_sources=footprint_sources,
        confidence=confidence,
    )


def _extract_line_items(
    aerial_analysis: dict,
    footprint_sqft: float,
    width_ft: float,
    depth_ft: float,
) -> LineItems:
    """
    Extract line items from aerial analysis, with smarter fallback.
    Uses actual building aspect ratio instead of assuming square.
    """
    # Start with whatever the vision model detected
    ridge_ft = float(aerial_analysis.get("ridge_length_ft", 0))
    hip_ft = float(aerial_analysis.get("hip_length_ft", 0))
    valley_ft = float(aerial_analysis.get("valley_length_ft", 0))
    rake_ft = float(aerial_analysis.get("rake_length_ft", 0))
    eave_ft = float(aerial_analysis.get("eave_length_ft", 0))
    flashing_ft = float(aerial_analysis.get("flashing_length_ft", 0))
    step_flashing_ft = float(aerial_analysis.get("step_flashing_length_ft", 0))

    # If vision didn't detect edges, estimate from building dimensions
    if eave_ft == 0 and footprint_sqft > 0:
        if width_ft > 0 and depth_ft > 0:
            # Use actual dimensions from vision/GIS
            perimeter = 2 * (width_ft + depth_ft)
            logger.info(
                "Line item fallback using actual dimensions: %.0fx%.0f ft, perimeter=%.0f ft",
                width_ft,
                depth_ft,
                perimeter,
            )
        else:
            # Fall back to aspect-ratio estimate (1.3:1 is typical for residential)
            # For area = w * d and d = 1.3 * w: w = sqrt(area / 1.3)
            aspect_ratio = 1.3
            w = math.sqrt(footprint_sqft / aspect_ratio)
            d = w * aspect_ratio
            perimeter = 2 * (w + d)
            width_ft = w
            depth_ft = d
            logger.info(
                "Line item fallback using 1.3:1 aspect ratio: est %.0fx%.0f ft, perimeter=%.0f ft",
                w,
                d,
                perimeter,
            )

        # Eave runs along the long sides (both sides)
        eave_ft = 2 * max(width_ft, depth_ft)
        # Rake runs along the gable ends (both sides, both edges)
        rake_ft = 2 * min(width_ft, depth_ft)
        # Ridge runs along the length of the building
        ridge_ft = max(width_ft, depth_ft) * 0.8  # ridge is slightly shorter than full length

    return LineItems(
        ridge_length_ft=ridge_ft,
        hip_length_ft=hip_ft,
        valley_length_ft=valley_ft,
        rake_length_ft=rake_ft,
        eave_length_ft=eave_ft,
        flashing_length_ft=flashing_ft,
        step_flashing_length_ft=step_flashing_ft,
    )


def _weighted_footprint(sources: list[FootprintSource]) -> float:
    """Compute weighted average of footprint estimates."""
    if len(sources) == 1:
        return sources[0].footprint_sqft

    # Source reliability weights (on top of self-reported confidence)
    source_weights = {
        "county_gis": 1.0,
        "sam2": 0.9,
        "microsoft_buildings": 0.85,
        "osm_overpass": 0.7,
        "vision_llm": 0.6,
        "sunroof_derived": 0.5,
    }

    total_weight = 0.0
    weighted_sum = 0.0

    for src in sources:
        base_name = src.source.split(":")[0]
        reliability = source_weights.get(base_name, 0.5)
        weight = src.confidence * reliability
        weighted_sum += src.footprint_sqft * weight
        total_weight += weight

    if total_weight == 0:
        return sources[0].footprint_sqft

    return weighted_sum / total_weight


def _compute_confidence(
    footprint_sources: list[FootprintSource],
    pitch: PitchEstimate,
    sunroof_sqft: float | None,
    total_sqft: float,
) -> float:
    """Compute overall confidence score."""
    score = 0.0

    # Footprint confidence (max 0.45)
    if footprint_sources:
        best_conf = max(s.confidence for s in footprint_sources)
        score += best_conf * 0.45

    # Multiple sources agree (max 0.20)
    if len(footprint_sources) >= 2:
        values = [s.footprint_sqft for s in footprint_sources]
        if values:
            mean = sum(values) / len(values)
            spread = max(abs(v - mean) / mean for v in values) if mean > 0 else 1.0
            if spread < 0.10:
                score += 0.20
            elif spread < 0.20:
                score += 0.10

    # Pitch confidence (max 0.20)
    score += pitch.confidence * 0.20

    # Sunroof cross-validation (max 0.15)
    if sunroof_sqft and sunroof_sqft > 0 and total_sqft > 0:
        estimated = sunroof_sqft / SUNROOF_USABLE_RATIO_MID
        ratio = total_sqft / estimated
        if 0.85 <= ratio <= 1.15:
            score += 0.15
        elif 0.75 <= ratio <= 1.25:
            score += 0.08

    return round(min(score, 1.0), 2)
