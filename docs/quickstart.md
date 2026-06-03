# Quick start

## 1. Install

See [installation.md](installation.md) — the one-liner takes ~30 seconds.

## 2. Verify

```bash
atelier --version
```

You should see `0.2.0` (or later).

## 3. List available tools

```bash
atelier tools list
```

Core tools include `context`, `verify`, `memory`, `route`, `code`, `read`,
`search`, `edit`, and `shell`.

## 4. Run a task with Atelier

```bash
atelier tools call context --args '{"task":"summarize this project"}'
```

Atelier enriches the task with context reuse, failure rescue, and
loop detection automatically.

## 5. Start the dashboard

```bash
atelier stack up
```

Open http://localhost:3125 to see sessions, analytics, savings, and
memory.

## 6. Wire into an agent host

- **Claude Code:** `bash integrations/claude/install.sh`
- **Codex CLI:** `bash integrations/codex/install.sh`
- **opencode:** `bash integrations/opencode/install.sh`

After wiring, any `claude`, `codex`, or `opencode` session in the repo
automatically uses Atelier's runtime.
