import math

import pytest

from miles_inquiry.geo import (DEFAULT_METHOD, HAVE_GEOGRAPHICLIB, METHODS, distance_km, geodesic_km,
                               haversine_km, round_km, site_km, vincenty_km)

# Coordinates exactly as in greatcirclemap.com's airports.csv (3 decimals)
TPE = (25.078, 121.233)
JFK = (40.640, -73.779)
MZG = (23.569, 119.628)
KHH = (22.577, 120.350)
TSA = (25.069, 121.552)
SHA = (31.198, 121.336)


def test_default_is_geodesic_with_geographiclib():
    assert DEFAULT_METHOD == "geodesic" and "geodesic" in METHODS
    assert HAVE_GEOGRAPHICLIB, "geographiclib must be installed for results to match the website exactly"


@pytest.mark.parametrize("a, b, expected", [
    (TPE, JFK, 12566),
    (MZG, KHH, 132),
    (TSA, MZG, 256),
    (SHA, TSA, 680),
])
def test_matches_greatcirclemap_display(a, b, expected):
    """These are the numbers the website displays for the same airport pairs."""
    assert site_km(*a, *b) == expected
    assert round_km(distance_km(*a, *b)) == expected                 # default method
    assert round_km(distance_km(*a, *b, method="geodesic")) == expected
    assert round_km(distance_km(*b, *a)) == expected                 # symmetric


def test_vincenty_agrees_with_geodesic():
    for a, b in ((TPE, JFK), (MZG, KHH), (TSA, MZG), (SHA, TSA)):
        assert vincenty_km(*a, *b) == pytest.approx(geodesic_km(*a, *b), abs=0.001)


def test_tpe_jfk_haversine_is_shorter():
    assert haversine_km(*TPE, *JFK) == pytest.approx(12545, abs=5)
    assert haversine_km(*TPE, *JFK) < geodesic_km(*TPE, *JFK)


def test_symmetric():
    assert geodesic_km(*TPE, *JFK) == pytest.approx(geodesic_km(*JFK, *TPE), abs=1e-6)
    assert vincenty_km(*TPE, *JFK) == pytest.approx(vincenty_km(*JFK, *TPE), abs=1e-6)
    assert haversine_km(*TPE, *JFK) == pytest.approx(haversine_km(*JFK, *TPE), abs=1e-9)


def test_zero_distance():
    assert geodesic_km(*TPE, *TPE) == 0.0
    assert vincenty_km(*TPE, *TPE) == 0.0
    assert haversine_km(*TPE, *TPE) == 0.0
    assert vincenty_km(0, 0, 0, 360) == 0.0


def test_near_antipodal_does_not_blow_up():
    for fn in (geodesic_km, vincenty_km):
        km = fn(0, 0, 0.5, 179.7)
        assert math.isfinite(km) and 19800 < km < 20100


def test_dispatch_and_bad_method():
    assert distance_km(*TPE, *JFK, method="vincenty") == pytest.approx(vincenty_km(*TPE, *JFK))
    assert distance_km(*TPE, *JFK, method="haversine") == pytest.approx(haversine_km(*TPE, *JFK))
    with pytest.raises(ValueError):
        distance_km(*TPE, *JFK, method="euclid")


def test_round_km_is_half_up_like_js_math_round():
    assert round_km(132.4) == 132 and isinstance(round_km(132.4), int)
    assert round_km(132.5) == 133          # Python's round(132.5) would give 132
    assert round_km(133.5) == 134
    assert round_km(0.5) == 1 and round_km(0.49999) == 0
    assert round_km(132.456, 1) == 132.5
    assert round_km(132.444, 2) == 132.44
    assert round_km(132.45, 1) == 132.5
