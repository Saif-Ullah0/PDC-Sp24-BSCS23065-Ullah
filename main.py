"""
StudySync Backend - FastAPI with Circuit Breaker Pattern
Saif Ullah | BSCS23065
PDC Assignment 4 - Part 3: Fault Tolerance Fix
"""

import asyncio
import time
import random
from enum import Enum
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware


# Circuit Breaker Implementation

class CircuitState(Enum):
    CLOSED = "CLOSED"       # Normal operation — requests pass through
    OPEN = "OPEN"           # Failing — reject immediately, return fallback
    HALF_OPEN = "HALF_OPEN" # Cooldown done — try one probe request


class CircuitBreaker:
    """
    A Circuit Breaker that protects against cascading failures
    from a slow or unreliable downstream service (e.g. an LLM API).

    States:
      CLOSED   -> requests pass through normally
      OPEN     -> requests are short-circuited, fallback returned instantly
      HALF_OPEN-> one probe request is allowed; success closes, failure reopens
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
        request_timeout: float = 5.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold   # failures before OPEN
        self.recovery_timeout = recovery_timeout     # seconds before HALF_OPEN
        self.request_timeout = request_timeout       # max wait per request

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._total_calls = 0
        self._total_failures = 0
        self._total_fallbacks = 0

    @property
    def state(self) -> CircuitState:
        # Automatically transition OPEN -> HALF_OPEN after recovery_timeout
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    def _on_success(self):
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def _on_failure(self):
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    async def call(self, coro, fallback_value: dict):
        """
        Execute `coro` (an awaitable) guarded by the circuit breaker.
        Returns fallback_value immediately if the circuit is OPEN.
        """
        self._total_calls += 1
        current_state = self.state  # triggers OPEN->HALF_OPEN transition if needed

        if current_state == CircuitState.OPEN:
            self._total_fallbacks += 1
            return {**fallback_value, "_circuit": "OPEN", "_fallback": True}

        try:
            result = await asyncio.wait_for(coro, timeout=self.request_timeout)
            self._on_success()
            return {**result, "_circuit": self._state.value, "_fallback": False}
        except (asyncio.TimeoutError, Exception) as exc:
            self._on_failure()
            self._total_fallbacks += 1
            return {
                **fallback_value,
                "_circuit": self._state.value,
                "_fallback": True,
                "_error": str(exc),
            }

    def stats(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_fallbacks": self._total_fallbacks,
            "recovery_timeout_sec": self.recovery_timeout,
            "seconds_until_half_open": max(
                0.0,
                self.recovery_timeout - (time.monotonic() - self._last_failure_time)
            ) if self._state == CircuitState.OPEN else 0.0,
        }


# Simulated LLM client

# Controls injected by the test suite
LLM_SHOULD_FAIL = False
LLM_FAKE_DELAY = 0.2  # seconds (normal fast response)


async def call_llm_api(prompt: str) -> dict:
    """
    Simulates an external LLM API call.
    When LLM_SHOULD_FAIL=True it hangs for 60 s (simulating a timeout scenario).
    The circuit breaker's request_timeout will cut it off well before that.
    """
    if LLM_SHOULD_FAIL:
        await asyncio.sleep(60)  # Simulate hung/unresponsive LLM
        return {"response": "..."}  # Never actually reached

    await asyncio.sleep(LLM_FAKE_DELAY)
    return {
        "response": f"Here is a study summary for: '{prompt[:60]}'",
        "tokens_used": random.randint(80, 300),
        "model": "gpt-mock-v1",
    }


# App setup

app = FastAPI(
    title="StudySync API",
    description="FastAPI backend with Circuit Breaker fault tolerance",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single shared circuit breaker for the LLM service
llm_breaker = CircuitBreaker(
    name="llm-api",
    failure_threshold=3,
    recovery_timeout=10.0,
    request_timeout=5.0,
)

LLM_FALLBACK = {
    "response": (
        "Our AI study assistant is temporarily unavailable. "
        "Please try again in a few seconds, or browse your saved notes in the meantime."
    ),
    "tokens_used": 0,
    "model": "fallback-cache",
}


# Middleware: inject X-Student-ID on every response

@app.middleware("http")
async def add_student_id_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Student-ID"] = "BSCS23065"
    return response


# Routes

@app.get("/", tags=["health"])
async def root():
    return {"status": "StudySync API running", "student_id": "BSCS23065"}


@app.post("/api/summarize", tags=["llm"])
async def summarize(body: dict):
    """
    Main endpoint that calls the LLM API.
    Protected by the circuit breaker — guaranteed fast response even when LLM is down.
    """
    prompt = body.get("prompt", "")
    result = await llm_breaker.call(
        call_llm_api(prompt),
        fallback_value=LLM_FALLBACK,
    )
    status = 200 if not result.get("_fallback") else 503
    return JSONResponse(content=result, status_code=status)


@app.get("/api/circuit/status", tags=["circuit-breaker"])
async def circuit_status():
    """Inspect the current circuit breaker state and counters."""
    return llm_breaker.stats()


@app.post("/api/circuit/reset", tags=["circuit-breaker"])
async def circuit_reset():
    """Manually reset the circuit breaker to CLOSED (for testing)."""
    llm_breaker._state = CircuitState.CLOSED
    llm_breaker._failure_count = 0
    return {"message": "Circuit breaker reset to CLOSED"}


# Test-control endpoints (used by the test script)

@app.post("/test/llm/fail", tags=["test-control"])
async def set_llm_fail():
    """Make the simulated LLM start hanging (simulates outage)."""
    global LLM_SHOULD_FAIL
    LLM_SHOULD_FAIL = True
    return {"llm_failing": True}


@app.post("/test/llm/recover", tags=["test-control"])
async def set_llm_recover():
    """Make the simulated LLM respond normally again."""
    global LLM_SHOULD_FAIL
    LLM_SHOULD_FAIL = False
    return {"llm_failing": False}
