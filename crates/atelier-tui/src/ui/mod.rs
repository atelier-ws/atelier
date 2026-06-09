//! Rendering for the Atelier TUI: 3-pane layout + permission overlay.

use crate::app::{App, CompletionMode, FocusedPane, PendingPermission, Role, ToolStatus};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, Clear, List, ListItem, ListState, Paragraph, Wrap};
use ratatui::Frame;

fn border_color(app: &App, pane: FocusedPane) -> Color {
    if app.focused_pane == pane {
        app.agent_mode.accent_color()
    } else {
        Color::DarkGray
    }
}

pub fn draw(frame: &mut Frame, app: &mut App) {
    let area = frame.area();

    if app.needs_api_key {
        draw_api_key_setup(frame, app, area);
        return;
    }

    let input_line_count = app.input.lines().len().max(1) as u16;
    let input_height = input_line_count.min(5) + 2; // +2 for border, max 5 lines

    let vertical = Layout::vertical([
        Constraint::Min(0),
        Constraint::Length(1),
        Constraint::Length(input_height),
    ])
    .split(area);

    let horizontal =
        Layout::horizontal([Constraint::Percentage(75), Constraint::Percentage(25)]).split(vertical[0]);

    draw_conversation(frame, app, horizontal[0]);
    draw_tools(frame, app, horizontal[1]);
    draw_status_bar(frame, app, vertical[1]);
    draw_input(frame, app, vertical[2]);

    if app.completion_mode != CompletionMode::None {
        draw_completion_popup(frame, app, vertical[2]);
    }

    if app.show_session_picker {
        draw_session_picker(frame, app, area);
    } else if app.pending_choice.is_some() {
        draw_choice_overlay(frame, app, area);
    } else if app.pending_permission.is_some() {
        draw_permission_overlay(frame, app, area);
    } else if app.pending_diff.is_some() {
        draw_diff_overlay(frame, app, area);
    }
}

fn draw_choice_overlay(frame: &mut Frame, app: &App, area: Rect) {
    let Some(choice) = &app.pending_choice else {
        return;
    };
    let accent = app.agent_mode.accent_color();
    let overlay = centered_rect(60, 40, area);
    frame.render_widget(Clear, overlay);

    let mut lines: Vec<Line> = vec![
        Line::from(Span::styled(
            format!("  ? {}", choice.question),
            Style::default().fg(accent).add_modifier(Modifier::BOLD),
        )),
        Line::raw(""),
    ];
    for (i, c) in choice.choices.iter().enumerate() {
        let selected = i == choice.selected && !choice.input_mode;
        let marker = if selected { "►" } else { " " };
        let style = if selected {
            Style::default().fg(accent).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::White)
        };
        lines.push(Line::from(Span::styled(
            format!("  {marker} {}. {c}", i + 1),
            style,
        )));
    }
    lines.push(Line::raw(""));
    if choice.input_mode {
        lines.push(Line::from(Span::styled(
            format!("  custom: {}_", choice.custom_input),
            Style::default().fg(Color::Yellow),
        )));
        lines.push(Line::from(Span::styled(
            "  Enter submit · Esc cancel",
            Style::default().fg(Color::DarkGray),
        )));
    } else {
        let hint = if choice.allow_freeform {
            "  ↑↓ navigate · Enter select · type for custom"
        } else {
            "  ↑↓ navigate · Enter select"
        };
        lines.push(Line::from(Span::styled(
            hint,
            Style::default().fg(Color::DarkGray),
        )));
    }

    let block = Block::bordered()
        .title(" Choose ")
        .border_style(Style::default().fg(accent));
    let para = Paragraph::new(lines).block(block).wrap(Wrap { trim: false });
    frame.render_widget(para, overlay);
}

