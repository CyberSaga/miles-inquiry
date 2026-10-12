"""Great-circle / geodesic distance on the WGS-84 ellipsoid.

Two methods are provided:

* ``vincenty`` – Vincenty's inverse formula on the WGS-84 ellipsoid (default).
  This is what most "great circle" web tools report (accuracy ~0.5 mm).
* ``haversine`` – spherical great-circle distance using the WGS-84 mean
  radius (6371.0088 km).  About 0.1–0.3 % shorter than the ellipsoidal value
  on long routes.

No third-party dependencies.
"""
from __future__ import annotations

import math

# WGS-84 constants
WGS84_A = 6378137.0                 # semi-major axis (m)
WGS84_F = 1 / 298.257223563         # flattening
WGS84_B = WGS84_A * (1 - WGS84_F)   # semi-minor axis (m)
MEAN_RADIUS_KM = 6371.0088          # WGS-84 mean radius (km)

METHODS = ("vincenty", "haversine")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Spherical great-circle distance in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * MEAN_RADIUS_KM * math.asin(math.sqrt(a))


def vincenty_km(lat1: float, lon1: float, lat2: float, lon2: float,
                max_iter: int = 200, tol: float = 1e-12) -> float:
    """Geodesic distance on the WGS-84 ellipsoid (Vincenty inverse), in km.

    Falls back to the haversine value for the rare nearly-antipodal pairs on
    which Vincenty's iteration does not converge.
    """
    if lat1 == lat2 and (lon1 - lon2) % 360.0 == 0.0:
        return 0.0

    a, b, f = WGS84_A, WGS84_B, WGS84_F
    U1 = math.atan((1 - f) * math.tan(math.radians(lat1)))
    U2 = math.atan((1 - f) * math.tan(math.radians(lat2)))
    L = math.radians(lon2 - lon1)
    sinU1, cosU1 = math.sin(U1), math.cos(U1)
    sinU2, cosU2 = math.sin(U2), math.cos(U2)

    lam = L
    for _ in range(max_iter):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.sqrt((cosU2 * sin_lam) ** 2 + (cosU1 * sinU2 - sinU1 * cosU2 * cos_lam) ** 2)
        if sin_sigma == 0.0:
            return 0.0  # coincident points
        cos_sigma = sinU1 * sinU2 + cosU1 * cosU2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cosU1 * cosU2 * sin_lam / sin_sigma
        cos_sq_alpha = 1 - sin_alpha ** 2
        if cos_sq_alpha == 0.0:
            cos2_sigma_m = 0.0  # equatorial line
        else:
            cos2_sigma_m = cos_sigma - 2 * sinU1 * sinU2 / cos_sq_alpha
        C = f / 16 * cos_sq_alpha * (4 + f * (4 - 3 * cos_sq_alpha))
        lam_prev = lam
        lam = L + (1 - C) * f * sin_alpha * (
            sigma + C * sin_sigma * (cos2_sigma_m + C * cos_sigma * (-1 + 2 * cos2_sigma_m ** 2))
        )
        if abs(lam - lam_prev) < tol:
            break
    else:
        # Did not converge (nearly antipodal) – fall back to spherical value.
        return haversine_km(lat1, lon1, lat2, lon2)

    u_sq = cos_sq_alpha * (a ** 2 - b ** 2) / b ** 2
    A = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    B = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    delta_sigma = B * sin_sigma * (
        cos2_sigma_m + B / 4 * (
            cos_sigma * (-1 + 2 * cos2_sigma_m ** 2)
            - B / 6 * cos2_sigma_m * (-3 + 4 * sin_sigma ** 2) * (-3 + 4 * cos2_sigma_m ** 2)
        )
    )
    return b * A * (sigma - delta_sigma) / 1000.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float,
                method: str = "vincenty") -> float:
    """Dispatch on *method* (``vincenty`` or ``haversine``)."""
    if method == "vincenty":
        return vincenty_km(lat1, lon1, lat2, lon2)
    if method == "haversine":
        return haversine_km(lat1, lon1, lat2, lon2)
    raise ValueError(f"unknown distance method: {method!r} (expected one of {METHODS})")


def round_km(km: float, decimals: int = 0):
    """Round half-up; returns ``int`` when *decimals* is 0."""
    if decimals <= 0:
        return int(math.floor(km + 0.5))
    factor = 10 ** decimals
    return math.floor(km * factor + 0.5) / factor
