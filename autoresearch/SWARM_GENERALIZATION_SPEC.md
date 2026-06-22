# Swarm Generalization Spec

**Status:** proposal / ready-to-implement
**Audience:** an implementing agent with NO prior context of the discussion that produced this. Read this top-to-bottom; everything you need is here plus the cited source.
**Primary source file:** `src/atelier/core/capabilities/swarm/capability.py` (the swarm runtime).
**Reference prototype:** branch `autoresearch/main`, dir `autoresearch/` (a working *fitness command* + frozen-baseline harness — see §12).

---

## 0. TL;DR

The swarm is already a wave-based, **worktree-isolated, parallel-candidate** engine with scoring, ranking, an LLM wave-evaluator, convergence detection, and accept-into-base. But it is **hardwired to one use case**: N agents solve a coding task, emit git patches, scored by a fixed heuristic + LLM judge, merged into a base.

Generalize it into a reusable primitive:

> **Fan out N isolated candidates → reduce by a pluggable selector → (optionally) iterate in waves.**

The same engine then solves: solve-task (today), **optimize-an-objective** (incl. Atelier self-improvement), **broad search/discovery**, **mechanical migration at scale**, **multi-perspective review/audit**, **adversarial verification**, **consensus answering**, **flaky-repro**, **param tuning** — in **any project**, with no project-specific assumptions baked into the runtime.

**Backward compatibility is mandatory:** today's behavior must remain the *default* knob combination. All generalization is additive.

---

## 1. The primitive: four orthogonal knobs

A `SwarmJob` is defined by four independent choices:

| knob | options | meaning |
| --- | --- | --- |
| **candidate type** | `patch` \| `findings` \| `answer` \| `metric` \| `artifact` | what each child produces |
| **generator** | N agents w/ varied prompts/seeds/strategies, or a deterministic variant matrix | how candidates are created |
| **reducer** (selector) | `best(fitness)` \| `union(dedup)` \| `vote(consensus)` \| `merge(compatible)` | **how candidates are combined** — the key new abstraction |
| **exec mode** | `edit` (worktrees+patches) \| `readonly` (parallel reasoning, no diffs); `one_shot` \| `waves` | how candidates run and whether it iterates |

**Today's swarm == one fixed combo:** `{candidate: patch, generator: N agents on a task, reducer: merge + heuristic-best + LLM-judge, mode: edit + waves}`. Everything below makes each knob pluggable while keeping that combo as the default.

---

## 2. Current architecture (what already exists — do not rebuild)

All in `src/atelier/core/capabilities/swarm/capability.py`. Key pieces:

- **Wave planning / execution:** `_plan_wave_runs`, `_prepare_wave`, `_run_wave_children`, `launch_swarm_children`, `run_child_once`, `run_provider_swarm_worker`, `build_child_env`.
- **Isolation:** each child runs in its own git worktree; patches captured via `_write_child_patch`, applied with `_apply_patch_to_worktree`, integrated in a dedicated worktree (`_recreate_integration_worktree`, `_run_integration_validation`, `_refresh_transplant_commands`).
- **Scoring (current reducer, part 1 — heuristic):** `_score_child(child) -> (float, reasons)` and `rank_children(children)`. Scores on: run status (+100 success / −30 stopped / −60 failed), validation pass/fail, files-changed, a **cost penalty (`cost_usd * 10`)**, and a duration penalty. This is a hardwired `best-of-N` reducer.
- **Evaluation (current reducer, part 2 — semantic):** `_evaluate_wave(state, wave, children) -> SwarmWaveEvaluation` calls an LLM evaluator (`internal_llm.chat` with `_SWARM_EVALUATION_SCHEMA`) that returns per-candidate `accept|reject|defer`, `conflicts_with`, `duplicates`, a `candidate_order`, **`next_wave_directives`**, and a **convergence `verdict`**. `_fallback_wave_evaluation` covers the no-backend case. This is a hardwired `merge-compatible` reducer + the iteration controller.
- **Accept into base:** `apply_wave_candidates` transplants accepted patches; iteration continues with the evaluator's directives until convergence.
- **State model:** `SwarmRunState`, `SwarmWaveState`, `SwarmChildState` (fields incl. `status`, `validation_results`, `files_changed`, `cost_usd`, `duration_seconds`, `score`, `score_breakdown`), `SwarmWaveEvaluation`, `SwarmWaveDecision`.
- **Spec / lifecycle:** `build_swarm_spec_payload`, `initialize_swarm_run`, `spawn_swarm_coordinator`, `format_swarm_summary`, `stop_swarm_run`, `cleanup_swarm_run`.
- **Env knobs:** `ATELIER_SWARM_SPEC_PATH`, `ATELIER_SWARM_METADATA_PATH`, `ATELIER_SWARM_PROVIDER`, `ATELIER_SWARM_MODEL`, `ATELIER_SWARM_STEP_BUDGET`, `ATELIER_SWARM_TIME_BUDGET_SECONDS`, `ATELIER_LLM_BACKEND`, `ATELIER_ROOT`.
- **Skill front-end:** `atelier:swarms` (gathers swarm parameters, calls the runtime).

