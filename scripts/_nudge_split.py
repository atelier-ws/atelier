"""Temp: classify completed atelier reps by whether the persona nudge was present
in the system prompt. Reps WITHOUT it (old persona) -> remove+rerun; WITH it -> keep.
"""

import glob
import json
import os
import re

from mitmproxy import http
from mitmproxy import io as mio

D = "reports/benchmark/codebench/swe50_stress_run1"
NUDGE = re.compile(r"Verify (only )?your change")


def system_text(fp):
    """First request's system prompt (string or block list), concatenated."""
    with open(fp, "rb") as fh:
        for f in mio.FlowReader(fh).stream():
            if not isinstance(f, http.HTTPFlow) or not f.request:
                continue
            body = f.request.get_text() or ""
            if '"system"' not in body:
                continue
            try:
                d = json.loads(body)
            except ValueError:
                continue
            s = d.get("system")
            if isinstance(s, str):
                return s
            if isinstance(s, list):
                return " ".join(b.get("text", "") for b in s if isinstance(b, dict))
    return ""


has = []
missing = []
for fp in sorted(glob.glob(f"{D}/*_atelier_rep*.flow")):
    stem = os.path.basename(fp)[: -len(".flow")]
    (has if NUDGE.search(system_text(fp)) else missing).append(stem)

print(f"atelier reps WITH nudge (KEEP): {len(has)}")
print(f"atelier reps WITHOUT nudge (REMOVE + rerun): {len(missing)}")
for s in missing:
    print("   rm", s)
# persist the remove-list for the deletion step
with open(f"{D}/.nudge_remove.txt", "w") as fh:
    fh.write("\n".join(missing))
print(f"\nwrote remove-list ({len(missing)}) to {D}/.nudge_remove.txt")
