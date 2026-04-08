import asyncio
import json
import re
import sys, os
from pathlib import Path
from typing import Dict, Any
from resources import *

from agents import Agent, Runner, trace, ModelSettings

# Single-run flow: orchestrator must not return until final decision (v2 prompt)
DEFAULT_MAX_TURNS = 25

# STATE 0/1 ACTION-REQUIRED only — orchestrator does not call claims_agent (see v5 orchestrator prompt).
_ACTION_REQUIRED_NO_CLAIMS_ACTIONS = frozenset(
    {"FIX_INVALID_ENTRY_REQUEST", "RETRY_SIGNAL_RETRIEVAL"}
)
_CLAIMS_SPEC_MISSING_TOKEN = "claims_agent.evidence_requirement_spec missing"
_CLAIMS_SPEC_CONFLICT_TOKEN = "claims_agent.evidence_requirement_spec conflicts with satisfied=true"


def _claims_call_required(decision: Dict[str, Any]) -> bool:
    """
    True if ACTION-REQUIRED implies visibility.claims_agent.called must be true.
    Exempt only STATE 0/1 early exits (fixed action list in prompt).
    """
    if decision.get("type") != "ACTION-REQUIRED":
        return False
    actions = decision.get("actions") or []
    if actions and all(a in _ACTION_REQUIRED_NO_CLAIMS_ACTIONS for a in actions):
        return False
    return True


def _extract_json_object(raw: str) -> Dict[str, Any]:
    """Extract first JSON object from raw text or fenced block."""
    text = (raw or "").strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1).strip())
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _claims_spec_present(claims: Dict[str, Any]) -> bool:
    """True when claims payload contains a non-empty evidence spec."""
    spec = claims.get("evidence_requirement_spec")
    return isinstance(spec, dict) and bool(spec.get("categories"))


def _fallback_evidence_requirement_spec(request: Dict[str, Any], action_id: str) -> Dict[str, Any]:
    """Build generic evidence requirement spec when claims output is malformed."""
    zone = request.get("zone") or {}
    pilot = request.get("pilot") or {}
    uav = request.get("uav") or {}
    return {
        "type": "EVIDENCE_REQUIREMENT",
        "spec_version": "1.0",
        "request_id": action_id,
        "subject": {
            "sade_zone_id": zone.get("sade_zone_id", "UNKNOWN"),
            "pilot_id": pilot.get("pilot_id", "UNKNOWN"),
            "organization_id": pilot.get("organization_id", "UNKNOWN"),
            "drone_id": uav.get("drone_id", "UNKNOWN"),
        },
        "categories": [
            {
                "category": "CAPABILITY",
                "requirements": [
                    {
                        "requirement_id": "req-generic-mitigation-evidence",
                        "expr": "PROVIDE_ADDITIONAL_EVIDENCE",
                        "keyword": "PROVIDE_ADDITIONAL_EVIDENCE",
                        "params": [],
                        "applicable_scopes": ["PILOT", "UAV"],
                    }
                ],
            }
        ],
    }


def _force_action_required_fallback(raw: str, request: Dict[str, Any]) -> Dict[str, Any]:
    """Force generic ACTION-REQUIRED if claims still omits required evidence spec."""
    parsed = _extract_json_object(raw) or {}
    decision = parsed.setdefault("decision", {})
    visibility = parsed.setdefault("visibility", {})
    claims = visibility.setdefault("claims_agent", {})

    action_id = decision.get("action_id") or f"REQ-{(request.get('evaluation_id') or 'GENERIC')[:8]}"
    spec = _fallback_evidence_requirement_spec(request, action_id)
    actions = decision.get("actions") or ["PROVIDE_ADDITIONAL_EVIDENCE"]

    decision["type"] = "ACTION-REQUIRED"
    decision["action_id"] = action_id
    decision["actions"] = actions
    decision["evidence_requirement_spec"] = spec
    decision["constraints"] = []
    decision["denial_code"] = None
    decision["explanation"] = (
        decision.get("explanation")
        or "Claims verification output was incomplete; additional evidence is required to continue review."
    )
    decision["sade_message"] = f"ACTION-ID,{action_id},({','.join(actions)})"

    claims["called"] = True
    claims["satisfied"] = False
    claims["evidence_requirement_spec"] = spec
    claims.setdefault("satisfied_actions", [])
    claims.setdefault("unsatisfied_actions", actions)
    claims.setdefault("why", ["Claims output omitted evidence requirement spec; generic remediation requested."])
    claims.setdefault("recommendation_prose", "Additional evidence is required before a final approval decision.")
    claims.setdefault("why_prose", "Claims verification did not include a required evidence specification.")

    visibility.setdefault("entry_request", request)
    visibility.setdefault("rule_trace", [])
    return parsed


