//! Rendering for the Atelier TUI: 3-pane layout + permission overlay.

use crate::app::{
    ActiveOverlay, App, CompletionMode, ContextMenu, FocusedPane, PendingPermission, Role,
    ToolStatus,
};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, BorderType, Clear, List, ListItem, Paragraph, Wrap};
use ratatui::Frame;

fn border_color(app: &App, pane: FocusedPane) -> Color {
    if app.focused_pane == pane {
        app.agent_mode.accent_color()
    } else {
        Color::DarkGray
    }
}

/// Rounded border for the focused pane, plain (thin) for inactive panes.
fn border_type_for_pane(app: &App, pane: FocusedPane) -> BorderType {
    if app.focused_pane == pane {
        BorderType::Rounded
    } else {
        BorderType::Plain
    }
}

pub fn draw(frame: &mut Frame, app: &mut App) {
    let area = frame.area();
    app.term_width = area.width;

    if app.needs_api_key {
        draw_api_key_setup(frame, app, area);
        return;
    }

    let input_line_count = app.input.lines().len().max(1) as u16;
    let input_height = input_line_count.min(5) + 2; // +2 for border, max 5 lines

    // Simple 3-row layout: conversation + input + status bar.
    let vertical = Layout::vertical([
        Constraint::Min(0),               // conversation
        Constraint::Length(input_height), // input
        Constraint::Length(1),            // status bar
    ])
    .split(area);

    app.conv_rect = vertical[0];
    app.input_rect = vertical[1];

    // Conversation pane — no border, full width, like Claude Code
    draw_conversation_content(frame, app, vertical[0]);

    draw_input(frame, app, vertical[1]);
    draw_status_bar(frame, app, vertical[2]);

    if app.completion_mode != CompletionMode::None {
        draw_completion_popup(frame, app, vertical[1]);
    }

    if !app.prompt_suggestions.is_empty() && app.completion_mode == CompletionMode::None {
        let sugg_area = Rect {
            y: vertical[1]
                .y
                .saturating_sub(app.prompt_suggestions.len() as u16 + 2),
            height: app.prompt_suggestions.len() as u16 + 2,
            ..vertical[1]
        };
        if sugg_area.y >= 1 {
            frame.render_widget(Clear, sugg_area);
            let items: Vec<ListItem> = app
                .prompt_suggestions
                .iter()
                .enumerate()
                .map(|(i, s)| {
                    ListItem::new(Line::from(Span::styled(
                        format!("  {} {s}", i + 1),
                        Style::default().fg(Color::DarkGray),
                    )))
                })
                .collect();
            let list = List::new(items).block(
                Block::bordered()
                    .title(" Suggestions (Tab to accept) ")
                    .border_style(Style::default().fg(Color::DarkGray)),
            );
            frame.render_widget(list, sugg_area);
        }
    }

    // Overlays on top of everything.
    if app.show_session_picker {
        draw_session_picker(frame, app, area);
    } else if app.pending_choice.is_some() {
        draw_choice_overlay(frame, app, area);
    } else if app.pending_permission.is_some() {
        draw_permission_overlay(frame, app, area);
    } else if app.pending_diff.is_some() {
        draw_diff_overlay(frame, app, area);
    }

    match &app.active_overlay {
        ActiveOverlay::None => {}
        ActiveOverlay::Help => draw_help_overlay(frame, app, area),
        ActiveOverlay::AgentPicker { selected } => draw_agent_picker(frame, app, *selected, area),
        ActiveOverlay::ModelPicker { selected, models } => {
            draw_model_picker(frame, app, *selected, models, area)
        }
        ActiveOverlay::AuthPicker { selected, providers } => {
            draw_auth_picker(frame, app, *selected, providers, area)
        }
    }

    // Context menu renders LAST, on top of everything else.
    if let Some(ref menu) = app.context_menu {
        draw_context_menu(frame, menu, app);
    }
}

