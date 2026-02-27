"""
Environment Agent Tools - Mock implementations for testing delegation system.

These tools retrieve raw environmental conditions and manufacturer flight
constraints (MFC). The Environment Agent calls both and assembles
EnvironmentAgentOutput (including risk_assessment, recommendation, why).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from agents import function_tool
from models import (
    RawConditions,
    SpatialConstraints,
    ManufacturerFC,
)


def _retrieveEnvironment_impl(
    pilot_id: str,
    org_id: str,
    drone_id: str,
    payload: str,
    entry_time: str,
    request: Dict[str, Any],
    env_profile: str = "good",
) -> RawConditions:
    """
    Retrieve environmental conditions for a DPO entry request.
    Mock: returns one of three fixed profiles. In production, query weather/airspace APIs.
    env_profile: "good" | "medium" | "bad" (optional; default "good"). Use for testing.
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

    # Test case: good conditions (typical safe operations)
    raw_conditions_wind_visibility_good = RawConditions(
        wind=5.2,
        wind_gust=8.0,
        precipitation="none",
        visibility=10.0,
        light_conditions=light,
        spatial_constraints=spatial,
    )

    # Test case: medium conditions (elevated wind/visibility)
    raw_conditions_wind_visibility_medium = RawConditions(
        wind=10.2,
        wind_gust=12.0,
        precipitation="none",
        visibility=6.0,
        light_conditions=light,
        spatial_constraints=spatial,
    )

    # Test case: bad conditions (high wind, poor visibility)
    raw_conditions_wind_visibility_bad = RawConditions(
        wind=20.0,
        wind_gust=22.0,
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
        input_json: JSON string with pilot_id, org_id, drone_id, payload, entry_time, request.

    Returns:
        RawConditions (wind, wind_gust, precipitation, visibility, light_conditions, spatial_constraints).
    """
    data = json.loads(input_json)
    env_profile = data.get("env_profile", "good")
    if env_profile not in ("good", "medium", "bad"):
        env_profile = "good"
    return _retrieveEnvironment_impl(
        pilot_id=data["pilot_id"],
        org_id=data["org_id"],
        drone_id=data["drone_id"],
        payload=data["payload"],
        entry_time=data["entry_time"],
        request=data["request"],
        env_profile=env_profile,
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
