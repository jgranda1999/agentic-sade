# SADE Agentic Orchestration System

A safety-critical, evidence-driven system for automatically determining whether a Drone | Pilot | Organization (DPO) trio may enter a controlled SADE Zone. The system uses environmental conditions (including live weather when configured), historical reputation data, and formal evidence attestations to make auditable admission decisions.

## Where the project is today

- **Orchestrator and sub-agents** use the **OpenAI Agents SDK** (`openai-agents`) with **`gpt-5.2`** and prompts under **`v5_prompts/`** (this is the active prompt set; older iterations remain in `v1_prompts/`–`v4_prompts/` for comparison).
- **Single-run flow**: `process_entry_request()` runs the orchestrator once; if the model emits STATE 3 `ACTION-REQUIRED` without calling `claims_agent`, a **one-shot corrective rerun** is attempted with an injected framework message (`main.py`).
- **Environment tooling**: `retrieveEnvironment` can use **Open-Meteo** for live US-area forecasts when mock weather is off; **mock wind/visibility profiles** remain for deterministic scenario runs (`tools/environment_tools.py`, `tools/open_meteo.py`).
- **Location for weather**: Before the run, `resolve_entry_request_location()` may set `weather_latitude` / `weather_longitude` from explicit coordinates in `request_payload` or from **`request_payload.location_query`** via **Google Geocoding** (`tools/location_resolution.py`). If nothing resolves, tools fall back to waypoints, polygon centroid, or a configurable US default (`SADE_WEATHER_LAT` / `SADE_WEATHER_LON`).
- **SafeCert / attestation agent**: The `action_required_agent` and `request_attestation` tool are **present in code but commented out** in `main.py`; the current loop does not expose them to the orchestrator. Claims verification via `claims_agent` is active when the prompt path requires it.
- **Outputs**: Runs write human-readable traces plus full JSON (`decision` + `visibility`) under **`results/`**, including **`live-environment/{good,medium,bad}/`** alongside older **weather** and **mfc-payload** scenario folders.

## Overview

The Safety-Aware Drone Ecosystem (SADE) admission system implements a **deterministic, evidence-driven, auditable agentic workflow**. Conceptually:

- **Phase 1 – Fast path**: Gather environment and reputation signals; decide when conditions are clear.
- **Phase 2 – Evidence escalation**: When the policy requires it, escalate to additional evidence and claims checks (per orchestrator state machine in `v5_prompts/orchestrator_prompt.md`).

## Architecture

Multi-agent setup with a **single decision authority**:

### Orchestrator Agent (decision authority)

- Accepts formatted entry requests.
- Delegates to sub-agents for data only.
- Performs pairwise analysis (Request × Environment, Request × Reputation, Environment × Reputation).
- Emits evidence requirements when needed.
- Issues the **only** entry decision (plus required visibility metadata).

### Sub-agents (advisory only)

| Agent | Role | Tools |
|--------|------|--------|
| **Environment** | Operating conditions: weather, light, airspace/spatial notes, MFC | `retrieveEnvironment`, `retrieveMFC` |
| **Reputation** | Trust signals: pilot, org, drone; incidents | `retrieve_reputations` |
| **Claims** | Verify required actions vs. DPO claims / follow-ups | `retrieve_claims` |

The **Action Required / SafeCert** interface (`request_attestation`) exists in `tools/action_required_tools.py` but is **not wired** into the orchestrator agent in the current `main.py`.

## Entry request model

Each entry request includes:

- `sade_zone_id`, `pilot_id`, `organization_id`, `drone_id`
- `requested_entry_time`: ISO8601 string (optional duplicate `entry_time` is normalized in code)
- `payload`: mass (string or number) where applicable
- `request_type`: `ZONE`, `REGION`, or `ROUTE`
- `request_payload`: type-specific (polygons, waypoints, ceiling/floor, optional **`location_query`** for geocoded weather, or explicit `lat`/`lon`)

Shared helpers: `tools/entry_request_fields.py` (canonical `entry_time` for tools).

## Decision outputs

The orchestrator emits exactly one of:

- `APPROVED`
- `APPROVED-CONSTRAINTS,(...)`
- `ACTION-REQUIRED,(...)`
- `DENIED,(DENIAL_CODE, explanation)`

## Evidence grammar

Evidence uses four categories (**CERTIFICATION**, **CAPABILITY**, **ENVIRONMENT**, **INTERFACE**). See `models.py` and `v5_prompts/` for the exact contract.

## Installation

### Prerequisites

- Python 3.8+
- pip

### Setup

```bash
git clone <repository-url>
cd agentic-sade-dev
pip install -r requirements.txt
```

Dependencies include **openai-agents**, **openai**, **pydantic**, and **httpx** (Open-Meteo and HTTP calls).

