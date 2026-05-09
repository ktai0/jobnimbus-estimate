"""
Cost estimator: convert roof measurements into itemized material + labor estimates
at three pricing tiers.
"""

import math

from models.schemas import (
    CostEstimate,
    EstimateLineItem,
    MaterialTier,
    RoofMeasurements,
)

# Pricing tables per tier: (economy, standard, premium)
PRICING = {
    "shingles_per_sq": (90, 130, 220),
    "underlayment_per_sq": (15, 20, 30),
    "starter_strip_per_bundle": (50, 55, 65),  # 1 bundle = 100 LF
    "ridge_cap_per_bundle": (55, 65, 85),  # 1 bundle = 20 LF
    "drip_edge_per_piece": (5, 7, 10),  # 1 piece = 10 LF
    "step_flashing_per_lf": (2, 3, 4),
    "pipe_flashing_per_ea": (12, 15, 20),
    "ice_water_per_roll": (100, 100, 100),  # 1 roll = 67 sqft
    "nails_per_box": (55, 55, 55),  # 1 box = 7200 nails
    "labor_tearoff_per_sq": (75, 75, 75),
    "labor_install_per_sq": (85, 100, 130),
    "dumpster_flat": (450, 450, 450),
    "permits_flat": (300, 300, 300),
}

WASTE_FACTOR = 0.12
OVERHEAD_PROFIT = 0.25
STARTER_STRIP_LF_PER_BUNDLE = 100
RIDGE_CAP_LF_PER_BUNDLE = 20
DRIP_EDGE_LF_PER_PIECE = 10
ICE_WATER_SQFT_PER_ROLL = 67
NAILS_PER_BOX = 7200
# Roughly 320 nails per square (100sqft)
NAILS_PER_SQ = 320
# Pipe flashings: estimate 2-4 per average house
DEFAULT_PIPE_FLASHINGS = 3


def _tier_index(tier: MaterialTier) -> int:
    return {MaterialTier.ECONOMY: 0, MaterialTier.STANDARD: 1, MaterialTier.PREMIUM: 2}[tier]


