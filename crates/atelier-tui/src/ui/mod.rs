//! Rendering for the Atelier TUI: 3-pane layout + permission overlay.

use crate::app::{
    ActiveOverlay, App, CompletionMode, ContextMenu, FocusedPane, PendingPermission, Role,
    SessionTimelineEntry, ToolStatus, SLASH_COMMANDS,
};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, BorderType, Clear, List, ListItem, Paragraph, Wrap};
use ratatui::Frame;

const SPINNER: &[&str] = &["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SIDE_MIN_WIDTH: u16 = 110;
const SIDE_WIDTH: u16 = 36;

#[allow(dead_code)]
fn border_color(app: &App, pane: FocusedPane) -> Color {
    if app.focused_pane == pane {
        app.agent_mode.accent_color()
    } else {
        Color::DarkGray
    }
}

/// Rounded border for the focused pane, plain (thin) for inactive panes.
#[allow(dead_code)]
fn border_type_for_pane(app: &App, pane: FocusedPane) -> BorderType {
    if app.focused_pane == pane {
        BorderType::Rounded
    } else {
        BorderType::Plain
    }
}

/// Whether the host terminal is known to support OSC-8 hyperlinks.
/// kitty / WezTerm / iTerm2 / VS Code integrated terminal all do.
fn supports_osc8() -> bool {
    if let Ok(tp) = std::env::var("TERM_PROGRAM") {
        let tp = tp.to_lowercase();
        if tp.contains("wezterm") || tp.contains("iterm") || tp.contains("vscode") {
            return true;
        }
    }
    if std::env::var("KITTY_WINDOW_ID").is_ok() {
        return true;
    }
    if let Ok(term) = std::env::var("TERM") {
        if term.contains("kitty") {
            return true;
        }
    }
    false
}

/// Byte offset of the next `http://` / `https://` occurrence in *text*.
fn find_url_start(text: &str) -> Option<usize> {
    let mut from = 0;
    while let Some(rel) = text[from..].find("http") {
        let idx = from + rel;
        if text[idx..].starts_with("http://") || text[idx..].starts_with("https://") {
            return Some(idx);
        }
        from = idx + 4; // "http" is ASCII, so this stays on a char boundary
    }
    None
}

/// Split *text* into spans, rendering `https?://…` URLs as clickable links.
///
/// On terminals with OSC-8 support the URL span carries the
/// `\x1b]8;;URL\x1b\\TEXT\x1b]8;;\x1b\\` escape so the text is clickable; on
/// everything else it falls back to a plain cyan-underlined span.
pub fn render_with_links(text: &str) -> Vec<Span<'static>> {
    let osc8 = supports_osc8();
    let link_style = Style::default()
        .fg(Color::Cyan)
        .add_modifier(Modifier::UNDERLINED);
    let mut spans: Vec<Span<'static>> = Vec::new();
    let mut rest = text;

    while let Some(start) = find_url_start(rest) {
        if start > 0 {
            spans.push(Span::raw(rest[..start].to_string()));
        }
        let tail = &rest[start..];
        let end = tail.find(char::is_whitespace).unwrap_or(tail.len());
        // Trim trailing punctuation that is almost never part of the URL.
        let url = tail[..end].trim_end_matches(|c: char| {
            matches!(c, '.' | ',' | ')' | ']' | '}' | '!' | '?' | ';' | ':' | '"' | '\'')
        });
        if url.is_empty() {
            spans.push(Span::raw(tail[..1].to_string()));
            rest = &tail[1..];
            continue;
        }
        if osc8 {
            spans.push(Span::styled(
                format!("\x1b]8;;{url}\x1b\\{url}\x1b]8;;\x1b\\"),
                link_style,
            ));
        } else {
            spans.push(Span::styled(url.to_string(), link_style));
        }
        rest = &rest[start + url.len()..];
    }
    if !rest.is_empty() {
        spans.push(Span::raw(rest.to_string()));
    }
    if spans.is_empty() {
        spans.push(Span::raw(String::new()));
    }
    spans
}

