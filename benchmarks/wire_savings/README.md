# wire_savings

Measure Atelier's **real** token savings by capturing the HTTP traffic between
Claude Code and its model provider, then diffing two runs of the same task
(Atelier MCP enabled vs disabled).

Why this and not Atelier's own counters? Atelier's internal savings numbers are
*counterfactual* ("tokens we would have spent minus what we did"). mitmproxy
reads the **actual `usage` blocks billed by the provider** — the ground truth.
If the counters claim savings the wire doesn't show, this is how you find out.

No Anthropic API key required: token counts are present in responses whether you
authenticate with a **Bedrock key**, **Bedrock IAM creds**, or a **Claude
Pro/Max subscription**. (On a subscription you only get tokens, not dollars —
which is fine, since dollars are just `tokens × price`.)

## 1. Install mitmproxy

```bash
uv pip install mitmproxy
mitmdump --version          # generates the CA at ~/.mitmproxy/ on first run
```

## 2. Capture two runs of the same task

Use the helper (starts the proxy and prints the env to paste in your Claude
terminal):

```bash
chmod +x benchmarks/wire_savings/capture.sh
./benchmarks/wire_savings/capture.sh atelier_off.flow   # Atelier MCP disabled
./benchmarks/wire_savings/capture.sh atelier_on.flow    # Atelier MCP enabled
```

Run the **identical prompt** in both, on the same model, changing only whether
the Atelier MCP server is configured. Quit mitmproxy (`q`) when the task ends.

Key gotchas (all handled by `capture.sh`'s printed env):

- `NODE_EXTRA_CA_CERTS` is **mandatory** — without it Claude Code's TLS rejects
  the proxy and it fails *silently*.
- For Bedrock, also export `AWS_CA_BUNDLE` (the AWS SDK has its own trust store)
  and `CLAUDE_CODE_USE_BEDROCK=1`.

## 3. Diff them

```bash
uv run python -m benchmarks.wire_savings.report \
    atelier_off=atelier_off.flow atelier_on=atelier_on.flow
```

List the **baseline first**; the `delta` row is `second vs first`, so a negative
percentage means the candidate (Atelier on) saved.

Example output:

```
metric              atelier_off    atelier_on
-----------------   -----------    ----------
requests                     42            39
input (non-cached)      120,400        58,900
cache read               18,000       240,500
cache write              22,100        19,800
output                   31,200        30,400
total input             160,500       319,200
total tokens            191,700       349,600
cache-read ratio          11.2%         75.3%
est. cost (USD)         $0.8956       $0.4012

delta (atelier_on vs atelier_off; negative = saved):
  total tokens : +157,900 (+82.4%)
  est. cost    : $-0.4944 (-55.2%)
```

Note how *total tokens can rise while cost falls*: a higher **cache-read ratio**
means more tokens bill at ~10% of the input price. That ratio and `est. cost`
are the metrics that matter, not raw token count.

Override pricing to match your model/region (USD per 1M tokens):

```bash
uv run python -m benchmarks.wire_savings.report base=off.flow cand=on.flow \
    --in 3.00 --out 15.00 --cache-read 0.30 --cache-write 3.75
```

## Notes

- Only responses to `bedrock-runtime*` and `*anthropic*` hosts are counted;
  other traffic (telemetry, MCP, etc.) is ignored.
- Handles all three response encodings: Bedrock event-stream, Anthropic SSE,
  and non-streaming JSON. Usage is read from `message_start` / `message_delta`
  events (and Bedrock Converse `metadata`).
- On Bedrock, `input (non-cached)` excludes cached tokens by convention; the
  table's `total input` adds cache read + write back so totals are comparable
  across providers.

## Tests

```bash
uv run pytest benchmarks/wire_savings/tests -q
```

Parser tests use synthetic frames and need no mitmproxy install.