def _claims_conflict_debug_message(raw: str) -> str:
    """Return compact debug context for claims spec/satisfied conflict."""
    parsed = _extract_json_object(raw) or {}
    decision = parsed.get("decision", {}) if isinstance(parsed, dict) else {}
    claims = ((parsed.get("visibility") or {}).get("claims_agent") or {}) if isinstance(parsed, dict) else {}
    return (
        "Debug: claims output conflict after retry. "
        f"decision.type={decision.get('type')}, "
        f"claims.called={claims.get('called')}, "
        f"claims.satisfied={claims.get('satisfied')}, "
        f"claims.has_spec={_claims_spec_present(claims)}"
    )

from models import (
    EnvironmentAgentOutput,
    ReputationAgentOutput,
    ActionRequiredAgentOutput,
    ClaimsAgentOutput,
    OrchestratorOutput,
)
def load_prompt(prompt_file: str, prompts_dir: str = "prompts") -> str:
    """Load prompt text from a markdown file."""
    prompt_path = Path(__file__).parent / prompts_dir / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text()


# Load agent prompts (v3: orchestrator, env, rm, claims with visibility _prose; v1: action_required for SafeCert tool)
ORCHESTRATOR_PROMPT = load_prompt("orchestrator_prompt.md", prompts_dir="v5_prompts")
ENVIRONMENT_AGENT_PROMPT = load_prompt("env_agent_prompt.md", prompts_dir="v5_prompts")
REPUTATION_AGENT_PROMPT = load_prompt("rm_agent_prompt.md", prompts_dir="v5_prompts")
# ACTION_REQUIRED_AGENT_PROMPT = load_prompt("action_required_agent_prompt.md")
CLAIMS_AGENT_PROMPT = load_prompt("claims_agent_prompt.md", prompts_dir="v5_prompts")


# Sub-Agents (Advisory Only - Never Make Decisions)

environment_agent = Agent(
    name="environment_agent",
    # model_settings=ModelSettings(temperature=0.4),
    model="gpt-5.2",
    instructions=ENVIRONMENT_AGENT_PROMPT,
    output_type=EnvironmentAgentOutput,
    handoff_description=(
        "Analyzes entry-request weather and UAV model data and returns "
        "EnvironmentAgentOutput with wind/payload risk signals."
    ),
)

reputation_agent = Agent(
    name="reputation_agent",    
    model="gpt-5.2",
    # model_settings=ModelSettings(temperature=0.4),
    instructions=REPUTATION_AGENT_PROMPT,
    output_type=ReputationAgentOutput,
    handoff_description=(
        "Analyzes provided reputation_records and returns deterministic "
        "ReputationAgentOutput historical risk signals."
    ),
)

# action_required_agent = Agent(
#     name="action_required_agent",
#     instructions=ACTION_REQUIRED_AGENT_PROMPT,
#     output_type=ActionRequiredAgentOutput,
#     tools=[request_attestation],
#     handoff_description="Interfaces with SafeCert to request and retrieve formal evidence attestations",
# )

claims_agent = Agent(
    name="claims_agent",
    # model_settings=ModelSettings(temperature=0.4),
    model="gpt-5.2",
    instructions=CLAIMS_AGENT_PROMPT,
    output_type=ClaimsAgentOutput,
    handoff_description=(
        "Verifies required_actions against provided attestation_claims and "
        "incident context; returns ClaimsAgentOutput and evidence requirement spec when needed."
    ),
)


# Orchestrator Agent (Sole Decision Authority)

