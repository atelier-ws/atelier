# Hermes override

- Hermes loads `integrations/hermes/AGENTS.atelier.md` as the workspace entrypoint (generated from `docs/agent-os/README.md`).
- Hermes has no rules sub-directory; all tool-selection and coding-guideline instructions are carried inline in the single entrypoint file.
- Hermes entrypoints must explicitly prefer Atelier MCP tools for reads, search, code intelligence, edits, and shell work; native Hermes file tools, shell `rg`, `grep`, or direct repository search are fallback only when Atelier is unavailable or returns `noop`.
- Keep the shared workflow, tool-substitution rules, and fallback rules aligned with the rest of the generated entrypoints.
