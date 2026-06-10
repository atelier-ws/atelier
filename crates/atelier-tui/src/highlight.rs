//! Syntax highlighting using syntect for accurate per-language coloring.

use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use std::sync::OnceLock;

static SYNTAX_SET: OnceLock<syntect::parsing::SyntaxSet> = OnceLock::new();
static THEME_SET: OnceLock<syntect::highlighting::ThemeSet> = OnceLock::new();

const CODE_BORDER: Color = Color::Rgb(70, 75, 100);
const CODE_LABEL: Color = Color::Rgb(120, 130, 170);
const CODE_INDENT: &str = "  ";

fn syntax_set() -> &'static syntect::parsing::SyntaxSet {
    SYNTAX_SET.get_or_init(syntect::parsing::SyntaxSet::load_defaults_newlines)
}

fn theme_set() -> &'static syntect::highlighting::ThemeSet {
    THEME_SET.get_or_init(syntect::highlighting::ThemeSet::load_defaults)
}

fn syntect_color_to_ratatui(color: syntect::highlighting::Color) -> Color {
    Color::Rgb(color.r, color.g, color.b)
}

/// Highlight a single line for the given file extension.
pub fn highlight_line_syntect(line: &str, ext: &str) -> Vec<Span<'static>> {
    use syntect::easy::HighlightLines;

    let ss = syntax_set();
    let ts = theme_set();

    let syntax = ss
        .find_syntax_by_extension(ext)
        .or_else(|| Some(ss.find_syntax_plain_text()))
        .unwrap_or_else(|| ss.find_syntax_plain_text());

    let theme = ts
        .themes
        .get("base16-ocean.dark")
        .or_else(|| ts.themes.get("Solarized (dark)"))
        .or_else(|| ts.themes.values().next())
        .unwrap();

    let mut h = HighlightLines::new(syntax, theme);

    match h.highlight_line(line, ss) {
        Ok(ranges) => ranges
            .iter()
            .map(|(style, text)| {
                let fg = syntect_color_to_ratatui(style.foreground);
                let mut ratatui_style = Style::default().fg(fg);
                if style.font_style.contains(syntect::highlighting::FontStyle::BOLD) {
                    ratatui_style = ratatui_style.add_modifier(Modifier::BOLD);
                }
                if style.font_style.contains(syntect::highlighting::FontStyle::ITALIC) {
                    ratatui_style = ratatui_style.add_modifier(Modifier::ITALIC);
                }
                Span::styled(text.to_string(), ratatui_style)
            })
            .collect(),
        Err(_) => vec![Span::raw(line.to_string())],
    }
}

fn lang_to_ext(lang: &str) -> &'static str {
    match lang {
        "python" | "py" => "py",
        "rust" | "rs" => "rs",
        "typescript" | "ts" => "ts",
        "javascript" | "js" => "js",
        "bash" | "sh" | "shell" | "zsh" | "fish" => "sh",
        "json" => "json",
        "yaml" | "yml" => "yaml",
        "toml" => "toml",
        "css" => "css",
        "html" | "htm" => "html",
        "sql" => "sql",
        "c" => "c",
        "cpp" | "c++" | "cxx" => "cpp",
        "go" => "go",
        "java" => "java",
        "kotlin" | "kt" => "kt",
        "swift" => "swift",
        "ruby" | "rb" => "rb",
        "php" => "php",
        "markdown" | "md" => "md",
        "diff" | "patch" => "diff",
        "makefile" | "make" => "mk",
        "dockerfile" => "dockerfile",
        "xml" => "xml",
        "ini" | "cfg" | "conf" => "ini",
        _ => "txt",
    }
}

/// Render markdown text into highlighted Lines (for conversation display).
/// Code blocks get box-drawn borders with language badge.
pub fn render_markdown_lines(text: &str) -> Vec<Line<'static>> {
    let mut lines: Vec<Line<'static>> = Vec::new();
    let mut in_code = false;
    let mut lang = String::new();

    for raw_line in text.lines() {
        if raw_line.starts_with("```") {
            if !in_code {
                in_code = true;
                lang = raw_line.trim_start_matches('`').trim().to_string();
                // Opening border: ╭─── lang ────────────────────
                let label = if lang.is_empty() {
                    " ────────────────────────────".to_string()
                } else {
                    format!(" {} ─────────────────────", lang)
                };
                lines.push(Line::from(vec![
                    Span::raw(CODE_INDENT),
                    Span::styled("╭─", Style::default().fg(CODE_BORDER)),
                    Span::styled(label, Style::default().fg(CODE_LABEL)),
                ]));
            } else {
                in_code = false;
                lang.clear();
                // Closing border
                lines.push(Line::from(vec![
                    Span::raw(CODE_INDENT),
                    Span::styled(
                        "╰────────────────────────────────────",
                        Style::default().fg(CODE_BORDER),
                    ),
                ]));
            }
        } else if in_code {
            let lang_lower = lang.to_lowercase();
            let ext = lang_to_ext(&lang_lower);
            let mut spans: Vec<Span<'static>> = vec![
                Span::raw(CODE_INDENT),
                Span::styled("│ ", Style::default().fg(CODE_BORDER)),
            ];
            if raw_line.is_empty() {
                spans.push(Span::raw(" "));
            } else {
                spans.extend(highlight_line_syntect(raw_line, ext));
            }
            lines.push(Line::from(spans));
        } else {
            lines.push(render_prose_line(raw_line));
        }
    }
    // Close unclosed code block gracefully
    if in_code {
        lines.push(Line::from(vec![
            Span::raw(CODE_INDENT),
            Span::styled(
                "╰────────────────────────────────────",
                Style::default().fg(CODE_BORDER),
            ),
        ]));
    }
    lines
}

