from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from miles_inquiry.airports import Airport, AirportDB  # noqa: E402
from miles_inquiry.lookup import Lookup  # noqa: E402

# Small synthetic airport set – no dependency on data/airports.csv for unit tests.
SYNTH_AIRPORTS = [
    Airport("TPE", "Taiwan Taoyuan International Airport", "Taoyuan", "TW", "large_airport", 25.0777, 121.233002),
    Airport("TSA", "Taipei Songshan International Airport", "Taipei", "TW", "large_airport", 25.067244, 121.552822),
    Airport("KHH", "Kaohsiung International Airport", "Kaohsiung", "TW", "large_airport", 22.577101, 120.349998),
    Airport("RMQ", "Taichung International Airport", "Taichung", "TW", "large_airport", 24.2647, 120.621002),
    Airport("MZG", "Penghu Magong Airport", "Huxi", "TW", "large_airport", 23.568701, 119.627998),
    Airport("KNH", "Kinmen Airport", "Shang-I", "TW", "medium_airport", 24.4279, 118.359001),
    Airport("JFK", "John F. Kennedy International Airport", "New York", "US", "large_airport", 40.639447, -73.779317),
    Airport("HKG", "Hong Kong International Airport", "Hong Kong", "HK", "large_airport", 22.31184, 113.914862),
    Airport("SEA", "Seattle–Tacoma International Airport", "Seattle", "US", "large_airport", 47.447943, -122.310276),
    Airport("LAX", "Los Angeles International Airport", "Los Angeles", "US", "large_airport", 33.942501, -118.407997),
    Airport("TAS", "Tashkent International Airport", "Tashkent", "UZ", "large_airport", 41.2579, 69.281197),
    Airport("SIA", "Xi'an Xiguan Airport", "Xi'an", "CN", "medium_airport", 34.376701, 109.120003, scheduled_service=False),
    Airport("PNH", "Phnom Penh International Airport", "Phnom Penh", "KH", "large_airport", 11.547155, 104.844699, scheduled_service=False),
    Airport("SAI", "Siem Reap-Angkor International Airport", "Siem Reap", "KH", "large_airport", 13.36974, 104.223831),
]

LOOKUP_CSV = "\ufeff" + """value,iata,review,note
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