orchestrator_agent = Agent(
    name="orchestrator_agent",
    model="gpt-5.2",
    instructions=ORCHESTRATOR_PROMPT,
    tools=[
        environment_agent.as_tool(
            tool_name="environment_agent",
            tool_description=(
                "Analyze environmental and MFC context from the provided nested entry-request JSON. "
                "Input: JSON string containing entry request fields including payload, uav/uav_model, zone, and weather_forecast."
                "Returns: EnvironmentAgentOutput (manufacturer_fc with manufacturer, model, category, mfc_payload_max_kg, mfc_max_wind_kt; raw_conditions; risk_assessment; constraint_suggestions_wind; constraint_suggestions_payload; recommendation_wind; recommendation_payload; recommendation_prose_wind; recommendation_prose_payload; why_prose_wind; why_prose_payload; why_wind; why_payload)."
            ),
        ),
        reputation_agent.as_tool(
            tool_name="reputation_agent",
            tool_description=(
                "Analyze provided historical reputation_records for the current DPO context. "
                "Input: JSON string containing entry request fields and reputation_records list. "
                "Returns: ReputationAgentOutput (validated Pydantic model) with incident_analysis, risk_assessment, orchestration fields."
            ),
        ),
        # action_required_agent.as_tool(
        #     tool_name="request_attestation",
        #     tool_description=(
        #         "Request evidence attestations from SafeCert. "
        #         "Input: JSON string with keys: pilot_id, org_id, drone_id, entry_time, safecert_pin, evidence_required. "
        #         "Returns: ActionRequiredAgentOutput (validated Pydantic model) with satisfied (boolean) and attestation. "
        #         "Only call this when ACTION-REQUIRED decision has been issued."
        #     ),
        # ),
        claims_agent.as_tool(
            tool_name="claims_agent",
            tool_description=(
                "Verify required_actions against provided attestation_claims and incident context. "
                "Input: JSON string with action_id, subject ids, required_actions, incident_codes, wind_context, and attestation_claims. "
                "Returns: ClaimsAgentOutput with satisfied, resolved/unresolved incident prefixes, satisfied/unsatisfied actions, "
                "optional evidence_requirement_spec, and why. Call this when STATE 3 yields ACTION-REQUIRED before emitting any final decision."
            ),
        ),
    ],
)


def format_entry_request(request: Dict[str, Any]) -> str:
    """
    Format an entry request dictionary into a structured text format
    for the Orchestrator Agent.
    """
    zone = request.get("zone") or {}
    pilot = request.get("pilot") or {}
    uav = request.get("uav") or {}
    request_type = request.get("request_type")
    if not request_type:
        request_type = "ZONE" if request.get("entry_request_kind") == "ENTRY" else "UNKNOWN"

    lines = [
        "ENTRY REQUEST",
        "=" * 50,
        f"Evaluation ID: {request.get('evaluation_id', 'MISSING')}",
        f"Evaluation Series ID: {request.get('evaluation_series_id', 'MISSING')}",
        f"Entry Request Kind: {request.get('entry_request_kind', 'MISSING')}",
        f"SADE Zone ID: {zone.get('sade_zone_id', 'MISSING')}",
        f"Pilot ID: {pilot.get('pilot_id', 'MISSING')}",
        f"Organization ID: {pilot.get('organization_id', 'MISSING')}",
        f"Drone ID: {uav.get('drone_id', 'MISSING')}",
        f"Payload (kg): {request.get('payload', 'MISSING')}",
        f"Requested Entry Time: {request.get('requested_entry_time', 'MISSING')}",
        f"Requested Exit Time: {request.get('requested_exit_time', 'MISSING')}",
        f"Request Type (derived): {request_type}",
    ]
    lines.extend(
        [
            "",
            "Provided Data Blocks:",
            f"- uav_model: {'present' if isinstance(request.get('uav_model'), dict) else 'missing'}",
            f"- weather_forecast: {'present' if isinstance(request.get('weather_forecast'), dict) else 'missing'}",
            f"- reputation_records: {len(request.get('reputation_records', []))}",
            f"- attestation_claims: {len(request.get('attestation_claims', []))}",
            f"- entry_request_history: {len(request.get('entry_request_history', []))}",
        ]
    )
    
    # Include safecert_pin if provided (for ACTION-REQUIRED re-evaluation)
    if 'safecert_pin' in request:
        lines.append(f"\nSafeCert PIN: {request['safecert_pin']}")
    
    # Include evidence_required if provided (for ACTION-REQUIRED re-evaluation)
    if 'evidence_required' in request:
        lines.append(f"\nEvidence Required:")
        lines.append(json.dumps(request['evidence_required'], indent=2))
    lines.append("\nENTRY REQUEST JSON (canonical):")
    lines.append(json.dumps(request, indent=2))
    
    return "\n".join(lines)


