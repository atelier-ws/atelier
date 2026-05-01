import uuid
from pathlib import Path

from atelier.core.foundation.models import Trace, ValidationResult
from atelier.core.foundation.store import ReasoningStore
from atelier.infra.runtime.run_ledger import RunLedger


def simulate():
    root = Path("./.atelier").resolve()
    store = ReasoningStore(root)
    store.init()

    run_id = "hf-demo-" + uuid.uuid4().hex[:8]
    print(f"Simulating High-Fidelity Run: {run_id}")

    # 1. Initialize Ledger
    led = RunLedger(
        run_id=run_id,
        agent="Gemini CLI (High-Fidelity)",
        root=root,
        task="Demonstrate Full-Stack Reasoning & Learning Capture",
        domain="beseam.demo"
    )

    # 2. Add Reasoning State
    led.add_hypothesis("Granular event logging enables automated ReasonBlock extraction.")
    led.add_verified_fact("The updated dashboard successfully renders nested JSON payloads in the timeline.")
    
    # 3. Record Granular Events
    led.record_tool_call(
        tool="grep_search",
        args={"pattern": "class SizingService", "include_pattern": "*.py"},
        output="backend/src/modules/sizing/service.py:42:class SizingService:"
    )

    led.record_command(
        command="pytest tests/test_sizing.py",
        ok=True,
        stdout="================== 1 passed in 0.12s ==================",
        stderr=""
    )

    led.record_call(
        operation="plan_refinement",
        model="gemini-2.0-flash-exp",
        input_tokens=1500,
        output_tokens=350,
        lessons_used=["sizing-identity-logic"],
        prompt="Analyze the sizing service for ID mismatches...",
        response="The service uses internal IDs. Suggesting a translation layer."
    )

    led.record_alert("security", "low", "Credential scanning passed for the current changeset.")

    # 4. Finalize and Persist
    led.close(status="success")
    led.persist()

    # 5. Record the Trace (Linked via run_id)
    trace = Trace(
        id=Trace.make_id(led.task, led.agent),
        run_id=run_id,
        agent=led.agent,
        domain=led.domain,
        task=led.task,
        status="success",
        files_touched=["atelier/src/atelier/adapters/mcp_server.py"],
        commands_run=["pytest tests/test_sizing.py"],
        output_summary="High-fidelity demonstration run complete. All events captured.",
        validation_results=[
            ValidationResult(name="Ledger Integrity", passed=True, detail="Full event timeline verified."),
            ValidationResult(name="Telemetry Accuracy", passed=True, detail="LLM token counts and costs recorded.")
        ]
    )
    store.record_trace(trace)
    print(f"Success! Trace recorded: {trace.id}")

if __name__ == "__main__":
    simulate()
