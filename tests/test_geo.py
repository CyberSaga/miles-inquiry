import math

import pytest

from miles_inquiry.geo import distance_km, haversine_km, round_km, vincenty_km

TPE = (25.0777, 121.233002)
JFK = (40.639447, -73.779317)


def test_tpe_jfk_vincenty():
    assert vincenty_km(*TPE, *JFK) == pytest.approx(12566, abs=5)


def test_tpe_jfk_haversine():
    assert haversine_km(*TPE, *JFK) == pytest.approx(12545, abs=5)


def test_symmetric():
    assert vincenty_km(*TPE, *JFK) == pytest.approx(vincenty_km(*JFK, *TPE), abs=1e-6)
    assert haversine_km(*TPE, *JFK) == pytest.approx(haversine_km(*JFK, *TPE), abs=1e-9)


def test_zero_distance():
    assert vincenty_km(*TPE, *TPE) == 0.0
    assert haversine_km(*TPE, *TPE) == 0.0
    assert vincenty_km(0, 0, 0, 360) == 0.0


def test_near_antipodal_does_not_blow_up():
    km = vincenty_km(0, 0, 0.5, 179.7)
    assert math.isfinite(km) and 19800 < km < 20100


def test_dispatch_and_bad_method():
    assert distance_km(*TPE, *JFK, method="vincenty") == pytest.approx(vincenty_km(*TPE, *JFK))
    assert distance_km(*TPE, *JFK, method="haversine") == pytest.approx(haversine_km(*TPE, *JFK))
    with pytest.raises(ValueError):
        distance_km(*TPE, *JFK, method="euclid")


def test_round_km():
    assert round_km(132.4) == 132 and isinstance(round_km(132.4), int)
    assert round_km(132.5) == 133
    assert round_km(132.456, 1) == 132.5
    assert round_km(132.444, 2) == 132.44
