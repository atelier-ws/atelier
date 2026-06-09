import { Heart } from "lucide-react";
import GitHubIcon from "./GitHubIcon";

const FOOTER_LINKS = [
  {
    title: "Docs",
    links: [
      { label: "Installation", href: "https://atelier.beseam.com/docs/installation" },
      { label: "Quickstart", href: "https://atelier.beseam.com/docs/quickstart" },
      { label: "CLI Reference", href: "https://atelier.beseam.com/docs/cli" },
      { label: "Troubleshooting", href: "https://atelier.beseam.com/docs/troubleshooting" },
    ],
  },
  {
    title: "Hosts",
    links: [
      { label: "Claude Code", href: "https://atelier.beseam.com/docs/hosts/claude-code-install" },
      { label: "Codex CLI", href: "https://atelier.beseam.com/docs/hosts/codex-install" },
      { label: "Copilot", href: "https://atelier.beseam.com/docs/hosts/copilot-install" },
      { label: "All Hosts", href: "https://atelier.beseam.com/docs/hosts/all-agent-clis" },
    ],
  },
  {
    title: "Community",
    links: [
      { label: "GitHub", href: "https://github.com/atelier-runtime/atelier" },
      { label: "Issues", href: "https://github.com/atelier-runtime/atelier/issues" },
      { label: "Discussions", href: "https://github.com/atelier-runtime/atelier/discussions" },
      { label: "Blog", href: "https://atelier.beseam.com/blog" },
    ],
  },
  {
    title: "Runtime",
    links: [
      { label: "Context Reuse", href: "#savings" },
      { label: "Failure Rescue", href: "#savings" },
      { label: "Model Routing", href: "#savings" },
      { label: "Savings", href: "#savings" },
    ],
  },
];

export default function Footer() {
  return (
    <footer className="border-t border-neutral-900 bg-neutral-950/60 px-6 py-16">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-5">
          {/* Brand */}
          <div className="lg:col-span-1">
            <a href="#" className="flex items-center gap-2.5 no-underline">
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-brand text-lg font-bold text-white">
                ❯
              </span>
              <span className="text-base font-bold tracking-wide text-neutral-100">
                ATELIER
              </span>
            </a>
            <p className="mt-4 text-xs leading-relaxed text-neutral-500">
              Open-source runtime engineering for agents. MCP server + SDK middleware for context reuse, failure rescue, cost tracking, and cross-vendor routing.
            </p>
            <div className="mt-4 flex items-center gap-3">
              <a
                href="https://github.com/atelier-runtime/atelier"
                className="text-neutral-500 transition hover:text-neutral-300"
                aria-label="GitHub"
              >
                <GitHubIcon size={19} />
              </a>
              <span className="text-[10px] text-neutral-600">
                MIT License
              </span>
            </div>
          </div>

          {/* Link columns */}
          {FOOTER_LINKS.map((group) => (
            <div key={group.title}>
              <div className="text-[10px] font-bold uppercase tracking-widest text-neutral-500">
                {group.title}
              </div>
              <ul className="mt-4 space-y-2.5">
                {group.links.map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      className="text-xs text-neutral-400 no-underline transition hover:text-brand-300"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 border-t border-neutral-900 pt-8">
          <div className="flex flex-col items-center justify-between gap-4 text-xs text-neutral-600 md:flex-row">
            <span>
              &copy; {new Date().getFullYear()} Atelier. Open source under the MIT License.
            </span>
            <span className="inline-flex items-center gap-1">
              Built with <Heart size={10} className="text-red-400" /> for agents everywhere.
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
