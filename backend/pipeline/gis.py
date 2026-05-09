"""
Query county GIS REST APIs for building footprint data.
Each county has a different ArcGIS endpoint; we try them in order
and fall back to Microsoft Building Footprints via Overpass/OSM.
"""

import logging
import math

import httpx

from models.schemas import FootprintSource

logger = logging.getLogger(__name__)

# Buffer in degrees (~50 meters) for spatial queries
BUFFER_DEG = 0.0005

# County GIS endpoint configurations
GIS_ENDPOINTS = {
    "harris_county_tx": {
        "url": "https://www.gis.hctx.net/arcgishcpid/rest/services/HCFCD/Building_Footprints_2018/MapServer/0/query",
        "srid": 2278,  # Texas South Central, US feet
        "area_field": None,  # Use Shape.STArea() - area in sqft
        "states": ["TX"],
        "counties": ["Harris"],
    },
    "adams_county_co": {
        "url": "https://gisapp.adcogov.org/arcgis/rest/services/AdamsCountyBasic/MapServer/34/query",
        "srid": None,
        "area_field": None,  # Compute from geometry
        "states": ["CO"],
        "counties": ["Adams"],
    },
    "lee_county_fl": {
        "url": "https://gismapserver.leegov.com/gisserver910/rest/services/DataExplorer/LandRecords/MapServer/8/query",
        "srid": None,
        "area_field": "ActualArea",  # "Actual Area (sq ft)"
        "states": ["FL"],
        "counties": ["Lee"],
    },
    "illinois_statewide": {
        "url": "https://geoservices3.dnr.illinois.gov/arcgis/rest/services/statewide_building_footprints/MapServer/0/query",
        "srid": None,
        "area_field": None,  # Use Shape.STArea()
        "states": ["IL"],
        "counties": None,  # Statewide
    },
    "virginia_vgin": {
        "url": "https://gismaps.vdem.virginia.gov/arcgis/rest/services/VA_Base_Layers/VA_Building_Footprints/FeatureServer/0/query",
        "srid": None,
        "area_field": None,  # Compute from geometry
        "states": ["VA"],
        "counties": None,  # Statewide
    },
}


