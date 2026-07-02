---
name: ux-review
description: Verify a shipped UI against objective design gates — WCAG accessibility, design-token fidelity, responsive/render integrity, and visual regression — by rendering it in a real browser. Enforces design quality; does not redesign or review code.
---

> **Active** — do not call `Skill("atelier:ux-review")` again.

# UX review

This skill checks whether a **shipped UI implementation** actually meets its design bar — it opens the app in a real browser and gates on **five** objective signals: **accessibility** (WCAG), **design-token fidelity**, **responsive & render integrity**, **interaction & state coverage**, and **visual regression** vs a baseline. It discovers the repo's _own_ design-token source, component stories, accessibility auditor, browser driver, and visual-regression harness rather than assuming a stack. It does **not** review code quality (use `/review` for that) and does **not** author or restyle UI (the designer owns authoring); on request it **orchestrates** remediation — one solver per blocker, re-rendered before merge (step 11).

When invoked, briefly tell the user what you'll render and check, and that any fixes are opt-in — handed to per-blocker solvers and re-rendered before merge — then gather inputs.

## Operating loop

1. **Ground the target and baseline.** Discover the project's _own_ design + UI tooling before assuming anything — its design-token source of truth, component stories, accessibility auditor, browser driver, and visual-regression harness, and how each is normally invoked (look in `CLAUDE.md` / `AGENTS.md`, the README, CI config, and the dependency manifest). Tooling varies by stack: token sources such as a design-token JSON/YAML, Style Dictionary, a Tailwind/theme config, CSS custom properties, or the **Figma MCP / Dev Mode** server; component harnesses such as Storybook stories, Ladle, or Histoire; accessibility auditors such as **axe-core**, `pa11y`, or Lighthouse; browser drivers such as the **Playwright MCP** tools, Cypress, or browser devtools; visual-regression harnesses such as Playwright `toHaveScreenshot`, Chromatic, Percy, BackstopJS, or reg-suit. Prefer the **accessibility tree (ARIA snapshot)** as the deterministic artifact and screenshots for what only pixels reveal. If this host provides a dedicated web-performance skill, hand page-load / Core-Web-Vitals measurement to it — that is perf's job, not this gate's. For what remains unknown, use `AskUserQuestion` in a single call covering all gaps — at minimum: the render target (route URL or component story), the **baseline** (default: the pre-change UI via the repo's VCS — a working-tree stash or the parent commit), the WCAG level (default **AA**), the breakpoints (default **360 / 768 / 1280**), the design-token source of truth, and the **state matrix** to exercise (interaction states, dark / high-contrast theming, reduced-motion, RTL/i18n, content stress) with which states are in scope. Before starting a dev server, hitting a URL, or running an audit / visual-regression harness, confirm the exact command via `AskUserQuestion` unless the repo's `CLAUDE.md` or an allow-rule already authorizes it.
2. **Establish the baseline.** Render the _unchanged_ UI first (stash the diff or check out the baseline via the repo's VCS). Capture its **accessibility tree and screenshots at every breakpoint** — this is the before. If you cannot get a baseline, say so — the visual-regression gate cannot run.
3. **Render the change.** Re-render the identical target on the changed code — same routes, breakpoints, viewport, data, and theme as the baseline. Capture the accessibility tree and screenshots again. Reason about the **accessibility tree first** (deterministic, resilient to styling churn) and the **actual rendered pixels** for overflow, clipping, contrast, and layout — never the markup alone.
4. **Gate — accessibility (WCAG).** Run the repo's accessibility auditor (axe-core / pa11y / Lighthouse) against the rendered page at the chosen level, and diff the accessibility tree against the baseline. Gate on: contrast below the WCAG ratio (AA needs **4.5:1** text, **3:1** large text & UI), missing alt text / form labels, broken ARIA, **keyboard operability and focus order** (tab through it — keyboard nav is a gate, not an afterthought), and visible focus indicators. A new or unresolved violation at the chosen level is a **Blocker**.
5. **Gate — design-token fidelity.** Compare the changed source (and, where feasible, computed styles in the rendered page) against the token set. Hardcoded colors, spacing, radii, and type values that bypass the design system are a **Blocker** — name the exact conforming token for each.
6. **Gate — responsive & render integrity.** Inspect the breakpoint screenshots for overflow, clipping, overlap, content that disappears or reflows wrong, and broken empty / loading / error states. A layout that breaks at any in-scope breakpoint is a **Blocker**.
7. **Gate — interaction & state coverage.** Drive the UI through its states — hover, focus, active, disabled, loading, and error / validation — and through **theming** (dark / high-contrast), **motion** (`prefers-reduced-motion` honored), **direction** (RTL where supported), and **content stress** (long strings, **200% text zoom** — itself a WCAG criterion, missing images / data, deeply nested or empty content). This is the layout's worst-case input. A state that breaks the layout, drops below the WCAG contrast bar, or hides essential content is a **Blocker**; a state you did not render is `not_checked`, not a pass.
8. **Gate — visual regression.** Diff the change's screenshots and accessibility tree against the baseline. Separate **intended** change (report it as before→after) from **unintended** drift outside the changed surface (a regression — a **Blocker**). Use the repo's visual-regression harness where one exists; otherwise compare the captured screenshots directly.
9. **Critique (advisory only).** Hierarchy, spacing rhythm, alignment, typographic taste, and "this feels off" are **Warnings** — never blockers. Aesthetic judgment is not gate-able.
10. **Verdict.** End the review with exactly one fenced JSON block (the final element of the review itself), so a caller can parse it:

```json
{
  "verdict": "NEEDS_FIX",
  "gates": {
    "a11y": "fail",
    "tokens": "pass",
    "responsive": "pass",
    "states": "fail",
    "regression": "pass"
  },
  "baseline": "parent commit (HEAD~1) vs working tree",
  "observations": {
    "a11y": "contrast 2.9:1 on .cta fg/bg (WCAG AA needs 4.5:1); axe: 1 critical, 0 serious",
    "states": "card body clips at 200% text zoom; dark-mode focus ring invisible (1.8:1)",
    "regression": "header diff is the intended nav change; no off-target drift",
    "breakpoints": [360, 768, 1280]
  },
  "blockers": [
    "contrast 2.9:1 on .cta (WCAG AA needs 4.5:1) — use token color/cta-fg (#0b5cad, 4.7:1)",
    "200% text zoom clips .card body — fixed container height; switch to min-height"
  ],
  "warnings": [
    "card spacing 14px is off the 4px scale; nearest token space-3 (12px)"
  ],
  "not_checked": [
    "screen-reader semantics (NVDA / VoiceOver)",
    "assistive-tech focus traps",
    "motion / animation timing",
    "production data shapes"
  ]
}
```

11. **Remediate (optional, user-gated — never automatic).** A `NEEDS_FIX` verdict hands the fix to the designer / engineer by default. Only if the user opts in (confirm via `AskUserQuestion` after the verdict) do you orchestrate fixes — and even then the reviewer **never hand-edits the UI itself**. **You stay the orchestrator**: spawn the solvers yourself with the host's own sub-agent capability and coordinate them directly — you create the worktrees, dispatch each solver, re-render, and open the PRs. Do **not** hand the whole remediation off to a separate workflow / swarm engine that runs it end-to-end without you; you own the loop. Drive each blocker through its own pipeline, **independently**:
    1. **Isolate.** Create a dedicated **git worktree per blocker** (use the host's worktree / swarm / sub-agent capability if it has one; otherwise `git worktree add`). One finding, one worktree — so fixes can't collide, mask each other, or merge as a bundle the user can't selectively reject.
    2. **Spawn one sub-agent per blocker, yourself.** Using the host's sub-agent tool, launch a separate solver for each finding (one per worktree) and orchestrate them directly. Hand each solver _only_ its single finding: the rendered evidence (the screenshot, the failing contrast ratio or axe rule, the exact element / selector) and the minimal conforming fix from the verdict (the exact token, the contrast-passing value). Do not let one solver fix two findings, and do not widen its scope into a restyle or refactor.
    3. **Re-render, don't trust the diff.** When the solver reports done, **re-render that finding's failed gate(s)** in its worktree with the _identical_ target, breakpoints, viewport, data, theme, and state matrix used originally, and re-run the accessibility audit. Confirm the gate now **passes** _and_ that no previously-passing gate regressed. A patch that doesn't move its gate to `pass` is not done — send it back or report it unresolved; never merge it.
    4. **Review.** Present each worktree's **before → after** (screenshots and the changed numbers — contrast ratio, token, axe count) to the user, per finding.
    5. **Merge gate.** Merge a worktree to `main` (per the repo's convention — open a PR or merge directly) **only** when both (a) its re-render proves the gate cleared on the same target, **and** (b) the user approves that finding's before/after evidence. Discard the worktree on rejection. Merge per-finding so the user accepts or rejects each fix on its own evidence.

## Guardrails

- **Gate only on the measurable** — accessibility, token fidelity, responsive/render integrity, state coverage, and visual regression. Aesthetic judgment is `Warning`-only; never emit a `Blocker` for "feels off." Do not manufacture a numeric "design score" to look quantitative — the real measurables are WCAG ratios, exact token equality, and binary render/layout integrity.
- **Reason about the accessibility tree first, pixels second.** The ARIA snapshot is deterministic, resilient to styling churn, and doubles as the a11y check; use screenshots for what only pixels reveal — overflow, clipping, contrast, layout. Never gate on the raw markup.
- **A clean axe run is not a clean a11y verdict.** Automated checks catch roughly half of WCAG; list what was not machine-checkable (screen-reader semantics, focus traps, cognitive load, motion timing) in `not_checked` and hand it to a human.
- **Consume the design system; don't invent it.** Take tokens, breakpoints, and states from the repo or the Figma MCP as source of truth. Do not guess the brand's intended values.
- **A state you didn't render is not a pass.** Interaction, theming, motion, RTL, and content-stress states only count when you actually rendered them — an unexercised state is `not_checked`, never `pass`.
- **No baseline, no regression claim.** If you cannot render the unchanged UI, you cannot diff intended vs unintended change — set the `regression` gate `skipped` and default the verdict to `NEEDS_FIX`.
- **Compare like for like.** Same routes, breakpoints, viewport, data, theme, and state matrix for both baseline and change — otherwise the diff is noise, not signal.
- **Verify, don't redesign.** Report drift and propose the minimal conforming fix (the exact token, the contrast-passing value). Do not restyle, refactor, or "improve" the UI — that authoring scope is the designer's call.
- **Remediation is opt-in, orchestrated by you, never inline (see step 11).** One finding → one worktree → one solver, scoped to the minimal conforming fix; re-render the failed gate with the identical target and state matrix before merge (reading the diff is not proof — a clean re-render and re-audit is). Never merge without that proof and the user's approval.
- **Rendering is a side-effect.** Starting a dev server, hitting a URL, or running an audit / visual-regression harness is a side-effect — confirm the command via `AskUserQuestion` before running it unless the repo already authorizes it.
- **Default to `NEEDS_FIX`.** A `DONE` verdict requires positive proof every gate passed; a skipped gate (`status: skipped`) is not a pass.
- **Screen-reader text is always `sr-only`.** Descriptions of visual-only content go in `className="sr-only"`.
