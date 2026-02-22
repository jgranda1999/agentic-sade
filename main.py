import asyncio
import json
import re
import sys, os
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
    OrchestratorOutput,
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


# Load agent prompts (v3: orchestrator, env, rm, claims with visibility _prose; v1: action_required for SafeCert tool)
ORCHESTRATOR_PROMPT = load_prompt("orchestrator_prompt.md", prompts_dir="v4_prompts")
ENVIRONMENT_AGENT_PROMPT = load_prompt("env_agent_prompt.md", prompts_dir="v4_prompts")
REPUTATION_AGENT_PROMPT = load_prompt("rm_agent_prompt.md", prompts_dir="v4_prompts")
ACTION_REQUIRED_AGENT_PROMPT = load_prompt("action_required_agent_prompt.md")
CLAIMS_AGENT_PROMPT = load_prompt("claims_agent_prompt.md", prompts_dir="v4_prompts")


# Sub-Agents (Advisory Only - Never Make Decisions)

environment_agent = Agent(
    name="environment_agent",
    instructions=ENVIRONMENT_AGENT_PROMPT,
    output_type=EnvironmentAgentOutput,
    tools=[retrieveEnvironment],
    handoff_description="Retrieves external environmental conditions (weather, light, airspace) for a Drone|Pilot|Organization entry request and makes a recommendation based on the environmental conditions",
)

reputation_agent = Agent(
    name="reputation_agent",
    instructions=REPUTATION_AGENT_PROMPT,
    output_type=ReputationAgentOutput,
    tools=[retrieve_reputations],
    handoff_description="Retrieves historical trust and reliability signals (pilot, organization, drone reputation and incidents) and makes a recommendation based on the reputation data",
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
    handoff_description="Verifies required_actions against DPO claims and follow-up records; returns satisfied/unsatisfied actions and incident resolution status and makes a recommendation based on the claims data",
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
                "Returns: ReputationAgentOutput (validated Pydantic model) with incident_analysis, risk_assessment, orchestration fields."
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


def _normalize_visibility(parsed: Dict[str, Any]) -> None:
    """Normalize visibility so it matches models.py (e.g. entry_request field names)."""
    vis = parsed.get("visibility") or {}
    entry = vis.get("entry_request") or {}
    if not isinstance(entry, dict):
        return
    # Map common LLM mistakes to canonical names (match EvidenceSubject / entry_requests.json)
    if "zone_id" in entry and "sade_zone_id" not in entry:
        entry["sade_zone_id"] = entry.pop("zone_id")
    if "org_id" in entry and "organization_id" not in entry:
        entry["organization_id"] = entry.pop("org_id")


def parse_orchestrator_output(raw: str) -> Dict[str, Any]:
    """
    Parse the orchestrator's final output as JSON (v2/v3 contract: decision + visibility).

    Tries raw JSON first, then a single ```json ... ``` code block.
    Normalizes visibility.entry_request to use sade_zone_id and organization_id.
    Raises ValueError if no valid JSON object with "decision" is found.
    """
    text = raw.strip()
    # Try raw parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "decision" in parsed:
            _normalize_visibility(parsed)
            try:
                OrchestratorOutput.model_validate(parsed)
            except Exception as e:
                pass  # allow through; model is for documentation and optional strict validation
            return parsed
    except json.JSONDecodeError:
        pass
    # Try extracting ```json ... ``` block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict) and "decision" in parsed:
                _normalize_visibility(parsed)
                try:
                    OrchestratorOutput.model_validate(parsed)
                except Exception:
                    pass
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

# Main function
async def main():
    """
    Example entry request processing.
    """
    # Example Entry Request (pilot_id/drone_id match sade-mock-data/reputation_model.json and user_input.json)
    with open("sade-mock-data/entry_requests.json", "r") as f:
        example_requests = json.load(f)
        
    for request in example_requests[:1]:
        print("=" * 70)
        print("SADE Entry Request Processing")
        print("=" * 70)
        print("\nEntry Request:")
        print(json.dumps(request, indent=2))
        print("\n" + "=" * 70)
        print("Processing...")
        print("=" * 70 + "\n")
        
        try:
            output = await process_entry_request(request)
            decision = output.get("decision", {})
            decision_type = decision.get("type", "UNKNOWN")
            sade_message = decision.get("sade_message", "")

            # Determine test number based on the loop index, if available
            # Since here we don't have direct access to loop index, let's assume
            # you want to name files like entry_result_1.txt, entry_result_2.txt, etc.
            # We'll try to infer test number based on the request or you may want to pass
            # loop index explicitly.
            #
            # To keep things robust, let's fallback to a per-request "sade_zone_id" as default.
            #
            # Recommended pattern: enumerate(example_request, start=1) in main()

            # You will need to get 'test_number' from outside this block. For now:
            test_number = request.get('sade_zone_id', 'result')  # fallback if no test number available
            case_1 = "wind-visibility-good"
            case_2 = "wind-visibility-medium"
            case_3 = "wind-visibility-bad"

            
            output_filename = f"results/weather/{case_3}/entry_result_{test_number}.txt"
            with open(output_filename, "w") as f:
                f.write("=" * 70 + "\n")
                f.write("FINAL DECISION\n")
                f.write("=" * 70 + "\n")
                f.write(f"Type: {decision_type}\n")
                f.write(f"SADE Message: {sade_message}\n")
                if decision.get("constraints"):
                    f.write(f"Constraints: {decision['constraints']}\n")
                if decision.get("denial_code"):
                    f.write(f"Denial Code: {decision['denial_code']}\n")
                # Always show explanation (orchestrator prompt requires it; fallback if legacy output)
                explanation = decision.get("explanation") or "(none)"
                f.write(f"Explanation: {explanation}\n")
                f.write("=" * 70 + "\n\n")
                f.write("Full output (decision + visibility):\n")
                f.write(json.dumps(output, indent=2))
                f.write("\n")
            print(f"\nOutput written to {output_filename}")

        except ValueError as e:
            print(f"\nParse error: {e}")
        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
        
        # Add delay after each request is processed to avoid rate limits
        print(f"\nWaiting 60 seconds before processing next request...\n")
        await asyncio.sleep(60.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user (Ctrl+C). Exiting.")
        sys.exit(0)