/// Parse inline markdown spans: `code`, **bold**, *italic*, plain text.
pub fn parse_inline_spans(line: &str) -> Vec<Span<'static>> {
    let mut spans: Vec<Span<'static>> = Vec::new();
    let mut chars = line.chars().peekable();
    let mut buf = String::new();

    while let Some(&ch) = chars.peek() {
        match ch {
            '`' => {
                if !buf.is_empty() {
                    spans.push(Span::raw(buf.clone()));
                    buf.clear();
                }
                chars.next();
                let mut code = String::new();
                while let Some(&c) = chars.peek() {
                    chars.next();
                    if c == '`' {
                        break;
                    }
                    code.push(c);
                }
                spans.push(Span::styled(
                    code,
                    Style::default()
                        .fg(Color::Rgb(255, 200, 100))
                        .bg(Color::Rgb(38, 40, 55)),
                ));
            }
            '*' => {
                chars.next();
                if chars.peek() == Some(&'*') {
                    // **bold**
                    chars.next();
                    if !buf.is_empty() {
                        spans.push(Span::raw(buf.clone()));
                        buf.clear();
                    }
                    let mut bold = String::new();
                    while let Some(&c) = chars.peek() {
                        chars.next();
                        if c == '*' && chars.peek() == Some(&'*') {
                            chars.next();
                            break;
                        }
                        bold.push(c);
                    }
                    spans.push(Span::styled(
                        bold,
                        Style::default().add_modifier(Modifier::BOLD),
                    ));
                } else {
                    // *italic*
                    if !buf.is_empty() {
                        spans.push(Span::raw(buf.clone()));
                        buf.clear();
                    }
                    let mut italic = String::new();
                    while let Some(&c) = chars.peek() {
                        chars.next();
                        if c == '*' {
                            break;
                        }
                        italic.push(c);
                    }
                    spans.push(Span::styled(
                        italic,
                        Style::default().add_modifier(Modifier::ITALIC),
                    ));
                }
            }
            _ => {
                buf.push(ch);
                chars.next();
            }
        }
    }
    if !buf.is_empty() {
        spans.push(Span::raw(buf));
    }
    if spans.is_empty() {
        spans.push(Span::raw(String::new()));
    }
    spans
}

fn render_prose_line(line: &str) -> Line<'static> {
    // H1
    if let Some(rest) = line.strip_prefix("# ") {
        return Line::from(Span::styled(
            rest.to_string(),
            Style::default()
                .fg(Color::Rgb(100, 210, 255))
                .add_modifier(Modifier::BOLD),
        ));
    }
    // H2
    if let Some(rest) = line.strip_prefix("## ") {
        return Line::from(Span::styled(
            rest.to_string(),
            Style::default()
                .fg(Color::Rgb(80, 185, 230))
                .add_modifier(Modifier::BOLD),
        ));
    }
    // H3
    if let Some(rest) = line.strip_prefix("### ") {
        return Line::from(Span::styled(
            rest.to_string(),
            Style::default().fg(Color::Rgb(70, 165, 210)),
        ));
    }
    // Blockquote
    if let Some(rest) = line.strip_prefix("> ") {
        let mut spans = vec![Span::styled(
            "┃ ",
            Style::default().fg(Color::Rgb(90, 95, 130)),
        )];
        let inner: Vec<Span<'static>> = parse_inline_spans(rest)
            .into_iter()
            .map(|s| {
                Span::styled(
                    s.content.to_string(),
                    s.style.add_modifier(Modifier::ITALIC).fg(Color::Rgb(160, 165, 185)),
                )
            })
            .collect();
        spans.extend(inner);
        return Line::from(spans);
    }
    // Horizontal rule
    if line == "---" || line == "===" || line == "***" || line.starts_with("───") {
        return Line::from(Span::styled(
            "  ─────────────────────────────────────────────────",
            Style::default().fg(Color::Rgb(60, 65, 85)),
        ));
    }
    // Unordered bullet
    if let Some(rest) = line.strip_prefix("- ").or_else(|| line.strip_prefix("* ")) {
        let mut spans = vec![Span::styled(
            "  ● ",
            Style::default().fg(Color::Rgb(100, 180, 230)),
        )];
        spans.extend(parse_inline_spans(rest));
        return Line::from(spans);
    }
    // Numbered list (up to 3-digit numbers)
    if line.len() > 2 {
        let dot_pos = line.find(". ");
        if let Some(pos) = dot_pos {
            if pos <= 3 && line[..pos].chars().all(|c| c.is_ascii_digit()) {
                let num = &line[..pos];
                let rest = &line[pos + 2..];
                let mut spans = vec![Span::styled(
                    format!("  {}. ", num),
                    Style::default().fg(Color::Rgb(100, 180, 230)),
                )];
                spans.extend(parse_inline_spans(rest));
                return Line::from(spans);
            }
        }
    }
    // Regular prose with inline formatting
    if line.contains("http://") || line.contains("https://") {
        return Line::from(crate::ui::render_with_links(line));
    }
    Line::from(parse_inline_spans(line))
}
