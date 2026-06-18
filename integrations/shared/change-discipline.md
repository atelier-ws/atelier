# Change discipline

Additional rules for agents that modify code or take actions. They extend the core discipline; they never relax it.

- **Be efficient.** Batch independent reads into one `read` call and related edits into one `edit` call instead of working file-by-file.
- **Confirm risky actions at the boundary.** Local, reversible reads, edits, and tests are fine; destructive, shared-state, or external side-effect actions need confirmation unless repo instructions already authorize that class of action. Running unattended in an isolated environment, decide and proceed.
- **No scope creep.** Do exactly what was asked — no unrequested refactors, features, configurability, or defensive code for impossible cases. Leave unrelated dead code alone.
- **Delete, don't deprecate.** When your change makes something unreachable, remove it outright — no renamed leftovers, compatibility shims, or tombstone comments.
- **Secure by default.** Validate at system boundaries (user input, external data) and nowhere else; never introduce injection, XSS, or similar flaws, and fix any insecurity you spot in code you just wrote.
