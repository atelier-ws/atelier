# Known-bad shell calls -> ALLOW or REDIRECT-and-execute, never block/message.
# Where a read-only equivalent exists we REWRITE: the equivalent runs behind the
# scenes and its result is returned in the SAME turn (like grep->grep_tool), so no
# turn is wasted. Everything else (incl. sed -i replacements, git navigation) is
# ALLOWED to run -- a git-archaeology *spiral* is caught by the convergence escalation.
_FETCH_RE = re.compile(r"\b(?:curl|wget)\b", re.IGNORECASE)
_FETCH_URL_RE = re.compile(r"https?://[^\s'\"|>;)]+", re.IGNORECASE)
_FETCH_SETUP_RE = re.compile(
    r"\|\s*(?:sudo\s+)?(?:sh|bash|zsh|pip[0-9]*|python[0-9.]*|tar|unzip|gunzip|apt|apt-get|brew|npm|node|tee)\b"
    r"|\s-[oO]\b|\s--output\b|>\s*\S"
    r"|&&\s*(?:tar|unzip|pip|sh|bash|make|python|\./)",
    re.IGNORECASE,
)
_FIND_NAME_RE = re.compile(r"\bfind\s+(?:(\S+)\s+)?-(?:i?name|wholename)\s+['\"]?([^'\"\s|>;]+)", re.IGNORECASE)
_SED_PRINT_RE = re.compile(r"\bsed\s+-n\s+['\"]?(\d+)(?:,(\d+))?\s*p['\"]?\s+(\S+)", re.IGNORECASE)


def _redirect_known_bad(command: str) -> CommandPolicyDecision | None:
    """Rewrite known-bad read-only calls to the right tool (executed inline). Never blocks."""
    if _FETCH_RE.search(command) and not _FETCH_SETUP_RE.search(command):
        m = _FETCH_URL_RE.search(command)
        if m:  # plain content fetch -> run web_fetch behind the scenes
            return CommandPolicyDecision(
                category="web-fetch", action="rewrite",
                rewrite_target="web_fetch", rewrite_payload={"url": m.group(0)},
            )
        return None  # no URL to fetch -> just allow
    mf = _FIND_NAME_RE.search(command)
    if mf:  # find -name PATTERN -> internal file glob, returned inline
        path = mf.group(1) or "."
        if path.startswith("-"):
            path = "."
        return CommandPolicyDecision(
            category="find", action="rewrite",
            rewrite_target="find_glob", rewrite_payload={"glob": mf.group(2), "path": path},
        )
    ms = _SED_PRINT_RE.search(command)
    if ms:  # sed -n 'A,Bp' FILE  (read-only print) -> read that exact range, inline
        a = ms.group(1)
        b = ms.group(2) or a
        return CommandPolicyDecision(
            category="sed-read", action="rewrite",
            rewrite_target="read_range", rewrite_payload={"spec": f"{ms.group(3)}:L{a}-L{b}"},
        )
    return None  # sed -i / other sed / other find / git navigation -> ALLOW
