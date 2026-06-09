//! Syntax highlighting using syntect for accurate per-language coloring.

use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use std::sync::OnceLock;

static SYNTAX_SET: OnceLock<syntect::parsing::SyntaxSet> = OnceLock::new();
static THEME_SET: OnceLock<syntect::highlighting::ThemeSet> = OnceLock::new();

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
/// Returns a Vec of styled Spans.
pub fn highlight_line_syntect(line: &str, ext: &str) -> Vec<Span<'static>> {
    use syntect::easy::HighlightLines;

    let ss = syntax_set();
    let ts = theme_set();

    // Find syntax by extension.
    let syntax = ss
        .find_syntax_by_extension(ext)
        .or_else(|| ss.find_syntax_by_extension("txt"))
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
                if style
                    .font_style
                    .contains(syntect::highlighting::FontStyle::BOLD)
                {
                    ratatui_style = ratatui_style.add_modifier(Modifier::BOLD);
                }
                if style
                    .font_style
                    .contains(syntect::highlighting::FontStyle::ITALIC)
                {
                    ratatui_style = ratatui_style.add_modifier(Modifier::ITALIC);
                }
                Span::styled(text.to_string(), ratatui_style)
            })
            .collect(),
        Err(_) => vec![Span::raw(line.to_string())],
    }
}

/// Render markdown text into highlighted Lines (for conversation display).
pub fn render_markdown_lines(text: &str) -> Vec<Line<'static>> {
    let mut lines: Vec<Line<'static>> = Vec::new();
    let mut in_code = false;
    let mut lang = String::new();

    for raw_line in text.lines() {
        if raw_line.starts_with("```") {
            if !in_code {
                in_code = true;
                lang = raw_line.trim_start_matches('`').to_string();
                lines.push(Line::from(Span::styled(
                    format!("  {raw_line}"),
                    Style::default().fg(Color::DarkGray),
                )));
            } else {
                in_code = false;
                lang.clear();
                lines.push(Line::from(Span::styled(
                    "  ```",
                    Style::default().fg(Color::DarkGray),
                )));
            }
        } else if in_code {
            // Use syntect for code blocks.
            let ext = match lang.as_str() {
                "python" | "py" => "py",
                "rust" | "rs" => "rs",
                "typescript" | "ts" => "ts",
                "javascript" | "js" => "js",
                "bash" | "sh" => "sh",
                "json" => "json",
                "yaml" | "yml" => "yaml",
                "toml" => "toml",
                other => other,
            };
            let mut spans = vec![Span::raw("  ")];
            spans.extend(highlight_line_syntect(raw_line, ext));
            lines.push(Line::from(spans));
        } else {
            lines.push(render_prose_line(raw_line));
        }
    }
    lines
}

/// Render a single file line with syntect highlighting.
pub fn render_file_line(line: &str, ext: &str) -> Vec<Span<'static>> {
    highlight_line_syntect(line, ext)
}

fn render_prose_line(line: &str) -> Line<'static> {
    if line.starts_with("# ") {
        Line::from(Span::styled(
            line.to_string(),
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
        ))
    } else if line.starts_with("## ") || line.starts_with("### ") {
        Line::from(Span::styled(
            line.to_string(),
            Style::default().fg(Color::Cyan),
        ))
    } else if line.starts_with("- ") || line.starts_with("* ") {
        let (bullet, rest) = line.split_once(' ').unwrap_or(("-", line));
        Line::from(vec![
            Span::styled(format!("{bullet} "), Style::default().fg(Color::Yellow)),
            Span::raw(rest.to_string()),
        ])
    } else if line.starts_with("**") && line.ends_with("**") && line.len() > 4 {
        Line::from(Span::styled(
            line.replace("**", ""),
            Style::default().add_modifier(Modifier::BOLD),
        ))
    } else {
        Line::from(Span::raw(line.to_string()))
    }
}
