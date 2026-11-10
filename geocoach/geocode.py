"""Offline reverse geocoding of guesses to an ISO country code."""

from __future__ import annotations

from functools import lru_cache

import pycountry


def country_of(lat: float, lng: float) -> str:
    import reverse_geocoder as rg

    hit = rg.search((lat, lng), mode=1)
    return (hit[0]["cc"] if hit else "").lower()


@lru_cache(maxsize=512)
def country_name(code: str) -> str:
    c = pycountry.countries.get(alpha_2=code.upper()) if code else None
    return c.name if c else code.upper()