def _normalize_visibility(parsed: Dict[str, Any]) -> None:
    """Normalize visibility aliases to the current nested entry_request shape."""
    vis = parsed.get("visibility") or {}
    entry = vis.get("entry_request") or {}
    if not isinstance(entry, dict):
        return
    zone = entry.get("zone")
    if isinstance(zone, dict) and "zone_id" in zone and "sade_zone_id" not in zone:
        zone["sade_zone_id"] = zone.pop("zone_id")
    pilot = entry.get("pilot")
    if isinstance(pilot, dict) and "org_id" in pilot and "organization_id" not in pilot:
        pilot["organization_id"] = pilot.pop("org_id")


def _align_decision_with_claims_evidence_spec(parsed: Dict[str, Any]) -> None:
    """
    When claims_agent emits evidence_requirement_spec, decision must echo it.
    If the model still emits DENIED (legacy STATE 5.1) while claims provided a spec,
    align to ACTION-REQUIRED with the same spec (product rule: remediation via evidence).
    """
    decision = parsed.get("decision")
    vis = parsed.get("visibility")
    if not isinstance(decision, dict) or not isinstance(vis, dict):
        return
    claims = vis.get("claims_agent") or {}
    if not isinstance(claims, dict) or not _claims_spec_present(claims):
        return
    spec = claims.get("evidence_requirement_spec")
    if not isinstance(spec, dict):
        return
    decision["evidence_requirement_spec"] = spec
    if decision.get("type") == "DENIED" and claims.get("called"):
        actions = claims.get("unsatisfied_actions") or []
        if not actions:
            actions = ["PROVIDE_ADDITIONAL_EVIDENCE"]
        rid = spec.get("request_id") or decision.get("action_id") or "ACT-REMEDIATION"
        decision["type"] = "ACTION-REQUIRED"
        decision["denial_code"] = None
        decision["constraints"] = []
        decision["action_id"] = rid
        decision["actions"] = actions
        decision["sade_message"] = f"ACTION-ID,{rid},({','.join(actions)})"
        if not decision.get("explanation"):
            decision["explanation"] = (
                "Action required: claims verification requires additional evidence per "
                "evidence_requirement_spec before a final admission decision."
            )


def parse_orchestrator_output(raw: str) -> Dict[str, Any]:
    """
    Parse the orchestrator's final output as JSON (v2/v3 contract: decision + visibility).

    Tries raw JSON first, then a single ```json ... ``` code block.
    Normalizes visibility.entry_request to use sade_zone_id and organization_id.
    Raises ValueError if no valid JSON object with "decision" is found.
    """
    parsed = _extract_json_object(raw)
    if isinstance(parsed, dict) and "decision" in parsed:
        _normalize_visibility(parsed)
        _align_decision_with_claims_evidence_spec(parsed)
        try:
            OrchestratorOutput.model_validate(parsed)
        except Exception:
            pass  # Keep permissive validation for compatibility while guardrails enforce critical rules.
        decision = parsed.get("decision", {})
        vis = parsed.get("visibility", {})
        claims = vis.get("claims_agent", {}) if isinstance(vis, dict) else {}
        if _claims_call_required(decision) and not claims.get("called", False):
            raise ValueError(
                "Invalid orchestrator output: ACTION-REQUIRED decision without claims_agent.called == true"
            )
        if _claims_spec_present(claims) and claims.get("satisfied") is True:
            raise ValueError(f"Invalid orchestrator output: {_CLAIMS_SPEC_CONFLICT_TOKEN}")
        if claims.get("called", False) and claims.get("satisfied") is False and not _claims_spec_present(claims):
            raise ValueError(f"Invalid orchestrator output: {_CLAIMS_SPEC_MISSING_TOKEN}")
        if _claims_spec_present(claims) and not isinstance(decision.get("evidence_requirement_spec"), dict):
            raise ValueError(
                "Invalid orchestrator output: claims provided evidence_requirement_spec but decision did not include it"
            )
        return parsed
    raise ValueError("Orchestrator output did not contain valid JSON with 'decision'")


