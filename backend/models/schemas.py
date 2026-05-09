from enum import StrEnum

from pydantic import BaseModel, Field


class RoofShape(StrEnum):
    GABLE = "gable"
    HIP = "hip"
    CROSS_GABLE = "cross-gable"
    CROSS_HIP = "cross-hip"
    GAMBREL = "gambrel"
    MANSARD = "mansard"
    FLAT = "flat"
    SHED = "shed"
    UNKNOWN = "unknown"


class LineItems(BaseModel):
    ridge_length_ft: float = 0
    hip_length_ft: float = 0
    valley_length_ft: float = 0
    rake_length_ft: float = 0
    eave_length_ft: float = 0
    flashing_length_ft: float = 0
    step_flashing_length_ft: float = 0
    drip_edge_length_ft: float = 0
    gutter_length_ft: float = 0


class PitchEstimate(BaseModel):
    pitch: str = "6:12"  # rise:run format
    rise: int = 6
    run: int = 12
    multiplier: float = 1.118
    confidence: float = 0.5


class FootprintSource(BaseModel):
    source: str  # "county_gis", "sam2", "sunroof", "vision_llm"
    footprint_sqft: float
    confidence: float


class RoofMeasurements(BaseModel):
    total_roof_sqft: float
    footprint_sqft: float
    pitch: PitchEstimate
    roof_shape: RoofShape = RoofShape.UNKNOWN
    facet_count: int = 0
    line_items: LineItems = Field(default_factory=LineItems)
    footprint_sources: list[FootprintSource] = []
    confidence: float = 0.0


class MaterialTier(StrEnum):
    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"


class EstimateLineItem(BaseModel):
    category: str
    description: str
    quantity: float
    unit: str
    unit_cost: float
    total_cost: float


class CostEstimate(BaseModel):
    tier: MaterialTier
    material_items: list[EstimateLineItem] = []
    labor_items: list[EstimateLineItem] = []
    other_items: list[EstimateLineItem] = []
    materials_subtotal: float = 0
    labor_subtotal: float = 0
    other_subtotal: float = 0
    waste_factor_amount: float = 0
    overhead_profit_amount: float = 0
    grand_total: float = 0


class PropertyReport(BaseModel):
    address: str
    formatted_address: str = ""
    lat: float = 0
    lng: float = 0
    measurements: RoofMeasurements
    estimates: dict[str, CostEstimate] = {}  # keyed by tier
    satellite_images: list[str] = []
    streetview_images: list[str] = []
    sunroof_image: str | None = None
    sunroof_usable_sqft: float | None = None
    report_date: str = ""
