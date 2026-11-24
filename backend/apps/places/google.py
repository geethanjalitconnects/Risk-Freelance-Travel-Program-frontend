"""Google Places API (New) client: Autocomplete (New) and Place Details (New).

The key (GOOGLE_MAPS_API_KEY) is sent only in the X-Goog-Api-Key header, never in URLs, logs or
error messages. Only the standard library is used.

Billing notes (see the Places pricing docs):
- Autocomplete is restricted to India with includedRegionCodes ["in"]. regionCode only affects
  formatting/ranking. locationBias is always sent: without it Google biases by the caller's IP,
  which is our server.
- Place Details asks only for `id`, `addressComponents` and `location`, all "Essentials" tier.
  Never add displayName (Pro tier): the whole call would be billed at the highest tier requested.
- The same session token is sent with every autocomplete request of a search and with the final
  Place Details call, which closes the session.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

API = "https://places.googleapis.com/v1"

AUTOCOMPLETE_FIELDS = ",".join([
    "suggestions.placePrediction.placeId",
    "suggestions.placePrediction.text.text",
    "suggestions.placePrediction.structuredFormat.mainText.text",
    "suggestions.placePrediction.structuredFormat.secondaryText.text",
])
DETAILS_FIELDS = "id,addressComponents,location"  # all three are Essentials tier

# Bounding box of India, used as a soft bias. The hard restriction is includedRegionCodes.
INDIA_BIAS = {"rectangle": {
    "low": {"latitude": 6.5, "longitude": 68.1},
    "high": {"latitude": 35.7, "longitude": 97.4},
}}


class PlacesError(Exception):
    """A Google call failed. ``status`` is the HTTP status (0 = network/timeout)."""

    def __init__(self, status=0, reason=""):
        super().__init__(f"Google Places error {status} {reason}".strip())
        self.status, self.reason = status, reason


def configured() -> bool:
    return bool(settings.GOOGLE_MAPS_API_KEY)


def _call(method, url, *, body=None, field_mask):
    headers = {
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": field_mask,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    path = urllib.parse.urlsplit(url).path
    try:
        with urllib.request.urlopen(req, timeout=settings.PLACES_TIMEOUT_SECONDS) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read() or b"{}").get("error", {}).get("status", "")
        except ValueError:
            reason = ""
        logger.warning("Google Places %s %s failed: HTTP %s %s", method, path.split("/places/")[0], e.code, reason)
        raise PlacesError(e.code, reason) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        logger.warning("Google Places %s unreachable: %s", method, type(e).__name__)
        raise PlacesError(0, type(e).__name__) from None


def autocomplete(text, session_token):
    """Up to 5 suggestions: [{placeId, text, main, secondary}]."""
    body = {
        "input": text,
        "sessionToken": session_token,
        "includedRegionCodes": ["in"],
        "regionCode": "in",
        "languageCode": "en",
        "locationBias": INDIA_BIAS,
    }
    types = [t for t in settings.PLACES_PRIMARY_TYPES if t]
    if types:
        body["includedPrimaryTypes"] = types
    res = _call("POST", f"{API}/places:autocomplete", body=body, field_mask=AUTOCOMPLETE_FIELDS)
    out = []
    for s in res.get("suggestions", []):
        p = s.get("placePrediction")
        if not p or not p.get("placeId"):
            continue
        fmt = p.get("structuredFormat") or {}
        full = (p.get("text") or {}).get("text", "")
        out.append({
            "placeId": p["placeId"],
            "text": full,
            "main": (fmt.get("mainText") or {}).get("text") or full,
            "secondary": (fmt.get("secondaryText") or {}).get("text", ""),
        })
    return out


def details(place_id, session_token):
    """The place's address components and location (Essentials tier). Closes the autocomplete session."""
    qs = urllib.parse.urlencode({"languageCode": "en", "regionCode": "in", "sessionToken": session_token})
    url = f"{API}/places/{urllib.parse.quote(place_id, safe='')}?{qs}"
    return _call("GET", url, field_mask=DETAILS_FIELDS)


GEOCODE_API = "https://maps.googleapis.com/maps/api/geocode/json"
# Area-level results only (not street addresses), so the answer is a taluk / locality.
GEOCODE_RESULT_TYPES = "sublocality|locality|administrative_area_level_3"


def reverse_geocode(lat, lng):
    """Geocoding API (reverse): the area-level place at a position.

    -> {placeId, label, components (Places API (New) shape), location: (lat, lng)} or None.
    The Geocoding API takes the key as a URL parameter, so the URL is never logged.
    """
    qs = urllib.parse.urlencode({
        "latlng": f"{lat:.6f},{lng:.6f}", "result_type": GEOCODE_RESULT_TYPES,
        "language": "en", "region": "in", "key": settings.GOOGLE_MAPS_API_KEY,
    })
    req = urllib.request.Request(f"{GEOCODE_API}?{qs}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=settings.PLACES_TIMEOUT_SECONDS) as res:
            data = json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        logger.warning("Google Geocoding failed: HTTP %s", e.code)
        raise PlacesError(e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        logger.warning("Google Geocoding unreachable: %s", type(e).__name__)
        raise PlacesError(0, type(e).__name__) from None

    status = data.get("status", "")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        logger.warning("Google Geocoding status %s", status)  # REQUEST_DENIED, OVER_QUERY_LIMIT, ...
        raise PlacesError(403 if status == "REQUEST_DENIED" else 429 if status == "OVER_QUERY_LIMIT" else 502, status)
    results = data.get("results") or []
    if not results:
        return None
    r = results[0]
    comps = [
        {"longText": c.get("long_name", ""), "shortText": c.get("short_name", ""), "types": c.get("types", [])}
        for c in r.get("address_components", [])
    ]
    loc = (r.get("geometry") or {}).get("location") or {}
    if not r.get("place_id") or "lat" not in loc:
        return None
    label = comps[0]["longText"] if comps else ""
    return {"placeId": r["place_id"], "label": label, "components": comps, "location": (loc["lat"], loc["lng"])}
