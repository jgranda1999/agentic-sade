# SADE Agentic Orchestration System

A safety-critical, evidence-driven system for automatically determining whether a Drone | Pilot | Organization (DPO) trio may enter a controlled SADE Zone. The system uses real-time environmental conditions, historical reputation data, and formal evidence attestations to make deterministic, auditable admission decisions.

## Overview

The Safety-Aware Drone Ecosystem (SADE) admission system replaces manual authorization with a **deterministic, evidence-driven, auditable agentic workflow**. The system operates in two phases:

- **Phase 1 - Fast Path**: Gathers environment and reputation data, makes immediate decisions when safe
- **Phase 2 - Evidence Escalation**: Triggers SafeCert attestation workflow when additional evidence or mitigation is required

## Architecture

The system uses a multi-agent architecture with a single decision authority:

### Orchestrator Agent (Decision Authority)
- Receives entry requests
- Delegates to sub-agents for data retrieval
- Performs pair-wise analysis (Request × Environment, Request × Reputation, Environment × Reputation)
- Generates evidence requirements when needed
- Issues the **only** entry decision

### Sub-Agents (Advisory Only)

#### Environment Agent
- **Purpose**: Retrieve external operating conditions
- **Data**: Weather (wind, gusts, precipitation, visibility), light conditions, airspace/spatial constraints
- **Tool**: `retrieveEnvironment`

#### Reputation Agent
- **Purpose**: Retrieve historical trust and reliability signals
- **Data**: Pilot, organization, and drone reputation scores; incident history (including unresolved incidents)
- **Tool**: `retrieve_reputations`

#### Action Required Agent (SafeCert Interface)
- **Purpose**: Interface with SafeCert/Proving Grounds
- **Function**: Requests and retrieves formal evidence attestations
- **Tool**: `request_attestation`
- **Note**: Never makes admission decisions

## Entry Request Model

Each entry request includes:

- `sade_zone_id`: Target SADE zone identifier
- `pilot_id`: FAA pilot registration (e.g., "FA-01234567")
- `organization_id`: Organization identifier
- `drone_id`: Drone identifier
- `requested_entry_time`: ISO8601 datetime string
- `request_type`: One of `ZONE`, `REGION`, or `ROUTE`
- `request_payload`: Type-specific payload
  - **ZONE**: Full zone access
  - **REGION**: `polygon` (lat/lon coordinates), `ceiling`, `floor` (meters ASL)
  - **ROUTE**: Ordered `waypoints` (lat, lon, altitude ASL)

## Decision Outputs

The Orchestrator outputs exactly one of:

- `APPROVED`: Entry allowed without constraints
- `APPROVED-CONSTRAINTS,(...)`: Entry allowed with enforceable operational limits
- `ACTION-REQUIRED,(...)`: Additional evidence/certification required (includes evidence requirement JSON)
- `DENIED,(DENIAL_CODE, explanation)`: Fundamentally unsafe or policy-forbidden

## Evidence Grammar

Evidence is expressed using a formal grammar with four fixed categories:

- **CERTIFICATION**: Regulatory certifications (e.g., PART_107, BVLOS)
- **CAPABILITY**: Operational capabilities (e.g., NIGHT_FLIGHT, PAYLOAD limits)
- **ENVIRONMENT**: Environmental mitigations (e.g., MAX_WIND_GUST)
- **INTERFACE**: System interface compatibility (e.g., SADE_ATC_API versions)

Evidence appears in two forms:
- **Evidence Requirement**: Requested when more proof is needed
- **Evidence Attestation**: Returned by SafeCert with satisfaction status

## Installation

### Prerequisites

- Python 3.8+
- pip

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd agentic-sade-dev
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

Note: The project uses the `agents` framework (from Anthropic). Ensure you have the necessary API keys configured.

## Usage

### Basic Example

```python
import asyncio
from main import process_entry_request

async def main():
    request = {
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
    
    decision = await process_entry_request(request)
    print(decision)

if __name__ == "__main__":
    asyncio.run(main())
```

### Running the Example

```bash
python main.py
```

## Decision Flow

The Orchestrator follows a mandatory state machine:

1. **Validate Request**: Check request format and required fields
2. **Retrieve Signals**: Call Environment and Reputation agents
3. **Pair-wise Analysis**: 
   - Request × Environment
   - Request × Reputation
   - Environment × Reputation
4. **Initial Decision**: Fast path decision (APPROVED, APPROVED-CONSTRAINTS, ACTION-REQUIRED, or DENIED)
5. **Evidence Escalation**: If ACTION-REQUIRED, request attestations from SafeCert
6. **Re-evaluation**: Evaluate attestation satisfaction
7. **Final Decision**: Emit final decision

The system loops until a final decision is reached (max 5 iterations by default).

## Project Structure

```
agentic-sade-dev/
├── main.py                    # Entry point and orchestration logic
├── models.py                  # Pydantic models for agent outputs
├── tools/
│   ├── environment_tools.py   # Environment agent tool implementation
│   ├── reputation_tools.py    # Reputation agent tool implementation
│   └── action_required_tools.py  # SafeCert interface tool
├── prompts/
│   ├── orchestrator_prompt.md      # Orchestrator agent instructions
│   ├── environment_agent_prompt.md # Environment agent instructions
│   ├── reputation_agent_prompt.md   # Reputation agent instructions
│   └── action_required_agent_prompt.md  # Action Required agent instructions
├── project_overview.md        # Detailed architecture documentation
└── README.md                  # This file
```

## Development Notes

### Safety-Critical Design Principles

- **Conservative**: When uncertain, require evidence
- **Evidence-driven**: Never assume unstated capabilities or certifications
- **Deterministic**: Follow the decision state machine exactly
- **Auditable**: Every decision must be defensible
- **Minimalism**: Request only the smallest set of evidence required

### Tool Communication Protocol

- Sub-agent tools accept **JSON string** inputs (not Python dicts)
- Tools return validated **Pydantic model** outputs (automatically validated)
- Field name mapping:
  - Entry Request `organization_id` → tool input `org_id`
  - Entry Request `requested_entry_time` → tool input `entry_time`

### Mock Implementations

The current tool implementations (`environment_tools.py`, `reputation_tools.py`, `action_required_tools.py`) are **mock implementations** for testing. In production, these would:

- Call actual weather APIs and airspace databases (Environment Agent)
- Query the Reputation Model Profile endpoint (Reputation Agent)
- Interface with the SafeCert API (Action Required Agent)

### Constraints

Constraints are enforceable operational limits such as:
- `SPEED_LIMIT(7m/s)`
- `MAX_ALTITUDE(300m)`
- Reduced region polygons
- Modified route waypoints

Constraints must be:
- Justified by environment or geometry
- NOT replace missing certifications or mitigations

## Testing

The system includes example requests in `main.py`. To test different scenarios, modify the `example_request` dictionary in the `main()` function.

## Contributing

This is a safety-critical system. All changes must:
- Maintain deterministic behavior
- Preserve auditability
- Follow the evidence grammar specification
- Not bypass safety checks

## License

[Specify license]

## References

- See `project_overview.md` for detailed architecture documentation
- See `prompts/orchestrator_prompt.md` for complete Orchestrator decision logic
- See `models.py` for complete data model specifications
