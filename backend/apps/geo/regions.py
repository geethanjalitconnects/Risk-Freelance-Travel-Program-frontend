"""Our own rules for areas created from picked places (no Google data is stored by these)."""
import hashlib

from .models import Coast

# Seasonal weather model: east = north-east monsoon (Oct-Dec), west = south-west monsoon (Jun-Sep).
EAST = {"tamil nadu", "puducherry", "andhra pradesh", "odisha", "west bengal"}
WEST = {"kerala", "goa", "maharashtra", "gujarat", "lakshadweep"}


def coast_for_state(state: str) -> str:
    s = (state or "").strip().lower()
    if s in EAST:
        return Coast.EAST
    if s in WEST:
        return Coast.WEST
    return Coast.INLAND


def area_code(state: str, district: str, name: str) -> str:
    """Stable 11-character code for an area, e.g. "A3F9C21B07D"."""
    key = "|".join(p.strip().lower() for p in (state, district, name))
    return "A" + hashlib.sha1(key.encode()).hexdigest()[:10].upper()