**Mental model:** `_score_child`+`rank_children` and `_evaluate_wave` together ARE the reducer today. The generalization extracts them behind a `Reducer` interface and adds new reducers + a measured-fitness scorer + a read-only execution path.

---

## 3. New interfaces

### 3.1 Typed candidate result
Children no longer always produce a patch. Extend `SwarmChildState` (or add a `result` envelope) with:

```
CandidateResult:
  id: str
  status: "success" | "stopped" | "failed"
  worktree: path | None          # None in readonly mode
  patch: str | None              # edit mode
  findings: list[Finding] | None  # search/audit/verify
  answer: str | None             # answer/design
  metric: float | None           # optimize/tune (parsed from fitness)
  gate_passed: bool | None       # optimize: did the gate command pass?
  cost_usd: float
  duration_seconds: float
  logs_ref: artifact-ref
```
`Finding`: `{kind, file?, line?, title, detail, signature}` (`signature` = dedup key).

### 3.2 Reducer interface (the core addition)

```
class Reducer(Protocol):
    name: str
    def reduce(self, candidates: list[CandidateResult], ctx: WaveContext) -> ReduceOutcome: ...

ReduceOutcome:
  accepted: list[str]            # candidate ids to keep/integrate
  rejected: list[str]
  deferred: list[str]
  ranking: list[str]             # best-first
  merged_output: Any | None      # union list / synthesized answer / chosen config
  converged: bool                # stop iterating?
  next_wave_directives: list[str]
  summary: str
```

Built-in reducers (register in a `REDUCERS` table keyed by name):
- **`best`** — rank by a fitness (heuristic `_score_child`, OR measured fitness §3.3). `accepted = [top-1]` (or top-k). Refactor existing `_score_child`/`rank_children` to live here unchanged as the default heuristic.
- **`merge`** — the existing `_evaluate_wave` LLM evaluator (accept multiple compatible, reject duplicates/conflicts, directives, convergence). Default for `solve-task`.
- **`union`** — collect all candidates' `findings`/`answer`, **dedup by `signature`**, optionally verify each survivor; `accepted = all that pass`. For search/discovery/audit.
- **`vote`** — group candidates' claims/answers, keep those with ≥ quorum agreement (configurable, e.g. majority). For verification/consensus. Supports the “N skeptics try to refute; keep if majority survive” pattern.

### 3.3 Fitness spec (project-agnostic, for `best`/optimize/tune)

The generic, NON-project-specific way to score a candidate by a real measurement:

```
FitnessSpec:
  objective: str                 # human description, e.g. "min $/task at fixed correctness"
  metric_command: str            # shell cmd run IN the candidate's worktree; emits the metric
  metric_parse: "json:<dotted.key>" | "regex:<pattern with one group>" | "stdout_float" | "exit_code"
  direction: "min" | "max"
  gate_command: str | None       # must exit 0 (correctness / no-regress). Optional but recommended.
  baseline: float | "auto"       # "auto" => run metric_command once on the base snapshot before wave 1
  improve_margin: float = 0.0    # require metric better than baseline by this margin to accept
```

`best`-reducer-with-fitness algorithm per child: run `gate_command` (if any) in the worktree; if it fails, score = −∞ (rejected). Else run `metric_command`, parse via `metric_parse`, compute improvement vs `baseline` honoring `direction`; rank by improvement; accept top-1 (or all that beat baseline by `improve_margin`, for additive configs). The existing `cost_usd`/`duration` penalties become *optional tie-breakers*, not the primary signal.

