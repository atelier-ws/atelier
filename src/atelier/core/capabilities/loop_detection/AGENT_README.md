# loop_detection

## Purpose

Detects pathological agent loops (patch-revert cycles, search-read loops, cascade failures, budget burn) from the run ledger and maps them to rescue strategies.

## Entry Point

`__init__.py` — re-exports `LoopDetectionCapability` (the only public surface).

## Module Layout

| File            | Responsibility                                                                                            |
| --------------- | --------------------------------------------------------------------------------------------------------- |
| `capability.py` | `LoopDetectionCapability()` — orchestrator; `check(ledger)` / `from_ledger(ledger)`                       |
| `patterns.py`   | 5 detector functions: patch_revert_cycle, search_read_loop, hypothesis_loop, cascade_failure, budget_burn |
| `signatures.py` | `_loop_signature()`, `_simhash()`, `hamming_distance()`, `near_duplicate_errors()`                        |
| `rescue.py`     | `_RESCUE_MAP`, `match_rescue(loop_types)`                                                                 |
| `models.py`     | `LoopReport`, `PatternMatch`, `TrajectoryPoint` dataclasses                                               |

## Key Contracts

- Constructor: `LoopDetectionCapability()` (no args)
- `check(ledger)` → `LoopReport`
- `from_ledger(ledger)` → `LoopReport` (alias used by `engine.py`)

## Where to look next

- `atelier/src/atelier/core/runtime/engine.py` — `self.loop_detection.from_ledger(ledger)`
