"""
PDC Assignment 4 - Demo Test Script
Saif Ullah | BSCS23065

Demonstrates:
  BEFORE: synchronous-style hang — each request to a broken LLM waits for timeout
  AFTER:  circuit breaker short-circuits after failure_threshold, returns fallback instantly

Run the server first:
    uvicorn main:app --reload --port 8000

Then run this script:
    python tests/test_circuit_breaker.py
"""

import asyncio
import time
import httpx

BASE = "http://localhost:8000"
PROMPT = {"prompt": "Summarise the causes of World War 1 for my history exam."}


def divider(title: str):
    print(f"\n{'=' * 58}")
    print(f"  {title}")
    print(f"{'=' * 58}")


async def hit_summarize(client: httpx.AsyncClient, label: str) -> dict:
    t0 = time.perf_counter()
    try:
        r = await client.post(f"{BASE}/api/summarize", json=PROMPT, timeout=15)
        elapsed = time.perf_counter() - t0
        data = r.json()
        student_id = r.headers.get("X-Student-ID", "MISSING")
        fallback = data.get("_fallback", False)
        circuit = data.get("_circuit", "?")
        print(
            f"  [{label:>20}] {elapsed:5.2f}s | "
            f"HTTP {r.status_code} | circuit={circuit:<9} | "
            f"fallback={str(fallback):<5} | X-Student-ID={student_id}"
        )
        return {"elapsed": elapsed, "fallback": fallback, "circuit": circuit, "status": r.status_code}
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  [{label:>20}] {elapsed:5.2f}s | ERROR: {e}")
        return {"elapsed": elapsed, "fallback": True, "circuit": "error", "status": 0}


async def get_circuit_state(client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{BASE}/api/circuit/status", timeout=5)
    return r.json()


async def main():
    async with httpx.AsyncClient() as client:

        # Verify server is up
        try:
            r = await client.get(BASE, timeout=3)
            print(f"Server up. X-Student-ID header: {r.headers.get('X-Student-ID')}")
        except Exception:
            print("ERROR: Server not running. Start with: uvicorn main:app --reload --port 8000")
            return

        # ── Reset state ──────────────────────────────────────────
        await client.post(f"{BASE}/api/circuit/reset", timeout=5)
        await client.post(f"{BASE}/test/llm/recover", timeout=5)

        
        # PHASE 1: Normal operation — LLM is healthy
        
        divider("PHASE 1 — Normal operation (LLM healthy)")
        print(f"  {'Request':>20}   time  | HTTP    | circuit    | fallback | Header")

        for i in range(3):
            await hit_summarize(client, f"request {i+1}")

        state = await get_circuit_state(client)
        print(f"\n  Circuit state: {state['state']}  |  failures so far: {state['failure_count']}")

        
        # PHASE 2: LLM starts hanging — WITHOUT circuit breaker this
        # would block each request for up to 60 seconds.
        # WITH the breaker (timeout=5s), requests still take ~5s until
        # the breaker trips, then become instantaneous.
        
        divider("PHASE 2 — LLM starts hanging (simulated outage)")
        print("  Injecting failure into the LLM simulator...")
        await client.post(f"{BASE}/test/llm/fail", timeout=5)
        print(f"  {'Request':>20}   time  | HTTP    | circuit    | fallback | Header")
        
        results = []
        for i in range(6):
            r = await hit_summarize(client, f"request {i+1}")
            results.append(r)

        state = await get_circuit_state(client)
        print(f"\n  Circuit state: {state['state']}  |  failures: {state['failure_count']}")
        print(f"  Seconds until HALF_OPEN: {state['seconds_until_half_open']:.1f}s")

        # Show the key insight: first 3 requests took ~5s each (hitting timeout),
        # requests 4+ were instant because the circuit is now OPEN.
        slow_requests = [r for r in results if r["elapsed"] > 1]
        fast_fallbacks = [r for r in results if r["elapsed"] < 1 and r["fallback"]]
        print(f"\n  Requests that timed out (slow path): {len(slow_requests)}")
        print(f"  Requests short-circuited instantly (fast fallback): {len(fast_fallbacks)}")

        
        # PHASE 3: Wait for recovery, LLM comes back online
        
        divider("PHASE 3 — Recovery (waiting for HALF_OPEN, then LLM recovers)")
        print("  Restoring LLM to healthy state...")
        await client.post(f"{BASE}/test/llm/recover", timeout=5)

        wait_sec = state["seconds_until_half_open"]
        print(f"  Waiting {wait_sec:.1f}s for circuit to enter HALF_OPEN...")
        await asyncio.sleep(wait_sec + 0.5)

        state = await get_circuit_state(client)
        print(f"  Circuit state after wait: {state['state']}")

        print(f"\n  Sending probe request (HALF_OPEN -> should close circuit)...")
        print(f"  {'Request':>20}   time  | HTTP    | circuit    | fallback | Header")
        
        await hit_summarize(client, "probe request")

        state = await get_circuit_state(client)
        print(f"\n  Circuit state after probe: {state['state']}")

        print(f"\n  Sending 3 more normal requests to confirm circuit is healthy again...")
        for i in range(3):
            await hit_summarize(client, f"recovery req {i+1}")

        
        # Final summary
        
        divider("SUMMARY")
        final = await get_circuit_state(client)
        print(f"  Total API calls:      {final['total_calls']}")
        print(f"  Total failures:       {final['total_failures']}")
        print(f"  Total fast fallbacks: {final['total_fallbacks']}")
        print(f"  Final circuit state:  {final['state']}")
        print()
        print("  KEY RESULT:")
        print("  Without the circuit breaker: all 6 failing requests would have")
        print("  hung for 60 seconds, freezing the entire server for all users.")
        print()
        print("  With the circuit breaker: only the first 3 requests wait for the")
        print("  5-second timeout. After that, the circuit opens and requests 4-6")
        print("  return a fallback in <10ms — server stays responsive throughout.")
        print()


if __name__ == "__main__":
    asyncio.run(main())