def generate_estimate(
    measurements: RoofMeasurements,
    tier: MaterialTier = MaterialTier.STANDARD,
) -> CostEstimate:
    """Generate a detailed cost estimate from roof measurements."""

    idx = _tier_index(tier)
    sqft = measurements.total_roof_sqft
    squares = sqft / 100  # 1 square = 100 sqft
    li = measurements.line_items

    material_items: list[EstimateLineItem] = []
    labor_items: list[EstimateLineItem] = []
    other_items: list[EstimateLineItem] = []

    # --- Materials ---

    # Shingles
    shingle_qty = math.ceil(squares * (1 + WASTE_FACTOR))
    material_items.append(
        EstimateLineItem(
            category="Materials",
            description="Roofing Shingles",
            quantity=shingle_qty,
            unit="squares",
            unit_cost=PRICING["shingles_per_sq"][idx],
            total_cost=shingle_qty * PRICING["shingles_per_sq"][idx],
        )
    )

    # Underlayment
    underlayment_qty = math.ceil(squares * (1 + WASTE_FACTOR))
    material_items.append(
        EstimateLineItem(
            category="Materials",
            description="Underlayment",
            quantity=underlayment_qty,
            unit="squares",
            unit_cost=PRICING["underlayment_per_sq"][idx],
            total_cost=underlayment_qty * PRICING["underlayment_per_sq"][idx],
        )
    )

    # Starter strip (along eaves + rakes)
    starter_lf = li.eave_length_ft + li.rake_length_ft
    if starter_lf == 0:
        # Estimate from perimeter: rough approximation
        side = math.sqrt(measurements.footprint_sqft) if measurements.footprint_sqft > 0 else 30
        starter_lf = side * 4 * 0.7  # not all perimeter needs starter
    starter_bundles = math.ceil(starter_lf / STARTER_STRIP_LF_PER_BUNDLE)
    material_items.append(
        EstimateLineItem(
            category="Materials",
            description="Starter Strip",
            quantity=starter_bundles,
            unit="bundles",
            unit_cost=PRICING["starter_strip_per_bundle"][idx],
            total_cost=starter_bundles * PRICING["starter_strip_per_bundle"][idx],
        )
    )

    # Ridge cap (along ridges + hips)
    ridge_lf = li.ridge_length_ft + li.hip_length_ft
    if ridge_lf == 0:
        # Estimate: ridge is roughly half the building length
        side = math.sqrt(measurements.footprint_sqft) if measurements.footprint_sqft > 0 else 30
        ridge_lf = side * 0.6
    ridge_bundles = math.ceil(ridge_lf / RIDGE_CAP_LF_PER_BUNDLE)
    material_items.append(
        EstimateLineItem(
            category="Materials",
            description="Ridge Cap",
            quantity=ridge_bundles,
            unit="bundles",
            unit_cost=PRICING["ridge_cap_per_bundle"][idx],
            total_cost=ridge_bundles * PRICING["ridge_cap_per_bundle"][idx],
        )
    )

    # Drip edge (eaves + rakes)
    drip_lf = li.eave_length_ft + li.rake_length_ft
    if drip_lf == 0:
        side = math.sqrt(measurements.footprint_sqft) if measurements.footprint_sqft > 0 else 30
        drip_lf = side * 4 * 0.7
    drip_pieces = math.ceil(drip_lf / DRIP_EDGE_LF_PER_PIECE)
    material_items.append(
        EstimateLineItem(
            category="Materials",
            description="Drip Edge",
            quantity=drip_pieces,
            unit="pieces (10ft)",
            unit_cost=PRICING["drip_edge_per_piece"][idx],
            total_cost=drip_pieces * PRICING["drip_edge_per_piece"][idx],
        )
    )

    # Step flashing
    step_lf = li.step_flashing_length_ft
    if step_lf > 0:
        material_items.append(
            EstimateLineItem(
                category="Materials",
                description="Step Flashing",
                quantity=step_lf,
                unit="LF",
                unit_cost=PRICING["step_flashing_per_lf"][idx],
                total_cost=step_lf * PRICING["step_flashing_per_lf"][idx],
            )
        )

    # Pipe flashing
    pipe_count = DEFAULT_PIPE_FLASHINGS
    material_items.append(
        EstimateLineItem(
            category="Materials",
            description="Pipe Flashing",
            quantity=pipe_count,
            unit="each",
            unit_cost=PRICING["pipe_flashing_per_ea"][idx],
            total_cost=pipe_count * PRICING["pipe_flashing_per_ea"][idx],
        )
    )

    # Ice & water shield (valleys + eaves first 3ft)
    ice_sqft = li.valley_length_ft * 3 + li.eave_length_ft * 3  # 3ft wide strip
    if ice_sqft == 0:
        ice_sqft = squares * 5  # minimal
    ice_rolls = math.ceil(ice_sqft / ICE_WATER_SQFT_PER_ROLL)
    material_items.append(
        EstimateLineItem(
            category="Materials",
            description="Ice & Water Shield",
            quantity=ice_rolls,
            unit="rolls",
            unit_cost=PRICING["ice_water_per_roll"][idx],
            total_cost=ice_rolls * PRICING["ice_water_per_roll"][idx],
        )
    )

    # Nails
    total_nails = squares * NAILS_PER_SQ
    nail_boxes = math.ceil(total_nails / NAILS_PER_BOX)
    material_items.append(
        EstimateLineItem(
            category="Materials",
            description="Roofing Nails (coil)",
            quantity=nail_boxes,
            unit="boxes",
            unit_cost=PRICING["nails_per_box"][idx],
            total_cost=nail_boxes * PRICING["nails_per_box"][idx],
        )
    )

    # --- Labor ---

    labor_items.append(
        EstimateLineItem(
            category="Labor",
            description="Tear-off & Disposal",
            quantity=round(squares, 1),
            unit="squares",
            unit_cost=PRICING["labor_tearoff_per_sq"][idx],
            total_cost=math.ceil(squares) * PRICING["labor_tearoff_per_sq"][idx],
        )
    )

    labor_items.append(
        EstimateLineItem(
            category="Labor",
            description="Installation",
            quantity=round(squares, 1),
            unit="squares",
            unit_cost=PRICING["labor_install_per_sq"][idx],
            total_cost=math.ceil(squares) * PRICING["labor_install_per_sq"][idx],
        )
    )

    # --- Other ---

    other_items.append(
        EstimateLineItem(
            category="Other",
            description="Dumpster Rental",
            quantity=1,
            unit="flat",
            unit_cost=PRICING["dumpster_flat"][idx],
            total_cost=PRICING["dumpster_flat"][idx],
        )
    )

    other_items.append(
        EstimateLineItem(
            category="Other",
            description="Permits & Fees",
            quantity=1,
            unit="flat",
            unit_cost=PRICING["permits_flat"][idx],
            total_cost=PRICING["permits_flat"][idx],
        )
    )

    # --- Totals ---

    materials_subtotal = sum(item.total_cost for item in material_items)
    labor_subtotal = sum(item.total_cost for item in labor_items)
    other_subtotal = sum(item.total_cost for item in other_items)

    waste_factor_amount = materials_subtotal * WASTE_FACTOR
    overhead_profit_amount = labor_subtotal * OVERHEAD_PROFIT

    grand_total = materials_subtotal + waste_factor_amount + labor_subtotal + overhead_profit_amount + other_subtotal

    return CostEstimate(
        tier=tier,
        material_items=material_items,
        labor_items=labor_items,
        other_items=other_items,
        materials_subtotal=round(materials_subtotal, 2),
        labor_subtotal=round(labor_subtotal, 2),
        other_subtotal=round(other_subtotal, 2),
        waste_factor_amount=round(waste_factor_amount, 2),
        overhead_profit_amount=round(overhead_profit_amount, 2),
        grand_total=round(grand_total, 2),
    )
