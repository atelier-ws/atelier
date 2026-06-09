//! Rendering for the Atelier TUI: 3-pane layout + permission overlay.

use crate::app::{
    ActiveOverlay, App, CompletionMode, FocusedPane, LeftTab, PendingPermission, RightTab, Role,
    TabContent, TaskStatus, ToolStatus,
};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, Clear, Gauge, List, ListItem, ListState, Paragraph, Tabs, Wrap};
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

    let left_w = if app.left_hidden { 0 } else { 25 };
    let right_w = if app.right_hidden { 0 } else { 25 };
    let mid_w = 100 - left_w - right_w;

    let input_line_count = app.input.lines().len().max(1) as u16;
    let input_height = input_line_count.min(5) + 2; // +2 for border, max 5 lines

    // Vertical: content + input + status
    let vertical = Layout::vertical([
        Constraint::Min(0),               // content row
        Constraint::Length(input_height), // input
        Constraint::Length(1),            // status bar
    ])
    .split(area);

    let content_horizontal = Layout::horizontal([
        Constraint::Percentage(left_w),
        Constraint::Percentage(mid_w),
        Constraint::Percentage(right_w),
    ])
    .split(vertical[0]);

    // Reset tab hit-test areas each frame; pane drawers repopulate them.
    app.tab_click_areas = Some(Vec::new());

    if !app.left_hidden {
        draw_left_pane(frame, app, content_horizontal[0]);
    }

    draw_middle_pane(frame, app, content_horizontal[1]);

    if !app.right_hidden {
        let right_split = Layout::vertical([
            Constraint::Percentage(70),
            Constraint::Percentage(30),
        ])
        .split(content_horizontal[2]);
        draw_right_top_pane(frame, app, right_split[0]);
        draw_context_pane(frame, app, right_split[1]);
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
        ActiveOverlay::ModelPicker { selected, models } => {
            draw_model_picker(frame, app, *selected, models, area)
        }
        ActiveOverlay::AuthPicker { selected, providers } => {
            draw_auth_picker(frame, app, *selected, providers, area)
        }
    }
}

fn draw_left_pane(frame: &mut Frame, app: &mut App, area: Rect) {
    let tab_titles: Vec<Line> = vec![
        Line::from(" Sessions "),
        Line::from(" Files "),
        Line::from(" Git "),
    ];
    let selected = match app.left_tab {
        LeftTab::Sessions => 0,
        LeftTab::Files => 1,
        LeftTab::Git => 2,
    };

    let layout = Layout::vertical([Constraint::Length(1), Constraint::Min(0)]).split(area);

    // Record tab hit-test areas (three equal-width slots across the tab row).
    if let Some(ref mut areas) = app.tab_click_areas {
        let tab_w = (layout[0].width / 3).max(1);
        areas.push((
            "left_sessions".to_string(),
            Rect { x: layout[0].x, y: layout[0].y, width: tab_w, height: 1 },
        ));
        areas.push((
            "left_files".to_string(),
            Rect { x: layout[0].x + tab_w, y: layout[0].y, width: tab_w, height: 1 },
        ));
        areas.push((
            "left_git".to_string(),
            Rect { x: layout[0].x + tab_w * 2, y: layout[0].y, width: tab_w, height: 1 },
        ));
    }

    let tabs = Tabs::new(tab_titles)
        .select(selected)
        .style(Style::default().fg(Color::DarkGray))
        .highlight_style(
            Style::default()
                .fg(app.agent_mode.accent_color())
                .add_modifier(Modifier::BOLD),
        )
        .divider(" ");
    frame.render_widget(tabs, layout[0]);

    let block = Block::bordered().border_style(Style::default().fg(border_color(
        app,
        FocusedPane::Sessions,
    )));
    let inner = block.inner(layout[1]);
    frame.render_widget(block, layout[1]);

    match app.left_tab {
        LeftTab::Sessions => draw_sessions_content(frame, app, inner),
        LeftTab::Files => draw_files_content(frame, app, inner),
        LeftTab::Git => draw_git_content(frame, app, inner),
    }
}

