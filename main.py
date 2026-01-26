import asyncio
import json
from pathlib import Path
from typing import Dict, Any

from agents import Agent, Runner, trace


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
    handoff_description="Retrieves external environmental conditions (weather, light, airspace) for a DPO entry request",
)

reputation_agent = Agent(
    name="reputation_agent",
    instructions=REPUTATION_AGENT_PROMPT,
    handoff_description="Retrieves historical trust and reliability signals (pilot, organization, drone reputation and incidents)",
)

action_required_agent = Agent(
    name="action_required_agent",
    instructions=ACTION_REQUIRED_AGENT_PROMPT,
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
                "Retrieve environmental conditions for a DPO entry request. "
                "Inputs: PilotID, OrgID, DroneID, EntryTime, Request. "
                "Returns: Weather, light conditions, airspace constraints, and environment recommendation."
            ),
        ),
        reputation_agent.as_tool(
            tool_name="retrieve_reputations",
            tool_description=(
                "Retrieve historical trust signals for a DPO trio. "
                "Inputs: PilotID, OrgID, DroneID. "
                "Returns: Pilot, organization, and drone reputation scores, incident history, and reputation recommendation."
            ),
        ),
        action_required_agent.as_tool(
            tool_name="request_attestation",
            tool_description=(
                "Request evidence attestations from SafeCert. "
                "Inputs: safecert-pin, evidence_required (JSON Evidence Requirement payload). "
                "Returns: satisfied (boolean), attestation (JSON Evidence Attestation payload). "
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


async def process_entry_request(request: Dict[str, Any]) -> str:
    """
    Process an entry request through the SADE Orchestrator Agent.
    
    Returns the final decision string (APPROVED, APPROVED-CONSTRAINTS, 
    ACTION-REQUIRED, or DENIED).
    """
    formatted_request = format_entry_request(request)
    
    with trace("SADE Entry Request Processing"):
        result = await Runner.run(orchestrator_agent, formatted_request)
        
        # Extract the final decision from the agent's output
        decision = result.final_output.strip()
        
        return decision


async def main():
    """
    Example entry request processing.
    """
    # Example Entry Request
    example_request = {
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