fn draw_context_menu(frame: &mut Frame, menu: &ContextMenu, app: &App) {
    let w = menu.items.iter().map(|i| i.label.len() + 6).max().unwrap_or(20) as u16;
    let h = menu.items.len() as u16 + 2;
    let popup = Rect {
        x: menu.x.min(frame.area().width.saturating_sub(w)),
        y: menu.y.min(frame.area().height.saturating_sub(h)),
        width: w,
        height: h,
    };

    frame.render_widget(Clear, popup);
    let items: Vec<ListItem> = menu
        .items
        .iter()
        .enumerate()
        .map(|(i, item)| {
            let bg = if i == menu.selected {
                app.agent_mode.accent_color()
            } else {
                Color::Reset
            };
            let fg = if i == menu.selected {
                Color::Black
            } else {
                Color::White
            };
            ListItem::new(Line::from(vec![
                Span::styled(
                    format!(" {} ", item.key),
                    Style::default().fg(Color::DarkGray).bg(bg),
                ),
                Span::styled(
                    format!(" {} ", item.label),
                    Style::default().fg(fg).bg(bg),
                ),
            ]))
        })
        .collect();
    let list = List::new(items).block(
        Block::bordered().border_style(Style::default().fg(app.agent_mode.accent_color())),
    );
    frame.render_widget(list, popup);
}

fn draw_agent_picker(frame: &mut Frame, app: &App, selected: usize, area: Rect) {
    let popup = centered_rect(60, 50, area);
    frame.render_widget(Clear, popup);

    let modes = [
        ("code", "Full tools — read, edit, shell, grep, explore"),
        ("explore", "Read-only — read, grep, explore (no edits)"),
        ("research", "Research — read, grep, explore (no edits)"),
        ("plan", "Planning — read, grep only"),
    ];

    let items: Vec<ListItem> = modes
        .iter()
        .enumerate()
        .map(|(i, (name, desc))| {
            let current = app.agent_mode.name().to_lowercase() == *name;
            let bg = if i == selected {
                app.agent_mode.accent_color()
            } else {
                Color::Reset
            };
            let fg = if i == selected { Color::Black } else { Color::White };
            let desc_fg = if i == selected {
                Color::Black
            } else {
                Color::DarkGray
            };
            let marker = if current { " \u{25cf}" } else { "  " };
            ListItem::new(Line::from(vec![
                Span::styled(
                    format!("{marker} {name:10} "),
                    Style::default().fg(fg).bg(bg).add_modifier(Modifier::BOLD),
                ),
                Span::styled(desc.to_string(), Style::default().fg(desc_fg).bg(bg)),
            ]))
        })
        .collect();

    let list = List::new(items).block(
        Block::bordered()
            .title(" Agent Mode  \u{2191}\u{2193} select \u{b7} Enter switch \u{b7} Esc close ")
            .border_style(Style::default().fg(app.agent_mode.accent_color())),
    );
    frame.render_widget(list, popup);
}

fn draw_model_picker(
    frame: &mut Frame,
    app: &App,
    selected: usize,
    models: &[(String, String)],
    area: Rect,
) {
    let popup = centered_rect(70, 60, area);
    frame.render_widget(Clear, popup);

    let items: Vec<ListItem> = models
        .iter()
        .enumerate()
        .map(|(i, (model_id, desc))| {
            let current = model_id == &app.current_model;
            let bg = if i == selected {
                app.agent_mode.accent_color()
            } else {
                Color::Reset
            };
            let fg = if i == selected { Color::Black } else { Color::White };
            let desc_fg = if i == selected {
                Color::Black
            } else {
                Color::DarkGray
            };
            let marker = if current { " \u{25cf}" } else { "  " };
            ListItem::new(Line::from(vec![
                Span::styled(
                    format!("{marker} {model_id:45} "),
                    Style::default().fg(fg).bg(bg),
                ),
                Span::styled(desc.to_string(), Style::default().fg(desc_fg).bg(bg)),
            ]))
        })
        .collect();

    let list = List::new(items).block(
        Block::bordered()
            .title(" Model Picker  \u{2191}\u{2193} select \u{b7} Enter switch \u{b7} Esc close ")
            .border_style(Style::default().fg(app.agent_mode.accent_color())),
    );
    frame.render_widget(list, popup);
}

