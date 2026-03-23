"""
Pre-orchestrator location resolution for weather and tooling.

Call ``resolve_entry_request_location`` on the entry-request dict before the
orchestrator runs. It sets top-level ``weather_latitude`` / ``weather_longitude``
when missing, using (in order):

1. Already present top-level ``weather_latitude`` / ``weather_longitude`` — no-op.
2. ``request_payload.latitude`` / ``longitude`` (or ``lat`` / ``lon``) — copied up.
3. ``request_payload.location_query`` — geocoded via Google; on success sets
   ``weather_location_formatted_address`` to Google’s **resolved** formatted
   address (do not pre-fill that field in ingress JSON).

**Requires** env var ``GOOGLE_MAPS_API_KEY`` when step 3 runs. If the key is
missing or geocoding fails, ``resolve_entry_request_location`` raises
``ValueError``.

If none of the above apply, the dict is unchanged (environment tools fall back to
waypoints or default US centroid).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

import httpx

from dotenv import load_dotenv
load_dotenv()

GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def geocode_google(address: str, *, region: str = "us") -> Tuple[float, float, str]:
    """
    Return (lat, lon, formatted_address) for the first Geocoding API result.

    Raises ValueError if the API key is missing, status is not OK, or there are
    no results.
    """
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not key:
        raise ValueError(
            "GOOGLE_MAPS_API_KEY is not set; cannot resolve location_query to coordinates."
        )
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            GOOGLE_GEOCODE_URL,
            params={"address": address, "key": key, "region": region},
        )
        response.raise_for_status()
        payload = response.json()

    status = payload.get("status")
    if status != "OK":
        err = payload.get("error_message", "")
        raise ValueError(f"Geocoding failed: status={status} {err}".strip())

    results = payload.get("results") or []
    if not results:
        raise ValueError(f"Geocoding returned no results for: {address!r}")

    loc = results[0]["geometry"]["location"]
    lat, lon = float(loc["lat"]), float(loc["lng"])
    formatted = results[0].get("formatted_address", address)
    return lat, lon, formatted


def resolve_entry_request_location(request: Dict[str, Any]) -> None:
    """
    Mutate ``request`` in place: set ``weather_latitude`` and ``weather_longitude``
    when they can be determined without overwriting existing values.

    Returns ``None`` on purpose—callers read results from ``request`` (no separate
    return value).
    """
    if request.get("weather_latitude") is not None and request.get("weather_longitude") is not None:
        return

    rp = request.get("request_payload")
    if not isinstance(rp, dict):
        rp = {}

    lat = rp.get("latitude", rp.get("lat"))
    lon = rp.get("longitude", rp.get("lon"))
    if lat is not None and lon is not None:
        request["weather_latitude"] = float(lat)
        request["weather_longitude"] = float(lon)
        return

    query = rp.get("location_query")
    if isinstance(query, str):
        query = query.strip()
    else:
        query = ""

    if not query:
        return

    lat, lon, formatted = geocode_google(query)
    request["weather_latitude"] = lat
    request["weather_longitude"] = lon
    request["weather_location_formatted_address"] = formatted
    return None
