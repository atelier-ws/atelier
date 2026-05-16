# Atelier Go-To-Market

> Honest content + data-driven distribution. We do not spend on ads.

## Audience segments — in priority order

### 1. Heavy individual users ($50–500/mo AI spend)
- **Profile**: Senior engineers, indie hackers, AI-curious devs running 2+ native CLIs already
- **Pain**: "I'm burning money but I can't tell where it goes. I lose context between Claude and Codex."
- **Wedge**: Free tier honest cost dashboard. Pro tier sync.

### 2. Eng leads at 10–50 person teams
- **Profile**: Engineering managers, CTOs of seed-stage startups, AI ops leads
- **Pain**: "My team is spending $5K/mo on AI tools and I have no visibility per engineer."
- **Wedge**: Team tier cost attribution + shared memory onboarding.

### 3. Open-source maintainers
- **Profile**: Maintainers of dev-tool libraries, contributors to popular repos
- **Pain**: "I want to recommend something that respects my users' privacy and data."
- **Wedge**: Local-first architecture, audit trail, OSS Pro tier.

### 4. Enterprise (deferred to Year 2)
- **Profile**: 50+ engineering orgs with security/compliance teams
- **Pain**: SOC2, audit trails for AI tool use, vendor risk
- **Wedge**: On-prem sync + audit export

## Channels

### Primary — owned content

**Weekly benchmark blog post.** This is *content-as-product*.
- Run benchmarks on real session data we have
- Publish numbers natives wouldn't publish (e.g., "Haiku diverges from Sonnet on 78% of tool calls")
- Cross-publish to dev.to, HN, lobste.rs, /r/programming
- Include raw data and reproduction instructions

**Example titles we can write:**
- "We measured Claude vs Codex on 500 real sessions. Here's where each wins."
- "Haiku is 78% wrong about which tool to call. Here's the data."
- "Your $200/month AI bill is 40% waste. We can prove it."
- "Compacting too early costs more than compacting too late."

**Cadence**: 1 post / week, every week. No exceptions.

### Secondary — community presence

- **Hacker News**: Submit benchmark posts. Always show data, never marketing.
- **Lobsters**: Engage thoughtfully on AI tooling discussions.
- **AI Engineering Discord / Latent Space Slack**: Show up with data, not pitches.
- **GitHub issue tracker mining**: Codex GitHub has open issues for cross-machine sync. Reply with "Atelier handles this" once we ship Phase 2.

### Tertiary — direct outreach

- **Newsletter writers** (Last Week in AI, Latent Space, AI Tinkerers): pitch the benchmark angle, not the product
- **Podcasts** (Latent Space, Software Engineering Daily): only after Phase 2 ships
- **YouTube creators** (Theo, Fireship, ThePrimeagen): send free Pro accounts + raw data, no demands

## Launch sequence

### Pre-launch (Weeks -2 to 0)
- [ ] Phase 1 specs complete and shipping
- [ ] Landing page live at atelier.dev with single CTA: "Install"
- [ ] README with 30-second demo gif
- [ ] First benchmark blog post drafted

### Launch week
- [ ] Day 1 (Tuesday morning PT): Hacker News post. Title: "Show HN: Atelier — honest cost dashboard for AI coding across Claude, Codex, Gemini"
- [ ] Day 1 PM: Cross-post to dev.to, lobste.rs
- [ ] Day 2: Twitter / Bluesky thread with screenshots
- [ ] Day 3: Reddit /r/programming, /r/MachineLearning
- [ ] Day 4–5: Engage with feedback, ship bug fixes
- [ ] Day 7: First retrospective + second benchmark post

### Post-launch (Weeks 1–4)
- [ ] Weekly benchmark publication
- [ ] Respond to every GitHub issue within 24h
- [ ] One Twitter / Bluesky thread per week with a specific data point
- [ ] Onboarding email sequence for installers (3 emails over 14 days)

## Messaging — what we say

### The headline
> "See where your AI coding spend actually goes. Across every vendor. Across every machine."

### Sub-headline
> "Atelier is the honest, open-source layer between you and Claude, Codex, and Gemini. Audit your memory. Compare costs. Sync across machines. Pay nothing for the local tool."

### The proof line
> "We publish brutally honest benchmarks every week. Yes, including the unflattering ones."

## Messaging — what we don't say

| Don't say | Why |
|-----------|-----|
| "Smarter AI" | Insulting to developers who can evaluate AI themselves |
| "Save 50% on AI costs" | We can prove ~30% in honest replays; never inflate |
| "Better than Claude / Codex / Gemini" | We're not — we complement them |
| "AI-powered" | We are not the AI |
| "Revolutionary" | Marketing-speak; trust signal goes down |
| "10x productivity" | Cannot prove; sounds like a scam |

## What we don't spend money on

- **Paid ads** (Google, LinkedIn, Twitter). Developers ignore them. Cost-per-acquisition will be 10× content marketing.
- **Conference sponsorships** until Year 2. Phase 1–3 doesn't need them.
- **PR firm.** We write our own content; PR firms don't understand the data.
- **Influencer paid placements.** Free product accounts are fine; paid endorsements destroy trust.

## Metrics

Track weekly:

| Metric | Phase 1 target | Phase 2 target | Phase 3 target |
|--------|---------------|---------------|---------------|
| GitHub stars | 200 | 1,500 | 5,000 |
| Free installs | 500 | 3,000 | 10,000 |
| Active sessions / week | 200 | 2,000 | 10,000 |
| Benchmark post views (avg) | 1,000 | 5,000 | 20,000 |
| Pro signups | 0 (no billing yet) | 100 | 500 |
| Team signups | 0 | 5 | 30 |
| HN front page hits | 1 | 2 | 4 |

## Anti-goals

- Going viral on Twitter. Viral isn't the goal; data-trust is.
- Top-of-Google for "AI coding assistant." Wrong audience.
- Conference keynote in Year 1. Distraction.
- Big-name VC tweet endorsement. Worth less than 10 honest devs saying "this saved me $200."

## Editorial calendar — first 8 weeks

Suggested posts; adjust as data comes in:

1. **Launch**: "Show HN: Atelier — honest cost dashboard for AI coding"
2. **Week 2**: "We measured haiku vs sonnet on 500 sessions. Haiku diverged 78% of the time."
3. **Week 3**: "Your AI coding bill is 40% waste. Here's how we measured."
4. **Week 4**: "Atelier 30-day update: 1,000 installs, what we learned."
5. **Week 5**: "Cross-vendor routing: Claude vs GPT vs Gemini on real tasks."
6. **Week 6**: "When to compact — the data behind 80% utilisation threshold."
7. **Week 7**: "Why your AI forgets — and how cross-vendor memory helps."
8. **Week 8**: "Pro tier launch: sync your AI memory across machines."

## Trust budget

We have a finite trust budget. Spend it on:
- Publishing data that makes us look bad if it's true
- Responding honestly to negative feedback
- Open-sourcing all measurement code

Do not spend it on:
- Promises we can't deliver in the next quarter
- Comparisons we don't have data to back up
- Engagement-bait social posts

When in doubt, ship data, not opinion.