This is the entire “optimize” capability: **the fitness is a command the user/skill supplies or infers** — nothing Atelier-specific in the runtime.

### 3.4 Generator spec
```
GeneratorSpec:
  kind: "agents" | "matrix"
  count: int                     # agents kind: number of children per wave
  prompt: str                    # the task / objective handed to each child
  strategy_hints: list[str] | None  # diversify children (e.g. ["MVP-first","perf-first"]) → mapped 1:1 onto children
  matrix: dict[str, list] | None  # matrix kind: cartesian product of knob settings => deterministic candidates
```
For optimize, `matrix` enables deterministic param/knob sweeps (no LLM per candidate); `agents` enables creative candidate generation (LLM proposes a change toward the objective).

### 3.5 Exec mode
- **`edit`** (current): worktree per child, patch captured + transplanted, integration validation. Required for `patch` candidates.
- **`readonly`** (new): child runs an agent that returns a structured `CandidateResult` (`findings`/`answer`/`metric`) **without** producing or applying a diff. Skip `_write_child_patch`, `_apply_patch_to_worktree`, `_run_integration_validation`. Cheaper/faster; required for search/answer/verify/audit. (A read-only child may still use a throwaway worktree for a clean cwd, or share the base read-only.)

---

## 4. The optimize / self-improvement use case (worked contract)

`/swarms "optimize <X>"` in ANY repo resolves to a `SwarmJob`:
- generator: `agents` (children propose changes toward `objective`) or `matrix` (sweep) — editing the declared **search space**.
- reducer: `best` with a `FitnessSpec`.
- mode: `edit` + `waves`.
- flow:
  1. **Resolve inputs** (§5): objective, `metric_command`, `metric_parse`, `direction`, `gate_command`, `search_space`.
  2. **Freeze baseline**: if `baseline == auto`, run `metric_command` on the base snapshot (`_ensure_snapshot_commit` / `_write_run_base_snapshot_manifest`) and store the number.
  3. **Waves**: each child edits the search space in its worktree; reducer runs `gate_command` then `metric_command` per worktree, scores vs baseline, globally selects the best (and `merge`-compatible additive winners), emits `next_wave_directives` (what lever to try next), checks convergence.
  4. **Output**: the winning diff(s) + measured improvement vs baseline, ready to apply.

**Self-improvement** is just this with the search space = the agent's own config/source and the fitness = a benchmark. There is nothing project-specific in the runtime; Atelier's instance is one `FitnessSpec` (§12).

---

## 5. Parameter elicitation / inference (works in any project)

The skill front-end (or `coordinator`) must obtain the `SwarmJob` from a natural-language goal. Order of resolution:
1. **Explicit args** the user provides.
2. **Infer from the repo**: detect test command (pytest/jest/go test), build command (Makefile targets, `package.json` scripts), an existing benchmark skill/command, lint/typecheck. Propose them.
3. **Ask** (≤3 questions) only for what's still missing — typically: *“what command measures the objective?”* (metric_command + parse), *“what must not regress?”* (gate_command), *“which files/knobs may candidates change?”* (search_space).

This elicitation is the only “intelligent” front-end; the runtime stays mechanical. Same `/swarms "make X faster|cheaper|smaller"` works across projects because the *project-specific knowledge lives in the elicited commands*, not the engine.

### 5.1 The fitness is per-project, and the skill can GENERATE it

The engine ships **no** fitness. The skill resolves it per run — and crucially it can **author the fitness itself** (exactly how `eval.py` was written by an AI in this project). Tiers, by how much the skill generates:
1. **Reuse** an existing measurable command — `npm run build && stat -c%s dist/bundle.js`, `pytest -q | tail -1`, `hyperfine ./bin`. Map to a `FitnessSpec` (command + parse + direction). Nothing generated.
2. **Generate the fitness harness** — the skill writes a `fitness` script from the objective + its understanding of the repo (available test/build/bench runners, what is measurable). This spans a thin wrapper *and* a non-trivial harness like Atelier's `eval.py` (which merely wraps an existing benchmark runner and computes a metric vs a baseline). **This is the default for anything past a one-liner.**
3. **Human-authored / pre-existing** — reserved for the genuinely un-generatable: needs special infra/access/hardware, production data, a subjective acceptance bar — or a maintained harness already exists to reuse. **Rare.**

