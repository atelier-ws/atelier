"""Warm in-memory index for the local Zoekt-compatible search backend."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from time import time

_TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".sql",
    ".sh",
    ".css",
    ".html",
}
_SKIP_PARTS = {".git", ".atelier", ".venv", "node_modules", "dist", "build", "__pycache__"}
_REGEX_META = set(".^$*+?{}[]\\|()")


@dataclass(frozen=True)
class ZoektIndexSnapshot:
    indexed_at: float
    total_lines: int
    contents: dict[str, str]
    trigrams: dict[str, set[str]]


class ZoektIndexer:
    """Keep a warm searchable snapshot for repeated large-repo queries."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._lock = threading.Lock()
        self._snapshot: ZoektIndexSnapshot | None = None

    def ensure_snapshot(self) -> ZoektIndexSnapshot:
        with self._lock:
            if self._snapshot is None:
                self._snapshot = self._build_snapshot()
            return self._snapshot

    def line_count(self, search_path: str | Path | None = None) -> int:
        snapshot = self.ensure_snapshot()
        if search_path is None:
            return snapshot.total_lines
        target = Path(search_path).resolve()
        if target == self.repo_root:
            return snapshot.total_lines
        prefix = self._relative_path(target)
        if prefix is None:
            return snapshot.total_lines
        if target.is_file():
            content = snapshot.contents.get(prefix, "")
            return len(content.splitlines())
        return sum(len(content.splitlines()) for path, content in snapshot.contents.items() if path.startswith(f"{prefix}/"))

    def index_age_seconds(self) -> int:
        snapshot = self.ensure_snapshot()
        return int(max(0, time() - snapshot.indexed_at))

    def search_files(self, *, query: str, num_matches: int, file_glob: str | None) -> list[dict[str, object]]:
        snapshot = self.ensure_snapshot()
        pattern = self._compile_pattern(query)
        candidate_paths = self._candidate_paths(snapshot, query)
        results: list[dict[str, object]] = []
        for path in candidate_paths:
            if file_glob and not fnmatch(path, file_glob):
                continue
            source = snapshot.contents[path]
            matches = []
            for match in pattern.finditer(source):
                char_start, char_end = match.span()
                byte_start = len(source[:char_start].encode("utf-8"))
                byte_end = byte_start + len(source[char_start:char_end].encode("utf-8"))
                line_number = source.count("\n", 0, char_start) + 1
                line_start = source.rfind("\n", 0, char_start)
                line_end = source.find("\n", char_end)
                line_start = 0 if line_start == -1 else line_start + 1
                line_end = len(source) if line_end == -1 else line_end
                matches.append(
                    {
                        "ByteStart": byte_start,
                        "ByteEnd": byte_end,
                        "LineNumber": line_number,
                        "Line": source[line_start:line_end],
                    }
                )
            if not matches:
                continue
            results.append({"FileName": path, "Matches": matches[:num_matches]})
            if len(results) >= num_matches:
                break
        return results

    def _build_snapshot(self) -> ZoektIndexSnapshot:
        contents: dict[str, str] = {}
        trigrams: dict[str, set[str]] = {}
        total_lines = 0
        for path in sorted(self.repo_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.repo_root).as_posix()
            if any(part in _SKIP_PARTS for part in path.parts):
                continue
            if path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            contents[rel] = source
            total_lines += len(source.splitlines())
            for trigram in self._trigrams(source):
                trigrams.setdefault(trigram, set()).add(rel)
        return ZoektIndexSnapshot(indexed_at=time(), total_lines=total_lines, contents=contents, trigrams=trigrams)

    def _candidate_paths(self, snapshot: ZoektIndexSnapshot, query: str) -> list[str]:
        literal = query if query and not any(char in _REGEX_META for char in query) else None
        if literal is None or len(literal) < 3:
            return sorted(snapshot.contents)
        trigram_hits = [snapshot.trigrams.get(trigram, set()) for trigram in self._trigrams(literal)]
        if not trigram_hits:
            return sorted(snapshot.contents)
        candidates = set.intersection(*trigram_hits) if trigram_hits else set(snapshot.contents)
        return sorted(candidates)

    def _compile_pattern(self, query: str) -> re.Pattern[str]:
        try:
            return re.compile(query)
        except re.error:
            return re.compile(re.escape(query))

    def _relative_path(self, target: Path) -> str | None:
        try:
            return target.relative_to(self.repo_root).as_posix()
        except ValueError:
            return None

    def _trigrams(self, source: str) -> set[str]:
        if len(source) < 3:
            return {source} if source else set()
        return {source[index : index + 3] for index in range(len(source) - 2)}


__all__ = ["ZoektIndexSnapshot", "ZoektIndexer"]
