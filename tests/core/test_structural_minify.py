from __future__ import annotations

from atelier.core.capabilities.context_compression.minify import minify_source


def test_safe_language_collapses_interior_whitespace_and_saves_tokens() -> None:
    source = (
        "package   main\n\n"
        'import   "fmt"\n\n'
        "func   main()   {\n"
        '    message := "keep   quoted   spacing"\n'
        "    fmt.Println(   message   )\n"
        "}\n"
    )

    minified, original_tokens, minified_tokens = minify_source(source, "go")

    assert "package main" in minified
    assert "func main() {" in minified
    assert "fmt.Println( message )" in minified
    assert '"keep   quoted   spacing"' in minified
    assert minified_tokens < original_tokens


def test_whitespace_significant_languages_keep_conservative_path() -> None:
    source = "def run():\n    value    =    1\n    return value\n"

    minified, _original_tokens, _minified_tokens = minify_source(source, "python")

    assert "value    =    1" in minified


def test_unknown_languages_keep_conservative_path() -> None:
    source = "value    =    still    spaced\n"

    minified, _original_tokens, _minified_tokens = minify_source(source, "text")

    assert minified == source


def test_minify_source_is_pure_and_preserves_json_string_content() -> None:
    source = '{  "message"  :  "keep   inner   spacing",  "count"  :  1  }\n'

    first, first_original_tokens, first_minified_tokens = minify_source(source, "json")
    second, second_original_tokens, second_minified_tokens = minify_source(source, "json")

    assert first == second
    assert first_original_tokens == second_original_tokens
    assert first_minified_tokens == second_minified_tokens
    assert '"keep   inner   spacing"' in first
