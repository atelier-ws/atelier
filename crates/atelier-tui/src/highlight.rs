//! Syntax highlighting for code blocks in conversation entries.
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};

/// Parse markdown text and return Vec<Line> with code blocks syntax-highlighted.
/// Non-code text is returned as plain white Lines.
/// Code blocks (```lang...```) get per-line Spans with basic token coloring.
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
                    "  ```".to_string(),
                    Style::default().fg(Color::DarkGray),
                )));
            }
        } else if in_code {
            lines.push(highlight_code_line(raw_line, &lang));
        } else {
            lines.push(render_prose_line(raw_line));
        }
    }
    lines
}

fn highlight_code_line(line: &str, _lang: &str) -> Line<'static> {
    let mut spans: Vec<Span<'static>> = vec![Span::raw("  ")]; // indent

    let keywords = [
        "fn ", "let ", "mut ", "use ", "pub ", "impl ", "struct ", "enum ", "def ", "class ",
        "import ", "from ", "return ", "if ", "else ", "for ", "while ", "match ", "async ",
        "await ", "const ", "type ",
    ];

    let trimmed = line.trim_start();
    let indent: String = " ".repeat(line.len() - trimmed.len() + 2);

    if trimmed.starts_with("//") || trimmed.starts_with('#') || trimmed.starts_with("--") {
        return Line::from(Span::styled(
            format!("  {line}"),
            Style::default().fg(Color::DarkGray),
        ));
    }

    let starts_with_keyword = keywords.iter().any(|k| trimmed.starts_with(k));
    if starts_with_keyword {
        let kw = keywords.iter().find(|k| trimmed.starts_with(*k)).unwrap();
        spans.clear();
        spans.push(Span::raw(indent));
        spans.push(Span::styled(kw.to_string(), Style::default().fg(Color::Cyan)));
        spans.push(Span::raw(trimmed[kw.len()..].to_string()));
    } else if (trimmed.starts_with('"') || trimmed.starts_with('\'')) && trimmed.len() > 1 {
        spans.clear();
        spans.push(Span::raw(indent));
        spans.push(Span::styled(
            trimmed.to_string(),
            Style::default().fg(Color::Green),
        ));
    } else {
        spans.clear();
        spans.push(Span::styled(
            format!("  {line}"),
            Style::default().fg(Color::White),
        ));
    }

    Line::from(spans)
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
    } else if line.starts_with("- ") || line.starts_with("* ") || line.starts_with("  - ") {
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
