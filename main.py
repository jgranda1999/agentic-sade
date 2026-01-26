import asyncio
import json
import re
from pathlib import Path
from typing import Dict, Any

from agents import Agent, Runner, trace

from models import (
    EnvironmentAgentOutput,
    ReputationAgentOutput,
    ActionRequiredAgentOutput,
)
from tools.environment_tools import retrieveEnvironment
from tools.reputation_tools import retrieve_reputations
from tools.action_required_tools import request_attestation


def load_prompt(prompt_file: str) -> str:
    """Load prompt text from a markdown file."""
    prompt_path = Path(__file__).parent / "prompts" / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text()


# Load agent prompts
ORCHESTRATOR_PROMPT = load_prompt("orchestrator_prompt.md")
ENVIRONMENT_AGENT_PROMPT = load_prompt("environment_agent_prompt.md")
REPUTATION_AGENT_PROMPT = load_prompt("reputation_agent_prompt.md")
ACTION_REQUIRED_AGENT_PROMPT = load_prompt("action_required_agent_prompt.md")


# Sub-Agents (Advisory Only - Never Make Decisions)

environment_agent = Agent(
    name="environment_agent",
    instructions=ENVIRONMENT_AGENT_PROMPT,
    output_type=EnvironmentAgentOutput,
    tools=[retrieveEnvironment],
    handoff_description="Retrieves external environmental conditions (weather, light, airspace) for a Drone|Pilot|Organization entry request",
)

reputation_agent = Agent(
    name="reputation_agent",
    instructions=REPUTATION_AGENT_PROMPT,
    output_type=ReputationAgentOutput,
    tools=[retrieve_reputations],
    handoff_description="Retrieves historical trust and reliability signals (pilot, organization, drone reputation and incidents)",
)

action_required_agent = Agent(
    name="action_required_agent",
    instructions=ACTION_REQUIRED_AGENT_PROMPT,
    output_type=ActionRequiredAgentOutput,
    tools=[request_attestation],
    handoff_description="Interfaces with SafeCert to request and retrieve formal evidence attestations",
)


# Orchestrator Agent (Sole Decision Authority)

orchestrator_agent = Agent(
    name="orchestrator_agent",
    instructions=ORCHESTRATOR_PROMPT,
    tools=[
        environment_agent.as_tool(
            tool_name="retrieveEnvironment",
            tool_description=(
                "Retrieve environmental conditions for a Drone|Pilot|Organization entry request. "
                "Input: JSON string with keys: pilot_id, org_id, drone_id, entry_time, request. "
                "Returns: EnvironmentAgentOutput (validated Pydantic model) with raw_conditions, risk_assessment, constraint_suggestions."
            ),
        ),
        reputation_agent.as_tool(
            tool_name="retrieve_reputations",
            tool_description=(
                "Retrieve historical trust signals for a Drone|Pilot|Organization trio. "
                "Input: JSON string with keys: pilot_id, org_id, drone_id, entry_time, request. "
                "Returns: ReputationAgentOutput (validated Pydantic model) with reputation_summary, incident_analysis, risk_assessment."
            ),
        ),
        action_required_agent.as_tool(
            tool_name="request_attestation",
            tool_description=(
                "Request evidence attestations from SafeCert. "
                "Input: JSON string with keys: pilot_id, org_id, drone_id, entry_time, safecert_pin, evidence_required. "
                "Returns: ActionRequiredAgentOutput (validated Pydantic model) with satisfied (boolean) and attestation. "
                "Only call this when ACTION-REQUIRED decision has been issued."
            ),
        ),
    ],
)


def format_entry_request(request: Dict[str, Any]) -> str:
    """
    Format an entry request dictionary into a structured text format
    for the Orchestrator Agent.
    """
    lines = [
        "ENTRY REQUEST",
        "=" * 50,
        f"SADE Zone ID: {request.get('sade_zone_id', 'MISSING')}",
        f"Pilot ID: {request.get('pilot_id', 'MISSING')}",
        f"Organization ID: {request.get('organization_id', 'MISSING')}",
        f"Drone ID: {request.get('drone_id', 'MISSING')}",
        f"Requested Entry Time: {request.get('requested_entry_time', 'MISSING')}",
        f"Request Type: {request.get('request_type', 'MISSING')}",
    ]
    
    request_payload = request.get('request_payload', {})
    if request_payload:
        lines.append(f"\nRequest Payload:")
        if request.get('request_type') == 'REGION':
            lines.append(f"  Polygon: {request_payload.get('polygon', 'MISSING')}")
            lines.append(f"  Ceiling: {request_payload.get('ceiling', 'MISSING')} m ASL")
            lines.append(f"  Floor: {request_payload.get('floor', 'MISSING')} m ASL")
        elif request.get('request_type') == 'ROUTE':
            waypoints = request_payload.get('waypoints', [])
            lines.append(f"  Waypoints ({len(waypoints)}):")
            for i, wp in enumerate(waypoints, 1):
                lines.append(f"    {i}. Lat: {wp.get('lat')}, Lon: {wp.get('lon')}, Alt: {wp.get('altitude')} m ASL")
        elif request.get('request_type') == 'ZONE':
            lines.append("  Full zone access requested")
    
    # Include safecert_pin if provided (for ACTION-REQUIRED re-evaluation)
    if 'safecert_pin' in request:
        lines.append(f"\nSafeCert PIN: {request['safecert_pin']}")
    
    # Include evidence_required if provided (for ACTION-REQUIRED re-evaluation)
    if 'evidence_required' in request:
        lines.append(f"\nEvidence Required:")
        lines.append(json.dumps(request['evidence_required'], indent=2))
    
    return "\n".join(lines)