“Complex ⇒ hand-authored” is too pessimistic: most complexity is *generatable*, because the building blocks (a test runner, a benchmark, a profiler) already exist and the skill just assembles + parses them. Atelier's `eval.py` is a **tier-2** artifact that merely happens to be committed (re-deriving it every run would be wasteful).

Baseline defaults to **`auto`** (engine measures HEAD once before wave 1); freeze it to a file only when re-measuring is expensive **and** invariant.

**Consequence:** nothing Atelier-specific is required by the engine. A user who installs Atelier gets the engine + the eliciting/**generating** skill, and the skill produces *their* project's fitness on demand — they never see Atelier's `eval.py`.

### 5.2 A generated fitness MUST be validated before the swarm (mandatory)

The fitness **is the objective function** — a buggy one silently optimizes the wrong thing (or rewards noise), making the entire wave search garbage. So before any wave runs, the skill MUST validate the resolved/generated fitness:
1. **Baseline sanity** — run it on HEAD: the metric parses, has plausible magnitude/units, and the gate passes on known-good HEAD.
2. **Direction check (perturbation)** — apply a known-worse change (or a prior rejected candidate) and confirm the metric moves the *expected* way and/or the gate trips. Proves the fitness measures the objective, not an artifact.
3. **Variance check** — run twice on HEAD; if run-to-run variance ≳ the improvements you're chasing, raise reps or choose a steadier metric (else the search chases noise).

Only a fitness that passes validation may drive a search. (The Atelier prototype's *frozen baseline* and *held-out split* are exactly these guards — anti-noise and anti-overfit — not engine requirements.)

---

## 6. Use-case catalog (knob settings per family)

**Best-of-N** (`reducer: best`):
- `solve <task>` — candidate `patch`, generator `agents`, fitness = heuristic+judge *(today)*.
- `optimize <objective>` / `tune <params>` — candidate `patch`/config, fitness = measured `FitnessSpec`, generator `agents`/`matrix`.
- `design <feature>` — candidate `answer`+`patch` (prototype), generator `agents` w/ distinct `strategy_hints`, reducer `best` via judge; synthesize from winner.

**Cover-all / union** (`reducer: union`, mode often `readonly`):
- `search/find <X>` — candidate `findings`, generator `agents` each searching a different way (by-symbol/content/history/entity); dedup+merge.
- `migrate <A→B>` — candidate `patch`, generator `matrix` (one site/module per child), mode `edit`; **accept ALL that pass the gate** (worktree isolation prevents mid-flight conflicts).
- `audit/find-bugs` — candidate `findings`, generator `agents` (per dimension), union+verify.

**Vote / consensus** (`reducer: vote`, mode `readonly`):
- `verify <claim/patch>` — N skeptics try to refute (distinct lenses); accept claim iff majority fail to refute.
- `answer <hard question>` — N independent answers; consensus / judge pick.
- `repro <flaky>` — N runs under varied conditions; aggregate failure rate / triggering condition.

---

## 7. CLI / skill surface

- Keep `atelier:swarms` as the entry; add an **optimize/general mode**. Natural language goal → elicit `SwarmJob` (§5) → run.
- Surface the knobs as optional explicit flags on the swarm spec payload (`build_swarm_spec_payload`): `--reducer {best,union,vote,merge}`, `--candidate {patch,findings,answer,metric}`, `--mode {edit,readonly}`, `--fitness-cmd`, `--metric-parse`, `--direction`, `--gate-cmd`, `--baseline {auto,<float>}`, `--search-space <globs>`, `--count N`, `--waves N`.
- Defaults reproduce today's behavior exactly when none are given.

---

## 8. Implementation plan (phased, backward-compatible)

**Phase 1 — extract the Reducer abstraction (no behavior change).** Introduce `Reducer` + `ReduceOutcome`; wrap existing `_score_child`/`rank_children` as `best(heuristic)` and `_evaluate_wave` as `merge`. The default job wires `merge` exactly as today. Ship behind no flag; verify identical output on existing swarm tests.

**Phase 2 — measured fitness + auto-baseline.** Add `FitnessSpec`, a `best(measured)` scorer that runs `gate_command`+`metric_command` per worktree and ranks vs baseline, and baseline auto-measure before wave 1. Unlocks `optimize`/`tune`. Add `metric` to `CandidateResult`.

**Phase 3 — readonly mode + typed outputs.** Add the read-only child path (no patch/transplant/integration) returning `findings`/`answer`/`metric`. Unlocks search/answer/verify without worktrees.

**Phase 4 — union + vote reducers.** Implement dedup-by-signature union and quorum vote. Unlocks search/discovery, audit, verification, consensus.

**Phase 5 — elicitation/inference + CLI/skill surface.** Repo inference + ≤3-question elicitation; the flag surface in §7.

Each phase is independently shippable and preserves prior behavior.

---

## 9. Data-model changes

- `SwarmRunState`: add `job_kind`, `reducer_name`, `fitness_spec` (optional), `exec_mode`, `generator_spec`, `search_space`.
- `SwarmChildState`: add `metric`, `gate_passed`, `findings`, `answer` (all optional; patch stays for edit mode).
- New: `FitnessSpec`, `GeneratorSpec`, `ReduceOutcome`, `Finding`, `Reducer` registry.
- Persist these in the swarm spec payload + run state JSON (`build_swarm_spec_payload`, `save_swarm_state`).

---

## 10. Acceptance criteria / tests

- **Regression:** existing swarm runs produce byte-identical decisions with the default combo (Phase 1 gate).
- **Optimize:** given a toy repo with a `metric_command` (e.g. echo a number influenced by a file), a 2-wave run measurably reduces the metric vs auto-baseline, gate enforced, winner diff applies.
- **Union:** a search job over a fixture returns the dedup’d union of multi-strategy findings; no duplicates by signature.
- **Vote:** a verify job with N children returns accept iff ≥ quorum; flips correctly at the boundary.
- **Readonly:** a readonly job creates no patches and no integration worktree.
- **Cross-project:** the same skill invocation resolves objective/fitness/gate via inference+elicitation on a non-Atelier fixture repo (e.g. a JS project with `npm run build`).

---

## 11. Non-goals / risks / open questions

- **Non-goal:** changing the worktree/wave execution engine — reuse it.
- **Risk — cost:** measured-fitness children each run `metric_command` (can be expensive, e.g. a benchmark). Mitigate: small population on a cheap subset, cap concurrency (Docker/heavy fitness), cheap-iterate then certify on a held-out set. Log any truncation/sampling — never silently cap coverage.
- **Risk — overfitting the fitness:** require a separate **held-out** evaluation before declaring a winner; a generic `holdout_command` or second metric run on unseen inputs. (Atelier instance does this via a held-out task split.)
- **Risk — isolation correctness:** read-only and matrix children must not write outside their worktree; enforce.
- **Open:** combination search (accept multiple additive winners then re-measure the combination to capture interactions) — supported by `merge`+re-eval, but define the policy (when to test combos vs single best).
- **Open:** concurrency policy when fitness is heavy (Docker) vs light (unit cmd) — expose a `--max-concurrent-fitness`.

---

## 12. Reference prototype (the first `FitnessSpec` instance)

A working *fitness command* + frozen-baseline harness already exists on branch **`autoresearch/main`**, dir `autoresearch/`:
- `autoresearch/eval.py` — runs Atelier’s SWE benchmark (atelier arm only, vs a frozen baseline) and prints a grep/JSON block with `savings_pct`, `correct`, `score`, `target_met`. This is exactly a `metric_command`.
- `autoresearch/baseline/swe30.json` — a frozen baseline (the `baseline` value, pre-measured).
- `autoresearch/freeze_baseline.py` — how to (re)measure a baseline from a prior run.
- `autoresearch/program.md` — the loop contract + the controlled search space (soft persona / hard tooling / env knobs).
- `autoresearch/knobs.env` — env-knob candidates (a `matrix` generator source).

Map to this spec:
```
FitnessSpec(
  objective    = "min $/task at >=50% vs baseline, correctness same-or-better",
  metric_command = "uv run python benchmarks/self_opt/eval.py --objective swe --tasks <subset> --reps 1 --json -",
  metric_parse = "json:savings_pct",
  direction    = "max",
  gate_command = None,   # correctness folded into eval: `correct` must be true; surface as gate
  baseline     = "auto", # or read benchmarks/self_opt/baseline/swe30.json
)
```
Validated findings from the prototype (useful priors): a *persona* change (“bias to act; don’t spelunk git history” in `integrations/shared/change-discipline.md`) cut the most expensive task’s churn dramatically (167→23 msgs, 76→0 git-log calls) for ~53% on the churn tasks at equal-or-better correctness; a blunt shell-output cap **backfired** (truncation → the agent re-ran commands). I.e. behavioral levers beat blunt tooling caps — a hint for `generator` strategy in self-improvement jobs.

---

## 13. Code organization & cleanup (where things live)

### 13.1 Generic generalization → stays in `src/atelier/core/capabilities/swarm/`
The swarm runtime is product code; ALL generic additions belong in this package. Keep `capability.py` as the orchestrator; it should *delegate* scoring/selection to a reducer rather than hardwire it. Proposed layout (refine freely):
- `swarm/capability.py` — engine: wave planning/exec, worktrees, lifecycle, `apply_wave_candidates` (orchestration unchanged; now calls a reducer).
- `swarm/reducers/__init__.py` — `Reducer` protocol, `ReduceOutcome`, a `REDUCERS` registry.
- `swarm/reducers/best.py` — the heuristic (`_score_child`/`rank_children` moved here verbatim) **and** the measured-fitness scorer.
- `swarm/reducers/merge.py` — the existing `_evaluate_wave` LLM evaluator, extracted (default for solve-task).
- `swarm/reducers/union.py`, `swarm/reducers/vote.py` — new.
- `swarm/fitness.py` — `FitnessSpec`, metric-command runner, parsers (`json:`/`regex:`/`stdout_float`/`exit_code`), baseline auto-measure, gate runner.
- `swarm/generator.py` — `GeneratorSpec` (agents/matrix).
- state types (`SwarmRunState`/`SwarmChildState`/…) extended in their current home with the `CandidateResult` fields (`metric`, `gate_passed`, `findings`, `answer`) and job fields (`job_kind`, `reducer_name`, `fitness_spec`, `exec_mode`, `generator_spec`, `search_space`).
- read-only exec path added to the child runner (`run_child_once`/`run_provider_swarm_worker`).

**Hard rule:** nothing in this package may reference Atelier benchmarks, swe-bench, or `ATELIER_*` knobs. Those are a *consumer's* fitness, never the engine.

### 13.2 Atelier's self-optimization fitness → NOT in `src/`; lives with the benchmarks
`autoresearch/eval.py` is Atelier's concrete *fitness command* — it wraps `benchmarks.codebench.multiswe_run`, so it is benchmark/test tooling, not product runtime. Relocate it out of `src/` and out of `autoresearch/`:
- `autoresearch/{eval.py, freeze_baseline.py, make_holdout.py, baseline/, tasks/, knobs.env}` → `benchmarks/self_opt/` (or alongside `benchmarks/codebench/`).
- This becomes the concrete `FitnessSpec` a user points the generic swarm at (§12). It is an *example consumer*, shipped as benchmark tooling.

### 13.3 Fate of the `autoresearch/` directory
It was two things; only one survives:
- **Obsolete (delete once the swarm generalization lands):** `program.md` (loop contract), `plot.py`, `README.md`, the bespoke loop framing — all subsumed by the generic swarm + the skill front-end.
- **Persists (relocate per §13.2):** the fitness command, frozen baseline, task sets, freeze/holdout utilities, `knobs.env` (a `matrix`-generator source).
- **The `bench` working-tree copy is a duplicate** of branch `autoresearch/main` and may be removed anytime; only the git-ignored experiment log (`results.tsv`) and run outputs are unique to it, and the conclusions are already in §12.
- **Source of truth:** branch `autoresearch/main` (this spec + the prototype).

### 13.4 Sequencing: organize as you build, not after
Implement to this layout from the start. Phase 1 (extract the reducer/fitness behind interfaces) **is** the organizing step — cheap to do first, and it leaves behavior identical. Do **not** build monolithically and reshuffle later. The only genuinely deferred work is mechanical: relocating the fitness (§13.2) and deleting the obsolete scaffolding (§13.3) once the generic path is proven.

---

*End of spec.*
