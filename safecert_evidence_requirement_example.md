### SAFEcert Evidence Requirement Example (`ACTION-REQUIRED`)

This document gives a concrete `Input -> LLM_AGENT(Input) -> evidence_requirement_spec` example, aligned to `results/integration/entry_result_2.txt`.

Goal: show exactly what SAFEcert receives when SADE decides `ACTION-REQUIRED` (the `evidence_requirement_spec` payload).

---

### 1) Input

#### 1.1 Subjects (UAV, UAV Model, Pilot, Zone)

```json
{
  "uav": {
    "drone_id": "drone-001",
    "model_id": "model-001",
    "owner_id": "owner-001"
  },
  "uav_model": {
    "model_id": "model-001",
    "name": "DJI Mavic 3",
    "max_wind_tolerance": 12.2,
    "max_temp_f": 110.0,
    "min_temp_f": -10.0,
    "max_payload_cap_kg": 2.268
  },
  "pilot": {
    "pilot_id": "pilot-001",
    "organization_id": "org-001"
  },
  "zone": {
    "sade_zone_id": "zone-001",
    "name": "Zone 001"
  },
  "requested_entry_time": "2026-03-09T18:00:00Z"
}
```

#### 1.2 Reputation Records and Claims on File

For this case, records/claims include:
- Incident history contains `0101-100` and `0011-010`.
- Claims on file include `FOLLOWUP_REPORT` for `0101-100`, and both follow-up + mitigation for `0011-010`.
- Missing on-file claims needed for this request:
  - `MITIGATION_EVIDENCE(incident_code=0101-100)`
  - PILOT-scoped `PART_107` valid at `2026-03-09T18:00:00Z`

```json
{
  "reputation_records": [
    { "reputation_record_id": "rep-003", "incidents": ["0101-100"] },
    { "reputation_record_id": "rep-005", "incidents": ["0011-010"] }
  ],
  "attestation_claims": [
    {
      "expr": "FOLLOWUP_REPORT(incident_code=0101-100)",
      "keyword": "FOLLOWUP_REPORT",
      "status": "SATISFIED"
    },
    {
      "expr": "FOLLOWUP_REPORT(incident_code=0011-010)",
      "keyword": "FOLLOWUP_REPORT",
      "status": "SATISFIED"
    },
    {
      "expr": "MITIGATION_EVIDENCE(incident_code=0011-010)",
      "keyword": "MITIGATION_EVIDENCE",
      "status": "SATISFIED"
    }
  ]
}
```

#### 1.3 Environmental Conditions

```json
{
  "weather_forecast": {
    "sade_zone_id": "zone-001",
    "window_start": "2026-03-09T18:00:00Z",
    "window_end": "2026-03-09T19:00:00Z",
    "max_wind_knots": 9.0,
    "max_gust_knots": 11.0,
    "min_temp_f": 50.0,
    "max_temp_f": 60.0,
    "visibility_min_nm": 10.0
  },
  "payload_kg": 1.6
}
```

Interpretation:
- Wind/gust and payload are within UAV model limits.
- The case is still `ACTION-REQUIRED` because claims verification is incomplete for required actions.

---

### 2) LLM_AGENT(Input) -> `ACTION-REQUIRED`

Given the above, the agent decides:
- `ACTION-REQUIRED`
- required actions include:
  - `RESOLVE_0100_0101_INCIDENTS_AND_MITIGATE_WIND_RISK`
  - `PART_107_VERIFICATION`

Only the `evidence_requirement_spec` below is sent to SAFEcert.

---

### 3) Output sent to SAFEcert (`evidence_requirement_spec`)

```json
{
  "type": "EVIDENCE_REQUIREMENT",
  "spec_version": "1.0",
  "request_id": "ACT-b80eac98e26b49889179c4e84fc4530f-1744135096",
  "subject": {
    "sade_zone_id": "",
    "pilot_id": "pilot-001",
    "organization_id": "org-001",
    "drone_id": "drone-001"
  },
  "categories": [
    {
      "category": "CAPABILITY",
      "requirements": [
        {
          "requirement_id": "req-mitigation-0101-100",
          "expr": "MITIGATION_EVIDENCE(incident_code=0101-100)",
          "keyword": "MITIGATION_EVIDENCE",
          "applicable_scopes": ["PILOT", "UAV"],
          "params": [
            {
              "prefix": "0101",
              "incident_code": "0101-100",
              "incident_codes": null,
              "key": null,
              "value": null
            }
          ]
        },
        {
          "requirement_id": "req-wind-risk-mitigation-artifact",
          "expr": "WIND_RISK_MITIGATION(entry_time=2026-03-09T18:00:00Z, wind_now_kt=9.0, gust_now_kt=11.0)",
          "keyword": "WIND_RISK_MITIGATION",
          "applicable_scopes": ["PILOT", "UAV"],
          "params": [
            {
              "prefix": null,
              "incident_code": null,
              "incident_codes": ["0101-100"],
              "key": "required_for_action",
              "value": "RESOLVE_0100_0101_INCIDENTS_AND_MITIGATE_WIND_RISK"
            }
          ]
        }
      ]
    },
    {
      "category": "CERTIFICATION",
      "requirements": [
        {
          "requirement_id": "req-part-107-valid-at-entry-time",
          "expr": "PART_107(valid_at=2026-03-09T18:00:00Z)",
          "keyword": "PART_107",
          "applicable_scopes": ["PILOT"],
          "params": [
            {
              "prefix": null,
              "incident_code": null,
              "incident_codes": null,
              "key": "valid_at",
              "value": "2026-03-09T18:00:00Z"
            }
          ]
        }
      ]
    }
  ]
}
```

This is the concrete payload SAFEcert receives for this `ACTION-REQUIRED` case.