fn draw_files_content(frame: &mut Frame, app: &App, area: Rect) {
    let gitignore_patterns = load_gitignore_patterns(&app.project_root);

    let all_files = crate::collect_repo_files(&app.project_root);
    let files: Vec<&String> = all_files
        .iter()
        .filter(|f| !is_gitignored(f, &gitignore_patterns))
        .filter(|f| {
            app.file_filter.is_empty()
                || f.to_lowercase().contains(&app.file_filter.to_lowercase())
        })
        .collect();

    let visible = area.height as usize;
    let offset = (app.files_scroll as usize).min(files.len().saturating_sub(1).max(0));

    let display: Vec<Line> = files
        .iter()
        .skip(offset)
        .take(visible)
        .map(|f| {
            let ext = f.split('.').next_back().unwrap_or("");
            let (icon, color) = file_icon_color(ext);
            Line::from(vec![
                Span::styled(format!("  {icon} "), Style::default().fg(color)),
                Span::styled(f.to_string(), Style::default().fg(Color::White)),
            ])
        })
        .collect();

    let para = Paragraph::new(display);
    frame.render_widget(para, area);
}

fn file_icon_color(ext: &str) -> (&'static str, Color) {
    match ext {
        "py" => ("\u{1f40d}", Color::Yellow),
        "rs" => ("\u{1f980}", Color::Red),
        "ts" | "tsx" => ("\u{1f4d8}", Color::Cyan),
        "js" | "jsx" => ("\u{1f4d2}", Color::Yellow),
        "md" => ("\u{1f4dd}", Color::White),
        "json" => ("\u{1f4cb}", Color::Green),
        "toml" | "yaml" | "yml" => ("\u{2699}\u{fe0f} ", Color::Green),
        "sh" => ("\u{1f4bb}", Color::Green),
        "html" => ("\u{1f310}", Color::Red),
        "css" => ("\u{1f3a8}", Color::Cyan),
        _ => ("\u{1f4c4}", Color::Gray),
    }
}

fn load_gitignore_patterns(root: &str) -> Vec<String> {
    let gitignore = std::path::Path::new(root).join(".gitignore");
    if !gitignore.exists() {
        return vec![];
    }
    std::fs::read_to_string(gitignore)
        .unwrap_or_default()
        .lines()
        .filter(|l| !l.starts_with('#') && !l.trim().is_empty())
        .map(|l| l.trim().to_string())
        .collect()
}

fn is_gitignored(path: &str, patterns: &[String]) -> bool {
    let path_lower = path.to_lowercase();
    patterns.iter().any(|p| {
        let p_lower = p.to_lowercase().trim_end_matches('/').to_string();
        if p_lower.is_empty() {
            return false;
        }
        path_lower.contains(&p_lower) || path_lower.starts_with(&p_lower)
    })
}

fn draw_git_content(frame: &mut Frame, app: &App, area: Rect) {
    if app.git_status.is_empty() {
        let para = Paragraph::new(Span::styled(
            "  Working tree clean",
            Style::default().fg(Color::DarkGray),
        ));
        frame.render_widget(para, area);
        return;
    }
    let items: Vec<Line> = app
        .git_status
        .iter()
        .skip(app.git_scroll as usize)
        .take(area.height as usize)
        .map(|f| {
            let color = match f.status.as_str() {
                "M" => Color::Yellow,
                "A" | "AM" => Color::Green,
                "D" => Color::Red,
                "?" | "??" => Color::DarkGray,
                _ => Color::White,
            };
            Line::from(vec![
                Span::styled(format!(" {:2} ", f.status), Style::default().fg(color)),
                Span::styled(f.path.clone(), Style::default().fg(Color::White)),
            ])
        })
        .collect();
    let para = Paragraph::new(items);
    frame.render_widget(para, area);
}