def _state_from_address(address: str) -> str | None:
    """Extract state abbreviation from address.

    Looks for a 2-letter state code that appears just before a ZIP code
    (5-digit number) to avoid false positives like 'Ct' (Court).
    """
    import re

    state_abbrevs = {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
    # Try to find state before ZIP code: "TX 77338" or "TX, 77338"
    match = re.search(r"\b([A-Z]{2})\b[,\s]+(\d{5})", address.upper())
    if match and match.group(1) in state_abbrevs:
        return match.group(1)
    # Fallback: look for state abbreviation after last comma
    parts = address.split(",")
    if len(parts) >= 2:
        last_part = parts[-1].strip().upper().split()
        for token in last_part:
            if token in state_abbrevs:
                return token
        # Try second to last part (state might be before zip in last segment)
        second_last = parts[-2].strip().upper().split()
        for token in second_last:
            if token in state_abbrevs:
                return token
    return None


def _compute_polygon_area_sqft(rings: list) -> float:
    """
    Compute area of polygon from coordinate rings using the Shoelace formula.
    Assumes coordinates are in a projected CRS with units in feet or meters.
    For lat/lng coordinates, we approximate using local projection.
    """
    if not rings or not rings[0]:
        return 0.0

    ring = rings[0]  # Outer ring
    n = len(ring)
    if n < 3:
        return 0.0

    # Check if coordinates are lat/lng (small numbers) or projected (large numbers)
    sample_x = abs(ring[0][0])
    is_geographic = sample_x < 360

    if is_geographic:
        # Convert to approximate sqft using local projection
        # At the centroid latitude
        avg_lat = sum(p[1] for p in ring) / n
        # meters per degree
        m_per_deg_lat = 111132.92
        m_per_deg_lng = 111132.92 * math.cos(math.radians(avg_lat))

        # Convert to meters and compute area
        area_sq_m = 0
        for i in range(n):
            j = (i + 1) % n
            xi = ring[i][0] * m_per_deg_lng
            yi = ring[i][1] * m_per_deg_lat
            xj = ring[j][0] * m_per_deg_lng
            yj = ring[j][1] * m_per_deg_lat
            area_sq_m += xi * yj - xj * yi
        area_sq_m = abs(area_sq_m) / 2.0
        return area_sq_m * 10.7639  # sq meters to sq feet
    else:
        # Already in projected coordinates (likely feet)
        area = 0
        for i in range(n):
            j = (i + 1) % n
            area += ring[i][0] * ring[j][1] - ring[j][0] * ring[i][1]
        return abs(area) / 2.0


async def query_county_gis(lat: float, lng: float, address: str) -> FootprintSource | None:
    """Query county GIS for building footprint at the given location."""

    state = _state_from_address(address)
    if not state:
        logger.warning("Could not determine state from address: %s", address)
        return None

    # Find matching endpoints
    matching_endpoints = [(name, config) for name, config in GIS_ENDPOINTS.items() if state in config["states"]]

    if not matching_endpoints:
        logger.info("No GIS endpoint configured for state: %s", state)
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, config in matching_endpoints:
            try:
                result = await _query_arcgis_endpoint(client, name, config, lat, lng)
                if result:
                    return result
            except Exception as e:
                logger.warning("GIS query failed for %s: %s", name, e)
                continue

    return None


async def _query_arcgis_endpoint(
    client: httpx.AsyncClient,
    name: str,
    config: dict,
    lat: float,
    lng: float,
) -> FootprintSource | None:
    """Query a single ArcGIS REST endpoint for building footprints."""

    # Build envelope geometry for spatial query
    xmin = lng - BUFFER_DEG
    ymin = lat - BUFFER_DEG
    xmax = lng + BUFFER_DEG
    ymax = lat + BUFFER_DEG

    params = {
        "where": "1=1",
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",  # Request results in WGS84 for distance calculation
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "json",
    }

    logger.info("Querying GIS endpoint: %s", name)
    response = await client.get(config["url"], params=params)
    response.raise_for_status()
    data = response.json()

    features = data.get("features", [])
    if not features:
        logger.info("No features found at %s for (%f, %f)", name, lat, lng)
        return None

    # Find the building closest to our query point
    # Since we requested outSR=4326, geometry is in lat/lng
    candidates: list[tuple[float, float]] = []  # (distance, area_sqft)

    for feature in features:
        attrs = feature.get("attributes", {})
        geometry = feature.get("geometry", {})
        rings = geometry.get("rings", [])

        # Get area from attributes (area fields are in native CRS units)
        area_sqft = 0.0
        area_field = config.get("area_field")

        if area_field and area_field in attrs:
            area_sqft = float(attrs[area_field])
        elif "Shape.STArea()" in attrs:
            area_sqft = float(attrs["Shape.STArea()"])
        elif "Shape_Area" in attrs:
            area_sqft = float(attrs["Shape_Area"])
        elif "SHAPE.AREA" in attrs:
            area_sqft = float(attrs["SHAPE.AREA"])
        elif "shape_area" in attrs:
            area_sqft = float(attrs["shape_area"])

        # If no area attribute, compute from geometry
        if area_sqft <= 0 and rings:
            area_sqft = _compute_polygon_area_sqft(rings)

        if area_sqft <= 100:  # Skip tiny features
            continue

        # Compute centroid distance to query point
        if rings and rings[0]:
            ring = rings[0]
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            # Geographic distance in degrees (fine for ranking nearby features)
            dist = math.sqrt((cx - lng) ** 2 + (cy - lat) ** 2)
            candidates.append((dist, area_sqft))

    if not candidates:
        return None

    # Sort by distance to query point, pick closest
    candidates.sort(key=lambda x: x[0])
    best_dist, best_area = candidates[0]

    logger.info(
        "Found building footprint from %s: %.1f sqft (closest of %d candidates, dist=%.6f deg)",
        name,
        best_area,
        len(candidates),
        best_dist,
    )
    return FootprintSource(
        source=f"county_gis:{name}",
        footprint_sqft=best_area,
        confidence=0.85,
    )


async def query_microsoft_buildings(lat: float, lng: float) -> FootprintSource | None:
    """
    Query Microsoft Building Footprints (hosted on ArcGIS Online).
    Universal coverage for US buildings — works even when no county GIS exists.
    """
    buf = 0.0015  # ~165m buffer
    xmin, ymin = lng - buf, lat - buf
    xmax, ymax = lng + buf, lat + buf

    url = "https://services.arcgis.com/P3ePLMYs2RVChkJx/ArcGIS/rest/services/MSBFP2/FeatureServer/0/query"
    params = {
        "where": "1=1",
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            features = data.get("features", [])
            if not features:
                logger.info("No Microsoft Building Footprints at (%.6f, %.6f)", lat, lng)
                return None

            # Find closest building to query point
            m_per_deg_lat = 111132.92
            m_per_deg_lng = 111132.92 * math.cos(math.radians(lat))

            best_dist = float("inf")
            best_area = 0.0

            for feat in features:
                rings = feat.get("geometry", {}).get("rings", [])
                if not rings or not rings[0]:
                    continue
                ring = rings[0]
                n = len(ring)

                # Centroid distance
                cx = sum(p[0] for p in ring) / n
                cy = sum(p[1] for p in ring) / n
                dist = math.sqrt(((cx - lng) * m_per_deg_lng) ** 2 + ((cy - lat) * m_per_deg_lat) ** 2)

                # Compute area in sqft from geographic coordinates
                area_sqft = _compute_polygon_area_sqft(rings)

                if area_sqft > 100 and dist < best_dist:
                    best_dist = dist
                    best_area = area_sqft

            if best_area > 100 and best_dist < 30:
                logger.info(
                    "Found Microsoft Building Footprint: %.1f sqft (dist=%.1fm)",
                    best_area,
                    best_dist,
                )
                return FootprintSource(
                    source="microsoft_buildings",
                    footprint_sqft=best_area,
                    confidence=0.80,
                )
            elif best_area > 100:
                logger.info(
                    "Microsoft Building Footprint found but too far: %.1f sqft at %.1fm",
                    best_area,
                    best_dist,
                )
        except Exception as e:
            logger.warning("Microsoft Building Footprints query failed: %s", e)

    return None


async def query_overpass_osm(lat: float, lng: float) -> FootprintSource | None:
    """
    Fallback: query OpenStreetMap Overpass API for building footprints.
    """
    bbox = f"{lat - BUFFER_DEG},{lng - BUFFER_DEG},{lat + BUFFER_DEG},{lng + BUFFER_DEG}"
    query = f"""
    [out:json][timeout:30];
    way["building"]({bbox});
    (._;>;);
    out body;
    """

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                "https://overpass-api.de/api/interpreter",
                params={"data": query.strip()},
                headers={"User-Agent": "CloudNimbus/1.0"},
            )
            response.raise_for_status()
            data = response.json()

            # Extract nodes and ways
            nodes = {}
            ways = []
            for element in data.get("elements", []):
                if element["type"] == "node":
                    nodes[element["id"]] = (element["lon"], element["lat"])
                elif element["type"] == "way":
                    ways.append(element)

            if not ways:
                return None

            # Find the building closest to our point
            m_per_deg_lat = 111132.92
            m_per_deg_lng = 111132.92 * math.cos(math.radians(lat))

            best_dist = float("inf")
            best_area = 0.0
            for way in ways:
                ring = []
                for node_id in way.get("nodes", []):
                    if node_id in nodes:
                        ring.append(nodes[node_id])
                if len(ring) >= 3:
                    area = _compute_polygon_area_sqft([ring])
                    if area > 100:
                        cx = sum(p[0] for p in ring) / len(ring)
                        cy = sum(p[1] for p in ring) / len(ring)
                        dist = math.sqrt(((cx - lng) * m_per_deg_lng) ** 2 + ((cy - lat) * m_per_deg_lat) ** 2)
                        if dist < best_dist:
                            best_dist = dist
                            best_area = area

            if best_area > 100:
                logger.info("Found OSM building footprint: %.1f sqft", best_area)
                return FootprintSource(
                    source="osm_overpass",
                    footprint_sqft=best_area,
                    confidence=0.7,
                )
        except Exception as e:
            logger.warning("Overpass query failed: %s", e)

    return None