fn draw_session_picker(frame: &mut Frame, app: &App, area: Rect) {
    let accent = app.agent_mode.accent_color();
    let overlay = centered_rect(70, 60, area);
    frame.render_widget(Clear, overlay);

    let mut lines: Vec<Line> = vec![
        Line::from(Span::styled(
            "  Resume a session",
            Style::default().fg(accent).add_modifier(Modifier::BOLD),
        )),
        Line::raw(""),
    ];
    if app.session_list.is_empty() {
        lines.push(Line::from(Span::styled(
            "  Loading sessions…",
            Style::default().fg(Color::DarkGray),
        )));
    } else {
        for (i, s) in app.session_list.iter().enumerate() {
            let selected = i == app.session_picker_selected;
            let marker = if selected { "►" } else { " " };
            let style = if selected {
                Style::default().fg(accent).add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::White)
            };
            lines.push(Line::from(Span::styled(
                format!("  {marker} {} — {} ({:.1}KB)", s.id, s.timestamp, s.size_kb),
                style,
            )));
        }
    }
    lines.push(Line::raw(""));
    lines.push(Line::from(Span::styled(
        "  ↑↓ navigate · Enter resume · Esc cancel",
        Style::default().fg(Color::DarkGray),
    )));

    let block = Block::bordered()
        .title(" Sessions ")
        .border_style(Style::default().fg(accent));
    let para = Paragraph::new(lines).block(block).wrap(Wrap { trim: false });
    frame.render_widget(para, overlay);
}

