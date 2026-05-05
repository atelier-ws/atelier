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


def test_build_repo_map_respects_budget(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "import b\n\ndef alpha():\n    return b.beta()\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text("def beta():\n    return 1\n", encoding="utf-8")

    result = build_repo_map(tmp_path, seed_files=["a.py"], budget_tokens=80)

    assert result.token_count <= result.budget_tokens
    assert any(path in result.ranked_files for path in ["a.py", "b.py"])
    assert "alpha" in result.outline or "beta" in result.outline
