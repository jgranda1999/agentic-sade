"""
Environment Agent Tools — manufacturer constraints (mock file) and weather (Open-Meteo).

retrieveEnvironment uses Open-Meteo for live US conditions unless use_mock_weather is true.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple

from agents import function_tool
from models import (
    RawConditions,
    SpatialConstraints,
    ManufacturerFC,
)

from tools.entry_request_fields import entry_time_iso
from tools.open_meteo import fetch_forecast_json, raw_conditions_from_forecast_json

# When the request has no coordinates (e.g. some ZONE payloads), use geographic US centroid.
DEFAULT_US_WEATHER_LAT = float(os.environ.get("SADE_WEATHER_LAT", "39.8283"))
DEFAULT_US_WEATHER_LON = float(os.environ.get("SADE_WEATHER_LON", "-98.5795"))


def _extract_lat_lon(data: Dict[str, Any]) -> Tuple[float, float]:
    """Resolve weather location: optional overrides, then waypoints/polygon, else default."""
    lat = data.get("weather_latitude")
    lon = data.get("weather_longitude")
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    rp_top = data.get("request_payload")
    if isinstance(rp_top, dict):
        la = rp_top.get("latitude", rp_top.get("lat"))
        lo = rp_top.get("longitude", rp_top.get("lon"))
        if la is not None and lo is not None:
            return float(la), float(lo)
    req = data.get("request") or {}
    rp = req.get("request_payload") or {}
    wps = req.get("waypoints") or rp.get("waypoints") or []
    if isinstance(wps, list) and len(wps) > 0:
        first = wps[0]
        la, lo = first.get("lat"), first.get("lon")
        if la is not None and lo is not None:
            return float(la), float(lo)
    poly = req.get("polygon") or rp.get("polygon") or []
    if isinstance(poly, list) and len(poly) > 0:
        first = poly[0]
        la, lo = first.get("lat"), first.get("lon")
        if la is not None and lo is not None:
            return float(la), float(lo)
    return DEFAULT_US_WEATHER_LAT, DEFAULT_US_WEATHER_LON


def _retrieve_environment_mock(entry_time: str, env_profile: str) -> RawConditions:
    """
    Deterministic profiles for tests. env_profile: "good" | "medium" | "bad".
    """
    try:
        time_str = entry_time.replace("Z", "+00:00") if entry_time.endswith("Z") else entry_time
        dt = datetime.fromisoformat(time_str)
        hour = dt.hour
        if 6 <= hour < 18:
            light = "daylight"
        elif hour == 6 or hour == 18:
            light = "dusk" if hour == 18 else "dawn"
        else:
            light = "night"
    except Exception:
        light = "daylight"

    spatial = SpatialConstraints(
        airspace_class="Class E",
        no_fly_zones=[],
        restricted_areas=[],
    )

    raw_conditions_wind_visibility_good = RawConditions(
        wind=5.2,
        wind_gust=8.0,
        precipitation="none",
        visibility=10.0,
        light_conditions=light,
        spatial_constraints=spatial,
    )

    raw_conditions_wind_visibility_medium = RawConditions(
        wind=16.0,
        wind_gust=17.8,
        precipitation="none",
        visibility=10.0,
        light_conditions=light,
        spatial_constraints=spatial,
    )

    raw_conditions_wind_visibility_bad = RawConditions(
        wind=21.0,
        wind_gust=23.5,
        precipitation="moderate",
        visibility=2.0,
        light_conditions=light,
        spatial_constraints=spatial,
    )

    if env_profile == "medium":
        return raw_conditions_wind_visibility_medium
    if env_profile == "bad":
        return raw_conditions_wind_visibility_bad
    return raw_conditions_wind_visibility_good


def _retrieve_environment_live(full_data: Dict[str, Any]) -> RawConditions:
    entry_time = entry_time_iso(full_data)
    lat, lon = _extract_lat_lon(full_data)
    forecast = fetch_forecast_json(lat, lon)
    return raw_conditions_from_forecast_json(forecast, entry_time)


def _retrieveEnvironment_impl(
    pilot_id: str,
    org_id: str,
    drone_id: str,
    payload: str,
    entry_time: str,
    request: Dict[str, Any],
    env_profile: str = "good",
    use_mock_weather: bool = False,
    full_data: Dict[str, Any] | None = None,
) -> RawConditions:
    """
    Environmental conditions for a DPO entry request.

    Live: Open-Meteo at coordinates from weather_latitude/longitude, waypoints,
    polygon, or SADE_WEATHER_LAT/LON default.

    Mock: set use_mock_weather true and optional env_profile good|medium|bad.
    """
    if use_mock_weather:
        return _retrieve_environment_mock(entry_time, env_profile)
    assert full_data is not None
    return _retrieve_environment_live(full_data)


def _retrieveMFC_impl(drone_id: str) -> ManufacturerFC:
    """
    Retrieve manufacturer flight constraints for drone_id from sade-mock-data/mfcs.json.
    Raises ValueError if record missing or payload_max_kg / max_wind_kt is null.
    """
    mfcs_path = Path(__file__).resolve().parent.parent / "sade-mock-data" / "mfcs.json"
    with mfcs_path.open("r") as f:
        records = json.load(f)

    for rec in records:
        if rec.get("drone_id") != drone_id:
            continue

        payload_max = rec.get("payload_max_kg")
        max_wind = rec.get("max_wind_kt")

        if payload_max is None or max_wind is None:
            raise ValueError(
                f"MFC data unavailable for drone_id={drone_id}: "
                "missing payload_max_kg or max_wind_kt"
            )

        return ManufacturerFC(
            manufacturer=rec.get("manufacturer", ""),
            model=rec.get("model", ""),
            category=rec.get("category", ""),
            mfc_payload_max_kg=float(payload_max),
            mfc_max_wind_kt=float(max_wind),
        )

    raise ValueError(f"MFC data not found for drone_id={drone_id}")


@function_tool
def retrieveEnvironment(input_json: str) -> RawConditions:
    """
    Retrieve raw environmental conditions for a Drone|Pilot|Organization entry request.

    Args:
        input_json: JSON with pilot_id, org_id, drone_id, payload, and entry_time or
            requested_entry_time (ISO8601); optional request.
            Optional: use_mock_weather (bool, default false) for fixed test profiles;
            env_profile good|medium|bad when mocking; weather_latitude, weather_longitude
            to override the location for Open-Meteo.

    Returns:
        RawConditions including optional forecast_by_day (7-day Open-Meteo aggregates).
    """
    data = json.loads(input_json)
    env_profile = data.get("env_profile", "good")
    if env_profile not in ("good", "medium", "bad"):
        env_profile = "good"
    use_mock = bool(data.get("use_mock_weather", False))
    et = entry_time_iso(data)
    return _retrieveEnvironment_impl(
        pilot_id=data["pilot_id"],
        org_id=data["org_id"],
        drone_id=data["drone_id"],
        payload=data["payload"],
        entry_time=et,
        request=data.get("request") or {},
        env_profile=env_profile,
        use_mock_weather=use_mock,
        full_data=data,
    )


@function_tool
def retrieveMFC(input_json: str) -> ManufacturerFC:
    """
    Retrieve Manufacturer Flight Constraints (MFC) for the drone in the entry request.

    Args:
        input_json: JSON string with at least drone_id (e.g. same as passed to retrieveEnvironment).

    Returns:
        ManufacturerFC (manufacturer, model, category, mfc_payload_max_kg, mfc_max_wind_kt).
    """
    data = json.loads(input_json)
    return _retrieveMFC_impl(drone_id=data["drone_id"])