def extract_evidence_required(decision_output: str) -> Dict[str, Any]:
    """
    Extract evidence_required JSON from ACTION-REQUIRED decision output.
    
    Looks for JSON code blocks in the output and parses the evidence_required structure.
    """
    # Try to find JSON code blocks
    json_pattern = r'```json\s*(\{.*?\})\s*```'
    matches = re.findall(json_pattern, decision_output, re.DOTALL)
    
    for match in matches:
        try:
            parsed = json.loads(match)
            # Check if this looks like an evidence requirement
            if isinstance(parsed, dict) and parsed.get("type") == "EVIDENCE_REQUIREMENT":
                return parsed
        except json.JSONDecodeError:
            continue
    
    # If no JSON block found, try to find evidence_required: followed by JSON
    evidence_pattern = r'evidence_required[:\s]*```json\s*(\{.*?\})\s*```'
    matches = re.findall(evidence_pattern, decision_output, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        try:
            parsed = json.loads(match)
            if isinstance(parsed, dict) and parsed.get("type") == "EVIDENCE_REQUIREMENT":
                return parsed
        except json.JSONDecodeError:
            continue
    
    return None


def is_final_decision(decision: str) -> bool:
    """Check if decision is final (not ACTION-REQUIRED)."""
    decision_upper = decision.upper()
    return (
        "APPROVED" in decision_upper and "ACTION-REQUIRED" not in decision_upper
    ) or "DENIED" in decision_upper


async def process_entry_request(request: Dict[str, Any], max_iterations: int = 5) -> str:
    """
    Process an entry request through the SADE Orchestrator Agent.
    
    Loops until a final decision is reached (APPROVED, APPROVED-CONSTRAINTS, or DENIED).
    If ACTION-REQUIRED is issued, extracts evidence_required and continues with
    safecert_pin and evidence_required in the request.
    
    Args:
        request: Entry request dictionary
        max_iterations: Maximum number of iterations to prevent infinite loops
    
    Returns:
        Final decision string (APPROVED, APPROVED-CONSTRAINTS, or DENIED)
    """
    current_request = request.copy()
    iteration = 0
    last_decision = None
    
    while iteration < max_iterations:
        iteration += 1
        formatted_request = format_entry_request(current_request)
        
        with trace(f"SADE Entry Request Processing - Iteration {iteration}"):
            result = await Runner.run(orchestrator_agent, formatted_request)
            
            # Extract the decision from the agent's output
            decision_output = result.final_output.strip()
            last_decision = decision_output
            
            # Check if this is a final decision
            if is_final_decision(decision_output):
                return decision_output
            
            # If ACTION-REQUIRED, extract evidence_required and continue
            if "ACTION-REQUIRED" in decision_output.upper():
                print(f"\n[Iteration {iteration}] ACTION-REQUIRED issued. Extracting evidence requirements...")
                
                evidence_required = extract_evidence_required(decision_output)
                
                if evidence_required:
                    # Add safecert_pin and evidence_required to request for next iteration
                    # Use a mock PIN for testing
                    current_request["safecert_pin"] = current_request.get("safecert_pin", "MOCK-PIN-12345")
                    current_request["evidence_required"] = evidence_required
                    
                    print(f"[Iteration {iteration}] Evidence requirements extracted. Continuing to ACTION-REQUIRED agent...\n")
                    continue
                else:
                    print(f"[Iteration {iteration}] WARNING: Could not extract evidence_required from output.")
                    print("Output was:")
                    print(decision_output[:500])  # Print first 500 chars
                    return decision_output  # Return as-is if we can't parse
            
            # If we get here and it's not a final decision, return what we have
            return decision_output
    
    # If we've exceeded max iterations, return the last decision we got
    print(f"\nWARNING: Maximum iterations ({max_iterations}) reached.")
    return last_decision if last_decision else "ERROR: Maximum iterations exceeded. Could not reach final decision."


async def main():
    """
    Example entry request processing.
    """
    # Example Entry Request
    example_request  = {
        "sade_zone_id": "ZONE-123",
        "pilot_id": "FA-01234567",
        "organization_id": "ORG-789",
        "drone_id": "DRONE-001",
        "requested_entry_time": "2026-01-26T14:00:00Z",
        "request_type": "REGION",
        "request_payload": {
            "polygon": [
                {"lat": 41.7000, "lon": -86.2400},
                {"lat": 41.7010, "lon": -86.2400},
                {"lat": 41.7010, "lon": -86.2390},
                {"lat": 41.7000, "lon": -86.2390},
            ],
            "ceiling": 300,  # meters ASL
            "floor": 100,    # meters ASL
        },
    }
    
    print("=" * 70)
    print("SADE Entry Request Processing")
    print("=" * 70)
    print("\nEntry Request:")
    print(json.dumps(example_request, indent=2))
    print("\n" + "=" * 70)
    print("Processing...")
    print("=" * 70 + "\n")
    
    try:
        decision = await process_entry_request(example_request)
        
        print("\n" + "=" * 70)
        print("FINAL DECISION")
        print("=" * 70)
        print(decision)
        print("=" * 70)
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
