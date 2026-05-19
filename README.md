Saif Ullah — BSCS23065

# PDC-Sp24-BSCS23065-Ullah

**Course:** Parallel and Distributed Computing (PDC) — Assignment 4  
**Problem implemented:** Fault Tolerance — Circuit Breaker Pattern for LLM API

---

## What this solves

StudySync calls an external LLM API synchronously. When the LLM goes down, each request
blocks for up to 60 seconds, freezing the server for all users.

This implementation adds a **Circuit Breaker** that:
1. Allows requests through normally (CLOSED state)
2. After 3 consecutive failures, opens the circuit (OPEN state) and returns a cached fallback response instantly, keeping the server responsive
3. After 10 seconds, transitions to HALF_OPEN and sends one probe request
4. On success, closes the circuit and resumes normal operation

Every API response also carries the `X-Student-ID: BSCS23065` header via FastAPI middleware.

---

## Setup

```bash
pip install -r requirements.txt
```

## Run the server

```bash
uvicorn main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

## Run unit tests (no server needed)

```bash
pytest tests/test_unit.py -v
```

## Run the demo/integration test (server must be running)

```bash
python tests/test_circuit_breaker.py
```

The demo script runs three phases automatically:
- **Phase 1:** Normal LLM operation — requests succeed
- **Phase 2:** LLM goes down — first 3 requests hit the 5s timeout, then the circuit opens and subsequent requests get instant fallback
- **Phase 3:** LLM recovers — circuit transitions OPEN -> HALF_OPEN -> CLOSED

---

## Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/summarize` | Main LLM endpoint (protected by circuit breaker) |
| GET | `/api/circuit/status` | Inspect circuit state and counters |
| POST | `/api/circuit/reset` | Reset circuit to CLOSED |
| POST | `/test/llm/fail` | Simulate LLM outage |
| POST | `/test/llm/recover` | Restore LLM to healthy |

---

## Signature header

Every response includes: `X-Student-ID: BSCS23065`

# PDC-Sp24-BSCS23065-Ullah