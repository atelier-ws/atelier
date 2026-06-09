import { ArrowRight, BookOpen } from "lucide-react";
import GitHubIcon from "./GitHubIcon";

export default function CtaSection() {
  return (
    <section className="relative overflow-hidden border-t border-neutral-900 px-6 py-24">
      {/* Background glow */}
      <div className="pointer-events-none absolute inset-0">
        <div className="glow-purple absolute left-1/2 top-1/2 h-[600px] w-[600px] -translate-x-1/2 -translate-y-1/2" />
      </div>
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-30" />

      <div className="relative z-10 mx-auto max-w-3xl text-center">
        <h2 className="text-2xl font-bold text-neutral-100 md:text-4xl">
          Ready to stop your agents from
          <br />
          <span className="text-brand-300">burning budget on repeat work?</span>
        </h2>
        <p className="mt-4 text-sm leading-relaxed text-neutral-400">
          One install. One MCP runtime. Every agent host. Measure every token saved.
        </p>

        <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <a
            href="#install"
            className="inline-flex items-center gap-2 border border-brand/60 bg-brand/10 px-6 py-3 text-sm font-bold uppercase tracking-widest text-brand-300 no-underline transition hover:bg-brand/20"
          >
            Install Now
            <ArrowRight size={16} />
          </a>
          <a
            href="https://github.com/atelier-runtime/atelier"
            className="inline-flex items-center gap-2 border border-neutral-700 px-6 py-3 text-sm font-bold uppercase tracking-widest text-neutral-300 no-underline transition hover:border-neutral-500 hover:text-neutral-100"
          >
            <GitHubIcon size={16} />
            Star on GitHub
          </a>
          <a
            href="https://atelier.beseam.com/docs/installation"
            className="inline-flex items-center gap-2 border border-neutral-800 px-6 py-3 text-sm uppercase tracking-widest text-neutral-500 no-underline transition hover:border-neutral-600 hover:text-neutral-300"
          >
            <BookOpen size={16} />
            Read the Docs
          </a>
        </div>
      </div>
    </section>
  );
}
