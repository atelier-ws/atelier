from __future__ import annotations

import ast
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

DEFAULT_CASE_QUOTAS: dict[str, int] = {
    "exact_symbol": 100,
    "exact_search": 100,
    "substring_search": 100,
    "file_outline": 100,
    "nohit_search": 100,
}


@dataclass(frozen=True)
class SymbolFact:
    name: str
    qualified_name: str
    path: str
    line: int
    kind: str


@dataclass(frozen=True)
class FileOutlineFact:
    path: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class ExternalBenchCase:
    case_id: str
    family: str
    query: str
    path: str | None = None
    symbol_name: str | None = None
    expected_paths: tuple[str, ...] = ()
    expected_names: tuple[str, ...] = ()
    metadata: dict[str, str] | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["expected_paths"] = list(self.expected_paths)
        payload["expected_names"] = list(self.expected_names)
        return payload


class _SymbolCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.class_stack: list[str] = []
        self.symbols: list[tuple[str, int, str, str]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified_name = ".".join((*self.class_stack, node.name))
        self.symbols.append((node.name, node.lineno, "class", qualified_name))
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        kind = "method" if self.class_stack else "function"
        qualified_name = ".".join((*self.class_stack, node.name))
        self.symbols.append((node.name, node.lineno, kind, qualified_name))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        kind = "method" if self.class_stack else "function"
        qualified_name = ".".join((*self.class_stack, node.name))
        self.symbols.append((node.name, node.lineno, kind, qualified_name))
        self.generic_visit(node)


def _repo_python_files(repo_root: Path) -> list[Path]:
    src_root = repo_root / "src" / "atelier"
    roots = [src_root] if src_root.exists() else [repo_root]
    files: list[Path] = []
    for root in roots:
        files.extend(sorted(path for path in root.rglob("*.py") if path.is_file()))
    return files


def _collect_symbol_facts(repo_root: Path) -> tuple[list[SymbolFact], list[FileOutlineFact]]:
    symbol_facts: list[SymbolFact] = []
    outline_facts: list[FileOutlineFact] = []
    for path in _repo_python_files(repo_root):
        relative_path = path.relative_to(repo_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        collector = _SymbolCollector()
        collector.visit(tree)
        ordered_symbols = [
            SymbolFact(
                name=name,
                qualified_name=qualified_name,
                path=relative_path,
                line=line,
                kind=kind,
            )
            for name, line, kind, qualified_name in collector.symbols
        ]
        symbol_facts.extend(ordered_symbols)
        if ordered_symbols:
            outline_facts.append(
                FileOutlineFact(
                    path=relative_path,
                    symbols=tuple(symbol.name for symbol in ordered_symbols[:6]),
                )
            )
    symbol_facts.sort(key=lambda item: (item.path, item.line, item.qualified_name))
    outline_facts.sort(key=lambda item: (item.path, tuple(item.symbols)))
    return symbol_facts, outline_facts


def _unique_symbol_facts(symbol_facts: Iterable[SymbolFact]) -> list[SymbolFact]:
    counts = Counter(symbol.name for symbol in symbol_facts)
    return [symbol for symbol in symbol_facts if counts[symbol.name] == 1]


def _unique_substring_queries(symbol_facts: Iterable[SymbolFact]) -> list[tuple[str, SymbolFact]]:
    token_to_symbols: dict[str, list[SymbolFact]] = defaultdict(list)
    for symbol in symbol_facts:
        tokens = [part for part in symbol.name.split("_") if len(part) >= 5]
        for token in tokens:
            token_to_symbols[token.lower()].append(symbol)
    pairs: list[tuple[str, SymbolFact]] = []
    for token, symbols in sorted(token_to_symbols.items()):
        if len(symbols) != 1:
            continue
        symbol = symbols[0]
        if token == symbol.name.lower():
            continue
        pairs.append((token, symbol))
    return pairs


def _make_nohit_query(index: int) -> str:
    return f"atelier_missing_symbol_{index:04d}_never_exists"


def generate_case_manifest(
    repo_root: Path,
    *,
    case_quotas: Mapping[str, int] = DEFAULT_CASE_QUOTAS,
) -> list[ExternalBenchCase]:
    symbol_facts, outline_facts = _collect_symbol_facts(repo_root)
    unique_symbols = _unique_symbol_facts(symbol_facts)
    substring_pairs = _unique_substring_queries(unique_symbols)

    required = {
        "exact_symbol": len(unique_symbols),
        "exact_search": len(unique_symbols),
        "substring_search": len(substring_pairs),
        "file_outline": len(outline_facts),
    }
    for family, quota in case_quotas.items():
        if family == "nohit_search":
            continue
        if required.get(family, quota) < quota:
            raise ValueError(
                f"not enough repository facts to satisfy {family}: " f"need {quota}, have {required.get(family, 0)}"
            )

    cases: list[ExternalBenchCase] = []

    for index, symbol in enumerate(unique_symbols[: case_quotas["exact_symbol"]], start=1):
        cases.append(
            ExternalBenchCase(
                case_id=f"exact-symbol-{index:04d}",
                family="exact_symbol",
                query=symbol.name,
                path=symbol.path,
                symbol_name=symbol.name,
                expected_paths=(symbol.path,),
                expected_names=(symbol.name,),
                metadata={"qualified_name": symbol.qualified_name, "kind": symbol.kind},
            )
        )

    len(cases)
    for index, symbol in enumerate(unique_symbols[: case_quotas["exact_search"]], start=1):
        cases.append(
            ExternalBenchCase(
                case_id=f"exact-search-{index:04d}",
                family="exact_search",
                query=symbol.name,
                path=symbol.path,
                symbol_name=symbol.name,
                expected_paths=(symbol.path,),
                expected_names=(symbol.name,),
                metadata={"qualified_name": symbol.qualified_name, "kind": symbol.kind},
            )
        )

    for index, (query, symbol) in enumerate(
        substring_pairs[: case_quotas["substring_search"]],
        start=1,
    ):
        cases.append(
            ExternalBenchCase(
                case_id=f"substring-search-{index:04d}",
                family="substring_search",
                query=query,
                path=symbol.path,
                symbol_name=symbol.name,
                expected_paths=(symbol.path,),
                expected_names=(symbol.name,),
                metadata={"qualified_name": symbol.qualified_name, "kind": symbol.kind},
            )
        )

    outline_candidates = [fact for fact in outline_facts if len(fact.symbols) >= 3]
    for index, outline in enumerate(outline_candidates[: case_quotas["file_outline"]], start=1):
        cases.append(
            ExternalBenchCase(
                case_id=f"file-outline-{index:04d}",
                family="file_outline",
                query=outline.path,
                path=outline.path,
                expected_paths=(outline.path,),
                expected_names=outline.symbols[:3],
            )
        )

    for index in range(1, case_quotas["nohit_search"] + 1):
        query = _make_nohit_query(index)
        cases.append(
            ExternalBenchCase(
                case_id=f"nohit-search-{index:04d}",
                family="nohit_search",
                query=query,
                expected_paths=(),
                expected_names=(),
            )
        )

    expected_total = sum(case_quotas.values())
    if len(cases) != expected_total:
        raise AssertionError(f"expected {expected_total} cases, got {len(cases)}")
    return cases


def write_case_manifest(path: Path, repo_root: Path) -> list[ExternalBenchCase]:
    cases = generate_case_manifest(repo_root)
    payload = {
        "repo_root": str(repo_root.resolve()),
        "case_quotas": DEFAULT_CASE_QUOTAS,
        "cases": [case.to_dict() for case in cases],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cases


def load_case_manifest(path: Path) -> list[ExternalBenchCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert isinstance(cases, list)
    return [
        ExternalBenchCase(
            case_id=item["case_id"],
            family=item["family"],
            query=item["query"],
            path=item.get("path"),
            symbol_name=item.get("symbol_name"),
            expected_paths=tuple(item.get("expected_paths", [])),
            expected_names=tuple(item.get("expected_names", [])),
            metadata=item.get("metadata"),
        )
        for item in cases
    ]