pub fn draw(frame: &mut Frame, app: &mut App) {
    let area = frame.area();
    app.term_width = area.width;

    if app.needs_api_key {
        draw_api_key_setup(frame, app, area);
        return;
    }

    let input_line_count = app.input.lines().len().max(1) as u16;
    let input_height = input_line_count.min(5) + 2;

    let vertical = Layout::vertical([
        Constraint::Min(0),
        Constraint::Length(input_height),
        Constraint::Length(1),
    ])
    .split(area);

    app.conv_rect = vertical[0];
    app.input_rect = vertical[1];

    // Optional side panel when wide enough
    let show_panel = app.show_side_panel && area.width >= SIDE_MIN_WIDTH;
    if show_panel {
        let horiz = Layout::horizontal([
            Constraint::Min(0),
            Constraint::Length(SIDE_WIDTH),
        ])
        .split(vertical[0]);
        draw_conversation_content(frame, app, horiz[0]);
        draw_side_panel(frame, app, horiz[1]);
    } else {
        draw_conversation_content(frame, app, vertical[0]);
    }

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
        ActiveOverlay::ModelPicker { selected, models, filter } => {
            draw_model_picker(frame, app, *selected, models, filter, area)
        }
        ActiveOverlay::AuthPicker { selected, providers } => {
            draw_auth_picker(frame, app, *selected, providers, area)
        }
        ActiveOverlay::CommandPalette { query, selected } => {
            let q = query.clone();
            let sel = *selected;
            draw_command_palette(frame, app, &q, sel, area);
        }
        ActiveOverlay::SessionTimeline { entries, selected } => {
            draw_session_timeline(frame, app, entries, *selected, area)
        }
        ActiveOverlay::WhichKey {
            leader_pressed,
            pending_keys,
        } => draw_which_key(frame, app, *leader_pressed, pending_keys, area),
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
    filter: &str,
    area: Rect,
) {
    let popup = centered_rect(70, 70, area);
    frame.render_widget(Clear, popup);

    let accent = app.agent_mode.accent_color();
    let filtered = crate::app::filter_grouped_models(models, filter);

    // Build list items: a non-selectable provider header before each group, then
    // each model. `selected` indexes the flat filtered list (headers excluded).
    let mut items: Vec<ListItem> = Vec::new();
    let mut last_provider: Option<String> = None;
    for (i, (model_id, desc)) in filtered.iter().enumerate() {
        let provider = crate::app::model_provider(model_id).to_string();
        if last_provider.as_deref() != Some(provider.as_str()) {
            let label = format!("  \u{2500}\u{2500} {provider} ");
            let pad_len = 44usize.saturating_sub(label.chars().count());
            items.push(ListItem::new(Line::from(Span::styled(
                format!("{label}{}", "\u{2500}".repeat(pad_len)),
                Style::default()
                    .fg(Color::Rgb(90, 95, 130))
                    .add_modifier(Modifier::BOLD),
            ))));
            last_provider = Some(provider);
        }
        let current = model_id == &app.current_model;
        let is_sel = i == selected;
        let bg = if is_sel { accent } else { Color::Reset };
        let fg = if is_sel { Color::Black } else { Color::White };
        let desc_fg = if is_sel { Color::Black } else { Color::DarkGray };
        let star_fg = if is_sel {
            Color::Black
        } else {
            Color::Yellow
        };
        let star = if current { "\u{2605} " } else { "  " };
        // Drop the provider prefix — the group header already shows it.
        let short = model_id.splitn(2, '/').nth(1).unwrap_or(model_id);
        items.push(ListItem::new(Line::from(vec![
            Span::styled(format!("   {star}"), Style::default().fg(star_fg).bg(bg)),
            Span::styled(format!("{short:38} "), Style::default().fg(fg).bg(bg)),
            Span::styled(desc.to_string(), Style::default().fg(desc_fg).bg(bg)),
        ])));
    }
    if filtered.is_empty() {
        items.push(ListItem::new(Line::from(Span::styled(
            "  no models match — Backspace to clear filter",
            Style::default().fg(Color::DarkGray),
        ))));
    }

    let title = if filter.is_empty() {
        " Model Picker  type to filter \u{b7} \u{2191}\u{2193} \u{b7} Enter \u{b7} Esc ".to_string()
    } else {
        format!(
            " Model Picker  filter: {filter}\u{2588}  \u{b7} {} match ",
            filtered.len()
        )
    };
    let list = List::new(items).block(
        Block::bordered()
            .title(title)
            .border_style(Style::default().fg(accent)),
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
            Span::styled("  Ctrl+K       ", Style::default().fg(Color::Cyan)),
            Span::raw("Command palette (fuzzy search all commands)"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+L       ", Style::default().fg(Color::Cyan)),
            Span::raw("Toggle side panel (tools / context stats)"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+X       ", Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)),
            Span::styled("Which-key leader — shows all leader keybindings", Style::default().fg(Color::White)),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+\\       ", Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)),
            Span::styled("Toggle selection mode — ENABLES native terminal text selection", Style::default().fg(Color::White)),
        ]),
        Line::from(vec![
            Span::styled("  Space        ", Style::default().fg(Color::Cyan)),
            Span::raw("Expand/collapse last tool output (in conversation focus)"),
        ]),
        Line::from(vec![
            Span::styled("  e            ", Style::default().fg(Color::Cyan)),
            Span::raw("Expand tool output inline (in conversation focus)"),
        ]),
        Line::from(vec![
            Span::styled("  y            ", Style::default().fg(Color::Cyan)),
            Span::raw("Copy last assistant response (in conversation focus)"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+F       ", Style::default().fg(Color::Cyan)),
            Span::raw("Search conversation (type to filter, ↑↓ navigate, Esc close)"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+M       ", Style::default().fg(Color::Cyan)),
            Span::raw("Cycle agent mode (code/explore/research/plan)"),
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

fn draw_session_timeline(
    frame: &mut Frame,
    app: &App,
    entries: &[SessionTimelineEntry],
    selected: usize,
    area: Rect,
) {
    let accent = app.agent_mode.accent_color();
    let overlay = centered_rect(78, 70, area);
    frame.render_widget(Clear, overlay);

    let mut lines: Vec<Line> = Vec::new();
    if entries.is_empty() {
        lines.push(Line::raw(""));
        lines.push(Line::from(Span::styled(
            "  Loading sessions…",
            Style::default().fg(Color::DarkGray),
        )));
    } else {
        for (i, e) in entries.iter().enumerate() {
            let is_sel = i == selected;
            let (dot_style, text_style, dim_style) = if is_sel {
                (
                    Style::default().fg(Color::Black).bg(accent),
                    Style::default()
                        .fg(Color::Black)
                        .bg(accent)
                        .add_modifier(Modifier::BOLD),
                    Style::default().fg(Color::Black).bg(accent),
                )
            } else {
                (
                    Style::default().fg(accent),
                    Style::default().fg(Color::White),
                    Style::default().fg(Color::DarkGray),
                )
            };
            let summary: String = e.summary.chars().take(40).collect();
            lines.push(Line::from(vec![
                Span::styled("  \u{25cf} ", dot_style),
                Span::styled(format!("{} ", e.id), text_style),
                Span::styled(format!(" {} ", e.timestamp), dim_style),
                Span::styled(format!(" {} msgs ", e.message_count), dim_style),
                Span::styled(summary, dim_style),
            ]));
        }
    }

    let block = Block::bordered()
        .title(" Session Timeline  \u{2191}\u{2193} navigate \u{b7} Enter resume \u{b7} d delete \u{b7} Esc close ")
        .border_style(Style::default().fg(accent));
    let para = Paragraph::new(lines)
        .block(block)
        .wrap(Wrap { trim: false });
    frame.render_widget(para, overlay);
}

fn draw_which_key(
    frame: &mut Frame,
    app: &App,
    leader_pressed: bool,
    pending_keys: &[char],
    area: Rect,
) {
    let accent = app.agent_mode.accent_color();
    let popup = centered_rect(60, 45, area);
    frame.render_widget(Clear, popup);

    let header = if leader_pressed {
        "  Leader key bindings (Ctrl+X + ...)"
    } else {
        "  Leader key bindings"
    };

    let bindings: [(char, &str); 8] = [
        ('n', "New session"),
        ('l', "Session list"),
        ('g', "Session timeline"),
        ('c', "Compact/summarize"),
        ('m', "Model picker"),
        ('a', "Auth/provider"),
        ('b', "Toggle side panel"),
        ('x', "Export conversation"),
    ];

    let mut lines: Vec<Line> = vec![
        Line::from(Span::styled(
            header,
            Style::default().fg(accent).add_modifier(Modifier::BOLD),
        )),
        Line::raw(""),
    ];
    for pair in bindings.chunks(2) {
        let mut spans: Vec<Span> = Vec::new();
        for (key, label) in pair {
            spans.push(Span::styled(
                format!("  {key}  "),
                Style::default().fg(accent).add_modifier(Modifier::BOLD),
            ));
            spans.push(Span::styled(
                format!("{label:<20}"),
                Style::default().fg(Color::White),
            ));
        }
        lines.push(Line::from(spans));
    }
    lines.push(Line::raw(""));
    if !pending_keys.is_empty() {
        let pending: String = pending_keys.iter().collect();
        lines.push(Line::from(Span::styled(
            format!("  pending: {pending}"),
            Style::default().fg(Color::Yellow),
        )));
    }
    lines.push(Line::from(Span::styled(
        "  press a key \u{b7} Esc to cancel",
        Style::default().fg(Color::DarkGray),
    )));

    let block = Block::bordered()
        .title(" Which-key  Ctrl+X leader ")
        .border_style(Style::default().fg(accent));
    let para = Paragraph::new(lines)
        .block(block)
        .wrap(Wrap { trim: false });
    frame.render_widget(para, popup);
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
    let popup_area = centered_rect(85, 75, area);
    frame.render_widget(Clear, popup_area);

    let diff_text = app.pending_diff.as_deref().unwrap_or("");
    let raw_lines: Vec<&str> = diff_text.lines().collect();

    // Diff stats for the title.
    let mut adds = 0usize;
    let mut dels = 0usize;
    for l in &raw_lines {
        if l.starts_with('+') && !l.starts_with("+++") {
            adds += 1;
        } else if l.starts_with('-') && !l.starts_with("---") {
            dels += 1;
        }
    }

    let green_fg = Color::Green;
    let green_bg = Color::Rgb(0, 50, 0);
    let red_fg = Color::Red;
    let red_bg = Color::Rgb(50, 0, 0);
    let gutter_fg = Color::Rgb(70, 75, 100);

    let mut lines: Vec<Line> = Vec::new();

    // Side-by-side style headers.
    lines.push(Line::from(vec![
        Span::styled(
            "  --- old --- ",
            Style::default().fg(red_fg).add_modifier(Modifier::BOLD),
        ),
        Span::styled(
            " +++ new +++ ",
            Style::default().fg(green_fg).add_modifier(Modifier::BOLD),
        ),
    ]));
    lines.push(Line::raw(""));

    let mut old_no = 0usize;
    let mut new_no = 0usize;

    for (i, &line) in raw_lines.iter().enumerate() {
        // The app prepends a "Files: ..." summary line before the raw diff.
        if line.starts_with("Files:") {
            lines.push(Line::from(Span::styled(
                line.to_string(),
                Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
            )));
            continue;
        }
        if line.starts_with("@@") {
            if let Some((o, n)) = parse_hunk_header(line) {
                old_no = o;
                new_no = n;
            }
            lines.push(Line::from(vec![
                Span::styled(DIFF_GUTTER_BLANK.to_string(), Style::default().fg(gutter_fg)),
                Span::styled(line.to_string(), Style::default().fg(Color::Cyan)),
            ]));
            continue;
        }
        if line.starts_with("+++") || line.starts_with("---") {
            lines.push(Line::from(vec![
                Span::styled(DIFF_GUTTER_BLANK.to_string(), Style::default().fg(gutter_fg)),
                Span::styled(
                    line.to_string(),
                    Style::default().fg(Color::DarkGray).add_modifier(Modifier::BOLD),
                ),
            ]));
            continue;
        }
        if let Some(content) = line.strip_prefix('+') {
            // Bold the changed suffix relative to the preceding '-' line, if any.
            let bold_from = i
                .checked_sub(1)
                .and_then(|p| raw_lines.get(p))
                .filter(|prev| prev.starts_with('-') && !prev.starts_with("---"))
                .map(|prev| first_diff_pos(&prev[1..], content));
            let mut spans = vec![Span::styled(diff_gutter(new_no), Style::default().fg(gutter_fg))];
            spans.extend(styled_diff_content(content, '+', green_fg, green_bg, bold_from));
            lines.push(Line::from(spans));
            new_no += 1;
            continue;
        }
        if let Some(content) = line.strip_prefix('-') {
            let bold_from = raw_lines
                .get(i + 1)
                .filter(|next| next.starts_with('+') && !next.starts_with("+++"))
                .map(|next| first_diff_pos(content, &next[1..]));
            let mut spans = vec![Span::styled(diff_gutter(old_no), Style::default().fg(gutter_fg))];
            spans.extend(styled_diff_content(content, '-', red_fg, red_bg, bold_from));
            lines.push(Line::from(spans));
            old_no += 1;
            continue;
        }
        // Context line.
        let content = line.strip_prefix(' ').unwrap_or(line);
        let gutter = if new_no > 0 {
            diff_gutter(new_no)
        } else {
            DIFF_GUTTER_BLANK.to_string()
        };
        lines.push(Line::from(vec![
            Span::styled(gutter, Style::default().fg(gutter_fg)),
            Span::styled(format!("  {content}"), Style::default()),
        ]));
        if old_no > 0 {
            old_no += 1;
        }
        if new_no > 0 {
            new_no += 1;
        }
    }

    let title = format!(" Changes: +{adds} -{dels}  ·  'a' apply · 'd' dismiss ");
    let block = Block::bordered()
        .title(title)
        .border_style(Style::default().fg(Color::Yellow));
    let paragraph = Paragraph::new(lines)
        .block(block)
        .wrap(Wrap { trim: false });
    frame.render_widget(paragraph, popup_area);
}

const DIFF_GUTTER_BLANK: &str = "    \u{2502} ";

/// Render a `  42│ ` style line-number gutter (│ stays aligned with the blank gutter).
fn diff_gutter(n: usize) -> String {
    format!(" {n:>3}\u{2502} ")
}

/// Index of the first character where `a` and `b` differ.
fn first_diff_pos(a: &str, b: &str) -> usize {
    a.chars().zip(b.chars()).take_while(|(x, y)| x == y).count()
}

/// Parse `@@ -old,n +new,n @@` into the 1-based (old_start, new_start) line numbers.
fn parse_hunk_header(line: &str) -> Option<(usize, usize)> {
    let body = line.trim_start_matches('@').trim();
    let mut old_start = None;
    let mut new_start = None;
    for token in body.split_whitespace() {
        if let Some(t) = token.strip_prefix('-') {
            old_start = t.split(',').next().and_then(|n| n.parse::<usize>().ok());
        } else if let Some(t) = token.strip_prefix('+') {
            new_start = t.split(',').next().and_then(|n| n.parse::<usize>().ok());
        }
    }
    match (old_start, new_start) {
        (Some(o), Some(n)) => Some((o, n)),
        _ => None,
    }
}

/// Build colored spans for a `+`/`-` diff line, bolding the changed suffix from `bold_from`.
fn styled_diff_content(
    content: &str,
    sign: char,
    fg: Color,
    bg: Color,
    bold_from: Option<usize>,
) -> Vec<Span<'static>> {
    let base = Style::default().fg(fg).bg(bg);
    let mut spans = vec![Span::styled(format!("{sign} "), base)];
    match bold_from {
        Some(pos) if pos < content.chars().count() => {
            let unchanged: String = content.chars().take(pos).collect();
            let changed: String = content.chars().skip(pos).collect();
            if !unchanged.is_empty() {
                spans.push(Span::styled(unchanged, base));
            }
            spans.push(Span::styled(changed, base.add_modifier(Modifier::BOLD)));
        }
        _ => spans.push(Span::styled(content.to_string(), base)),
    }
    spans
}

/// Hard-wrap text to `width` columns, preserving existing line breaks.
fn wrap_text(text: &str, width: usize) -> Vec<String> {
    let mut out = Vec::new();
    for line in text.lines() {
        let chars: Vec<char> = line.chars().collect();
        if chars.is_empty() {
            out.push(String::new());
            continue;
        }
        let mut start = 0;
        while start < chars.len() {
            let end = (start + width).min(chars.len());
            out.push(chars[start..end].iter().collect());
            start = end;
        }
    }
    out
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
            "  ╭───────────────────────────────────────────────────╮",
            "  │   ◆  A T E L I E R                                 │",
            "  │      Agent Coding Workspace                        │",
            "  ╰───────────────────────────────────────────────────╯",
        ];

        let mut welcome_lines: Vec<Line> = vec![
            Line::raw(""),
            Line::from(Span::styled(logo_lines[0], Style::default().fg(agent_color))),
            Line::from(Span::styled(
                logo_lines[1],
                Style::default().fg(agent_color).add_modifier(Modifier::BOLD),
            )),
            Line::from(Span::styled(
                logo_lines[2],
                Style::default().fg(agent_color),
            )),
            Line::from(Span::styled(logo_lines[3], Style::default().fg(agent_color))),
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
                Span::styled("  (scan below)", Style::default().fg(Color::DarkGray)),
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
            welcome_lines.push(Line::from(Span::styled(
                "  \u{1f4f1} Scan to open on your phone",
                Style::default().fg(Color::Green),
            )));
            for qr_line in &app.qr_lines {
                welcome_lines.push(Line::from(Span::styled(
                    format!("     {qr_line}"),
                    Style::default().fg(Color::White),
                )));
            }
        }

        // Quick-start sample prompts — type the number-tagged prompt to begin.
        let samples = [
            "Explain the architecture of this project",
            "Find and fix a bug in the codebase",
            "Write tests for the module I'm working on",
            "Refactor this file for readability",
        ];
        welcome_lines.push(Line::raw(""));
        welcome_lines.push(Line::from(Span::styled(
            "  Quick start",
            Style::default()
                .fg(Color::White)
                .add_modifier(Modifier::BOLD),
        )));
        for (i, sample) in samples.iter().enumerate() {
            welcome_lines.push(Line::from(vec![
                Span::styled(
                    format!("    {} ", i + 1),
                    Style::default()
                        .fg(agent_color)
                        .add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    format!("\u{203a} {sample}"),
                    Style::default().fg(Color::Gray),
                ),
            ]));
        }

        // Compact two-column keyboard cheat sheet.
        welcome_lines.push(Line::raw(""));
        welcome_lines.push(Line::from(Span::styled(
            "  Shortcuts",
            Style::default()
                .fg(Color::White)
                .add_modifier(Modifier::BOLD),
        )));
        let key_style = Style::default().fg(agent_color);
        let desc_style = Style::default().fg(Color::DarkGray);
        let shortcut_rows: [(&str, &str, &str, &str); 4] = [
            ("Enter", "send", "Ctrl+\\", "selection mode"),
            ("Ctrl+J", "newline", "y", "copy last response"),
            ("Ctrl+K", "commands", "?", "help"),
            ("Ctrl+L", "toggle panel", "", ""),
        ];
        for (lk, ld, rk, rd) in shortcut_rows {
            let mut spans = vec![
                Span::styled(format!("    {lk:<8}"), key_style),
                Span::styled(format!("{ld:<18}"), desc_style),
            ];
            if !rk.is_empty() {
                spans.push(Span::styled(format!("{rk:<8}"), key_style));
                spans.push(Span::styled(rd.to_string(), desc_style));
            }
            welcome_lines.push(Line::from(spans));
        }

        welcome_lines.push(Line::raw(""));
        welcome_lines.push(Line::from(Span::styled(
            "  Type a message to start · /help for commands · /agents to switch mode",
            Style::default().fg(Color::DarkGray),
        )));

        // Debug builds are noticeably slower to start — nudge toward release mode.
        #[cfg(debug_assertions)]
        {
            welcome_lines.push(Line::raw(""));
            welcome_lines.push(Line::from(Span::styled(
                "  \u{26a1} Run 'cargo build --release' for 10\u{d7} faster startup",
                Style::default().fg(Color::Yellow),
            )));
        }

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
        let spinner = SPINNER[app.spinner_tick as usize % SPINNER.len()];
        let elapsed = app.streaming_start
            .map(|s| {
                let ms = s.elapsed().as_millis();
                if ms >= 1000 { format!(" {:.1}s", ms as f64 / 1000.0) } else { format!(" {}ms", ms) }
            })
            .unwrap_or_default();
        all_lines.push(Line::from(vec![
            Span::styled("▌ ", Style::default().fg(accent)),
            Span::styled(
                "Atelier",
                Style::default().fg(accent).add_modifier(Modifier::BOLD),
            ),
            Span::styled(format!(" {spinner}"), Style::default().fg(Color::Yellow)),
            Span::styled(elapsed, Style::default().fg(Color::Rgb(80, 85, 100))),
        ]));
        for mut hl_line in render_markdown_lines(&app.streaming_text) {
            let mut spans = vec![Span::styled("▌ ", Style::default().fg(accent))];
            spans.extend(hl_line.spans.drain(..));
            all_lines.push(Line::from(spans));
        }
    } else if app.is_streaming {
        // Show thinking spinner even when streaming_text is empty (early thinking phase)
        let accent = app.agent_mode.accent_color();
        let spinner = SPINNER[app.spinner_tick as usize % SPINNER.len()];
        let elapsed = app.streaming_start
            .map(|s| format!(" {:.1}s", s.elapsed().as_secs_f64()))
            .unwrap_or_default();
        all_lines.push(Line::from(vec![
            Span::styled("▌ ", Style::default().fg(accent)),
            Span::styled("Atelier ", Style::default().fg(accent).add_modifier(Modifier::BOLD)),
            Span::styled(spinner, Style::default().fg(Color::Yellow)),
            Span::styled(" thinking…", Style::default().fg(Color::Rgb(80, 85, 100))),
            Span::styled(elapsed, Style::default().fg(Color::Rgb(65, 70, 90))),
        ]));
    }

    // Compact inline tool timeline: collapsible tool calls below the stream.
    // Collapsed shows a one-line header; press Space/e in conversation focus to
    // expand the most recent tool's output inline.
    if !app.tools.is_empty() {
        let spinner = SPINNER[app.spinner_tick as usize % SPINNER.len()];
        for tool in app.tools.iter().rev().take(6).rev() {
            let (_icon, color) = match tool.status {
                ToolStatus::Requested => ("◌", Color::DarkGray),
                ToolStatus::Running => (spinner, Color::Yellow),
                ToolStatus::Done => ("✓", Color::Green),
                ToolStatus::Failed => ("✗", Color::Red),
            };
            let elapsed = tool.elapsed_ms
                .map(|ms| {
                    if ms >= 1000 { format!("  {:.1}s", ms as f64 / 1000.0) }
                    else { format!("  {}ms", ms) }
                })
                .or_else(|| {
                    if tool.status == ToolStatus::Running {
                        tool.started_at.map(|s| {
                            let ms = s.elapsed().as_millis();
                            if ms >= 1000 { format!("  {:.1}s…", ms as f64 / 1000.0) }
                            else { format!("  {}ms…", ms) }
                        })
                    } else { None }
                })
                .unwrap_or_default();
            let expanded = app.tool_expanded.contains(&tool.id);
            let has_output = tool
                .output_preview
                .as_deref()
                .map(|p| !p.trim().is_empty())
                .unwrap_or(false);
            let triangle = if expanded { "▼" } else { "▶" };
            let mut header = vec![
                Span::styled(format!("  {triangle} "), Style::default().fg(color)),
                Span::styled(tool.name.clone(), Style::default().fg(Color::Gray)),
                Span::styled(elapsed, Style::default().fg(Color::Rgb(80, 85, 100))),
            ];
            if !expanded && has_output {
                header.push(Span::styled(
                    "  [press Space to expand]".to_string(),
                    Style::default().fg(Color::Rgb(70, 75, 95)),
                ));
            }
            all_lines.push(Line::from(header));

            if expanded {
                if let Some(preview) = tool.output_preview.as_deref() {
                    for wrapped in wrap_text(preview, 80).into_iter().take(10) {
                        all_lines.push(Line::from(vec![
                            Span::raw("      "),
                            Span::styled(wrapped, Style::default().fg(Color::DarkGray)),
                        ]));
                    }
                }
            }
        }
        // Summary line when more tools than visible
        if app.tools.len() > 6 {
            all_lines.push(Line::from(Span::styled(
                format!("  … {} more tool calls", app.tools.len() - 6),
                Style::default().fg(Color::Rgb(70, 75, 95)),
            )));
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
        let mode_indicator = format!(" {} \u{203a} ", app.agent_mode.name());
        let block = Block::bordered()
            .border_type(BorderType::Rounded)
            .border_style(Style::default().fg(accent))
            .title(Line::from(vec![
                Span::styled(
                    mode_indicator,
                    Style::default().fg(accent).add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    "Type a message · Ctrl+J for newline · /command",
                    Style::default().fg(Color::DarkGray),
                ),
            ]));
        app.input.set_block(block);
    }
    frame.render_widget(&app.input, area);
}

fn draw_status_bar(frame: &mut Frame, app: &App, area: Rect) {
    // When in selection mode show a prominent indicator
    if app.selection_mode {
        frame.render_widget(
            Paragraph::new(Line::from(vec![
                Span::styled(
                    " ✂ SELECTION MODE ",
                    Style::default().fg(Color::Black).bg(Color::Yellow).add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    "  click+drag to select text · Ctrl+\\ to exit · y to copy last response",
                    Style::default().fg(Color::Yellow),
                ),
            ])),
            area,
        );
        return;
    }

    let accent = app.agent_mode.accent_color();
    let mode_badge = format!(" {} ›", app.agent_mode.name());

    let model_short = if app.current_model.is_empty() {
        " /model".to_string()
    } else {
        let s = app.current_model.split('/').last().unwrap_or(&app.current_model);
        format!(" {}", &s[..s.len().min(24)])
    };

    let branch = if !app.git_branch.is_empty() {
        format!(" ⎇ {}", &app.git_branch[..app.git_branch.len().min(18)])
    } else {
        String::new()
    };

    // Context bar: tiny progress indicator
    let ctx_pct = app.context_stats.estimated_context_pct;
    let ctx_bar = if ctx_pct > 0.0 {
        let filled = ((ctx_pct / 100.0) * 8.0) as usize;
        let empty = 8usize.saturating_sub(filled);
        let col = if ctx_pct > 85.0 { Color::Red } else if ctx_pct > 65.0 { Color::Yellow } else { Color::Green };
        Some((format!(" │ {}{} {:.0}%", "█".repeat(filled), "░".repeat(empty), ctx_pct), col))
    } else {
        None
    };

    let cache = app.cache_efficiency
        .filter(|&v| v > 0.0)
        .map(|v| format!(" │ ⚡{v:.0}%"))
        .unwrap_or_default();

    let cost = if app.total_cost_usd > 0.001 {
        format!(" │ ${:.4}", app.total_cost_usd)
    } else {
        String::new()
    };

    let saved = if app.total_savings_usd > 0.001 {
        format!(" │ ↓${:.4}", app.total_savings_usd)
    } else {
        String::new()
    };

    let tool_badge = if !app.tools.is_empty() {
        let running = app.tools.iter().filter(|t| t.status == ToolStatus::Running).count();
        let spinner = SPINNER[app.spinner_tick as usize % SPINNER.len()];
        if running > 0 {
            format!(" │ {spinner} {running} running")
        } else {
            format!(" │ ✓ {} tools", app.tools.len())
        }
    } else {
        String::new()
    };

    let panel_hint = if area.width >= SIDE_MIN_WIDTH {
        if app.show_side_panel { " │ Ctrl+L" } else { " │ Ctrl+L panel" }
    } else {
        ""
    };

    let mut spans = vec![
        Span::styled(mode_badge, Style::default().fg(accent).add_modifier(Modifier::BOLD)),
        Span::styled(model_short, Style::default().fg(Color::DarkGray)),
    ];
    if !branch.is_empty() {
        spans.push(Span::styled(branch, Style::default().fg(Color::Rgb(100, 100, 130))));
    }
    if let Some((bar_text, bar_col)) = ctx_bar {
        spans.push(Span::styled(bar_text, Style::default().fg(bar_col)));
    }
    if !cache.is_empty() {
        spans.push(Span::styled(cache, Style::default().fg(Color::Green)));
    }
    if !cost.is_empty() {
        spans.push(Span::styled(cost, Style::default().fg(Color::DarkGray)));
    }
    if !saved.is_empty() {
        spans.push(Span::styled(saved, Style::default().fg(Color::Green).add_modifier(Modifier::BOLD)));
    }
    if !tool_badge.is_empty() {
        let tc = if tool_badge.contains("running") { Color::Yellow } else { Color::Green };
        spans.push(Span::styled(tool_badge, Style::default().fg(tc)));
    }
    spans.push(Span::styled(" │ ? help", Style::default().fg(Color::Rgb(55, 60, 75))));
    spans.push(Span::styled(" │ Ctrl+K cmds", Style::default().fg(Color::Rgb(55, 60, 75))));
    if !panel_hint.is_empty() {
        spans.push(Span::styled(panel_hint.to_string(), Style::default().fg(Color::Rgb(50, 55, 70))));
    }

    frame.render_widget(Paragraph::new(Line::from(spans)), area);
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

// ─────────────────────────────────────────────────────────────────────────────
// Side panel: tools list + context stats
// ─────────────────────────────────────────────────────────────────────────────

fn draw_side_panel(frame: &mut Frame, app: &App, area: Rect) {
    // Split vertically: top = tools, bottom = context stats (8 rows)
    let ctx_height = 9u16;
    let sections = if area.height > ctx_height + 4 {
        Layout::vertical([
            Constraint::Min(0),
            Constraint::Length(ctx_height),
        ])
        .split(area)
    } else {
        // Tiny terminal — just show context
        Layout::vertical([Constraint::Percentage(0), Constraint::Percentage(100)]).split(area)
    };
    draw_tools_panel(frame, app, sections[0]);
    draw_context_panel(frame, app, sections[1]);
}

fn draw_tools_panel(frame: &mut Frame, app: &App, area: Rect) {
    if area.height == 0 {
        return;
    }
    let spinner = SPINNER[app.spinner_tick as usize % SPINNER.len()];
    let accent = app.agent_mode.accent_color();
    let name_w = (area.width as usize).saturating_sub(8).max(4);

    let recent_tools: Vec<_> = app.tools.iter().rev().take(area.height.saturating_sub(2) as usize).collect();
    let mut items: Vec<ListItem> = recent_tools
        .iter()
        .rev()
        .map(|tool| {
            let (icon, color) = match tool.status {
                ToolStatus::Requested => ("◌", Color::DarkGray),
                ToolStatus::Running => (spinner, Color::Yellow),
                ToolStatus::Done => ("✓", Color::Green),
                ToolStatus::Failed => ("✗", Color::Red),
            };
            let elapsed = tool.elapsed_ms
                .map(|ms| if ms >= 1000 { format!(" {:.1}s", ms as f64 / 1000.0) } else { format!(" {}ms", ms) })
                .unwrap_or_default();
            let name: String = tool.name.chars().take(name_w.saturating_sub(elapsed.len())).collect();
            ListItem::new(Line::from(vec![
                Span::styled(format!(" {icon} "), Style::default().fg(color)),
                Span::styled(name, Style::default().fg(Color::Gray)),
                Span::styled(elapsed, Style::default().fg(Color::DarkGray)),
            ]))
        })
        .collect();

    // Show running task count in title
    let running = app.tools.iter().filter(|t| t.status == ToolStatus::Running).count();
    let title = if running > 0 {
        format!(" {} Tools  {spinner} {} running ", app.tools.len(), running)
    } else if app.tools.is_empty() {
        " Tools ".to_string()
    } else {
        format!(" Tools  {} done ", app.tools.len())
    };

    if items.is_empty() {
        items.push(ListItem::new(Line::from(Span::styled(
            "  waiting…",
            Style::default().fg(Color::DarkGray),
        ))));
    }

    // Show background tasks too
    for task in app.background_tasks.iter().rev().take(3) {
        let (icon, color) = match task.status {
            crate::app::TaskStatus::Running => (spinner, Color::Yellow),
            crate::app::TaskStatus::Done => ("✓", Color::Green),
            crate::app::TaskStatus::Failed => ("✗", Color::Red),
        };
        let name: String = task.name.chars().take(name_w).collect();
        items.push(ListItem::new(Line::from(vec![
            Span::styled(format!(" {icon} "), Style::default().fg(color)),
            Span::styled(name, Style::default().fg(Color::DarkGray)),
        ])));
    }

    let border_col = if running > 0 { Color::Yellow } else { Color::Rgb(55, 60, 80) };
    let list = List::new(items).block(
        Block::bordered()
            .title(Span::styled(title, Style::default().fg(accent)))
            .border_style(Style::default().fg(border_col))
            .border_type(BorderType::Plain),
    );
    frame.render_widget(list, area);
}

fn draw_context_panel(frame: &mut Frame, app: &App, area: Rect) {
    if area.height == 0 {
        return;
    }
    let ctx = &app.context_stats;
    let accent = app.agent_mode.accent_color();

    // Context window bar
    let used_pct = ctx.estimated_context_pct.min(100.0);
    let bar_w = (area.width as usize).saturating_sub(6).min(24);
    let filled = ((used_pct / 100.0) * bar_w as f64) as usize;
    let empty = bar_w.saturating_sub(filled);
    let bar_color = if used_pct > 85.0 {
        Color::Red
    } else if used_pct > 65.0 {
        Color::Yellow
    } else {
        Color::Green
    };

    let bar = format!("{}{}", "█".repeat(filled), "░".repeat(empty));

    // Short model name
    let model_short: String = ctx.model
        .rsplit('/')
        .next()
        .unwrap_or(&ctx.model)
        .chars()
        .take((area.width as usize).saturating_sub(4))
        .collect();

    let mut lines = vec![
        Line::from(vec![
            Span::styled("  ", Style::default()),
            Span::styled(bar, Style::default().fg(bar_color)),
            Span::styled(
                format!(" {:.0}%", used_pct),
                Style::default().fg(Color::DarkGray),
            ),
        ]),
    ];

    if !ctx.cache_efficiency.is_nan() && ctx.cache_efficiency > 0.0 {
        lines.push(Line::from(vec![
            Span::styled("  cache  ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                format!("{:.1}%", ctx.cache_efficiency),
                Style::default().fg(Color::Green),
            ),
        ]));
    }
    if ctx.total_cost_usd > 0.0 {
        lines.push(Line::from(vec![
            Span::styled("  cost   ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                format!("${:.4}", ctx.total_cost_usd),
                Style::default().fg(Color::White),
            ),
        ]));
    }
    if ctx.total_savings_usd > 0.001 {
        lines.push(Line::from(vec![
            Span::styled("  saved  ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                format!("${:.4}", ctx.total_savings_usd),
                Style::default().fg(Color::Green).add_modifier(Modifier::BOLD),
            ),
        ]));
    }
    if !model_short.is_empty() {
        lines.push(Line::from(vec![
            Span::styled("  model  ", Style::default().fg(Color::DarkGray)),
            Span::styled(model_short, Style::default().fg(accent)),
        ]));
    }
    if !ctx.memory_hits.is_empty() {
        let hit: String = ctx.memory_hits.last().unwrap().chars().take((area.width as usize).saturating_sub(12)).collect();
        lines.push(Line::from(vec![
            Span::styled("  mem    ", Style::default().fg(Color::DarkGray)),
            Span::styled(hit, Style::default().fg(Color::Magenta)),
        ]));
    }
    // Ctrl+L hint
    lines.push(Line::from(Span::styled(
        "  Ctrl+L hide panel",
        Style::default().fg(Color::Rgb(50, 55, 70)),
    )));

    let para = Paragraph::new(lines).block(
        Block::bordered()
            .title(Span::styled(" Context ", Style::default().fg(accent)))
            .border_style(Style::default().fg(Color::Rgb(55, 60, 80)))
            .border_type(BorderType::Plain),
    );
    frame.render_widget(para, area);
}

// ─────────────────────────────────────────────────────────────────────────────
// Ctrl+K Command Palette
// ─────────────────────────────────────────────────────────────────────────────

fn draw_command_palette(frame: &mut Frame, app: &App, query: &str, selected: usize, area: Rect) {
    let accent = app.agent_mode.accent_color();
    let popup_w = (area.width as f32 * 0.65) as u16;
    let popup_h = 20u16;
    let popup = Rect {
        x: (area.width.saturating_sub(popup_w)) / 2,
        y: (area.height.saturating_sub(popup_h)) / 3,
        width: popup_w,
        height: popup_h,
    };
    frame.render_widget(Clear, popup);

    // Split: search input (3) + results list
    let inner = Layout::vertical([
        Constraint::Length(3),
        Constraint::Min(0),
    ])
    .split(popup);

    // Search box
    let search_block = Block::bordered()
        .border_style(Style::default().fg(accent))
        .border_type(BorderType::Rounded)
        .title(Span::styled(
            " ⌘ Command Palette  Ctrl+K ",
            Style::default().fg(accent).add_modifier(Modifier::BOLD),
        ));
    let search_text = Line::from(vec![
        Span::styled("  ", Style::default()),
        Span::styled(query, Style::default().fg(Color::White)),
        Span::styled("█", Style::default().fg(accent)),
    ]);
    frame.render_widget(
        Paragraph::new(search_text).block(search_block),
        inner[0],
    );

    // Results: slash commands matching query, then recent files
    let q = query.to_lowercase();
    let cmds: Vec<_> = SLASH_COMMANDS
        .iter()
        .filter(|(name, desc)| {
            q.is_empty()
                || name.contains(q.as_str())
                || desc.to_lowercase().contains(q.as_str())
        })
        .take(12)
        .collect();

    let items: Vec<ListItem> = cmds
        .iter()
        .enumerate()
        .map(|(i, (name, desc))| {
            let is_sel = i == selected;
            let bg = if is_sel { accent } else { Color::Reset };
            let fg = if is_sel { Color::Black } else { Color::White };
            let dfg = if is_sel { Color::Black } else { Color::DarkGray };
            ListItem::new(Line::from(vec![
                Span::styled(format!("  /{name:<18} "), Style::default().fg(fg).bg(bg)),
                Span::styled(desc.to_string(), Style::default().fg(dfg).bg(bg)),
            ]))
        })
        .collect();

    let results_block = Block::bordered()
        .border_style(Style::default().fg(Color::Rgb(55, 60, 80)))
        .border_type(BorderType::Plain)
        .title(Span::styled(
            format!(" {} commands ", cmds.len()),
            Style::default().fg(Color::DarkGray),
        ));
    frame.render_widget(List::new(items).block(results_block), inner[1]);
}
