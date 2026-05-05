from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.repo_map import build_repo_map
from atelier.infra.tree_sitter.tags import extract_tags


def test_extract_tags_python_symbols(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        "class CheckoutService:\n"
        "    def apply_coupon(self):\n"
        "        return True\n"
        "\n"
        "def helper():\n"
        "    return CheckoutService()\n",
        encoding="utf-8",
    )

    tags = extract_tags(path)
    names = {tag.name for tag in tags}
    assert {"CheckoutService", "apply_coupon", "helper"}.issubset(names)


def test_extract_tags_javascript_symbols(tmp_path: Path) -> None:
    path = tmp_path / "utils.js"
    path.write_text(
        "function fetchUser(id) { return id; }\n"
        "class UserStore {\n"
        "  constructor() { this.data = {}; }\n"
        "}\n"
        "const MAX_RETRIES = 3;\n",
        encoding="utf-8",
    )

    tags = extract_tags(path)
    defs = {t.name for t in tags if t.kind == "definition"}
    assert {"fetchUser", "UserStore", "MAX_RETRIES"}.issubset(defs)


def test_extract_tags_typescript_symbols(tmp_path: Path) -> None:
    path = tmp_path / "service.ts"
    path.write_text(
        "interface ApiResponse { status: number; }\n"
        "type UserId = string;\n"
        "function parseResponse(r: ApiResponse): UserId { return String(r.status); }\n"
        "class ApiClient {\n"
        "  fetch() { return null; }\n"
        "}\n",
        encoding="utf-8",
    )

    tags = extract_tags(path)
    defs = {t.name for t in tags if t.kind == "definition"}
    assert {"ApiResponse", "UserId", "parseResponse", "ApiClient"}.issubset(defs)


def test_extract_tags_go_symbols(tmp_path: Path) -> None:
    path = tmp_path / "handler.go"
    path.write_text(
        "package main\n\n"
        "type Request struct { ID string }\n"
        "func HandleRequest(r Request) error { return nil }\n"
        "var DefaultTimeout = 30\n",
        encoding="utf-8",
    )

    tags = extract_tags(path)
    defs = {t.name for t in tags if t.kind == "definition"}
    assert {"Request", "HandleRequest", "DefaultTimeout"}.issubset(defs)


def test_extract_tags_rust_symbols(tmp_path: Path) -> None:
    path = tmp_path / "lib.rs"
    path.write_text(
        "struct Config { timeout: u32 }\n"
        "enum Status { Ok, Err }\n"
        "fn process(cfg: Config) -> Status { Status::Ok }\n"
        "trait Runnable { fn run(&self); }\n",
        encoding="utf-8",
    )

    tags = extract_tags(path)
    defs = {t.name for t in tags if t.kind == "definition"}
    assert {"Config", "Status", "process", "Runnable"}.issubset(defs)


def test_extract_tags_unknown_extension_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert extract_tags(path) == []


def test_build_repo_map_respects_budget(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "import b\n\ndef alpha():\n    return b.beta()\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text("def beta():\n    return 1\n", encoding="utf-8")

    result = build_repo_map(tmp_path, seed_files=["a.py"], budget_tokens=80)

    assert result.token_count <= result.budget_tokens
    assert any(path in result.ranked_files for path in ["a.py", "b.py"])
    assert "alpha" in result.outline or "beta" in result.outline
