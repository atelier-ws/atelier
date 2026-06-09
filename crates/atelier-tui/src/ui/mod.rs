//! Rendering for the Atelier TUI: 3-pane layout + permission overlay.

use crate::app::{App, FocusedPane, PendingPermission, Role, ToolStatus};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, Clear, List, ListItem, ListState, Paragraph, Wrap};
use ratatui::Frame;

fn border_color(app: &App, pane: FocusedPane) -> Color {
    if app.focused_pane == pane {
        Color::Cyan
    } else {
        Color::DarkGray
    }
}

pub fn draw(frame: &mut Frame, app: &mut App) {
    let area = frame.area();

    let vertical = Layout::vertical([
        Constraint::Min(0),
        Constraint::Length(3),
        Constraint::Length(1),
    ])
    .split(area);

    let horizontal =
        Layout::horizontal([Constraint::Percentage(75), Constraint::Percentage(25)]).split(vertical[0]);

    draw_conversation(frame, app, horizontal[0]);
    draw_tools(frame, app, horizontal[1]);
    draw_input(frame, app, vertical[1]);
    draw_status_bar(frame, app, vertical[2]);

    if app.pending_permission.is_some() {
        draw_permission_overlay(frame, app, area);
    } else if app.pending_diff.is_some() {
        draw_diff_overlay(frame, app, area);
    }
}

fn draw_diff_overlay(frame: &mut Frame, app: &App, area: Rect) {
    let popup_area = centered_rect(80, 70, area);
    frame.render_widget(Clear, popup_area);

    let diff_text = app.pending_diff.as_deref().unwrap_or("");
    let lines: Vec<Line> = diff_text
        .lines()
        .map(|l| {
            if l.starts_with('+') && !l.starts_with("+++") {
                Line::from(Span::styled(l.to_string(), Style::default().fg(Color::Green)))
            } else if l.starts_with('-') && !l.starts_with("---") {
                Line::from(Span::styled(l.to_string(), Style::default().fg(Color::Red)))
            } else if l.starts_with("@@") {
                Line::from(Span::styled(l.to_string(), Style::default().fg(Color::Cyan)))
            } else {
                Line::from(Span::raw(l.to_string()))
            }
        })
        .collect();

    let block = Block::bordered()
        .title(" Proposed Changes — press 'a' to apply, 'd' to dismiss ")
        .border_style(Style::default().fg(Color::Yellow));
    let paragraph = Paragraph::new(lines).block(block).wrap(Wrap { trim: false });
    frame.render_widget(paragraph, popup_area);
}

fn draw_conversation(frame: &mut Frame, app: &App, area: Rect) {
    use crate::highlight::render_markdown_lines;

    let mut all_lines: Vec<Line> = Vec::new();
    for entry in &app.conversation {
        match entry.role {
            Role::User => {
                all_lines.push(Line::from(Span::styled(
                    "▶ You".to_string(),
                    Style::default().fg(Color::Green).add_modifier(Modifier::BOLD),
                )));
                for line in entry.text.lines() {
                    all_lines.push(Line::from(Span::styled(
                        format!("  {line}"),
                        Style::default().fg(Color::Green),
                    )));
                }
                all_lines.push(Line::raw(""));
            }
            Role::Assistant => {
                all_lines.push(Line::from(Span::styled(
                    "◉ Atelier",
                    Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
                )));
                for hl_line in render_markdown_lines(&entry.text) {
                    all_lines.push(hl_line);
                }
                all_lines.push(Line::raw(""));
            }
            Role::System => {
                all_lines.push(Line::from(Span::styled(
                    format!("  ◆ {}", entry.text),
                    Style::default().fg(Color::DarkGray),
                )));
            }
        }
    }

    if app.is_streaming && !app.streaming_text.is_empty() {
        all_lines.push(Line::from(Span::styled(
            "◉ Atelier",
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
        )));
        for hl_line in render_markdown_lines(&app.streaming_text) {
            all_lines.push(hl_line);
        }
    }

    let content_height = all_lines.len() as u16;
    let visible_height = area.height.saturating_sub(2);
    let max_scroll = content_height.saturating_sub(visible_height);
    let scroll = app.scroll.min(max_scroll);

    let title = if app.current_model.is_empty() {
        " Conversation ".to_string()
    } else {
        format!(" Conversation — {} ", app.current_model)
    };

    let block = Block::bordered()
        .title(title)
        .border_style(Style::default().fg(border_color(app, FocusedPane::Conversation)));

    let paragraph = Paragraph::new(all_lines)
        .block(block)
        .wrap(Wrap { trim: false })
        .scroll((scroll, 0));
    frame.render_widget(paragraph, area);
}

