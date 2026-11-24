"""Distance and route-profile maths, ported from frontend src/data/cities.js and src/lib/risk.js.

A ride's km is estimated when it is published (straight line x 1.28 between the picked places).
Route risk inputs come from a RouteProfile row when an admin has entered one for the two areas,
otherwise from the deterministic default below.
"""
import math

from common.jsmath import fnv1a_32, js_round


def haversine_km(a_lat, a_lng, b_lat, b_lng) -> float:
    r = 6371
    rad = math.radians
    d_lat = rad(b_lat - a_lat)
    d_lng = rad(b_lng - a_lng)
    x = math.sin(d_lat / 2) ** 2 + math.cos(rad(a_lat)) * math.cos(rad(b_lat)) * math.sin(d_lng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def road_km(a, b) -> int:
    """Straight-line distance padded by a typical road-winding factor. ``a``/``b`` have lat/lng."""
    return max(20, js_round(haversine_km(a.lat, a.lng, b.lat, b.lng) * 1.28))


def route_key(code_a: str, code_b: str) -> str:
    return "-".join(sorted([code_a, code_b]))


def compute_route_profile(a, b, km=None) -> dict:
    """Deterministic default profile; identical to routeProfile() in risk.js.

    ``a``/``b`` need a ``code``; they also need lat/lng when ``km`` isn't given.
    """
    h = fnv1a_32(route_key(a.code, b.code))
    return {
        "km": km if km is not None else road_km(a, b),
        "incident_index": js_round((2 + (h % 700) / 100) * 10) / 10,  # 2.0 - 9.0
        "highway_share": 55 + ((h >> 3) % 40),
        "ghat_sections": (h >> 5) % 3,
    }


AVERAGE_SPEED_KMH = 58


def duration_minutes(km: int) -> int:
    """Driving time rounded to 5 minutes, minimum 30 (same as Publish.jsx / rides.js)."""
    return max(30, js_round(((km / AVERAGE_SPEED_KMH) * 60) / 5) * 5)
