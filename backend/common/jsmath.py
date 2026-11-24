"""Helpers that reproduce JavaScript number behaviour.

The risk model was written in JavaScript (frontend src/lib/risk.js). To return exactly the same
scores and texts from the server we need JS semantics where Python differs:

* ``Math.round`` rounds .5 up (towards +infinity); Python's ``round`` rounds half to even.
* ``String(5.0)`` is ``"5"`` in JS but ``"5.0"`` in Python.
* ``Math.imul`` / ``>>> 0`` work on 32-bit unsigned integers.
"""
import math

UINT32 = 0xFFFFFFFF


def js_round(x: float) -> int:
    return math.floor(x + 0.5)


def js_num_str(x) -> str:
    """Format a number the way a JS template literal would (for the values used here)."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def fnv1a_32(text: str) -> int:
    """Port of hashString() in frontend src/lib/seed.js (FNV-1a, 32-bit, unsigned)."""
    h = 2166136261
    for ch in text:
        h ^= ord(ch)
        h = (h * 16777619) & UINT32
    return h
