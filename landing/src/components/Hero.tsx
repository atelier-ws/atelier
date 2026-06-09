import { ArrowRight } from "lucide-react";
import GitHubIcon from "./GitHubIcon";

export default function Hero() {
  return (
    <section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pt-20 pb-24">
      {/* Background gradient orbs */}
      <div className="pointer-events-none absolute inset-0">
        <div className="glow-purple absolute -top-40 left-1/2 h-[500px] w-[500px] -translate-x-1/2 md:h-[700px] md:w-[700px]" />
        <div className="glow-cyan absolute -bottom-40 right-0 h-[400px] w-[400px]" />
      </div>

      {/* Grid overlay */}
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-40" />

      {/* Content */}
      <div className="relative z-10 mx-auto flex max-w-4xl flex-col items-center text-center">
        {/* Eyebrow */}
        <div className="mb-6 inline-flex items-center gap-2 rounded border border-brand/30 bg-brand/5 px-3 py-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-[10px] font-bold uppercase tracking-[0.25em] text-brand-300">
            Open Source &mdash; MIT License
          </span>
        </div>

        {/* Headline */}
        <h1 className="text-4xl font-bold leading-tight tracking-tight text-neutral-100 md:text-6xl md:leading-[1.1]">
          Runtime Engineering
          <br />
          <span className="bg-gradient-to-r from-brand-300 via-brand-400 to-purple-400 bg-clip-text text-transparent">
            for Agents
          </span>
        </h1>

        {/* Subtitle */}
        <p className="mt-6 max-w-2xl text-sm leading-relaxed text-neutral-400 md:text-base md:leading-relaxed">
MCP server + SDK middleware that gives every agent shared
           procedures, failure rescue, loop detection, cost tracking, and
           cross-vendor routing &mdash; across Claude Code, Codex, Copilot,
           LangChain, OpenAI SDK, Gemini ADK, and any MCP host.
        </p>

        {/* CTA buttons */}
        <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <a
            href="#install"
            className="inline-flex items-center gap-2 border border-brand/60 bg-brand/10 px-6 py-3 text-sm font-bold uppercase tracking-widest text-brand-300 no-underline transition hover:bg-brand/20"
          >
            Install
            <ArrowRight size={16} />
          </a>
          <a
            href="https://github.com/atelier-runtime/atelier"
            className="inline-flex items-center gap-2 border border-neutral-700 px-6 py-3 text-sm font-bold uppercase tracking-widest text-neutral-300 no-underline transition hover:border-neutral-500 hover:text-neutral-100"
          >
            <GitHubIcon size={16} />
            GitHub
          </a>
          <a
            href="https://atelier.beseam.com/docs/installation"
            className="inline-flex items-center gap-2 border border-neutral-800 px-6 py-3 text-sm uppercase tracking-widest text-neutral-500 no-underline transition hover:border-neutral-600 hover:text-neutral-300"
          >
            Documentation
          </a>
        </div>

        {/* Animated terminal preview */}
        <div className="mt-16 w-full max-w-2xl">
          <div className="border border-neutral-800 bg-neutral-950/80">
            <div className="flex items-center gap-2 border-b border-neutral-800 px-4 py-2.5">
              <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-500/70" />
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
              <span className="ml-3 text-[10px] uppercase tracking-widest text-neutral-600">
                Terminal
              </span>
            </div>
            <pre className="overflow-x-auto border-0 bg-transparent p-5 text-xs leading-relaxed text-neutral-300 md:text-sm">
              <span className="text-emerald-400">$</span>{" "}
              <span className="text-neutral-100">curl -fsSL</span> https://raw.githubusercontent.com/atelier-runtime/atelier/main/scripts/install.sh
              <br />
              <span className="text-neutral-500">  → installing atelier (CLI)</span>
              <br />
              <span className="text-neutral-500">  → installing atelierd (background service)</span>
              <br />
              <span className="text-neutral-500">  → installing atelier-mcp (MCP server)</span>
              <br />
              <span className="text-neutral-500">  → initializing runtime store...</span>
              <br />
              <span className="mt-1 inline-block text-emerald-400">✓ Atelier ready</span>
              <br />
              <span className="text-emerald-400">$</span>{" "}
              <span className="text-neutral-100">atelier --version</span>
              <br />
              <span className="text-cyan-300">0.2.0</span>
            </pre>
          </div>
        </div>
      </div>
    </section>
  );
}