fn draw_middle_pane(frame: &mut Frame, app: &mut App, area: Rect) {
    let tab_titles: Vec<Line> = app
        .middle_tabs
        .iter()
        .map(|t| {
            let title = t.title();
            let close = if t.closeable() { " \u{00d7}" } else { "" };
            Line::from(format!(" {title}{close} "))
        })
        .collect();

    let layout = Layout::vertical([Constraint::Length(1), Constraint::Min(0)]).split(area);

    // Record middle tab hit-test areas, advancing x by each rendered title width.
    if let Some(ref mut areas) = app.tab_click_areas {
        let mut x = layout[0].x;
        for (idx, line) in tab_titles.iter().enumerate() {
            let w = line.width() as u16;
            areas.push((
                format!("middle_{idx}"),
                Rect { x, y: layout[0].y, width: w, height: 1 },
            ));
            // +1 for the divider rendered between tabs.
            x = x.saturating_add(w).saturating_add(1);
        }
    }

    let tabs = Tabs::new(tab_titles)
        .select(app.middle_tab_idx)
        .style(Style::default().fg(Color::DarkGray))
        .highlight_style(
            Style::default()
                .fg(app.agent_mode.accent_color())
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(tabs, layout[0]);

    let content_area = layout[1];
    let block = Block::bordered().border_style(Style::default().fg(border_color(
        app,
        FocusedPane::Conversation,
    )));
    let inner = block.inner(content_area);
    frame.render_widget(block, content_area);

    match app.middle_tabs.get(app.middle_tab_idx).cloned() {
        Some(TabContent::Conversation) => draw_conversation_content(frame, app, inner),
        Some(TabContent::FileView(path)) => {
            let scroll = app
                .middle_tab_scroll
                .get(app.middle_tab_idx)
                .copied()
                .unwrap_or(0);
            draw_file_content(frame, path, scroll, inner)
        }
        Some(TabContent::DiffView(_, diff)) => draw_side_by_side_diff(frame, diff, inner),
        None => {}
    }
}

fn draw_file_content(frame: &mut Frame, path: String, scroll: u16, area: Rect) {
    let content =
        std::fs::read_to_string(&path).unwrap_or_else(|e| format!("Error reading {path}: {e}"));
    let ext = path.split('.').next_back().unwrap_or("");
    let lines: Vec<Line> = content
        .lines()
        .enumerate()
        .map(|(i, l)| {
            let mut spans = vec![Span::styled(
                format!("{:4} \u{2502} ", i + 1),
                Style::default().fg(Color::DarkGray),
            )];
            spans.extend(highlight_line(l, ext));
            Line::from(spans)
        })
        .collect();
    let para = Paragraph::new(lines)
        .scroll((scroll, 0))
        .wrap(Wrap { trim: false });
    frame.render_widget(para, area);
}

fn highlight_line(line: &str, ext: &str) -> Vec<Span<'static>> {
    let keywords_color: Option<(&[&str], Color)> = match ext {
        "py" => Some((
            &[
                "def ", "class ", "import ", "from ", "return ", "if ", "else:", "elif ", "for ",
                "while ", "with ", "async ", "await ", "lambda ", "yield ",
            ],
            Color::Cyan,
        )),
        "rs" => Some((
            &[
                "fn ", "let ", "mut ", "pub ", "use ", "impl ", "struct ", "enum ", "trait ",
                "async ", "await ", "match ", "if ", "else ", "for ", "while ", "return ", "mod ",
            ],
            Color::Cyan,
        )),
        "ts" | "js" => Some((
            &[
                "function ", "const ", "let ", "var ", "class ", "import ", "export ", "return ",
                "if ", "else ", "for ", "while ", "async ", "await ", "new ",
            ],
            Color::Cyan,
        )),
        _ => None,
    };

    let comment_prefix = match ext {
        "py" | "sh" | "yaml" | "toml" => "#",
        "rs" | "ts" | "js" | "cpp" | "c" => "//",
        _ => "",
    };

    let trimmed = line.trim_start();

    if !comment_prefix.is_empty() && trimmed.starts_with(comment_prefix) {
        return vec![Span::styled(
            line.to_string(),
            Style::default().fg(Color::DarkGray),
        )];
    }

    if let Some((keywords, kw_color)) = keywords_color {
        for kw in keywords {
            if trimmed.starts_with(kw) {
                let indent_len = line.len() - trimmed.len();
                let indent = &line[..indent_len];
                return vec![
                    Span::raw(indent.to_string()),
                    Span::styled(kw.to_string(), Style::default().fg(kw_color)),
                    Span::raw(trimmed[kw.len()..].to_string()),
                ];
            }
        }
    }

    if (trimmed.starts_with('"') || trimmed.starts_with('\'')) && trimmed.len() > 1 {
        return vec![Span::styled(
            line.to_string(),
            Style::default().fg(Color::Green),
        )];
    }

    vec![Span::raw(line.to_string())]
}

