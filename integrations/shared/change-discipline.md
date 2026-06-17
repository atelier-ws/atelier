# Change discipline

Additional rules for agents that modify code or take actions. They extend the core discipline; they never relax it.

- **Be efficient.** For multi-file edits, read all target files in one batched `read` call, then apply all changes in one `edit` call with multiple descriptors instead of working file-by-file. Skip exploration only on greenfield work with no existing code; a new feature in an existing repo still needs grounding.
- **Confirm risky actions at the boundary.** Local, reversible reads, edits, and tests are fine; destructive, hard-to-reverse, shared-state, or external side-effect actions require user confirmation unless durable repo instructions already authorize that exact class of action. When running unattended in an isolated environment, decide and proceed instead of waiting.
- **No scope creep.** Do exactly what was asked — no unrequested refactors, features, configurability, or defensive code for impossible cases. Remove only the orphans your own change created; leave unrelated dead code alone.
- **Delete, don't deprecate.** When your change makes something unreachable, remove it outright. No underscore-renamed leftovers, no compatibility re-exports or shims, no tombstone comments where code used to be.
- **Secure by default.** Validate at system boundaries (user input, external data) and nowhere else; never introduce injection, XSS, or similar boundary flaws, and fix any insecurity you spot in code you just wrote before moving on.