fn draw_completion_popup(frame: &mut Frame, app: &App, anchor: Rect) {
    match &app.completion_mode {
        CompletionMode::None => {}
        CompletionMode::SlashCommand { selected, filter } => {
            let commands = app.filtered_slash_commands(filter);
            if commands.is_empty() {
                return;
            }
            let popup_h = (commands.len().min(8) + 2) as u16;
            let popup_y = anchor.y.saturating_sub(popup_h);
            let popup = Rect {
                x: anchor.x,
                y: popup_y,
                width: anchor.width,
                height: popup_h,
            };
            frame.render_widget(Clear, popup);
            let items: Vec<ListItem> = commands
                .iter()
                .enumerate()
                .map(|(i, (name, desc))| {
                    let style = if i == *selected {
                        Style::default().fg(Color::Black).bg(Color::Cyan)
                    } else {
                        Style::default().fg(Color::White)
                    };
                    let desc_style = if i == *selected {
                        style.fg(Color::Black)
                    } else {
                        style.fg(Color::DarkGray)
                    };
                    ListItem::new(Line::from(vec![
                        Span::styled(format!("  /{name:<15}"), style),
                        Span::styled(format!(" {desc}"), desc_style),
                    ]))
                })
                .collect();
            let list = List::new(items).block(
                Block::bordered()
                    .title(" Commands ")
                    .border_style(Style::default().fg(Color::Cyan)),
            );
            frame.render_widget(list, popup);
        }
        CompletionMode::FileRef { selected, filter, .. } => {
            let files = app.filtered_files(filter);
            if files.is_empty() {
                return;
            }

            let visible = 12usize; // show more
            let offset = if *selected >= visible {
                selected - visible + 1
            } else {
                0
            };
            let visible_files: Vec<_> = files.iter().skip(offset).take(visible).enumerate().collect();

            let popup_h = (visible_files.len().min(visible) + 2) as u16;
            let popup_y = anchor.y.saturating_sub(popup_h);
            let popup = Rect {
                x: anchor.x,
                y: popup_y,
                width: anchor.width.min(80),
                height: popup_h,
            };

            frame.render_widget(Clear, popup);
            let items: Vec<ListItem> = visible_files
                .iter()
                .map(|(i, path)| {
                    let abs_idx = i + offset;
                    let is_selected = abs_idx == *selected;
                    let is_recent = app.recent_files.contains(*path);
                    let ext = path.split('.').next_back().unwrap_or("");
                    let ext_color = match ext {
                        "py" => Color::Yellow,
                        "rs" => Color::Red,
                        "ts" | "js" => Color::Cyan,
                        "md" => Color::White,
                        "json" | "toml" | "yaml" | "yml" => Color::Green,
                        _ => Color::DarkGray,
                    };
                    let bg = if is_selected { Color::Yellow } else { Color::Reset };
                    let fg = if is_selected { Color::Black } else { Color::White };
                    let recent_marker = if is_recent { "★ " } else { "  " };
                    let ext_badge = format!("[{ext:>4}]");

                    ListItem::new(Line::from(vec![
                        Span::styled(recent_marker.to_string(), Style::default().fg(Color::Yellow).bg(bg)),
                        Span::styled(ext_badge, Style::default().fg(ext_color).bg(bg)),
                        Span::styled(format!(" {path}"), Style::default().fg(fg).bg(bg)),
                    ]))
                })
                .collect();

            let title = if filter.is_empty() {
                format!(" Files ({}) ", files.len())
            } else {
                format!(" Files matching '{}' ({}) ", filter, files.len())
            };

            let list = List::new(items).block(
                Block::bordered()
                    .title(title.as_str())
                    .border_style(Style::default().fg(Color::Yellow)),
            );
            frame.render_widget(list, popup);
        }
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

fn draw_conversation(frame: &mut Frame, app: &mut App, area: Rect) {
    use crate::highlight::render_markdown_lines;

    let title = if let Some(s) = &app.search {
        let total = s.matches.len();
        let pos = if total == 0 { 0 } else { s.current_match + 1 };
        format!(" SEARCH: \"{}\" — {}/{} matches ", s.query, pos, total)
    } else if app.current_model.is_empty() {
        " Conversation ".to_string()
    } else {
        format!(" Conversation — {} ", app.current_model)
    };
    let border = if app.search.is_some() {
        Color::Yellow
    } else {
        border_color(app, FocusedPane::Conversation)
    };
    let block = Block::bordered()
        .title(title)
        .border_style(Style::default().fg(border));

    if app.conversation.is_empty() && !app.is_streaming {
        let model_line = if app.current_model.is_empty() {
            "no model configured — type a message to set up".to_string()
        } else {
            app.current_model.clone()
        };
        let welcome_lines = vec![
            Line::raw(""),
            Line::from(Span::styled(
                "  ◆  ATELIER",
                Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
            )),
            Line::raw(""),
            Line::from(vec![
                Span::styled("  Project  ", Style::default().fg(Color::DarkGray)),
                Span::styled(app.project_root.clone(), Style::default().fg(Color::White)),
                if !app.git_branch.is_empty() {
                    Span::styled(
                        format!("  [{}]", app.git_branch),
                        Style::default().fg(Color::Yellow),
                    )
                } else {
                    Span::raw("")
                },
            ]),
            Line::from(vec![
                Span::styled("  Model    ", Style::default().fg(Color::DarkGray)),
                Span::styled(model_line, Style::default().fg(Color::Cyan)),
            ]),
            Line::raw(""),
            Line::from(Span::styled(
                "  Type a message to start · /help for commands",
                Style::default().fg(Color::DarkGray),
            )),
            Line::raw(""),
        ];
        let para = Paragraph::new(welcome_lines).block(block);
        frame.render_widget(para, area);
        return;
    }

    let mut all_lines: Vec<Line> = Vec::new();
    let current_match_idx = app
        .search
        .as_ref()
        .and_then(|s| s.matches.get(s.current_match).copied());
    for (entry_idx, entry) in app.conversation.iter().enumerate() {
        let is_match = app
            .search
            .as_ref()
            .map(|s| s.matches.contains(&entry_idx))
            .unwrap_or(false);
        let match_marker = if Some(entry_idx) == current_match_idx {
            Some(Style::default().bg(Color::Yellow).fg(Color::Black))
        } else if is_match {
            Some(Style::default().bg(Color::Rgb(60, 50, 0)))
        } else {
            None
        };
        match entry.role {
            Role::User => {
                all_lines.push(Line::from(Span::styled(
                    "▶ You".to_string(),
                    match_marker.unwrap_or_else(|| {
                        Style::default().fg(Color::Green).add_modifier(Modifier::BOLD)
                    }),
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
                    match_marker.unwrap_or_else(|| {
                        Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)
                    }),
                )));
                for hl_line in render_markdown_lines(&entry.text) {
                    all_lines.push(hl_line);
                }
                all_lines.push(Line::raw(""));
            }
            Role::System => {
                all_lines.push(Line::from(Span::styled(
                    format!("  ◆ {}", entry.text),
                    match_marker.unwrap_or_else(|| Style::default().fg(Color::DarkGray)),
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
    let scroll = if app.auto_scroll {
        max_scroll
    } else {
        app.scroll.min(max_scroll)
    };
    app.scroll = scroll;

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
    let mut model = if app.current_model.is_empty() {
        "—".to_string()
    } else {
        app.current_model.clone()
    };
    if model.chars().count() > 30 {
        model = model.chars().take(30).collect();
    }
    let cache = app
        .cache_efficiency
        .map(|v| format!("{v:.0}%"))
        .unwrap_or_else(|| "—".to_string());
    let cost = if app.total_cost_usd > 0.0 {
        format!("${:.4}", app.total_cost_usd)
    } else {
        "—".to_string()
    };
    let saved = if app.total_savings_usd > 0.0 {
        format!("${:.4}", app.total_savings_usd)
    } else {
        "—".to_string()
    };
    let turns = app.conversation.len() / 2;

    let style = Style::default().fg(Color::DarkGray);
    let mode = app.agent_mode;
    let spans = vec![
        Span::styled(
            format!("  [{}]", mode.name()),
            Style::default()
                .fg(mode.accent_color())
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled(format!("  ◆ {model}"), style),
        Span::styled("  │  ", style),
        Span::styled(format!("cache {cache}"), style),
        Span::styled("  │  ", style),
        Span::styled(format!("session {cost}"), style),
        Span::styled("  │  ", style),
        Span::styled(format!("saved {saved}"), style),
        Span::styled("  │  ", style),
        Span::styled(format!("ctx {turns} turns"), style),
        Span::styled("  │  ", style),
        Span::styled("↑↓ scroll · Tab focus · Shift+Enter newline", style),
    ];
    frame.render_widget(Paragraph::new(Line::from(spans)), area);
}

fn draw_api_key_setup(frame: &mut Frame, app: &App, area: Rect) {
    let popup = centered_rect(70, 60, area);
    frame.render_widget(Clear, popup);

    let lines = vec![
        Line::raw(""),
        Line::from(Span::styled(
            "  ⚠  No API key configured",
            Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
        )),
        Line::raw(""),
        Line::from(Span::styled(
            "  Set one of these environment variables:",
            Style::default().fg(Color::White),
        )),
        Line::raw(""),
        Line::from(vec![
            Span::styled("    ANTHROPIC_API_KEY", Style::default().fg(Color::Cyan)),
            Span::raw("  — Claude models"),
        ]),
        Line::from(vec![
            Span::styled("    OPENAI_API_KEY   ", Style::default().fg(Color::Cyan)),
            Span::raw("  — GPT-4o / o-series"),
        ]),
        Line::from(vec![
            Span::styled("    GOOGLE_API_KEY   ", Style::default().fg(Color::Cyan)),
            Span::raw("  — Gemini models"),
        ]),
        Line::raw(""),
        Line::from(Span::styled(
            "  Or type a model string to continue (e.g. ollama/llama3):",
            Style::default().fg(Color::DarkGray),
        )),
        Line::raw(""),
        Line::from(Span::styled(
            "  Press Ctrl-D to exit.",
            Style::default().fg(Color::DarkGray),
        )),
    ];

    let block = Block::bordered()
        .title(" Atelier Setup ")
        .border_style(Style::default().fg(Color::Yellow));
    let para = Paragraph::new(lines).block(block).wrap(Wrap { trim: false });
    frame.render_widget(para, popup);

    let input_area = Rect {
        y: popup.y + popup.height,
        height: 3,
        ..popup
    };
    if input_area.y + input_area.height <= area.height {
        frame.render_widget(&app.input, input_area);
    }
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
