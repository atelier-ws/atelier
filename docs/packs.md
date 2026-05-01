# Pack System

Packs are portable bundles of Atelier artefacts — reasonblocks, rubrics, environments, evals, and benchmarks — that can be installed into any Atelier instance.

## What a Pack Contains

```
my-pack/
├── pack.yaml           # Manifest (required)
├── reasonblocks/       # Procedure memory blocks
├── rubrics/            # Safety / quality gate definitions
├── environments/       # Domain environment configs
├── evals/              # Eval scenario files
├── benchmarks/         # Benchmark definitions
└── docs/               # Pack documentation
```

### `pack.yaml` schema (required fields)

```yaml
pack_id: my-org-pack-name
version: "1.0.0"
domain: "Agent.coding"
author: my-org
license: MIT
description: "Internal coding best practices pack."
required_atelier_version: ">=0.1.0"
dependencies: []
tags: [coding, internal]
```

## Pack Sources

| Source type | Example | Enabled by default |
|---|---|---|
| Local path | `/path/to/my-pack` | Yes |
| Private internal | `private://my-pack` | Yes |
| Official internal | Bundled with Atelier | Yes |
| External git / URL | `https://...` | **No** (dev only) |

External sources require `ATELIER_ENABLE_EXTERNAL_PACK_SOURCES=1`.

## CLI Commands

```bash
# Create a new pack scaffold
atelier pack create my-pack --type reasonblocks --author my-org

# Validate structure and manifest
atelier pack validate ./my-pack
atelier pack validate ./my-pack --json

# Install from a local path
atelier pack install ./my-pack --dry-run   # preview first
atelier pack install ./my-pack

# Install from private internal source
atelier pack install private://my-pack

# List installed packs
atelier pack list
atelier pack list --json

# Search installed + official packs
atelier pack search coding
atelier pack search coding --json

# Show pack details
atelier pack info my-pack-id --json

# Uninstall
atelier pack uninstall my-pack-id

# Benchmark a pack against a host
atelier pack benchmark my-pack-id --host codex
atelier pack benchmark my-pack-id --host generic --json
```

## Official Internal Packs

Atelier ships with these packs pre-bundled:

| Pack ID | Domain |
|---|---|
| `atelier-pack-coding-general` | Agent.coding |
| `atelier-pack-swe-bench` | Agent.swe-bench |
| `atelier-pack-open-source-maintainer` | Agent.oss |
| `atelier-pack-audit-service` | Agent.audit |
| `atelier-pack-ai-referral` | Agent.ai-referral |
| `atelier-pack-beseam-shopify` | Agent.shopify |

These are installed on demand — use `atelier pack install atelier-pack-coding-general` (or pass the path to the bundled directory) to activate one.

## Host Bootstrap

Atelier can recommend and auto-install packs for a given host:

```bash
# See what packs are recommended for the Codex host
atelier bootstrap-host codex --dry-run
atelier bootstrap-host codex --auto-install
```

## Authoring Guides

See [Pack Authoring](community/) for guides on creating:

- [Environments](community/environment-authoring.md)
- [ReasonBlocks](community/reasonblock-authoring.md)
- [Rubrics](community/rubric-authoring.md)
- [Failure Clusters](community/failure-cluster-authoring.md)