async def process_entry_request(
    request: Dict[str, Any],
    max_turns: int = DEFAULT_MAX_TURNS,
) -> Dict[str, Any]:
    """
    Process an entry request through the SADE Orchestrator Agent (single run).

    The v2 orchestrator runs until it emits a final JSON (calling env, reputation,
    and claims_agent as needed in one run). If the model emits STATE 3 ACTION-REQUIRED
    without calling claims_agent, one corrective follow-up run is attempted.

    Args:
        request: Entry request dictionary
        max_turns: Max LLM/tool turns per run (default 25)

    Returns:
        Parsed output dict with "decision" and "visibility" (v2 contract).
        Raises ValueError if output could not be parsed as JSON.
    """
    formatted_request = format_entry_request(request)
    correction = (
        "FRAMEWORK CORRECTION (mandatory): Your last JSON was invalid because "
        "decision.type was ACTION-REQUIRED from STATE 3 but visibility.claims_agent.called "
        "was false. In the same run you MUST call claims_agent with the correct "
        "action_id and inputs, complete STATE 5 using its output, then emit exactly "
        "one final JSON with claims_agent.called true. Do not emit final JSON until "
        "this is done."
    )
    claims_spec_correction = (
        "FRAMEWORK CORRECTION (mandatory): claims_agent returned satisfied=false without "
        "evidence_requirement_spec. Re-run the claims path and ensure claims_agent output includes "
        "a valid evidence_requirement_spec. Then copy that exact object to decision.evidence_requirement_spec "
        "and emit one final JSON."
    )
    claims_conflict_correction = (
        "FRAMEWORK CORRECTION (mandatory): claims_agent output is internally inconsistent because "
        "evidence_requirement_spec was present while satisfied=true. Re-run claims verification and emit "
        "a consistent result: if evidence_requirement_spec exists, satisfied must be false and final decision "
        "must be ACTION-REQUIRED; if satisfied is true, omit evidence_requirement_spec."
    )
    with trace("SADE Entry Request Processing"):
        result = await Runner.run(
            orchestrator_agent,
            formatted_request,
            max_turns=max_turns,
        )
    raw = result.final_output.strip()
    try:
        return parse_orchestrator_output(raw)
    except ValueError as e:
        if (
            "claims_agent.called" not in str(e)
            and _CLAIMS_SPEC_MISSING_TOKEN not in str(e)
            and _CLAIMS_SPEC_CONFLICT_TOKEN not in str(e)
        ):
            raise
        if "claims_agent.called" in str(e):
            fix_prompt = correction
        elif _CLAIMS_SPEC_MISSING_TOKEN in str(e):
            fix_prompt = claims_spec_correction
        else:
            fix_prompt = claims_conflict_correction
        with trace("SADE Entry Request Processing (claims correction)"):
            result = await Runner.run(
                orchestrator_agent,
                formatted_request + "\n\n" + fix_prompt,
                max_turns=max_turns,
            )
        raw = result.final_output.strip()
        try:
            return parse_orchestrator_output(raw)
        except ValueError as e2:
            if _CLAIMS_SPEC_MISSING_TOKEN in str(e2):
                return _force_action_required_fallback(raw, request)
            if _CLAIMS_SPEC_CONFLICT_TOKEN in str(e2):
                raise ValueError(_claims_conflict_debug_message(raw))
            raise

# Main function
async def main():
    """
    Example entry request processing.
    """
    if "good" in sys.argv:
        entry_request_file = "resources/good_entry_request.json"
        test_number = 1
    elif "medium" in sys.argv:
        entry_request_file = "resources/medium_entry_request.json"
        test_number = 2
    elif "bad" in sys.argv:
        entry_request_file = "resources/bad_entry_request.json"
        test_number = 3
    else:
        raise ValueError("Invalid entry request file")

    print("=" * 70)
    print(f"Processing {entry_request_file}...")
    print("=" * 70)
    print("=" * 70)

    # Example Entry Request (pilot_id/drone_id match sade-mock-data/reputation_model.json and user_input.json)
    with open(entry_request_file, "r") as f:
        request = json.load(f)
    # Adding other resources to the request
    with open("resources/attestation_claims.json", "r") as f:
        request["attestation_claims"] = json.load(f)
    with open("resources/reputation_records.json", "r") as f:
        request["reputation_records"] = json.load(f)
    with open("resources/entry_request_history.json", "r") as f:
        request["entry_request_history"] = json.load(f)
    
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

        output_filename = f"results/integration/entry_result_{test_number}.txt"
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

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user (Ctrl+C). Exiting.")
        sys.exit(0)
