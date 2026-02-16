import asyncio
import json
import re
from pathlib import Path
from typing import Dict, Any

from agents import Agent, Runner, trace

# Single-run flow: orchestrator must not return until final decision (v2 prompt)
DEFAULT_MAX_TURNS = 25

from models import (
    EnvironmentAgentOutput,
    ReputationAgentOutput,
    ActionRequiredAgentOutput,
    ClaimsAgentOutput,
)
from tools.environment_tools import retrieveEnvironment
from tools.reputation_tools import retrieve_reputations
from tools.action_required_tools import request_attestation
from tools.claims_tools import retrieve_claims


def load_prompt(prompt_file: str, prompts_dir: str = "prompts") -> str:
    """Load prompt text from a markdown file."""
    prompt_path = Path(__file__).parent / prompts_dir / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text()


# Load agent prompts (v2: orchestrator, env, rm, claims; v1: action_required for SafeCert tool)
ORCHESTRATOR_PROMPT = load_prompt("orchestrator_prompt.md", prompts_dir="v2_prompts")
ENVIRONMENT_AGENT_PROMPT = load_prompt("env_agent_prompt.md", prompts_dir="v2_prompts")
REPUTATION_AGENT_PROMPT = load_prompt("rm_agent_prompt.md", prompts_dir="v2_prompts")
ACTION_REQUIRED_AGENT_PROMPT = load_prompt("action_required_agent_prompt.md")
CLAIMS_AGENT_PROMPT = load_prompt("claims_agent_prompt.md", prompts_dir="v2_prompts")


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

claims_agent = Agent(
    name="claims_agent",
    instructions=CLAIMS_AGENT_PROMPT,
    output_type=ClaimsAgentOutput,
    tools=[retrieve_claims],
    handoff_description="Verifies required_actions against DPO claims and follow-up records; returns satisfied/unsatisfied actions and incident resolution status",
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
        claims_agent.as_tool(
            tool_name="claims_agent",
            tool_description=(
                "Verify required_actions against DPO claims and follow-up records. "
                "Input: JSON string with keys: action_id, pilot_id, org_id, drone_id, entry_time, "
                "required_actions (list), incident_codes (list of hhhh-sss), wind_context (wind_now_kt, gust_now_kt, demo_steady_max_kt, demo_gust_max_kt). "
                "Returns: ClaimsAgentOutput with satisfied, resolved_incident_prefixes, unresolved_incident_prefixes, "
                "satisfied_actions, unsatisfied_actions, why. Call this when STATE 3 yields ACTION-REQUIRED before emitting any final decision."
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


def parse_orchestrator_output(raw: str) -> Dict[str, Any]:
    """
    Parse the orchestrator's final output as JSON (v2 contract: decision + visibility).

    Tries raw JSON first, then a single ```json ... ``` code block.
    Raises ValueError if no valid JSON object with "decision" is found.
    """
    text = raw.strip()
    # Try raw parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "decision" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    # Try extracting ```json ... ``` block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict) and "decision" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    raise ValueError("Orchestrator output did not contain valid JSON with 'decision'")


async def process_entry_request(
    request: Dict[str, Any],
    max_turns: int = DEFAULT_MAX_TURNS,
) -> Dict[str, Any]:
    """
    Process an entry request through the SADE Orchestrator Agent (single run).

    The v2 orchestrator runs until it emits a final JSON (calling env, reputation,
    and claims_agent as needed in one run). No outer loop.

    Args:
        request: Entry request dictionary
        max_turns: Max LLM/tool turns per run (default 25)

    Returns:
        Parsed output dict with "decision" and "visibility" (v2 contract).
        Raises ValueError if output could not be parsed as JSON.
    """
    formatted_request = format_entry_request(request)
    with trace("SADE Entry Request Processing"):
        result = await Runner.run(
            orchestrator_agent,
            formatted_request,
            max_turns=max_turns,
        )
    raw = result.final_output.strip()
    return parse_orchestrator_output(raw)


async def main():
    """
    Example entry request processing.
    """
    # Example Entry Request (pilot_id/drone_id match sade-mock-data/reputation_model.json and user_input.json)
    example_request = {
        "sade_zone_id": "ZONE-001",
        "pilot_id": "PILOT-12345",
        "organization_id": "ORG-ABC",
        "drone_id": "DRONE-XYZ-001",
        "requested_entry_time": "2026-02-02T10:00:00Z",
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
        output = await process_entry_request(example_request)
        decision = output.get("decision", {})
        decision_type = decision.get("type", "UNKNOWN")
        sade_message = decision.get("sade_message", "")

        print("\n" + "=" * 70)
        print("FINAL DECISION")
        print("=" * 70)
        print(f"Type: {decision_type}")
        print(f"SADE Message: {sade_message}")
        if decision.get("constraints"):
            print(f"Constraints: {decision['constraints']}")
        if decision.get("denial_code"):
            print(f"Denial Code: {decision['denial_code']}")
        if decision.get("explanation"):
            print(f"Explanation: {decision['explanation']}")
        print("=" * 70)
        print("\nFull output (decision + visibility):")
        print(json.dumps(output, indent=2))

    except ValueError as e:
        print(f"\nParse error: {e}")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
