import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'doc',
      id: 'README',
      label: 'Home',
    },
    {
      type: 'doc',
      id: 'quickstart',
    },
    {
      type: 'doc',
      id: 'installation',
    },
    {
      type: 'doc',
      id: 'open-source-strategy',
    },
    {
      label: 'Getting Started',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'cli',
        },
        {
          type: 'doc',
          id: 'packs',
        },
        {
          type: 'doc',
          id: 'production-readiness',
        },
      ],
    },
    {
      label: 'Integration',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'integration-codex',
        },
        {
          type: 'doc',
          id: 'integration-claude-code',
        },
      ],
    },
    {
      label: 'Hosts',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'hosts/all-agent-clis',
        },
        {
          type: 'doc',
          id: 'hosts/claude-code',
        },
        {
          type: 'doc',
          id: 'hosts/claude-code-install',
        },
        {
          type: 'doc',
          id: 'hosts/codex',
        },
        {
          type: 'doc',
          id: 'hosts/codex-install',
        },
        {
          type: 'doc',
          id: 'hosts/copilot',
        },
        {
          type: 'doc',
          id: 'hosts/copilot-install',
        },
        {
          type: 'doc',
          id: 'hosts/gemini-cli',
        },
        {
          type: 'doc',
          id: 'hosts/gemini-cli-install',
        },
        {
          type: 'doc',
          id: 'hosts/opencode',
        },
        {
          type: 'doc',
          id: 'hosts/opencode-install',
        },
      ],
    },
    {
      label: 'Architecture',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'architecture/ecosystem',
        },
      ],
    },
    {
      label: 'Engineering',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'engineering/architecture',
        },
        {
          type: 'doc',
          id: 'engineering/contributing',
        },
        {
          type: 'doc',
          id: 'engineering/deployment-modes',
        },
        {
          type: 'doc',
          id: 'engineering/dogfooding',
        },
        {
          type: 'doc',
          id: 'engineering/evals',
        },
        {
          type: 'doc',
          id: 'engineering/mcp',
        },
        {
          type: 'doc',
          id: 'engineering/security',
        },
        {
          type: 'doc',
          id: 'engineering/service',
        },
        {
          type: 'doc',
          id: 'engineering/storage',
        },
        {
          type: 'doc',
          id: 'engineering/workers',
        },
      ],
    },
    {
      label: 'Community',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'community/reasonblock-authoring',
        },
        {
          type: 'doc',
          id: 'community/rubric-authoring',
        },
        {
          type: 'doc',
          id: 'community/environment-authoring',
        },
        {
          type: 'doc',
          id: 'community/failure-cluster-authoring',
        },
      ],
    },
    {
      label: 'Benchmarks',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'benchmarks/beseam',
        },
        {
          type: 'doc',
          id: 'benchmarks/custom',
        },
        {
          type: 'doc',
          id: 'benchmarks/phase7-2026-04-29',
        },
        {
          type: 'doc',
          id: 'benchmarks/sdk-benchmark',
        },
      ],
    },
    {
      label: 'SDK',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'sdk/cli',
        },
        {
          type: 'doc',
          id: 'sdk/mcp',
        },
        {
          type: 'doc',
          id: 'sdk/python',
        },
      ],
    },
    {
      label: 'Integrations',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'integrations/README',
          label: 'Overview',
        },
        {
          type: 'doc',
          id: 'integrations/continue',
        },
        {
          type: 'doc',
          id: 'integrations/host-matrix',
        },
        {
          type: 'doc',
          id: 'integrations/memory-interop',
        },
      ],
    },
    {
      label: 'Copy-Paste',
      type: 'category',
      items: [
        {
          type: 'doc',
          id: 'copy-paste/copilot-instructions',
        },
      ],
    },
    {
      type: 'doc',
      id: 'troubleshooting',
    },
  ],
};

export default sidebars;
