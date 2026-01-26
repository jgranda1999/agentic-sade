"""
Action Required Agent Tools - Mock implementations for testing delegation system.

These tools interface with SafeCert to request and retrieve evidence attestations.
"""

import json
from typing import Dict, Any, List
from datetime import datetime
from agents import function_tool

from models import (
    ActionRequiredAgentOutput,
    EvidenceAttestation,
    EvidenceSubject,
    AttestationCategory,
    AttestedRequirement,
    RequirementMeta,
    Signature,
    EvidenceRef,
    EvidenceRequirementPayload,
)


def _request_attestation_impl(
    safecert_pin: str,
    evidence_required: Dict[str, Any]
) -> ActionRequiredAgentOutput:
    """
    Request evidence attestations from SafeCert.
    
    Args:
        safecert_pin: SafeCert PIN for authentication
        evidence_required: EvidenceRequirementPayload dict
    
    Returns:
        ActionRequiredAgentOutput with satisfied flag and attestation
    """
    # Mock SafeCert response - simulate attestation retrieval
    # In production, this would call the actual SafeCert API
    
    try:
        req_payload = EvidenceRequirementPayload(**evidence_required)
    except Exception as e:
        return ActionRequiredAgentOutput(
            satisfied=False,
            attestation=None,
            error=f"Invalid evidence requirement: {str(e)}"
        )
    
    # Mock attestation response - simulate SafeCert processing
    # For testing, we'll satisfy most requirements but can vary based on PIN or requirements
    
    attestation_categories = []
    all_satisfied = True
    
    for req_category in req_payload.categories:
        attested_requirements = []
        
        for req in req_category.requirements:
            # Mock logic: satisfy most requirements, but can simulate failures
            # For testing, satisfy all CERTIFICATION and CAPABILITY, 
            # conditionally satisfy ENVIRONMENT and INTERFACE
            
            if req_category.category == "CERTIFICATION":
                status = "SATISFIED"
                meta_extra = {"cert_id": f"CERT-{req.keyword}-12345", "issuer": "FAA"}
            elif req_category.category == "CAPABILITY":
                status = "SATISFIED"
                meta_extra = {"actual": True}
            elif req_category.category == "ENVIRONMENT":
                # Simulate conditional satisfaction
                if "MAX_WIND_GUST" in req.keyword:
                    status = "SATISFIED"
                    meta_extra = {"actual_limit": "30mph"}
                else:
                    status = "SATISFIED"
                    meta_extra = {}
            elif req_category.category == "INTERFACE":
                # Simulate PARTIAL status for INTERFACE (testing PARTIAL policy)
                if "SADE_ATC_API" in req.keyword:
                    status = "PARTIAL"
                    meta_extra = {"actual": "v1.0"}
                else:
                    status = "SATISFIED"
                    meta_extra = {}
            else:
                status = "SATISFIED"
                meta_extra = {}
            
            if status != "SATISFIED":
                all_satisfied = False
            
            # Create meta with status and extra fields
            meta_dict = {"status": status, **meta_extra}
            meta = RequirementMeta(**meta_dict)
            
            attested_req = AttestedRequirement(
                expr=req.expr,
                keyword=req.keyword,
                params=req.params,
                meta=meta
            )
            attested_requirements.append(attested_req)
        
        attestation_categories.append(
            AttestationCategory(
                category=req_category.category,
                requirements=attested_requirements
            )
        )
    
    # Create attestation
    attestation = EvidenceAttestation(
        type="EVIDENCE_ATTESTATION",
        spec_version=req_payload.spec_version,
        attestation_id=f"ATT-{req_payload.request_id}",
        in_response_to=req_payload.request_id,
        subject=req_payload.subject,
        categories=attestation_categories,
        signatures=[
            Signature(
                signer=req_payload.subject.organization_id,
                signature_type="DIGITAL_SIGNATURE",
                signature_ref="sig-ref-mock-123"
            )
        ],
        evidence_refs=[
            EvidenceRef(
                evidence_id="EVID-MOCK-001",
                kind="DOCUMENT_OR_ARTIFACT",
                ref="ev-ref-mock-456"
            )
        ]
    )
    
    return ActionRequiredAgentOutput(
        satisfied=all_satisfied,
        attestation=attestation,
        error=None
    )


@function_tool
def request_attestation(input_json: str) -> ActionRequiredAgentOutput:
    """
    Request evidence attestations from SafeCert.
    
    Args:
        input_json: JSON string with pilot_id, org_id, drone_id, entry_time, safecert_pin, evidence_required
    
    Returns:
        ActionRequiredAgentOutput with satisfied flag and attestation
    """
    data = json.loads(input_json)
    
    # Handle error case
    if "error" in data:
        return ActionRequiredAgentOutput(
            satisfied=False,
            attestation=None,
            error=data.get("error", "Unknown error")
        )
    
    return _request_attestation_impl(
        safecert_pin=data["safecert_pin"],
        evidence_required=data["evidence_required"]
    )