fn draw_auth_picker(frame: &mut Frame, app: &App, selected: usize, providers: &[String], area: Rect) {
    let popup = centered_rect(60, 60, area);
    frame.render_widget(Clear, popup);

    let items: Vec<ListItem> = providers
        .iter()
        .enumerate()
        .map(|(i, provider)| {
            let bg = if i == selected {
                app.agent_mode.accent_color()
            } else {
                Color::Reset
            };
            let fg = if i == selected { Color::Black } else { Color::White };
            ListItem::new(Line::from(Span::styled(
                format!("  {provider} "),
                Style::default().fg(fg).bg(bg),
            )))
        })
        .collect();

    let list = List::new(items).block(
        Block::bordered()
            .title(" Configure Provider  \u{2191}\u{2193} select \u{b7} Enter \u{b7} Esc close ")
            .border_style(Style::default().fg(app.agent_mode.accent_color())),
    );
    frame.render_widget(list, popup);
}

fn draw_help_overlay(frame: &mut Frame, app: &App, area: Rect) {
    let popup = centered_rect(75, 80, area);
    frame.render_widget(Clear, popup);

    let lines = vec![
        Line::from(Span::styled(
            "  Keyboard Shortcuts",
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )),
        Line::raw(""),
        Line::from(vec![Span::styled(
            "  Navigation",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )]),
        Line::from(vec![
            Span::styled("  Tab          ", Style::default().fg(Color::Cyan)),
            Span::raw("Cycle agent mode (code → explore → research → plan)"),
        ]),
        Line::from(vec![
            Span::styled("  ↑ ↓          ", Style::default().fg(Color::Cyan)),
            Span::raw("Scroll conversation"),
        ]),
        Line::from(vec![
            Span::styled("  PgUp/PgDn    ", Style::default().fg(Color::Cyan)),
            Span::raw("Scroll faster"),
        ]),
        Line::from(vec![
            Span::styled("  End          ", Style::default().fg(Color::Cyan)),
            Span::raw("Scroll to bottom (auto-scroll)"),
        ]),
        Line::from(vec![
            Span::styled("  Right-click  ", Style::default().fg(Color::Cyan)),
            Span::raw("Context menu (copy, search, clear...)"),
        ]),
        Line::from(vec![
            Span::styled("  Scroll wheel ", Style::default().fg(Color::Cyan)),
            Span::raw("Scroll conversation"),
        ]),
        Line::raw(""),
        Line::from(vec![Span::styled(
            "  Input",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )]),
        Line::from(vec![
            Span::styled("  Enter        ", Style::default().fg(Color::Cyan)),
            Span::raw("Send message"),
        ]),
        Line::from(vec![
            Span::styled("  Shift/Alt+Enter ", Style::default().fg(Color::Cyan)),
            Span::raw("New line in message"),
        ]),
        Line::from(vec![
            Span::styled("  Alt+↑ ↓      ", Style::default().fg(Color::Cyan)),
            Span::raw("Navigate message history"),
        ]),
        Line::from(vec![
            Span::styled("  /            ", Style::default().fg(Color::Cyan)),
            Span::raw("Show command picker (filter by typing)"),
        ]),
        Line::from(vec![
            Span::styled("  @            ", Style::default().fg(Color::Cyan)),
            Span::raw("File picker (fuzzy search)"),
        ]),
        Line::raw(""),
        Line::from(vec![Span::styled(
            "  Actions",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )]),
        Line::from(vec![
            Span::styled("  Ctrl+C       ", Style::default().fg(Color::Cyan)),
            Span::raw("Interrupt agent (double: exit)"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+D       ", Style::default().fg(Color::Cyan)),
            Span::raw("Exit"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+F       ", Style::default().fg(Color::Cyan)),
            Span::raw("Search conversation"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+M       ", Style::default().fg(Color::Cyan)),
            Span::raw("Cycle agent mode (code/explore/research/plan)"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+F       ", Style::default().fg(Color::Cyan)),
            Span::raw("Search conversation (type to filter, ↑↓ navigate, Esc close)"),
        ]),
        Line::from(vec![
            Span::styled("  y / n / a    ", Style::default().fg(Color::Cyan)),
            Span::raw("Approve/Deny (when permission prompt shown)"),
        ]),
        Line::raw(""),
        Line::from(vec![Span::styled(
            "  Commands",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )]),
        Line::from(vec![
            Span::styled("  /help        ", Style::default().fg(Color::DarkGray)),
            Span::raw("List all commands"),
        ]),
        Line::from(vec![
            Span::styled("  /model <m>   ", Style::default().fg(Color::DarkGray)),
            Span::raw("Switch model"),
        ]),
        Line::from(vec![
            Span::styled("  /mcp         ", Style::default().fg(Color::DarkGray)),
            Span::raw("List MCP servers"),
        ]),
        Line::from(vec![
            Span::styled("  /analytics   ", Style::default().fg(Color::DarkGray)),
            Span::raw("Session analytics"),
        ]),
        Line::from(vec![
            Span::styled("  /doctor      ", Style::default().fg(Color::DarkGray)),
            Span::raw("Health check"),
        ]),
        Line::raw(""),
        Line::from(Span::styled(
            "  Press ? or Esc to close",
            Style::default().fg(Color::DarkGray),
        )),
    ];

    let block = Block::bordered()
        .title(" Help — Atelier TUI ")
        .border_style(Style::default().fg(app.agent_mode.accent_color()));
    let para = Paragraph::new(lines)
        .block(block)
        .wrap(Wrap { trim: false });
    frame.render_widget(para, popup);
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
    let para = Paragraph::new(lines)
        .block(block)
        .wrap(Wrap { trim: false });
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
    let para = Paragraph::new(lines)
        .block(block)
        .wrap(Wrap { trim: false });
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
            // Use up to most of the available height above the input.
            let max_visible = (anchor.y.saturating_sub(2) as usize)
                .max(4)
                .min(commands.len());
            let offset = if *selected >= max_visible {
                selected - max_visible + 1
            } else {
                0
            };

            let popup_h = (max_visible.min(commands.len()) + 2) as u16;
            let popup_y = anchor.y.saturating_sub(popup_h);
            let popup = Rect {
                x: anchor.x,
                y: popup_y,
                width: anchor.width,
                height: popup_h,
            };
            frame.render_widget(Clear, popup);

            let visible_commands: Vec<_> = commands
                .iter()
                .skip(offset)
                .take(max_visible)
                .enumerate()
                .collect();

            let items: Vec<ListItem> = visible_commands
                .iter()
                .map(|(i, (name, desc))| {
                    let abs_idx = i + offset;
                    let is_selected = abs_idx == *selected;
                    let bg = if is_selected {
                        app.agent_mode.accent_color()
                    } else {
                        Color::Reset
                    };
                    let fg = if is_selected {
                        Color::Black
                    } else {
                        Color::White
                    };
                    let dfg = if is_selected {
                        Color::Black
                    } else {
                        Color::DarkGray
                    };
                    ListItem::new(Line::from(vec![
                        Span::styled(format!("  /{name:<18}"), Style::default().fg(fg).bg(bg)),
                        Span::styled(format!(" {desc}"), Style::default().fg(dfg).bg(bg)),
                    ]))
                })
                .collect();

            let scroll_hint = if commands.len() > max_visible {
                format!(" {}/{} ↑↓ ", selected + 1, commands.len())
            } else {
                format!(" {} ", commands.len())
            };
            let title = format!(" Commands{scroll_hint}");

            let list = List::new(items).block(
                Block::bordered()
                    .title(title.as_str())
                    .border_style(Style::default().fg(app.agent_mode.accent_color())),
            );
            frame.render_widget(list, popup);
        }
        CompletionMode::FileRef {
            selected, filter, ..
        } => {
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
            let visible_files: Vec<_> = files
                .iter()
                .skip(offset)
                .take(visible)
                .enumerate()
                .collect();

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
                    let bg = if is_selected {
                        Color::Yellow
                    } else {
                        Color::Reset
                    };
                    let fg = if is_selected {
                        Color::Black
                    } else {
                        Color::White
                    };
                    let recent_marker = if is_recent { "★ " } else { "  " };
                    let ext_badge = format!("[{ext:>4}]");

                    ListItem::new(Line::from(vec![
                        Span::styled(
                            recent_marker.to_string(),
                            Style::default().fg(Color::Yellow).bg(bg),
                        ),
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
                Line::from(Span::styled(
                    l.to_string(),
                    Style::default().fg(Color::Green),
                ))
            } else if l.starts_with('-') && !l.starts_with("---") {
                Line::from(Span::styled(l.to_string(), Style::default().fg(Color::Red)))
            } else if l.starts_with("@@") {
                Line::from(Span::styled(
                    l.to_string(),
                    Style::default().fg(Color::Cyan),
                ))
            } else {
                Line::from(Span::raw(l.to_string()))
            }
        })
        .collect();

    let block = Block::bordered()
        .title(" Proposed Changes — press 'a' to apply, 'd' to dismiss ")
        .border_style(Style::default().fg(Color::Yellow));
    let paragraph = Paragraph::new(lines)
        .block(block)
        .wrap(Wrap { trim: false });
    frame.render_widget(paragraph, popup_area);
}

fn draw_conversation_content(frame: &mut Frame, app: &mut App, area: Rect) {
    use crate::highlight::render_markdown_lines;

    if app.conversation.is_empty() && !app.is_streaming {
        let agent_color = app.agent_mode.accent_color();
        let project_name = app
            .project_root
            .trim_end_matches('/')
            .rsplit('/')
            .next()
            .unwrap_or("project");
        let logo_lines = [
            "  ┌─────────────────────────────────────────────────┐",
            "  │  ◆  ATELIER  —  Agent Coding Workspace          │",
            "  └─────────────────────────────────────────────────┘",
        ];

        let mut welcome_lines: Vec<Line> = vec![
            Line::raw(""),
            Line::from(Span::styled(logo_lines[0], Style::default().fg(agent_color))),
            Line::from(Span::styled(
                logo_lines[1],
                Style::default().fg(agent_color).add_modifier(Modifier::BOLD),
            )),
            Line::from(Span::styled(logo_lines[2], Style::default().fg(agent_color))),
            Line::raw(""),
            Line::from(vec![
                Span::styled("  Project   ", Style::default().fg(Color::DarkGray)),
                Span::styled(
                    project_name.to_string(),
                    Style::default().fg(Color::White).add_modifier(Modifier::BOLD),
                ),
                if !app.git_branch.is_empty() {
                    Span::styled(
                        format!("  [{}]", app.git_branch),
                        Style::default().fg(agent_color),
                    )
                } else {
                    Span::raw("")
                },
            ]),
            Line::from(vec![
                Span::styled("  Model     ", Style::default().fg(Color::DarkGray)),
                Span::styled(
                    if app.current_model.is_empty() {
                        "not set — /model or /auth".to_string()
                    } else {
                        app.current_model
                            .rsplit('/')
                            .next()
                            .unwrap_or(&app.current_model)
                            .to_string()
                    },
                    Style::default().fg(agent_color),
                ),
            ]),
            Line::from(vec![
                Span::styled("  Agent     ", Style::default().fg(Color::DarkGray)),
                Span::styled(
                    app.agent_mode.name().to_string(),
                    Style::default().fg(agent_color).add_modifier(Modifier::BOLD),
                ),
                Span::styled(" (Tab to cycle)", Style::default().fg(Color::DarkGray)),
            ]),
            Line::raw(""),
        ];

        if let Some(ref url) = app.tunnel_url {
            welcome_lines.push(Line::from(vec![
                Span::styled("  Access    ", Style::default().fg(Color::DarkGray)),
                Span::styled(
                    url.clone(),
                    Style::default().fg(Color::Green).add_modifier(Modifier::BOLD),
                ),
            ]));
        } else if let Some(port) = app.web_port {
            welcome_lines.push(Line::from(vec![
                Span::styled("  Web       ", Style::default().fg(Color::DarkGray)),
                Span::styled(
                    format!("http://localhost:{port}"),
                    Style::default().fg(Color::DarkGray),
                ),
            ]));
            welcome_lines.push(Line::from(Span::styled(
                "  \u{27f3} Tunnel starting... (cloudflared / bore)",
                Style::default().fg(Color::Yellow),
            )));
        }

        if !app.qr_lines.is_empty() {
            welcome_lines.push(Line::raw(""));
            for qr_line in &app.qr_lines {
                welcome_lines.push(Line::from(Span::styled(
                    format!("     {qr_line}"),
                    Style::default().fg(Color::White),
                )));
            }
        }

        welcome_lines.push(Line::raw(""));
        welcome_lines.push(Line::from(Span::styled(
            "  Type a message to start · /help for commands · /agents to switch mode",
            Style::default().fg(Color::DarkGray),
        )));
        welcome_lines.push(Line::raw(""));
        frame.render_widget(Paragraph::new(welcome_lines), area);
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
                all_lines.push(Line::from(vec![
                    Span::styled("▌ ", Style::default().fg(Color::Green)),
                    Span::styled(
                        "You",
                        match_marker.unwrap_or_else(|| {
                            Style::default()
                                .fg(Color::Green)
                                .add_modifier(Modifier::BOLD)
                        }),
                    ),
                ]));
                for line in entry.text.lines() {
                    all_lines.push(Line::from(vec![
                        Span::styled("▌ ", Style::default().fg(Color::Green)),
                        Span::styled(line.to_string(), Style::default().fg(Color::White)),
                    ]));
                }
                all_lines.push(Line::raw(""));
            }
            Role::Assistant => {
                let accent = app.agent_mode.accent_color();
                all_lines.push(Line::from(vec![
                    Span::styled("▌ ", Style::default().fg(accent)),
                    Span::styled(
                        "Atelier",
                        match_marker.unwrap_or_else(|| {
                            Style::default().fg(accent).add_modifier(Modifier::BOLD)
                        }),
                    ),
                ]));
                for mut hl_line in render_markdown_lines(&entry.text) {
                    let mut spans = vec![Span::styled("▌ ", Style::default().fg(accent))];
                    spans.extend(hl_line.spans.drain(..));
                    all_lines.push(Line::from(spans));
                }
                all_lines.push(Line::raw(""));
            }
            Role::System => {
                all_lines.push(Line::from(Span::styled(
                    format!("  ◆ {}", entry.text),
                    match_marker.unwrap_or_else(|| Style::default().fg(Color::DarkGray)),
                )));
                // Render the QR code inline right after the public tunnel URL message.
                if entry.text.contains("http") && !app.qr_lines.is_empty() {
                    if let Some(ref url) = app.tunnel_url {
                        if entry.text.contains(url.as_str()) {
                            all_lines.push(Line::raw(""));
                            for qr_line in &app.qr_lines {
                                all_lines.push(Line::from(Span::styled(
                                    format!("    {qr_line}"),
                                    Style::default().fg(Color::White),
                                )));
                            }
                            all_lines.push(Line::raw(""));
                        }
                    }
                }
            }
        }
    }

    if app.is_streaming && !app.streaming_text.is_empty() {
        let accent = app.agent_mode.accent_color();
        all_lines.push(Line::from(vec![
            Span::styled("▌ ", Style::default().fg(accent)),
            Span::styled(
                "Atelier",
                Style::default().fg(accent).add_modifier(Modifier::BOLD),
            ),
        ]));
        for mut hl_line in render_markdown_lines(&app.streaming_text) {
            let mut spans = vec![Span::styled("▌ ", Style::default().fg(accent))];
            spans.extend(hl_line.spans.drain(..));
            all_lines.push(Line::from(spans));
        }
    }

    // Compact inline tool timeline: show the last few tool calls below the stream.
    if !app.tools.is_empty() {
        for tool in app.tools.iter().rev().take(5).rev() {
            let (icon, color) = match tool.status {
                ToolStatus::Requested => ("\u{25cc}", Color::DarkGray),
                ToolStatus::Running => ("\u{27f3}", Color::Yellow),
                ToolStatus::Done => ("\u{2713}", Color::Green),
                ToolStatus::Failed => ("\u{2717}", Color::Red),
            };
            let detail = tool
                .output_preview
                .as_deref()
                .map(|p| p.trim())
                .filter(|p| !p.is_empty())
                .unwrap_or("");
            all_lines.push(Line::from(vec![
                Span::styled(format!("  {icon} "), Style::default().fg(color)),
                Span::styled(tool.name.clone(), Style::default().fg(Color::Gray)),
                Span::styled(
                    if detail.is_empty() {
                        String::new()
                    } else {
                        format!("  {detail}")
                    },
                    Style::default().fg(Color::DarkGray),
                ),
            ]));
        }
    }

    let content_height = all_lines.len() as u16;
    let visible_height = area.height;
    let max_scroll = content_height.saturating_sub(visible_height);
    let scroll = if app.auto_scroll {
        max_scroll
    } else {
        app.scroll.min(max_scroll)
    };
    app.scroll = scroll;

    let paragraph = Paragraph::new(all_lines)
        .wrap(Wrap { trim: false })
        .scroll((scroll, 0));
    frame.render_widget(paragraph, area);
}

fn draw_input(frame: &mut Frame, app: &mut App, area: Rect) {
    let accent = app.agent_mode.accent_color();
    if let Some(rs) = app.reverse_search.as_ref() {
        let input_title = if rs.matches.is_empty() {
            format!(" reverse-search: '{}' (no matches) ", rs.query)
        } else {
            format!(
                " reverse-search: '{}' ({}/{}) ",
                rs.query,
                rs.current + 1,
                rs.matches.len()
            )
        };
        let block = Block::bordered()
            .border_type(BorderType::Rounded)
            .title(input_title)
            .border_style(Style::default().fg(accent));
        app.input.set_block(block);
    } else {
        // Left side of input shows ◆ (atelier icon) instead of mode slug
        let block = Block::bordered()
            .border_type(BorderType::Rounded)
            .border_style(Style::default().fg(accent))
            .title(Line::from(vec![
                Span::styled(
                    " ◆ ",
                    Style::default().fg(accent).add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    "Type a message or /command",
                    Style::default().fg(Color::DarkGray),
                ),
            ]));
        app.input.set_block(block);
    }
    frame.render_widget(&app.input, area);
}

fn draw_status_bar(frame: &mut Frame, app: &App, area: Rect) {
    let accent = app.agent_mode.accent_color();
    let mode_badge = format!("[{}]", app.agent_mode.name());

    // Short model name — take last segment after /
    let model_text = if app.current_model.is_empty() {
        " /model to set".to_string()
    } else {
        let short = app.current_model.split('/').last().unwrap_or(&app.current_model);
        format!(" {}", short.chars().take(25).collect::<String>())
    };

    let cache = app
        .cache_efficiency
        .filter(|&v| v > 0.0)
        .map(|v| format!(" │ cache {v:.0}%"))
        .unwrap_or_default();

    let cost = if app.total_cost_usd > 0.001 {
        format!(" │ ${:.4}", app.total_cost_usd)
    } else {
        String::new()
    };

    let saved = if app.total_savings_usd > 0.001 {
        format!(" │ saved ${:.4}", app.total_savings_usd)
    } else {
        String::new()
    };

    let turns = if app.conversation.len() > 1 {
        format!(" │ {} turns", app.conversation.len() / 2)
    } else {
        String::new()
    };

    let line = Line::from(vec![
        Span::styled(
            format!(" {mode_badge}"),
            Style::default().fg(accent).add_modifier(Modifier::BOLD),
        ),
        Span::styled(model_text, Style::default().fg(Color::DarkGray)),
        Span::styled(cache, Style::default().fg(Color::DarkGray)),
        Span::styled(cost, Style::default().fg(Color::DarkGray)),
        Span::styled(saved, Style::default().fg(Color::Green)),
        Span::styled(turns, Style::default().fg(Color::DarkGray)),
        Span::styled(" │ ? help", Style::default().fg(Color::DarkGray)),
    ]);
    let para = Paragraph::new(line);
    frame.render_widget(para, area);
}

fn draw_api_key_setup(frame: &mut Frame, app: &App, area: Rect) {
    let popup = centered_rect(70, 60, area);
    frame.render_widget(Clear, popup);

    let lines = vec![
        Line::raw(""),
        Line::from(Span::styled(
            "  ⚠  No API key configured",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
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
    let para = Paragraph::new(lines)
        .block(block)
        .wrap(Wrap { trim: false });
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
            Style::default()
                .fg(border_color)
                .add_modifier(Modifier::BOLD),
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
