const GROUPS = [
  {
    label: "Cloud APIs",
    items: ["Anthropic", "OpenAI", "Google Gemini", "Mistral", "Groq"],
  },
  {
    label: "Platforms",
    items: ["AWS Bedrock", "Azure", "Vertex AI", "Together", "Fireworks"],
  },
  {
    label: "Gateways",
    items: ["OpenRouter", "Ollama"],
  },
];

export default function Providers() {
  return (
    <section className="relative border-t border-neutral-900 px-6 py-24">
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-20" />
      <div className="relative z-10 mx-auto max-w-5xl">
        <div className="text-center">
          <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-neutral-500">
            Providers
          </div>
          <h2 className="mt-3 text-2xl font-bold text-neutral-100 md:text-3xl">
            Provider Support
          </h2>
          <p className="mt-3 text-sm text-neutral-400">
            Auth wizard, smart routing, and pricing built in. Wire up any
            backend in seconds.
          </p>
        </div>

        <div className="mt-10 space-y-6">
          {GROUPS.map((group) => (
            <div key={group.label}>
              <div className="mb-3 text-center text-[10px] font-bold uppercase tracking-[0.2em] text-neutral-600">
                {group.label}
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {group.items.map((name) => (
                  <span
                    key={name}
                    className="inline-flex items-center gap-2 border border-neutral-800 bg-neutral-950/60 px-3.5 py-1.5 text-xs font-medium tracking-wide text-neutral-300 transition hover:border-brand-400/30 hover:text-neutral-100"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-10 text-center">
          <a
            href="https://atelier.beseam.com/docs/providers"
            className="inline-flex items-center gap-1.5 text-xs uppercase tracking-widest text-brand-300 no-underline transition hover:text-brand-200"
          >
            View provider documentation →
          </a>
        </div>
      </div>
    </section>
  );
}
