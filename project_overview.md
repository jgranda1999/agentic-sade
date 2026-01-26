# SADE Agentic Orchestration System — Developer Handoff (for Cursor)

This document explains the **current state, architecture, and expectations** of the SADE Agentic Orchestration System. It is written specifically to onboard an autonomous coding agent (e.g., Cursor) so it can continue implementation work correctly and safely.

---

## 1. What This Project Is

You are working on the **Safety‑Aware Drone Ecosystem (SADE)** admission system.

The goal is to **automatically decide whether a Drone | Pilot | Organization (DPO) trio may enter a controlled SADE Zone**, using:

* Real‑time environment conditions
* Historical reputation data
* Formal evidence and attestations (via SafeCert)

The system replaces manual authorization with a **deterministic, evidence‑driven, auditable agentic workflow**.

This is a **safety‑critical system**. Conservative behavior is mandatory.

---

## 2. Big Idea (Read This First)

The system is a **two‑phase admission protocol** controlled by a single Orchestrator Agent.

### Phase 1 — Fast Path (No SafeCert)

* Gather environment + reputation
* Decide immediately if safe

### Phase 2 — Evidence Escalation (SafeCert Loop)

* Triggered only if more evidence or mitigation is required
* Uses a formal evidence grammar
* May loop until resolved

SafeCert is **never called unless Phase 1 cannot decide safely**.

---

## 3. Agents and Responsibilities

### Orchestrator Agent (Decision Authority)

* Receives Entry Requests
* Delegates to sub‑agents
* Performs pair‑wise analysis
* Generates evidence requirements
* Issues the **only** entry decision

The Orchestrator must behave like a **state machine**, not a chatbot.

---

### Environment Agent

**Role:** Retrieve external operating conditions.

* Weather (wind, gusts, precipitation, visibility)
* Light conditions
* Airspace / spatial constraints

It does NOT reason about reputation or evidence.

---

### Reputation Model Agent

**Role:** Retrieve historical trust and reliability signals.

* Pilot reputation
* Organization reputation
* Drone reputation
* Incident history (including unresolved incidents)

It does NOT reason about environment.

---

### ACTION‑REQUIRED Agent (SafeCert Interface)

**Role:** Interface with SafeCert / Proving Grounds.

* Accepts `evidence_required` JSON
* Requests attestations
* Returns `(satisfied, attestation)`

It NEVER makes an admission decision.

---

## 4. Entry Request Model

Each Entry Request always includes:

* `sade_zone_id`
* `pilot_id`
* `organization_id`
* `drone_id`
* `requested_entry_time`
* `request_type`

### Request Types

* **ZONE** — entire zone
* **REGION** — polygon + ceiling/floor (meters ASL)
* **ROUTE** — ordered waypoints (lat, lon, altitude ASL)

Malformed requests **do not reach sub‑agents**.

---

## 5. Decision Outputs (Authoritative)

The Orchestrator must output **exactly one** of:

* `APPROVED`
* `APPROVED-CONSTRAINTS,(...)`
* `ACTION-REQUIRED,(...)`
* `DENIED,(DENIAL_CODE, explanation)`

No additional text, reasoning, or debug output is allowed.

---

## 6. Constraints

Constraints are **enforceable operational limits**, such as:

* `SPEED_LIMIT(7m/s)`
* `MAX_ALTITUDE(300m)`
* Reduced region polygon
* Modified route waypoints

Constraints:

* Must be justified by environment or geometry
* Must NOT replace missing certifications or mitigations

---

## 7. Evidence Grammar (Critical)

Evidence is expressed using a **formal grammar** with four fixed categories:

* CERTIFICATION
* CAPABILITY
* ENVIRONMENT
* INTERFACE

Evidence appears in two forms:

### Evidence Requirement

Used when more proof is needed.

```json
{
  "type": "EVIDENCE_REQUIREMENT",
  "spec_version": "1.0",
  "subject": { ... },
  "categories": [ ... ]
}
```

### Evidence Attestation

Returned by SafeCert.

```json
{
  "type": "EVIDENCE_ATTESTATION",
  "spec_version": "1.0",
  "categories": [ ... ]
}
```

A requirement is satisfied **only if** `meta.status == SATISFIED`.

`PARTIAL`, `NOT_SATISFIED`, and `UNKNOWN` are insufficient unless explicitly allowed by policy (INTERFACE only).

---

## 8. Canonical Matching Rules

To evaluate an attestation:

Match requirements using:

* category
* keyword
* expr (exact string match)
* params (equivalent)

Extra attestation parameters are allowed only if required ones are present and unchanged.

---

## 9. PARTIAL Handling (Important Edge Case)

`PARTIAL` is only conditionally acceptable for **INTERFACE** requirements.

If:

* policy allows partial compatibility, AND
* actual version falls within allowed window

Then:

* Admit with constraints (e.g., `INTERFACE_LIMIT(...)`)

Otherwise:

* Treat as unmet → ACTION‑REQUIRED

---

## 10. Orchestrator Decision State Machine

The Orchestrator MUST follow this order:

0. Validate Entry Request
1. Retrieve Environment + Reputation
2. Pair‑wise Analysis:

   * Request × Environment
   * Request × Reputation
   * Environment × Reputation
3. Initial Decision
4. Evidence Escalation (if ACTION‑REQUIRED)
5. Re‑evaluation after attestation
6. Emit final decision

Skipping steps is not allowed.

---

## 11. Minimal Evidence Principle

When requesting evidence:

* Include **only blocking requirements**
* Reduce requirements after partial satisfaction
* Never request evidence already satisfied

This minimizes pilot burden and system latency.

---

## 12. Non‑Goals (Do NOT Implement)

* Do NOT verify cryptographic signatures
* Do NOT interpret evidence artifacts
* Do NOT auto‑approve on reputation alone
* Do NOT bypass SafeCert for missing certifications

---

## 13. What Cursor Should Build Next

Cursor should focus on:

1. Python implementation of the Orchestrator state machine
2. Tool wrappers for the three agents
3. Evidence matching + satisfaction evaluation logic
4. Clean decision output formatting
5. Deterministic control flow (no free‑form reasoning)

This is a **policy‑driven system**, not a conversational agent.

---

## 14. Final Reminder

This system is safety‑critical.

When uncertain:

* Require evidence
* Do not approve

All behavior must be auditable, conservative, and defensible.
