from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from miles_inquiry.airports import SOURCE_OURAIRPORTS, Airport, AirportDB  # noqa: E402
from miles_inquiry.lookup import Lookup  # noqa: E402

# Small synthetic airport set – no dependency on data/ files for unit tests.
# Coordinates are the 3-decimal values from greatcirclemap.com's airports.csv, so
# distances equal what the website displays (TPE-JFK 12566, MZG-KHH 132, TSA-MZG 256).
SYNTH_AIRPORTS = [
    Airport("TPE", "Taiwan Taoyuan International Airport", "Taipei", "TW", "large_airport", 25.078, 121.233),
    Airport("TSA", "Taipei Songshan Airport", "Taipei", "TW", "large_airport", 25.069, 121.552),
    Airport("KHH", "Kaohsiung International Airport", "Kaohsiung", "TW", "large_airport", 22.577, 120.350),
    Airport("RMQ", "Taichung Ching Chuang Kang Airport", "Taichung", "TW", "large_airport", 24.265, 120.621),
    Airport("MZG", "Makung Airport", "Makung", "TW", "large_airport", 23.569, 119.628),
    Airport("KNH", "Kinmen Airport", "Kinmen", "TW", "medium_airport", 24.428, 118.359),
    Airport("JFK", "John F Kennedy International Airport", "New York", "US", "large_airport", 40.640, -73.779),
    Airport("HKG", "Hong Kong International Airport", "Hong Kong", "HK", "large_airport", 22.309, 113.915),
    Airport("SEA", "Seattle Tacoma International Airport", "Seattle", "US", "large_airport", 47.449, -122.309),
    Airport("LAX", "Los Angeles International Airport", "Los Angeles", "US", "large_airport", 33.942, -118.408),
    Airport("TAS", "Tashkent International Airport", "Tashkent", "UZ", "large_airport", 41.258, 69.281),
    Airport("SIA", "Xi'an Xiguan Airport", "Xi'an", "CN", "medium_airport", 34.377, 109.120, scheduled_service=False),
    Airport("PNH", "Phnom Penh International Airport", "Phnom Penh", "KH", "large_airport", 11.547, 104.844, scheduled_service=False),
    # SAI is absent from the website's data → coordinates come from OurAirports (fallback)
    Airport("SAI", "Siem Reap-Angkor International Airport", "Siem Reap", "KH", "large_airport", 13.36974, 104.223831,
            source=SOURCE_OURAIRPORTS),
]

LOOKUP_CSV = "﻿" + """value,iata,review,note
# comment line
澎湖,MZG,,
高雄,KHH,,
金門,KNH,,
台北,TSA,yes,台北預設松山；國際線請改 TPE
台中,RMQ,,
新竹,,,新竹無民航機場
西雅圖,SEA,,
洛杉磯,LAX,,
HONG KONG,HKG,,
LGA/EWR,LGA,是,原值含兩個機場
TAS,TSA,,疑為 TSA 誤植
SIA,SAI,,SIA 已停用
"""


@pytest.fixture(scope="session")
def airports() -> AirportDB:
    return AirportDB(SYNTH_AIRPORTS)


@pytest.fixture
def lookup_path(tmp_path: Path) -> Path:
    p = tmp_path / "lookup.csv"
    p.write_text(LOOKUP_CSV, encoding="utf-8")
    return p


@pytest.fixture
def lookup(lookup_path: Path, airports: AirportDB) -> Lookup:
    return Lookup.load(lookup_path, airports)