fn draw_side_by_side_diff(frame: &mut Frame, diff: String, area: Rect) {
    let half_w = area.width / 2;
    let left_area = Rect {
        width: half_w,
        ..area
    };
    let right_area = Rect {
        x: area.x + half_w,
        width: area.width - half_w,
        ..area
    };

    let mut old_lines: Vec<Line> = Vec::new();
    let mut new_lines: Vec<Line> = Vec::new();

    for line in diff.lines() {
        if line.starts_with('-') && !line.starts_with("---") {
            old_lines.push(Line::from(Span::styled(
                line.to_string(),
                Style::default().fg(Color::Red),
            )));
            new_lines.push(Line::raw(""));
        } else if line.starts_with('+') && !line.starts_with("+++") {
            old_lines.push(Line::raw(""));
            new_lines.push(Line::from(Span::styled(
                line.to_string(),
                Style::default().fg(Color::Green),
            )));
        } else if line.starts_with("@@") {
            let span = Span::styled(line.to_string(), Style::default().fg(Color::Cyan));
            old_lines.push(Line::from(span.clone()));
            new_lines.push(Line::from(span));
        } else {
            old_lines.push(Line::raw(line.to_string()));
            new_lines.push(Line::raw(line.to_string()));
        }
    }

    let left_block = Block::bordered()
        .title(" Before ")
        .border_style(Style::default().fg(Color::Red));
    let right_block = Block::bordered()
        .title(" After ")
        .border_style(Style::default().fg(Color::Green));

    frame.render_widget(
        Paragraph::new(old_lines)
            .block(left_block)
            .wrap(Wrap { trim: false }),
        left_area,
    );
    frame.render_widget(
        Paragraph::new(new_lines)
            .block(right_block)
            .wrap(Wrap { trim: false }),
        right_area,
    );
}

