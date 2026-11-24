"""OpenRouteService distance matrix (road distances between cities).

Used once, by `manage.py fetch_route_distances`; the results are stored in RouteProfile.km, so the
app never calls ORS while serving requests. One matrix request covers every city pair (14 cities
-> 196 elements), well inside the free plan. OpenStreetMap data (c) OpenStreetMap contributors.
"""
import json
import urllib.error
import urllib.request

from django.conf import settings


class ORSError(Exception):
    pass


def distance_matrix_km(cities) -> dict:
    """{(code_a, code_b): km} for every ordered pair of ``cities`` (objects with code/lat/lng)."""
    if not settings.ORS_API_KEY:
        raise ORSError("ORS_API_KEY is not set.")
    cities = list(cities)
    body = json.dumps(
        {"locations": [[c.lng, c.lat] for c in cities], "metrics": ["distance"], "units": "km"}
    ).encode()
    req = urllib.request.Request(
        settings.ORS_MATRIX_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": settings.ORS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "vconnects-backend",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.ORS_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise ORSError(f"OpenRouteService returned HTTP {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ORSError(f"OpenRouteService request failed: {e}") from e

    rows = data.get("distances")
    if not isinstance(rows, list) or len(rows) != len(cities):
        raise ORSError("Unexpected response from OpenRouteService.")
    out = {}
    for i, a in enumerate(cities):
        for j, b in enumerate(cities):
            if i != j and rows[i][j] is not None:
                out[(a.code, b.code)] = float(rows[i][j])
    return out
