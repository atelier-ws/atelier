from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.starter_packs import load_template_block


def test_all_reasonblock_templates_parse() -> None:
    template_root = Path("templates") / "reasonblocks"
    templates = sorted(template_root.glob("*/*.md"))
    assert templates
    for path in templates:
        block = load_template_block(path)
        assert block.id.startswith("template-")
        assert block.procedure
        assert "TODO" in path.read_text(encoding="utf-8")
