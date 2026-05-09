"""
PDF report generation using Jinja2 templates and WeasyPrint.
"""

import base64
import logging
import mimetypes
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from models.schemas import PropertyReport

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def _format_currency(value: float | int | None) -> str:
    """Format a number as USD currency string."""
    if value is None:
        return "$0.00"
    return f"${value:,.2f}"


def _format_number(value: float | int | None) -> str:
    """Format a number with comma separators, no decimals."""
    if value is None:
        return "0"
    return f"{value:,.0f}"


def _image_to_data_uri(file_path: str) -> str | None:
    """Read an image file and return a base64 data URI."""
    resolved = Path(file_path).resolve()
    if not resolved.exists():
        logger.warning("Image not found: %s", resolved)
        return None

    mime, _ = mimetypes.guess_type(str(resolved))
    if not mime:
        mime = "image/png"

    with open(resolved, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")

    return f"data:{mime};base64,{data}"


def generate_pdf(report: PropertyReport, output_dir: str) -> str:
    """
    Generate a PDF report from a PropertyReport.

    Args:
        report: The completed property report.
        output_dir: Directory to write the PDF into.

    Returns:
        Absolute path to the generated PDF file.
    """
    logger.info("Generating PDF report for %s", report.address)

    # Convert images to base64 data URIs
    satellite_image_uri = None
    if report.satellite_images:
        satellite_image_uri = _image_to_data_uri(report.satellite_images[0])

    streetview_image_uris = []
    for img_path in report.streetview_images[:4]:
        uri = _image_to_data_uri(img_path)
        if uri:
            streetview_image_uris.append(uri)

    # Format report date
    try:
        dt = datetime.fromisoformat(report.report_date)
        report_date_formatted = dt.strftime("%B %d, %Y")
    except (ValueError, TypeError):
        report_date_formatted = report.report_date or datetime.now().strftime("%B %d, %Y")

    # Extract measurement data
    m = report.measurements
    line_items = [
        ("Ridge", m.line_items.ridge_length_ft),
        ("Hip", m.line_items.hip_length_ft),
        ("Valley", m.line_items.valley_length_ft),
        ("Rake", m.line_items.rake_length_ft),
        ("Eave", m.line_items.eave_length_ft),
        ("Flashing", m.line_items.flashing_length_ft),
        ("Step Flashing", m.line_items.step_flashing_length_ft),
        ("Drip Edge", m.line_items.drip_edge_length_ft),
        ("Gutter", m.line_items.gutter_length_ft),
    ]

    # Extract estimates
    estimates = report.estimates
    standard_estimate = estimates.get("standard")
    economy_estimate = estimates.get("economy")
    premium_estimate = estimates.get("premium")

    # Build template context
    context = {
        "address": report.address,
        "formatted_address": report.formatted_address,
        "lat": report.lat,
        "lng": report.lng,
        "report_date_formatted": report_date_formatted,
        "confidence": m.confidence,
        "satellite_image_uri": satellite_image_uri,
        "streetview_image_uris": streetview_image_uris,
        "total_roof_sqft": m.total_roof_sqft,
        "footprint_sqft": m.footprint_sqft,
        "pitch_display": m.pitch.pitch,
        "pitch_multiplier": f"{m.pitch.multiplier:.3f}",
        "roof_shape": m.roof_shape.replace("-", " ").title(),
        "facet_count": m.facet_count,
        "footprint_sources": [src.model_dump() for src in m.footprint_sources],
        "line_items": line_items,
        "estimates": {k: v.model_dump() for k, v in estimates.items()},
        "standard_estimate": standard_estimate.model_dump() if standard_estimate else None,
        "economy_estimate": economy_estimate.model_dump() if economy_estimate else None,
        "premium_estimate": premium_estimate.model_dump() if premium_estimate else None,
    }

    # Render template
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    env.filters["format_currency"] = _format_currency
    env.filters["format_number"] = _format_number
    template = env.get_template("report.html")
    html_content = template.render(**context)

    # Generate PDF
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(output_dir, "report.pdf")
    HTML(string=html_content).write_pdf(pdf_path)

    logger.info("PDF report saved to %s", pdf_path)
    return os.path.abspath(pdf_path)