fn draw_tools(frame: &mut Frame, app: &App, area: Rect) {
    let items: Vec<ListItem> = app
        .tools
        .iter()
        .map(|tool| {
            let (marker, style) = match tool.status {
                ToolStatus::Requested => ("●", Style::default().fg(Color::DarkGray)),
                ToolStatus::Running => ("⟳", Style::default().fg(Color::Yellow)),
                ToolStatus::Done => ("✓", Style::default().fg(Color::Green)),
                ToolStatus::Failed => ("✗", Style::default().fg(Color::Red)),
            };
            let mut lines = vec![Line::from(vec![
                Span::styled(format!("{marker} "), style),
                Span::raw(tool.name.clone()),
            ])];
            if let Some(preview) = &tool.output_preview {
                lines.push(Line::from(Span::styled(
                    format!("  {preview}"),
                    Style::default().fg(Color::DarkGray),
                )));
            }
            ListItem::new(lines)
        })
        .collect();

    let block = Block::bordered()
        .title(" Tools ")
        .border_style(Style::default().fg(border_color(app, FocusedPane::Tools)));

    let list = List::new(items).block(block);

    let mut state = ListState::default();
    let offset = app.tool_scroll as usize;
    *state.offset_mut() = offset;
    if !app.tools.is_empty() {
        state.select(Some(offset.min(app.tools.len().saturating_sub(1))));
    }

    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_input(frame: &mut Frame, app: &mut App, area: Rect) {
    let focused = app.focused_pane == FocusedPane::Input;
    let color = if focused { Color::Cyan } else { Color::DarkGray };
    let block = Block::bordered()
        .title(" atelier> ")
        .border_style(Style::default().fg(color));
    app.input.set_block(block);
    frame.render_widget(&app.input, area);
}

fn draw_status_bar(frame: &mut Frame, app: &App, area: Rect) {
    let session = if app.session_id.is_empty() {
        "—".to_string()
    } else {
        app.session_id.clone()
    };
    let model = if app.current_model.is_empty() {
        "—".to_string()
    } else {
        app.current_model.clone()
    };
    let style = Style::default().fg(Color::DarkGray);
    let mut spans = vec![
        Span::styled(format!(" session: {session}"), style),
        Span::styled("  │  ", style),
        Span::styled(format!("model: {model}"), style),
        Span::styled("  │  ", style),
        Span::styled(format!("tools: {}", app.tools.len()), style),
    ];
    if let Some(eff) = app.cache_efficiency {
        spans.push(Span::styled("  │  ", style));
        spans.push(Span::styled(format!("cache: {eff:.0}%"), style));
        spans.push(Span::styled("  │  ", style));
        spans.push(Span::styled(format!("cost: ${:.4}", app.cost_usd), style));
        spans.push(Span::styled("  │  ", style));
        spans.push(Span::styled(format!("saved: ${:.4}", app.savings_usd), style));
    }
    spans.push(Span::styled("  │  ", style));
    spans.push(Span::styled(
        "↑↓ scroll · Tab focus · Shift+Enter newline",
        style,
    ));
    let line = Line::from(spans);
    frame.render_widget(Paragraph::new(line), area);
}

fn draw_permission_overlay(frame: &mut Frame, app: &App, area: Rect) {
    let Some(PendingPermission::Waiting { action, risk, .. }) = &app.pending_permission else {
        return;
    };

    let overlay = centered_rect(60, 30, area);
    frame.render_widget(Clear, overlay);

    let high_risk = risk == "high";
    let border_color = if high_risk { Color::Red } else { Color::Yellow };

    let lines = vec![
        Line::from(Span::styled(
            "⚠  Permission Required",
            Style::default().fg(border_color).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        Line::from(format!("{action} ({risk} risk)")),
        Line::from(""),
        Line::from(Span::styled(
            "[y] Approve   [n] Deny",
            Style::default().fg(Color::Cyan),
        )),
    ];

    let block = Block::bordered().border_style(Style::default().fg(border_color));
    let paragraph = Paragraph::new(Text::from(lines))
        .wrap(Wrap { trim: false })
        .block(block);
    frame.render_widget(paragraph, overlay);
}

fn centered_rect(percent_x: u16, percent_y: u16, area: Rect) -> Rect {
    let vertical = Layout::vertical([
        Constraint::Percentage((100 - percent_y) / 2),
        Constraint::Percentage(percent_y),
        Constraint::Percentage((100 - percent_y) / 2),
    ])
    .split(area);
    Layout::horizontal([
        Constraint::Percentage((100 - percent_x) / 2),
        Constraint::Percentage(percent_x),
        Constraint::Percentage((100 - percent_x) / 2),
    ])
    .split(vertical[1])[1]
}
