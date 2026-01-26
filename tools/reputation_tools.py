"""
Reputation Agent Tools - Mock implementations for testing delegation system.

These tools retrieve historical reputation and incident data from the Reputation Model Profile.
"""

import json
from typing import Dict, Any, List
from datetime import datetime, timedelta

from agents import function_tool
from models import (
    ReputationAgentOutput,
    ReputationSummary,
    ReputationScore,
    Incident,
    IncidentAnalysis,
    ReputationRiskAssessment,
)


# Incident code mapping table
INCIDENT_CATEGORIES = {
    "0001": {
        "category": "Injury-Related Incidents",
        "subcategories": {
            "001": "Serious Injury",
            "010": "Loss of Consciousness"
        },
        "severity": "HIGH"
    },
    "0010": {
        "category": "Property Damage",
        "subcategories": {
            "001": "Damage > $500"
        },
        "severity": "MEDIUM"
    },
    "0011": {
        "category": "Mid-Air Collisions / Near-Misses",
        "subcategories": {
            "001": "Collision with Manned Aircraft",
            "010": "Near Mid-Air Collision (NMAC)"
        },
        "severity": "HIGH"
    },
    "0100": {
        "category": "Loss of Control / Malfunctions",
        "subcategories": {
            "001": "GPS or Navigation Failure",
            "010": "Flight Control Failure",
            "011": "Battery Failure / Fire",
            "100": "Communication Loss (C2 Link)",
            "101": "Flyaway (Uncontrolled Drone)"
        },
        "severity": "MEDIUM"
    },
    "0101": {
        "category": "Airspace Violations",
        "subcategories": {
            "001": "Unauthorized Entry into Controlled Airspace",
            "010": "Violation of Temporary Flight Restriction (TFR)",
            "011": "Overflight of People Without Waiver",
            "100": "Night Operations Without Proper Lighting"
        },
        "severity": "MEDIUM"
    },
    "0110": {
        "category": "Security & Law Enforcement Events",
        "subcategories": {
            "001": "Intercepted by Law Enforcement or Military",
            "010": "Suspected Cyberattack or GPS Jamming",
            "011": "Drone Used in Criminal Activity"
        },
        "severity": "HIGH"
    },
    "1111": {
        "category": "Incomplete Flight Log",
        "subcategories": {
            "001": "Drone did not exit zone"
        },
        "severity": "LOW"
    }
}


def parse_incident_code(incident_code: str) -> tuple[str, str, str, str]:
    """
    Parse incident code "hhhh-sss" into components.
    
    Returns:
        (high_level_code, sub_code, category, subcategory, severity)
    """
    parts = incident_code.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid incident code format: {incident_code}")
    
    high_level = parts[0]
    sub_code = parts[1]
    
    if high_level not in INCIDENT_CATEGORIES:
        return (high_level, sub_code, "Unknown", "Unknown", "LOW")
    
    cat_info = INCIDENT_CATEGORIES[high_level]
    category = cat_info["category"]
    subcategory = cat_info["subcategories"].get(sub_code, "Unknown")
    severity = cat_info["severity"]
    
    return (high_level, sub_code, category, subcategory, severity)


