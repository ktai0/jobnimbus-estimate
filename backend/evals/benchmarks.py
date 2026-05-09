"""
Single source of truth for benchmark properties used in evals.
Consolidates data from calibrate.py, test_pipeline.py, and run_test.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BenchmarkProperty:
    """A property with known reference measurements for evaluation."""

    name: str
    address: str
    lat: float
    lng: float
    ref_a_sqft: float | None = None
    ref_b_sqft: float | None = None
    known_pitch: str | None = None
    known_rise: int | None = None

    @property
    def ref_avg(self) -> float | None:
        """Average of two reference measurements."""
        if self.ref_a_sqft is not None and self.ref_b_sqft is not None:
            return (self.ref_a_sqft + self.ref_b_sqft) / 2
        return None


# Calibration properties — have known pitch and two reference sqft measurements
CALIBRATION_PROPERTIES: list[BenchmarkProperty] = [
    BenchmarkProperty(
        name="humble_tx",
        address="21106 Kenswick Meadows Ct, Humble, TX 77338",
        lat=30.019412,
        lng=-95.311886,
        ref_a_sqft=2443,
        ref_b_sqft=2343,
        known_pitch="6:12",
        known_rise=6,
    ),
    BenchmarkProperty(
        name="spring_tx",
        address="5914 Copper Lilly Lane, Spring, TX 77389",
        lat=30.111684,
        lng=-95.509071,
        ref_a_sqft=4391,
        ref_b_sqft=4296,
        known_pitch="8:12",
        known_rise=8,
    ),
    BenchmarkProperty(
        name="cape_coral_fl",
        address="122 NW 13th Ave, Cape Coral, FL 33993",
        lat=26.655194,
        lng=-82.000614,
        ref_a_sqft=2917,
        ref_b_sqft=2851,
        known_pitch="6:12",
        known_rise=6,
    ),
    BenchmarkProperty(
        name="orland_park_il",
        address="14132 Trenton Ave, Orland Park, IL 60462",
        lat=41.633227,
        lng=-87.843128,
        ref_a_sqft=2990,
        ref_b_sqft=2935,
        known_pitch="4:12",
        known_rise=4,
    ),
    BenchmarkProperty(
        name="nixa_mo",
        address="835 S Cobble Creek, Nixa, MO 65714",
        lat=37.028963,
        lng=-93.283332,
        ref_a_sqft=3070,
        ref_b_sqft=3017,
        known_pitch="8:12",
        known_rise=8,
    ),
]

# Test properties — used for validation, no reference measurements
TEST_PROPERTIES: list[BenchmarkProperty] = [
    BenchmarkProperty(
        name="thornton_co",
        address="3561 E 102nd Ct, Thornton, CO 80229",
        lat=39.8811632,
        lng=-104.9453839,
    ),
    BenchmarkProperty(
        name="springfield_mo_1",
        address="1612 S Canton Ave, Springfield, MO 65802",
        lat=37.1860933,
        lng=-93.3695914,
    ),
    BenchmarkProperty(
        name="houston_tx",
        address="6310 Laguna Bay Court, Houston, TX 77041",
        lat=29.8603157,
        lng=-95.5903959,
    ),
    BenchmarkProperty(
        name="springfield_mo_2",
        address="3820 E Rosebrier St, Springfield, MO 65809",
        lat=37.1596926,
        lng=-93.2159481,
    ),
    BenchmarkProperty(
        name="newport_news_va",
        address="1261 20th Street, Newport News, VA 23607",
        lat=36.9845554,
        lng=-76.4016532,
    ),
]
