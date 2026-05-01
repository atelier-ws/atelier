# Tests

## Purpose

Targeted validation for Atelier runtime, adapters, domain bundles, SDK, and host contracts.

## Key Files

- `test_sdk.py` — SDK surface
- `test_domains.py` — domain bundle system: DomainManager, DomainLoader, CLI `domain list/info`
- `test_phase_d3_d4.py` — MCP domain tools (`atelier_domain_list`, `atelier_domain_info`), pack tools absent
- `test_adapters.py` — host adapter scaffolds
- `test_memory_adapters.py` — memory interop wrappers (requires `atelier.integrations.memory`)
- `test_runtime_benchmarking.py` — benchmark helper workflows
- `test_runtime_pack_reasoning_context.py` — runtime context merge (learned store blocks + domain bundle reasonblocks)
- `test_benchmark_cli_actions.py` — benchmark CLI action modes, Phase T benchmark commands, and compatibility

## Notes

Prefer narrow pytest runs for the touched slice before widening to broader suites.
`test_memory_adapters.py` requires the optional `atelier.integrations.memory` module and will fail collection without it.
`test_agent_cli_install_artifacts.py` tests are order-sensitive; run the file in isolation if failures appear only in full-suite runs.
