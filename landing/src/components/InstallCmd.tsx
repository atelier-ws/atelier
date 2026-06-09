import { useState } from "react";
import { Copy, Check } from "lucide-react";

const INSTALL_CMD = "curl -fsSL https://raw.githubusercontent.com/atelier-runtime/atelier/main/scripts/install.sh | bash";

export default function InstallCmd() {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(INSTALL_CMD);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  return (
    <section id="install" className="border-t border-neutral-900 bg-neutral-950/40 px-6 py-20">
      <div className="mx-auto max-w-3xl text-center">
        <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-neutral-500">
          Get Started
        </div>
        <h2 className="mt-3 text-2xl font-bold text-neutral-100 md:text-3xl">
          Install in One Command
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-neutral-400">
          The installer sets up the CLI, MCP server, background services, and
          runtime store. No HTTP server required for core functionality.
        </p>

        {/* Terminal command box */}
        <div className="relative mt-8">
          <div className="flex items-center justify-between border border-neutral-800 bg-black px-4 py-3.5">
            <code className="overflow-x-auto whitespace-nowrap text-xs text-emerald-300 md:text-sm">
              <span className="text-neutral-500">$</span> {INSTALL_CMD}
            </code>
            <button
              onClick={handleCopy}
              className="ml-3 inline-flex shrink-0 items-center gap-1.5 border border-neutral-700 px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-widest text-neutral-400 transition hover:border-neutral-500 hover:text-neutral-200"
            >
              {copied ? (
                <>
                  <Check size={12} className="text-emerald-400" />
                  Copied
                </>
              ) : (
                <>
                  <Copy size={12} />
                  Copy
                </>
              )}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-center gap-3 text-xs text-neutral-600">
            <span className="text-emerald-500/70">✓ Installs CLI + MCP</span>
            <span className="text-emerald-500/70">✓ atelierd background service</span>
            <span className="text-emerald-500/70">✓ Host integrations</span>
          </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          {[
            { cmd: "atelier --version", label: "Check CLI" },
            { cmd: "atelier-mcp --version", label: "Check MCP" },
            { cmd: "atelierd status", label: "Check Services" },
          ].map((item) => (
            <div
              key={item.label}
              className="border border-neutral-800 bg-neutral-950/60 px-4 py-3"
            >
              <div className="text-[10px] font-bold uppercase tracking-widest text-neutral-500">
                {item.label}
              </div>
              <code className="mt-1 block truncate text-xs text-cyan-300">
                {item.cmd}
              </code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
