"""
Environment Agent Tools - Mock implementations for testing delegation system.

These tools retrieve environmental conditions data.
"""

import json
from typing import Dict, Any
from datetime import datetime

from agents import function_tool
from models import (
    EnvironmentAgentOutput,
    RawConditions,
    SpatialConstraints,
    RiskAssessment,
)


def _retrieveEnvironment_impl(
    pilot_id: str,
    org_id: str,
    drone_id: str,
    entry_time: str,
    request: Dict[str, Any]
) -> EnvironmentAgentOutput:
    """
    Retrieve environmental conditions for a DPO entry request.
    
    Args:
        pilot_id: FAA pilot registration
        org_id: Organization identifier
        drone_id: Drone identifier
        entry_time: ISO8601 datetime string
        request: Request payload with type, polygon, ceiling, floor, waypoints
    
    Returns:
        EnvironmentAgentOutput with environmental conditions and risk assessment
    """
    # Mock data - simulate retrieving weather/light/airspace conditions
    # In production, this would call actual weather APIs, airspace databases, etc.
    
    # Determine light conditions based on entry time
    try:
        # Handle ISO8601 format with Z or timezone
        time_str = entry_time.replace('Z', '+00:00') if entry_time.endswith('Z') else entry_time
        dt = datetime.fromisoformat(time_str)
        hour = dt.hour
        if 6 <= hour < 18:
            light = "daylight"
        elif hour == 6 or hour == 18:
            light = "dusk" if hour == 18 else "dawn"
        else:
            light = "night"
    except Exception:
        light = "daylight"  # Default
    
    # Mock environmental conditions
    raw_conditions_wind_visibility_good = RawConditions(
        wind=5.2,  # knots (typical for normal safe operations)
        wind_gust=8.0,  # knots (modest gusts, within normal limits)
        precipitation="none",
        visibility=10.0,  # nautical miles (good visibility)
        light_conditions=light,
        spatial_constraints=SpatialConstraints(
            airspace_class="Class E",
            no_fly_zones=[],
            restricted_areas=[]
        )
    )
    raw_conditions_wind_visibility_medium = RawConditions(
        wind=10.2,  # knots (typical for normal safe operations)
        wind_gust=12.0,  # knots (modest gusts, within normal limits)
        precipitation="none",
        visibility=6.0,  # nautical miles (good visibility)
        light_conditions=light,
        spatial_constraints=SpatialConstraints(
            airspace_class="Class E",
            no_fly_zones=[],
            restricted_areas=[]
        )
    )
    raw_conditions_wind_visibility_bad = RawConditions(
        wind=20.0,  # knots (bad wind, close to or above many UAS limits)
        wind_gust=22.0,  # knots (dangerous gusts, well above normal)
        precipitation="moderate",  # must be one of: none, light, moderate, heavy
        visibility=2.0,  # nautical miles (very poor visibility)
        light_conditions=light,
        spatial_constraints=SpatialConstraints(
            airspace_class="Class E",
            no_fly_zones=[],
            restricted_areas=[]
        )
    )
    
    # Risk assessment based on conditions
    risk_level = "LOW"
    blocking_factors = []
    marginal_factors = []
    raw_conditions = raw_conditions_wind_visibility_good

    if raw_conditions.wind_gust > 25:
        risk_level = "HIGH"
        blocking_factors.append("high_wind_gusts")
    elif raw_conditions.wind_gust > 20:
        risk_level = "MEDIUM"
        marginal_factors.append("elevated_wind_gusts")
    
    if raw_conditions.visibility and raw_conditions.visibility < 3:
        risk_level = "HIGH"
        blocking_factors.append("low_visibility")
    elif raw_conditions.visibility and raw_conditions.visibility < 5:
        risk_level = "MEDIUM" if risk_level == "LOW" else risk_level
        marginal_factors.append("reduced_visibility")
    
    if raw_conditions.light_conditions == "night":
        marginal_factors.append("night_operations")
    
    risk_assessment = RiskAssessment(
        risk_level=risk_level,
        blocking_factors=blocking_factors,
        marginal_factors=marginal_factors
    )
    
    # Constraint suggestions based on conditions
    constraint_suggestions = []
    if raw_conditions.wind_gust > 20:
        constraint_suggestions.append("SPEED_LIMIT(7 m/s)")
    if raw_conditions.wind_gust > 15:
        constraint_suggestions.append("MAX_ALTITUDE(300 m)")

    # v2/v3 visibility: recommendation (wind risk signal), prose, and why
    recommendation = risk_level
    why = [
        f"wind_steady_kt={raw_conditions.wind}",
        f"wind_gust_kt={raw_conditions.wind_gust}",
        f"risk_level={risk_level}",
    ]
    if blocking_factors:
        why.append(f"blocking_factors={blocking_factors}")
    if marginal_factors:
        why.append(f"marginal_factors={marginal_factors}")
    recommendation_prose = (
        f"Wind risk signal: {risk_level}. Steady wind {raw_conditions.wind} kt, gusts {raw_conditions.wind_gust} kt."
    )
    why_prose = "; ".join(why[:6])

    return EnvironmentAgentOutput(
        raw_conditions=raw_conditions,
        risk_assessment=risk_assessment,
        constraint_suggestions=constraint_suggestions,
        recommendation=recommendation,
        recommendation_prose=recommendation_prose,
        why_prose=why_prose,
        why=why[:6],
    )


@function_tool
def retrieveEnvironment(input_json: str) -> EnvironmentAgentOutput:
    """
    Retrieve environmental conditions for a Drone|Pilot|Organization entry request.
    
    Args:
        input_json: JSON string with pilot_id, org_id, drone_id, entry_time, request
    
    Returns:
        EnvironmentAgentOutput with environmental conditions and risk assessment
    """
    data = json.loads(input_json)
    return _retrieveEnvironment_impl(
        pilot_id=data["pilot_id"],
        org_id=data["org_id"],
        drone_id=data["drone_id"],
        entry_time=data["entry_time"],
        request=data["request"]
    )