def _retrieve_reputations_impl(
    pilot_id: str,
    org_id: str,
    drone_id: str
) -> ReputationAgentOutput:
    """
    Retrieve historical trust signals for a DPO trio from Reputation Model Profile endpoint.
    
    Args:
        pilot_id: FAA pilot registration
        org_id: Organization identifier
        drone_id: Drone identifier
    
    Returns:
        ReputationAgentOutput with reputation summary, incident analysis, and risk assessment
    """
    # Mock session records - simulate Reputation Model Profile data
    # In production, this would query the actual endpoint
    
    mock_sessions = [
        {
            "session_id": "550e8400-e29b-41d4-a716-446655440000",
            "pilot_id": pilot_id,
            "uav_id": drone_id,
            "time_in": "2025-06-15T10:30:00Z",
            "time_out": "2025-06-15T11:00:00Z",
            "incidents": ["0100-010"],  # Flight Control Failure
            "record_type": "001"
        },
        {
            "session_id": "660e8400-e29b-41d4-a716-446655440001",
            "pilot_id": pilot_id,
            "uav_id": drone_id,
            "time_in": "2025-12-20T14:15:00Z",
            "time_out": "2025-12-20T14:45:00Z",
            "incidents": ["0001-001"],  # Serious Injury
            "record_type": "001"
        },
        {
            "session_id": "770e8400-e29b-41d4-a716-446655440002",
            "pilot_id": pilot_id,
            "uav_id": drone_id,
            "time_in": "2025-08-10T09:20:00Z",
            "time_out": "2025-08-10T09:50:00Z",
            "incidents": ["0101-011"],  # Overflight Without Waiver
            "record_type": "001"
        },
        # Follow-up report for first incident
        {
            "session_id": "880e8400-e29b-41d4-a716-446655440003",
            "pilot_id": pilot_id,
            "uav_id": drone_id,
            "time_in": "2025-06-16T10:00:00Z",
            "time_out": "2025-06-16T10:30:00Z",
            "incidents": ["0100-010"],  # Follow-up for Flight Control Failure
            "record_type": "010"  # Follow-up report
        }
    ]
    
    # Collect all incidents
    all_incidents = []
    incident_codes_seen = set()
    
    for session in mock_sessions:
        for incident_code in session.get("incidents", []):
            if incident_code not in incident_codes_seen:
                incident_codes_seen.add(incident_code)
                high_level, sub_code, category, subcategory, severity = parse_incident_code(incident_code)
                
                # Check if resolved (has follow-up report)
                resolved = any(
                    s.get("record_type") == "010" and incident_code in s.get("incidents", [])
                    for s in mock_sessions
                )
                
                incident = Incident(
                    incident_code=incident_code,
                    incident_category=category,
                    incident_subcategory=subcategory,
                    severity=severity,
                    resolved=resolved,
                    session_id=session["session_id"],
                    date=session["time_in"]
                )
                all_incidents.append(incident)
    
    # Calculate recent incidents (last 30 days)
    # Use a reference date for testing (2026-01-26)
    from datetime import timezone
    reference_date = datetime.fromisoformat("2026-01-26T00:00:00Z".replace('Z', '+00:00'))
    thirty_days_ago = reference_date - timedelta(days=30)
    
    recent_count = 0
    for inc in all_incidents:
        inc_date = datetime.fromisoformat(inc.date.replace('Z', '+00:00'))
        if inc_date >= thirty_days_ago:
            recent_count += 1
    
    # Determine unresolved incidents
    unresolved_present = any(not inc.resolved for inc in all_incidents)
    
    incident_analysis = IncidentAnalysis(
        incidents=all_incidents,
        unresolved_incidents_present=unresolved_present,
        total_incidents=len(all_incidents),
        recent_incidents_count=recent_count
    )
    
    # Mock reputation scores/tiers (in production, these come from endpoint)
    # For testing, return null to simulate endpoint not providing scores
    reputation_summary = ReputationSummary(
        pilot_reputation=ReputationScore(score=8.5, tier="HIGH"),
        organization_reputation=ReputationScore(score=7.2, tier="MEDIUM"),
        drone_reputation=ReputationScore(score=9.0, tier="HIGH")
    )
    
    # Risk assessment based on incidents
    risk_level = "LOW"
    blocking_factors = []
    confidence_factors = []
    
    if unresolved_present:
        high_severity_unresolved = any(
            not inc.resolved and inc.severity == "HIGH"
            for inc in all_incidents
        )
        if high_severity_unresolved:
            risk_level = "HIGH"
            blocking_factors.append("unresolved_high_severity_incident")
        else:
            risk_level = "MEDIUM"
            blocking_factors.append("unresolved_incidents_present")
    
    if recent_count == 0:
        confidence_factors.append("no_recent_incidents")
    
    if all(inc.resolved for inc in all_incidents):
        confidence_factors.append("all_incidents_resolved")
    
    if reputation_summary.pilot_reputation.tier == "HIGH":
        confidence_factors.append("high_pilot_reputation")
    
    if reputation_summary.drone_reputation.tier == "HIGH":
        confidence_factors.append("high_drone_reputation")
    
    risk_assessment = ReputationRiskAssessment(
        risk_level=risk_level,
        blocking_factors=blocking_factors,
        confidence_factors=confidence_factors
    )
    
    return ReputationAgentOutput(
        reputation_summary=reputation_summary,
        incident_analysis=incident_analysis,
        risk_assessment=risk_assessment
    )


@function_tool
def retrieve_reputations(input_json: str) -> ReputationAgentOutput:
    """
    Retrieve historical trust signals for a Drone|Pilot|Organization trio from Reputation Model Profile endpoint.
    
    Args:
        input_json: JSON string with pilot_id, org_id, drone_id, entry_time, request
    
    Returns:
        ReputationAgentOutput with reputation summary, incident analysis, and risk assessment
    """
    data = json.loads(input_json)
    return _retrieve_reputations_impl(
        pilot_id=data["pilot_id"],
        org_id=data["org_id"],
        drone_id=data["drone_id"]
    )
