# Spec 06 — Cross-Machine Sync

> Phase 2. The wedge that drives Pro tier conversions.

## Why

Codex explicitly cannot sync memory across machines. Claude's auto-memory is local filesystem. Developers who work on a laptop + dev container + cloud machine lose context every time they switch. Atelier solves this **today** for memories, costs, and session state.

This is also the primary reason a developer pays $12/mo for Pro.

## What — user-visible

```bash
# One-time setup
$ atelier sync init
Choose backend:
  1. Atelier Cloud (managed, encrypted) — recommended
  2. Self-host via S3 / Backblaze / Cloudflare R2
  3. Self-host via SSH/SCP to your own server
> 1
Enter your Atelier account email: pankaj4u4m@gmail.com
[link sent to email]
✓ Setup complete. Machine ID: studio-mbp

# Daily use
$ atelier sync up        # push local state to cloud
$ atelier sync down      # pull from cloud to local
$ atelier sync           # bidirectional, default
$ atelier sync status
  Last push:  2 min ago    (84 facts, 12 sessions)
  Last pull:  2 min ago
  Conflicts:  0
  Machines:   studio-mbp, dev-vm, cloud-shell
```

## What gets synced

- **Memory facts** (from spec 03 + Atelier's own ledger memory)
- **Outcome capture data** (spec 01) — enables federated learning later
- **Session reports** (spec 02) — for cross-machine insights
- **Workspace `session_state.json`** (excluding currently-running sessions)

**Not synced:**
- Active session events (each machine runs its own)
- Vendor API keys
- Files in the user's repo (we only sync Atelier's own state)

## Where — files

| File | What changes |
|------|-------------|
| `src/atelier/core/capabilities/sync/__init__.py` | **New package.** |
| `src/atelier/core/capabilities/sync/sync_engine.py` | Orchestrator |
| `src/atelier/core/capabilities/sync/backend_cloud.py` | Atelier Cloud client |
| `src/atelier/core/capabilities/sync/backend_s3.py` | Self-host S3 backend |
| `src/atelier/core/capabilities/sync/backend_ssh.py` | Self-host SSH backend |
| `src/atelier/core/capabilities/sync/encryption.py` | E2E encryption with user-derived key |
| `src/atelier/core/capabilities/sync/merge.py` | Conflict resolution |
| `src/atelier/gateway/adapters/cli.py` | Add `sync` command group |
| Cloud-side service | **Out of scope of this repo** — separate atelier-cloud repo |

## Encryption model

- Local-derived encryption key from user passphrase (Argon2id)
- All data encrypted client-side before upload
- Atelier Cloud only stores ciphertext + metadata (machine IDs, timestamps)
- Server cannot read user data even with full database access

## Merge / conflict rules

For each entity type:

| Entity | Conflict strategy |
|--------|-------------------|
| Memory fact | Last-write-wins by `captured_at`; both kept in audit log |
| Outcome window | Per-session, immutable once captured — no conflicts possible |
| Session report | Immutable once session closed; conflicts only on still-running session metadata |
| Workspace settings | Last-write-wins, with audit |

## Out of scope

- **Real-time sync** (push every change). Manual `sync up/down` for v1; auto-sync timer in v2.
- **Conflict UI.** Last-write-wins for v1; visual diff merge in spec 08.
- **Multi-user shared workspace.** Spec 12 (Team).
- **Backup / restore tools.** Future.

## Acceptance criteria

- [ ] `atelier sync init` walks user through backend choice and stores config
- [ ] `atelier sync up` and `down` work against the cloud backend
- [ ] Data is encrypted in transit AND at rest (ciphertext-only on server)
- [ ] Sync of 10MB of state takes <10 seconds on a typical connection
- [ ] Conflict on same memory fact resolves by `captured_at` and both are kept in audit log
- [ ] Network failure mid-sync leaves local state consistent (no partial writes)
- [ ] Self-host S3 backend works against MinIO test container
- [ ] Unit + integration tests cover all conflict scenarios

## Open questions for the executor

1. **Cloud service infrastructure.** Where does atelier-cloud live? Recommendation: separate repo, deployed on Cloud Run / Fly.io. This spec needs the API contract.
2. **Authentication.** Magic link via email or OAuth (GitHub/Google)? **Default: magic link to start, OAuth later.**
3. **Account model.** One account per user, multiple machines per account? **Default: yes.**
4. **Quota.** Free tier Pro tier gets unlimited storage? **Default: 1GB Pro, 10GB Team. Hard limit, not a trial.**
5. **Self-host configuration.** YAML config or env vars? **Default: YAML in `~/.atelier/sync.yaml`.**

## Implementation order

1. Encryption module + tests (no I/O dependencies)
2. Local serialization + diff (what to sync)
3. Backend interface (`SyncBackend` protocol)
4. S3 backend (easiest to test locally with MinIO)
5. Cloud backend (depends on atelier-cloud service)
6. SSH backend
7. CLI commands

## Dependencies

- Phase 1 outcome capture, cost reports, and memory adapters must exist
- atelier-cloud service must be live (separate work)

## Status

- [ ] Pending — blocked on atelier-cloud service spec
- [ ] In progress
- [ ] Shipped
