"""
Google Solar API integration.
Provides roof area, pitch per segment, and panel layout data.
"""

from __future__ import annotations

import logging
import math

import httpx

logger = logging.getLogger(__name__)

# Square meters to square feet
M2_TO_SQFT = 10.7639


async def get_solar_insights(lat: float, lng: float, api_key: str) -> dict | None:
    """
    Query Google Solar API for building insights at a lat/lng.

    Returns dict with:
      - whole_roof_sqft: total roof area in sqft
      - usable_sqft: max solar-viable area in sqft
      - segments: list of {area_sqft, pitch_degrees, azimuth_degrees}
      - avg_pitch_degrees: area-weighted average pitch
      - avg_pitch_rise: approximate rise:12 from weighted pitch
      - segment_count: number of roof segments
    """
    url = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
    params = {
        "location.latitude": lat,
        "location.longitude": lng,
        "requiredQuality": "HIGH",
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            quality_used = "HIGH"
            r = await client.get(url, params=params)
            if r.status_code != 200:
                logger.warning("Solar API error %d: %s", r.status_code, r.text[:200])
                # Try with MEDIUM quality if HIGH fails
                params["requiredQuality"] = "MEDIUM"
                quality_used = "MEDIUM"
                r = await client.get(url, params=params)
                if r.status_code != 200:
                    logger.warning("Solar API MEDIUM also failed: %d", r.status_code)
                    return None

            data = r.json()
            solar = data.get("solarPotential", {})
            if not solar:
                logger.info("No solar potential data for (%.6f, %.6f)", lat, lng)
                return None

            # Extract whole roof stats
            whole_roof_m2 = solar.get("wholeRoofStats", {}).get("areaMeters2", 0)
            max_array_m2 = solar.get("maxArrayAreaMeters2", 0)

            # Extract per-segment data
            segments = []
            total_weighted_pitch = 0.0
            total_area = 0.0

            for seg in solar.get("roofSegmentStats", []):
                stats = seg.get("stats", {})
                area_m2 = stats.get("areaMeters2", 0)
                pitch_deg = seg.get("pitchDegrees", 0)
                azimuth_deg = seg.get("azimuthDegrees", 0)

                segments.append(
                    {
                        "area_sqft": round(area_m2 * M2_TO_SQFT),
                        "pitch_degrees": round(pitch_deg, 1),
                        "azimuth_degrees": round(azimuth_deg),
                    }
                )

                total_weighted_pitch += pitch_deg * area_m2
                total_area += area_m2

            # Compute area-weighted average pitch
            avg_pitch_deg = total_weighted_pitch / total_area if total_area > 0 else 0
            # Convert degrees to rise:12
            avg_pitch_rise = round(math.tan(math.radians(avg_pitch_deg)) * 12)
            avg_pitch_rise = max(0, min(avg_pitch_rise, 24))  # clamp

            result = {
                "whole_roof_sqft": round(whole_roof_m2 * M2_TO_SQFT),
                "usable_sqft": round(max_array_m2 * M2_TO_SQFT),
                "segments": segments,
                "segment_count": len(segments),
                "avg_pitch_degrees": round(avg_pitch_deg, 1),
                "avg_pitch_rise": avg_pitch_rise,
                "raw_whole_roof_m2": whole_roof_m2,
                "quality": quality_used,
            }

            logger.info(
                "Solar API: whole roof %.0f sqft, %d segments, avg pitch %.1f° (%d:12)",
                result["whole_roof_sqft"],
                result["segment_count"],
                avg_pitch_deg,
                avg_pitch_rise,
            )

            return result

        except Exception as e:
            logger.warning("Solar API request failed: %s", e)
            return None
