"""Replace emoji+savings in SWE per-task Save column with shields.io badge images."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]


def savings_badge(pct: float, pct_str: str) -> str:
    if pct >= 30:
        color = "brightgreen"
    elif pct >= 0:
        color = "yellow"
    elif pct >= -50:
        color = "orange"
    else:
        color = "red"
    # shields.io: hyphens separate segments; double-hyphen = literal hyphen;
    # percent must be URL-encoded as %25
    label = pct_str.replace("-", "--").replace("%", "%25")
    url = f"https://img.shields.io/badge/{label}-{color}?style=flat-square"
    return f"![{pct_str}]({url})"


readme_path = ROOT / "README.md"
readme = readme_path.read_text()

lines = readme.splitlines(keepends=True)
out = []
in_swe_table = False

for line in lines:
    if "Per-task breakdown" in line:
        in_swe_table = True
    if in_swe_table and line.startswith("| `"):
        # Replace the emoji+pct cell (e.g. "| 🟢 63.0% |") with a badge
        line = re.sub(
            r"\| [\U0001f7e0-\U0001f7e4\U0001f534]+ (-?[\d.]+%) ",
            lambda m: f"| {savings_badge(float(m.group(1).rstrip('%')), m.group(1))} ",
            line,
            count=1,
        )
    out.append(line)

readme_path.write_text("".join(out))
print("Done — badge savings cells written to README.md")