fn draw_right_top_pane(frame: &mut Frame, app: &mut App, area: Rect) {
    let tab_titles = [" Tools ", " Tasks ", " Agents "];
    let selected = match app.right_tab {
        RightTab::Tools => 0,
        RightTab::Tasks => 1,
        RightTab::Subagents => 2,
    };

    let layout = Layout::vertical([Constraint::Length(1), Constraint::Min(0)]).split(area);

    if let Some(ref mut areas) = app.tab_click_areas {
        let tab_w = (layout[0].width / 3).max(1);
        areas.push((
            "right_tools".to_string(),
            Rect { x: layout[0].x, y: layout[0].y, width: tab_w, height: 1 },
        ));
        areas.push((
            "right_tasks".to_string(),
            Rect { x: layout[0].x + tab_w, y: layout[0].y, width: tab_w, height: 1 },
        ));
        areas.push((
            "right_agents".to_string(),
            Rect { x: layout[0].x + tab_w * 2, y: layout[0].y, width: tab_w, height: 1 },
        ));
    }

    let tabs = Tabs::new(tab_titles.iter().map(|t| Line::from(*t)).collect::<Vec<_>>())
        .select(selected)
        .style(Style::default().fg(Color::DarkGray))
        .highlight_style(Style::default().fg(app.agent_mode.accent_color()));
    frame.render_widget(tabs, layout[0]);

    let block = Block::bordered().border_style(Style::default().fg(border_color(
        app,
        FocusedPane::Tools,
    )));
    let inner = block.inner(layout[1]);
    frame.render_widget(block, layout[1]);

    match app.right_tab {
        RightTab::Tools => draw_tools_content(frame, app, inner),
        RightTab::Tasks => draw_tasks_content(frame, app, inner),
        RightTab::Subagents => draw_subagents_content(frame, app, inner),
    }
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
            Span::raw("Cycle pane focus (Input → Conversation → Tools)"),
        ]),
        Line::from(vec![
            Span::styled("  ↑ ↓          ", Style::default().fg(Color::Cyan)),
            Span::raw("Scroll focused pane"),
        ]),
        Line::from(vec![
            Span::styled("  PgUp/PgDn    ", Style::default().fg(Color::Cyan)),
            Span::raw("Scroll faster"),
        ]),
        Line::from(vec![
            Span::styled("  End          ", Style::default().fg(Color::Cyan)),
            Span::raw("Scroll to bottom (auto-scroll)"),
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
            Span::styled("  Shift+Enter  ", Style::default().fg(Color::Cyan)),
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
            Span::styled("  Ctrl+L       ", Style::default().fg(Color::Cyan)),
            Span::raw("Clear screen"),
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
        let model_line = if app.current_model.is_empty() {
            "no model configured — type a message to set up".to_string()
        } else {
            app.current_model.clone()
        };
        let welcome_lines = vec![
            Line::raw(""),
            Line::from(Span::styled(
                "  ◆  ATELIER",
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD),
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
        ];
        let mut welcome_lines = welcome_lines;
        if let Some(port) = app.web_port {
            let local_url = format!("http://localhost:{port}");
            welcome_lines.push(Line::from(vec![
                Span::styled("  Web      ", Style::default().fg(Color::DarkGray)),
                Span::styled(local_url, Style::default().fg(Color::Cyan)),
            ]));
            if let Some(ref tunnel_url) = app.tunnel_url {
                welcome_lines.push(Line::from(vec![
                    Span::styled("  Public   ", Style::default().fg(Color::DarkGray)),
                    Span::styled(tunnel_url.clone(), Style::default().fg(Color::Green)),
                ]));
            } else {
                welcome_lines.push(Line::from(Span::styled(
                    "  Tunnel   connecting...",
                    Style::default().fg(Color::DarkGray),
                )));
            }
        }
        welcome_lines.push(Line::raw(""));
        if !app.qr_lines.is_empty() {
            for qr_line in &app.qr_lines {
                welcome_lines.push(Line::from(Span::styled(
                    format!("  {qr_line}"),
                    Style::default().fg(Color::DarkGray),
                )));
            }
            welcome_lines.push(Line::raw(""));
        }
        welcome_lines.push(Line::from(Span::styled(
            "  Type a message to start · /help for commands",
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
                all_lines.push(Line::from(Span::styled(
                    "▶ You".to_string(),
                    match_marker.unwrap_or_else(|| {
                        Style::default()
                            .fg(Color::Green)
                            .add_modifier(Modifier::BOLD)
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
                        Style::default()
                            .fg(Color::Cyan)
                            .add_modifier(Modifier::BOLD)
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
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )));
        for hl_line in render_markdown_lines(&app.streaming_text) {
            all_lines.push(hl_line);
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

fn draw_sessions_content(frame: &mut Frame, app: &App, area: Rect) {
    let mut lines: Vec<Line> = Vec::new();

    let current = if app.session_id.is_empty() {
        "(starting…)".to_string()
    } else {
        let id: String = app.session_id.chars().take(20).collect();
        id
    };
    lines.push(Line::from(vec![
        Span::styled("\u{25cf} ", Style::default().fg(Color::Green)),
        Span::raw(current),
        Span::styled(" (active)", Style::default().fg(Color::DarkGray)),
    ]));
    lines.push(Line::from(Span::styled(
        format!("  Background tasks: {}", app.background_tasks.len()),
        Style::default().fg(Color::DarkGray),
    )));
    for task in &app.background_tasks {
        let (marker, style) = match task.status {
            TaskStatus::Running => ("\u{27f3}", Style::default().fg(Color::Yellow)),
            TaskStatus::Done => ("\u{2713}", Style::default().fg(Color::Green)),
            TaskStatus::Failed => ("\u{2717}", Style::default().fg(Color::Red)),
        };
        lines.push(Line::from(vec![
            Span::styled(format!("   {marker} "), style),
            Span::raw(task.name.clone()),
        ]));
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Past sessions:",
        Style::default().fg(Color::DarkGray),
    )));
    if app.sessions_list.is_empty() {
        for entry in app.session_list.iter().take(8) {
            let id: String = entry.id.chars().take(18).collect();
            lines.push(Line::from(Span::raw(format!("   {id}"))));
        }
    } else {
        for s in app.sessions_list.iter().take(8) {
            let id: String = s.id.chars().take(18).collect();
            lines.push(Line::from(vec![
                Span::raw(format!("   {id}  ")),
                Span::styled(
                    format!("${:.4}", s.cost_usd),
                    Style::default().fg(Color::DarkGray),
                ),
            ]));
        }
    }

    frame.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), area);
}

fn draw_context_pane(frame: &mut Frame, app: &App, area: Rect) {
    let stats = &app.context_stats;
    let block = Block::bordered()
        .title(" Context / Route ")
        .border_style(Style::default().fg(border_color(app, FocusedPane::Context)));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    // Split into a header/info area, a gauge line, and a footer area.
    let rows = Layout::vertical([
        Constraint::Length(3), // provider/model
        Constraint::Length(1), // cache gauge
        Constraint::Min(0),    // rest
    ])
    .split(inner);

    let provider = if stats.provider.is_empty() {
        "—".to_string()
    } else {
        stats.provider.clone()
    };
    let model = if stats.model.is_empty() {
        app.current_model.clone()
    } else {
        stats.model.clone()
    };
    let model_short: String = model.chars().take(28).collect();
    let header = vec![
        Line::from(vec![
            Span::styled(
                "\u{25c6} ",
                Style::default().fg(app.agent_mode.accent_color()),
            ),
            Span::raw(provider),
        ]),
        Line::from(Span::styled(
            format!("  {model_short}"),
            Style::default().fg(Color::DarkGray),
        )),
    ];
    frame.render_widget(Paragraph::new(header), rows[0]);

    let ratio = (stats.cache_efficiency / 100.0).clamp(0.0, 1.0);
    let gauge = Gauge::default()
        .gauge_style(Style::default().fg(app.agent_mode.accent_color()))
        .ratio(ratio)
        .label(format!("Cache {:.0}%", stats.cache_efficiency));
    frame.render_widget(gauge, rows[1]);

    let used_k = (stats.input_tokens + stats.cache_read_tokens) as f64 / 1000.0;
    let mut footer: Vec<Line> = vec![
        Line::from(Span::styled(
            format!("Cost   ${:.4}", stats.total_cost_usd),
            Style::default().fg(Color::DarkGray),
        )),
        Line::from(Span::styled(
            format!("Saved  ${:.4}", stats.total_savings_usd),
            Style::default().fg(Color::DarkGray),
        )),
        Line::from(Span::styled(
            format!("Tokens {used_k:.0}k ({:.0}%)", stats.estimated_context_pct),
            Style::default().fg(Color::DarkGray),
        )),
        Line::from(""),
        Line::from(Span::styled(
            "Memory hits:",
            Style::default().fg(Color::DarkGray),
        )),
    ];
    for hit in &stats.memory_hits {
        footer.push(Line::from(Span::raw(format!(" \u{b7} {hit}"))));
    }
    frame.render_widget(Paragraph::new(footer).wrap(Wrap { trim: false }), rows[2]);
}

fn draw_tools_content(frame: &mut Frame, app: &App, area: Rect) {
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

    let list = List::new(items);

    let mut state = ListState::default();
    let offset = app.tool_scroll as usize;
    *state.offset_mut() = offset;
    if !app.tools.is_empty() {
        state.select(Some(offset.min(app.tools.len().saturating_sub(1))));
    }

    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_tasks_content(frame: &mut Frame, app: &App, area: Rect) {
    if app.background_tasks.is_empty() {
        let para = Paragraph::new(Span::styled(
            "  No background tasks",
            Style::default().fg(Color::DarkGray),
        ));
        frame.render_widget(para, area);
        return;
    }
    let lines: Vec<Line> = app
        .background_tasks
        .iter()
        .map(|task| {
            let (marker, style) = match task.status {
                TaskStatus::Running => ("\u{27f3}", Style::default().fg(Color::Yellow)),
                TaskStatus::Done => ("\u{2713}", Style::default().fg(Color::Green)),
                TaskStatus::Failed => ("\u{2717}", Style::default().fg(Color::Red)),
            };
            Line::from(vec![
                Span::styled(format!(" {marker} "), style),
                Span::raw(task.name.clone()),
            ])
        })
        .collect();
    frame.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), area);
}

fn draw_subagents_content(frame: &mut Frame, app: &App, area: Rect) {
    if app.sessions_list.is_empty() {
        let para = Paragraph::new(Span::styled(
            "  No subagents running",
            Style::default().fg(Color::DarkGray),
        ));
        frame.render_widget(para, area);
        return;
    }
    let lines: Vec<Line> = app
        .sessions_list
        .iter()
        .map(|s| {
            Line::from(vec![
                Span::styled(" \u{25c6} ", Style::default().fg(app.agent_mode.accent_color())),
                Span::raw(s.label.clone()),
            ])
        })
        .collect();
    frame.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), area);
}

fn draw_input(frame: &mut Frame, app: &mut App, area: Rect) {
    let focused = app.focused_pane == FocusedPane::Input;
    let color = if focused {
        Color::Cyan
    } else {
        Color::DarkGray
    };
    let input_title = if let Some(rs) = app.reverse_search.as_ref() {
        if rs.matches.is_empty() {
            format!(" reverse-search: '{}' (no matches) ", rs.query)
        } else {
            format!(
                " reverse-search: '{}' ({}/{}) ",
                rs.query,
                rs.current + 1,
                rs.matches.len()
            )
        }
    } else {
        " atelier> ".to_string()
    };
    let block = Block::bordered()
        .title(input_title)
        .border_style(Style::default().fg(color));
    app.input.set_block(block);
    frame.render_widget(&app.input, area);
}

fn draw_status_bar(frame: &mut Frame, app: &App, area: Rect) {
    let mode_badge = format!("[{}]", app.agent_mode.name());
    let model_text = if app.current_model.is_empty() {
        "no model".to_string()
    } else {
        app.current_model.chars().take(28).collect()
    };
    let cache = app
        .cache_efficiency
        .map(|v| format!(" \u{2502} cache {v:.0}%"))
        .unwrap_or_default();
    let cost = if app.total_cost_usd > 0.0 {
        format!(" \u{2502} ${:.4}", app.total_cost_usd)
    } else {
        String::new()
    };
    let tunnel = match &app.tunnel_url {
        Some(url) => format!(" \u{2502} {}", url.chars().take(35).collect::<String>()),
        None => String::new(),
    };
    let hint = " \u{2502} ?";

    let text = format!(" {mode_badge} {model_text}{cache}{cost}{tunnel}{hint}");
    let para = Paragraph::new(Span::styled(text, Style::default().fg(Color::DarkGray)));
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
