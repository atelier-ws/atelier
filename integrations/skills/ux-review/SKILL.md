---
name: ux-review
description: Verify an implemented UI against objective design gates — accessibility, design-token fidelity, and responsive behavior — by rendering it in a real browser and reasoning about what it actually looks like. Enforces design quality; does not redesign or review code.
---

# UX review

This skill checks whether a **shipped UI implementation** actually matches the design system — it opens the app in a real browser and gates on three objective measures: accessibility (WCAG), design-token fidelity (no hardcoded colors/spacing), and responsive behavior. It does **not** review code quality (use `/review` for that) and does **not** generate or restyle UI (the designer owns authoring).

When invoked, tell the user in plain English: "I'll open your app in a browser, screenshot it at multiple breakpoints, run an accessibility audit, and check for design-token drift. I need to know what to render and a few other things first." Then gather inputs.

## Operating loop

1. **Ground the target.** Infer from the repo what you can (dev-server command, token file location). For what remains unknown, use `AskUserQuestion` with a single call covering all gaps — at minimum: the render target (route URL or component story), WCAG level (default **AA**), breakpoints to check (default 360 / 768 / 1280), and the design-token source of truth. Before starting a dev server or hitting a URL, confirm the command via `AskUserQuestion` unless the repo's `CLAUDE.md` or an allow-rule already authorizes it.
2. **Render.** Start/confirm the app, drive a real browser via the Playwright MCP tools, navigate to the target, and screenshot at every breakpoint. Reason about the actual rendered pixels, not the markup.
3. **Gate — accessibility.** Run axe-core against the rendered page (inject via `browser_evaluate`, or run an `axe`/`pa11y`/Lighthouse CLI). Collect violations at the chosen WCAG level: contrast, alt text, ARIA, focus order, labels.
4. **Gate — token fidelity.** Compare the changed source (and, where feasible, computed styles) against the token set. Flag hardcoded colors, spacing, radii, and type values that bypass the design system.
5. **Gate — responsive & render integrity.** Inspect the breakpoint screenshots for overflow, clipping, overlap, broken empty/loading/error states, and content that disappears or reflows wrong.
6. **Critique (advisory only).** Note hierarchy, spacing, alignment, and typography observations as **Warnings** — never blockers. Taste is not gate-able.
7. **Verdict.** End with exactly one fenced JSON block as the final element, so a caller can parse it:

```json
{"verdict": "NEEDS_FIX",
 "gates": {"a11y": "fail", "tokens": "pass", "responsive": "pass", "render": "pass"},
 "blockers": ["contrast 2.9:1 on .cta (WCAG AA needs 4.5:1) — tokens/color/cta-fg"],
 "warnings": ["card spacing 14px is off the 4px scale; nearest token space-3 (12px)"],
 "not_checked": ["keyboard navigation", "screen-reader semantics", "motion/animation"]}
```

## Guardrails

- **Gate only on the measurable three** — accessibility, token fidelity, responsive/render integrity. Aesthetic judgment is `Warning`-only; never emit a `Blocker` for "feels off."
- **A clean axe run is not a clean a11y verdict.** Automated checks catch roughly half of WCAG; list what was not machine-checkable (keyboard nav, screen-reader semantics, focus traps) in `not_checked` and hand it to a human.
- **Consume the design system; don't invent it.** Take tokens from the repo or the Figma MCP as source of truth. Do not guess the brand's intended values.
- **Verify, don't redesign.** Report drift and propose the minimal conforming fix (the exact token, the contrast-passing value). Do not restyle, refactor, or "improve" the UI.
- **Render at the boundary.** Starting a dev server or hitting a URL is a side-effect — confirm via `AskUserQuestion` before running it unless the repo already authorizes it.
- **Default to `NEEDS_FIX`.** A `DONE` verdict requires positive proof every gate passed; a skipped gate (`status: skipped`) is not a pass.