### API keys and environment

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required for model calls |
| `SADE_WEATHER_LAT`, `SADE_WEATHER_LON` | Optional defaults when no geometry or query resolves (see `environment_tools.py`) |

Geocoding for `location_query` uses the Google Geocoding API path in `location_resolution.py` (ensure your deployment supplies valid credentials / keys as required by that module).

### Rate limiting

`main()` sleeps **60 seconds** after a run to reduce API rate-limit issues. Adjust the `asyncio.sleep()` value in `main.py` if needed.

## Usage

### Programmatic

```python
import asyncio
from main import process_entry_request

async def run():
    request = {
        "sade_zone_id": "ZONE-123",
        "pilot_id": "FA-01234567",
        "organization_id": "ORG-789",
        "drone_id": "DRONE-001",
        "requested_entry_time": "2026-01-26T14:00:00Z",
        "request_type": "REGION",
        "payload": "5.0",
        "request_payload": {
            "polygon": [
                {"lat": 41.7000, "lon": -86.2400},
                {"lat": 41.7010, "lon": -86.2400},
                {"lat": 41.7010, "lon": -86.2390},
                {"lat": 41.7000, "lon": -86.2390},
            ],
            "ceiling": 300,
            "floor": 100,
        },
    }
    out = await process_entry_request(request)
    print(out["decision"])

asyncio.run(run())
```

### CLI

```bash
python main.py
```

The sample `main()` loads **`sade-mock-data/entry_requests.json`**, picks a request (currently the first “good” example is assigned to `request`), runs `process_entry_request`, and writes a file under **`results/`** (the exact subdirectory is set in `main.py`—e.g. live-environment vs. weather scenarios). Edit `main()` to point at another index or output path.

### GUI visualizer

PyQt5 app for inspecting saved result files:

```bash
python gui.py
python gui.py results/live-environment/good/entry_result_ZONE-003.txt
```

Bundled **presets** in the GUI cover **Weather · Wind** (good/medium/bad) and **MFC/Payload** (good/medium/bad). Add live-environment samples manually via **Open file** or extend `PRESETS` in `gui.py` if you want one-click access.

## Decision flow (high level)

1. Validate / normalize request (including location resolution).
2. Retrieve environment and reputation signals via tools.
3. Pair-wise analysis and state machine (see `v5_prompts/orchestrator_prompt.md`).
4. If `ACTION-REQUIRED` from STATE 3, **claims_agent** must be invoked before a final JSON; code enforces this where applicable.
5. Emit final JSON with `decision` and `visibility`.

Max turns per run default to **25** (`DEFAULT_MAX_TURNS` in `main.py`).

## Project structure

```
agentic-sade-dev/
├── main.py                     # Agents, process_entry_request, CLI example
├── gui.py                      # PyQt5 decision visualizer
├── models.py                   # Pydantic models, evidence shapes
├── tools/
│   ├── environment_tools.py    # MFC + weather (Open-Meteo / mock)
│   ├── open_meteo.py           # Open-Meteo client helpers
│   ├── location_resolution.py  # Geocoding / weather lat-lon prep
│   ├── entry_request_fields.py # entry_time normalization
│   ├── reputation_tools.py
│   ├── claims_tools.py
│   └── action_required_tools.py  # SafeCert mock (not wired in main.py)
├── v5_prompts/                 # Active prompts (orchestrator + sub-agents)
├── v4_prompts/ … v1_prompts/   # Historical prompts
├── sade-mock-data/             # entry_requests.json, reputation, claims fixtures
├── results/
│   ├── weather/wind-visibility-{good,medium,bad}/
│   ├── mfc-payload/mfc-payload-{good,medium,bad}/
│   └── live-environment/{good,medium,bad}/
├── other/project_overview.md   # Deeper architecture notes
├── to-dos.md
├── requirements.txt
└── README.md
```

## Development notes

- **Conservative / evidence-driven / auditable** design goals are unchanged; see existing sections in `other/project_overview.md`.
- **Tool I/O**: Sub-agent tools expect **JSON strings**; returns are validated toward Pydantic models where defined.
- **Mocks**: Reputation, claims, and MFC file paths remain mock-oriented; weather can be live or profile-driven depending on tool configuration.

## Testing

Use `sade-mock-data/entry_requests.json` and tune `main()` to iterate requests. Result files land under `results/.../entry_result_{ZONE_ID}.txt` (naming may vary with zone id).

## Contributing

Changes should preserve deterministic policy behavior, auditability, and the evidence grammar—no silent bypass of safety checks.

## License

[Specify license]

## References

- `other/project_overview.md` — extended architecture
- `v5_prompts/orchestrator_prompt.md` — current orchestrator logic
- `models.py` — data models
- `v1_prompts/`–`v4_prompts/` — prompt history
