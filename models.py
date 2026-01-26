"""
Pydantic models for SADE agent outputs.

These models define the structured output types for all agents,
ensuring type safety and automatic validation.
"""

from typing import List, Optional, Dict, Any, Literal, Union
from pydantic import BaseModel, Field


# ============================================================================
# Environment Agent Models
# ============================================================================

class SpatialConstraints(BaseModel):
    """Spatial constraints from environment data."""
    airspace_class: Optional[str] = None
    no_fly_zones: List[str] = Field(default_factory=list)
    restricted_areas: List[str] = Field(default_factory=list)


class RawConditions(BaseModel):
    """Raw environmental conditions."""
    wind: float
    wind_gust: float
    precipitation: Literal["none", "light", "moderate", "heavy"]
    visibility: Optional[float] = None
    light_conditions: Literal["daylight", "dusk", "dawn", "night"]
    spatial_constraints: SpatialConstraints


class RiskAssessment(BaseModel):
    """Risk assessment with factors."""
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    blocking_factors: List[str] = Field(default_factory=list)
    marginal_factors: List[str] = Field(default_factory=list)


class EnvironmentAgentOutput(BaseModel):
    """Output from Environment Agent."""
    raw_conditions: RawConditions
    risk_assessment: RiskAssessment
    constraint_suggestions: List[str] = Field(default_factory=list)


# ============================================================================
# Reputation Agent Models
# ============================================================================

class ReputationScore(BaseModel):
    """Reputation score and tier."""
    score: Optional[float] = None
    tier: Optional[str] = None


class ReputationSummary(BaseModel):
    """Summary of reputation scores."""
    pilot_reputation: ReputationScore
    organization_reputation: ReputationScore
    drone_reputation: ReputationScore


class Incident(BaseModel):
    """Incident record."""
    incident_code: str = Field(..., description="Format: hhhh-sss")
    incident_category: str
    incident_subcategory: str
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    resolved: bool
    session_id: str
    date: str = Field(..., description="ISO8601 datetime string")


class IncidentAnalysis(BaseModel):
    """Analysis of incidents."""
    incidents: List[Incident] = Field(default_factory=list)
    unresolved_incidents_present: bool
    total_incidents: int
    recent_incidents_count: int


class ReputationRiskAssessment(BaseModel):
    """Risk assessment from reputation data."""
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    blocking_factors: List[str] = Field(default_factory=list)
    confidence_factors: List[str] = Field(default_factory=list)


class ReputationAgentOutput(BaseModel):
    """Output from Reputation Agent."""
    reputation_summary: ReputationSummary
    incident_analysis: IncidentAnalysis
    risk_assessment: ReputationRiskAssessment


# ============================================================================
# Action Required Agent Models (Evidence/Attestation)
# ============================================================================

class EvidenceSubject(BaseModel):
    """Subject of evidence requirement/attestation."""
    sade_zone_id: str
    pilot_id: str
    organization_id: str
    drone_id: str


class EvidenceRequirement(BaseModel):
    """Single evidence requirement."""
    expr: str
    keyword: str
    params: List[Union[str, Dict[str, str]]] = Field(
        default_factory=list,
        description="Can be empty list, list of strings, or list of {'key': 'value'} dicts"
    )


class EvidenceCategory(BaseModel):
    """Category of evidence requirements."""
    category: Literal["CERTIFICATION", "CAPABILITY", "ENVIRONMENT", "INTERFACE"]
    requirements: List[EvidenceRequirement]


class EvidenceRequirementPayload(BaseModel):
    """Complete evidence requirement payload."""
    type: Literal["EVIDENCE_REQUIREMENT"] = "EVIDENCE_REQUIREMENT"
    spec_version: str
    request_id: str
    subject: EvidenceSubject
    categories: List[EvidenceCategory]


class RequirementMeta(BaseModel):
    """Metadata for a requirement in an attestation."""
    status: Literal["SATISFIED", "PARTIAL", "NOT_SATISFIED", "UNKNOWN"]
    # Additional fields may be present but are opaque
    # Using Dict[str, Any] to allow extra fields
    class Config:
        extra = "allow"


class AttestedRequirement(BaseModel):
    """A requirement in an attestation."""
    expr: str
    keyword: str
    params: List[Union[str, Dict[str, str]]] = Field(
        default_factory=list,
        description="Can be empty list, list of strings, or list of {'key': 'value'} dicts"
    )
    meta: RequirementMeta


class AttestationCategory(BaseModel):
    """Category in an attestation."""
    category: str
    requirements: List[AttestedRequirement]


class Signature(BaseModel):
    """Digital signature (opaque)."""
    signer: str
    signature_type: str
    signature_ref: str


class EvidenceRef(BaseModel):
    """Evidence reference (opaque)."""
    evidence_id: str
    kind: str
    ref: str


class EvidenceAttestation(BaseModel):
    """Complete evidence attestation payload."""
    type: Literal["EVIDENCE_ATTESTATION"] = "EVIDENCE_ATTESTATION"
    spec_version: str
    attestation_id: str
    in_response_to: str
    subject: EvidenceSubject
    categories: List[AttestationCategory]
    signatures: List[Signature] = Field(default_factory=list)
    evidence_refs: List[EvidenceRef] = Field(default_factory=list)


class ActionRequiredAgentOutput(BaseModel):
    """Output from Action Required Agent."""
    satisfied: bool
    attestation: Optional[EvidenceAttestation] = None
    error: Optional[str] = None
