//! Rendering for the Atelier TUI: 3-pane layout + permission overlay.

use crate::app::{
    ActiveOverlay, App, CompletionMode, ContextMenu, FocusedPane, FuzzyFinder, GitRowKind, LeftTab,
    PendingPermission, RightTab, Role, TabContent, TaskStatus, ToolStatus,
};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{
    Block, BorderType, Clear, List, ListItem, ListState, Paragraph, Tabs, Wrap,
};
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

/// Build a styled tab title. The active tab is highlighted via color/bold only;
/// no leading dot (activity dots are prepended to the label by the caller).
fn styled_tab(app: &App, label: &str, id: &str, is_active: bool) -> Line<'static> {
    let text = format!(" {label}");
    let mut style = if is_active {
        Style::default()
            .fg(app.agent_mode.accent_color())
            .add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(Color::DarkGray)
    };
    if app.hovered_tab.as_deref() == Some(id) {
        style = style.add_modifier(Modifier::UNDERLINED);
    }
    Line::from(Span::styled(text, style))
}

pub fn draw(frame: &mut Frame, app: &mut App) {
    let area = frame.area();
    app.term_width = area.width;

    if app.needs_api_key {
        draw_api_key_setup(frame, app, area);
        return;
    }

    let left_w = if app.left_hidden { 0 } else { app.left_pane_pct };
    let right_w = if app.right_hidden { 0 } else { app.right_pane_pct };
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
        app.pane_rects = Some(crate::app::PaneRects {
            left: content_horizontal[0],
            middle: content_horizontal[1],
            right_top: right_split[0],
            right_bottom: right_split[1],
            input: vertical[1],
        });
    } else {
        app.pane_rects = Some(crate::app::PaneRects {
            left: content_horizontal[0],
            middle: content_horizontal[1],
            right_top: Rect::default(),
            right_bottom: Rect::default(),
            input: vertical[1],
        });
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

    // Fuzzy finder (Ctrl+P) renders above panes but below the context menu.
    if let Some(ref ff) = app.fuzzy_finder {
        draw_fuzzy_finder(frame, ff, app, area);
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

fn draw_fuzzy_finder(frame: &mut Frame, ff: &FuzzyFinder, app: &App, area: Rect) {
    let popup = centered_rect(70, 70, area);
    frame.render_widget(Clear, popup);

    let layout = Layout::vertical([Constraint::Length(3), Constraint::Min(0)]).split(popup);

    // Search input
    let input_text = format!(" \u{1f50d} {}_", ff.query);
    let input_block = Block::bordered()
        .title(" Find File  Ctrl+P ")
        .border_style(Style::default().fg(app.agent_mode.accent_color()));
    frame.render_widget(Paragraph::new(input_text).block(input_block), layout[0]);

    // File list
    let visible = layout[1].height.saturating_sub(2) as usize;
    let offset = if ff.selected >= visible {
        ff.selected - visible + 1
    } else {
        0
    };

    let items: Vec<ListItem> = ff
        .filtered
        .iter()
        .skip(offset)
        .take(visible)
        .enumerate()
        .map(|(i, path)| {
            let abs_idx = i + offset;
            let (_, color) = file_icon_color(path, false);
            let bg = if abs_idx == ff.selected {
                app.agent_mode.accent_color()
            } else {
                Color::Reset
            };
            let fg = if abs_idx == ff.selected { Color::Black } else { color };
            ListItem::new(Line::from(Span::styled(
                format!("  {path}"),
                Style::default().fg(fg).bg(bg),
            )))
        })
        .collect();

    let title = format!(" {} results ", ff.filtered.len());
    let list = List::new(items).block(
        Block::bordered()
            .title(title.as_str())
            .border_style(Style::default().fg(app.agent_mode.accent_color())),
    );
    frame.render_widget(list, layout[1]);
}

fn draw_left_pane(frame: &mut Frame, app: &mut App, area: Rect) {
    let sess_dot = if app.sessions_activity { "\u{25cf} " } else { "" };
    let labels: [(String, &str, bool); 3] = [
        (
            format!("{sess_dot}\u{ebc7}  Sessions "),
            "left_sessions",
            matches!(app.left_tab, LeftTab::Sessions),
        ),
        (" \u{f07b}  Files ".to_string(), "left_files", matches!(app.left_tab, LeftTab::Files)),
        (" \u{e702}  Git ".to_string(), "left_git", matches!(app.left_tab, LeftTab::Git)),
    ];
    let tab_titles: Vec<Line> = labels
        .iter()
        .map(|(label, id, active)| styled_tab(app, label, id, *active))
        .collect();
    let selected = match app.left_tab {
        LeftTab::Sessions => 0,
        LeftTab::Files => 1,
        LeftTab::Git => 2,
    };

    let layout = Layout::vertical([Constraint::Length(1), Constraint::Min(0)]).split(area);

    // Record tab hit-test areas using actual title widths (not equal division).
    if let Some(ref mut areas) = app.tab_click_areas {
        let mut x = layout[0].x;
        for (i, (label, id, _)) in labels.iter().enumerate() {
            let w = label.chars().count() as u16 + 1;
            areas.push((id.to_string(), Rect { x, y: layout[0].y, width: w.max(1), height: 1 }));
            x += w;
            if i < labels.len() - 1 {
                x += 1; // account for the 1-char divider between tabs
            }
        }
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

    let block = Block::bordered()
        .border_type(border_type_for_pane(app, FocusedPane::Sessions))
        .border_style(Style::default().fg(border_color(app, FocusedPane::Sessions)));
    let inner = block.inner(layout[1]);
    frame.render_widget(block, layout[1]);

    match app.left_tab {
        LeftTab::Sessions => draw_sessions_content(frame, app, inner),
        LeftTab::Files => draw_files_content(frame, app, inner),
        LeftTab::Git => draw_git_content(frame, app, inner),
    }
}

fn draw_files_content(frame: &mut Frame, app: &mut App, area: Rect) {
    let height = area.height as usize;
    if height == 0 {
        return;
    }
    let sel = app.file_tree_selected;
    let offset = if sel >= height { sel - height + 1 } else { 0 };
    app.files_view_offset = offset;

    let mut lines: Vec<Line> = Vec::new();
    for (i, node) in app.file_tree.iter().enumerate().skip(offset).take(height) {
        let (icon, mut color) = file_icon_color(&node.name, node.is_dir);
        if node.gitignored {
            color = Color::DarkGray;
        }
        let is_hovered = app.hovered_file_idx == Some(i);
        let name_style = if i == sel {
            Style::default()
                .fg(app.agent_mode.accent_color())
                .add_modifier(Modifier::BOLD)
        } else if is_hovered {
            Style::default()
                .fg(app.agent_mode.accent_color())
                .add_modifier(Modifier::UNDERLINED)
        } else {
            Style::default().fg(color)
        };

        let mut spans: Vec<Span> = vec![Span::raw("  ".repeat(node.depth))];
        if node.is_dir {
            let chevron = if node.expanded { "\u{25be} " } else { "\u{25b8} " };
            spans.push(Span::styled(chevron, Style::default().fg(Color::DarkGray)));
        } else {
            spans.push(Span::raw("  "));
        }
        spans.push(Span::styled(icon, Style::default().fg(color)));
        spans.push(Span::styled(node.name.clone(), name_style));
        lines.push(Line::from(spans));
    }

    frame.render_widget(Paragraph::new(lines), area);
}

/// Devicons-style icon + color per file type. Directories get a folder glyph.
pub(crate) fn file_icon_color(filename: &str, is_dir: bool) -> (&'static str, Color) {
    if is_dir {
        return ("\u{f024b} ", Color::Cyan); // nf-md-folder
    }
    let ext = filename.rsplit('.').next().unwrap_or("");
    let lower_name = filename.to_lowercase();

    // Special filenames
    if lower_name == "readme.md" || lower_name == "readme" {
        return ("\u{f00ba} ", Color::LightBlue);
    }
    if lower_name.starts_with("cargo") {
        return ("\u{f1617} ", Color::Red);
    }
    if lower_name == "package.json" || lower_name == "package-lock.json" {
        return ("\u{f0399} ", Color::Green);
    }
    if lower_name == "dockerfile" || lower_name.starts_with("docker-compose") {
        return ("\u{f0868} ", Color::Blue);
    }
    if lower_name == ".gitignore" || lower_name == ".gitattributes" {
        return ("\u{f02a2} ", Color::Red);
    }
    if lower_name == "makefile" {
        return ("\u{f1064} ", Color::Yellow);
    }
    if lower_name == ".env" || lower_name.starts_with(".env.") {
        return ("\u{f0669} ", Color::Yellow);
    }

    match ext {
        "rs" => ("\u{f1617} ", Color::Red),
        "py" => ("\u{e606} ", Color::Yellow),
        "ts" | "tsx" => ("\u{f06e6} ", Color::Cyan),
        "js" | "jsx" | "mjs" => ("\u{f031e} ", Color::Yellow),
        "go" => ("\u{f07d3} ", Color::Cyan),
        "sh" | "bash" | "zsh" => ("\u{f489} ", Color::Green),
        "md" | "mdx" => ("\u{f0354} ", Color::LightBlue),
        "json" => ("\u{f0626} ", Color::Yellow),
        "toml" => ("\u{e6b2} ", Color::Red),
        "yaml" | "yml" => ("\u{f066e} ", Color::Red),
        "html" => ("\u{f031d} ", Color::Red),
        "css" | "scss" => ("\u{f031c} ", Color::Cyan),
        "sql" => ("\u{f1632} ", Color::Cyan),
        "lua" => ("\u{e620} ", Color::Blue),
        "vim" => ("\u{e62b} ", Color::Green),
        "c" | "h" => ("\u{e61e} ", Color::Blue),
        "cpp" | "hpp" => ("\u{e61d} ", Color::Blue),
        "java" => ("\u{e738} ", Color::Red),
        "kt" => ("\u{e634} ", Color::Magenta),
        "swift" => ("\u{e755} ", Color::Red),
        "dart" => ("\u{e798} ", Color::Cyan),
        "rb" => ("\u{e791} ", Color::Red),
        "php" => ("\u{e73d} ", Color::Magenta),
        "lock" => ("\u{f023} ", Color::DarkGray),
        "log" => ("\u{f0331} ", Color::DarkGray),
        "png" | "jpg" | "jpeg" | "gif" | "svg" | "ico" => ("\u{f0469} ", Color::LightBlue),
        "pdf" => ("\u{f0219} ", Color::Red),
        "zip" | "tar" | "gz" => ("\u{f410} ", Color::Yellow),
        _ => ("\u{f0214} ", Color::Gray),
    }
}

fn draw_git_content(frame: &mut Frame, app: &mut App, area: Rect) {
    let mut lines: Vec<Line> = Vec::new();
    let mut targets: Vec<Option<GitRowKind>> = Vec::new();
    let mut targets_status_idx: usize = 0;

    // Status section
    if !app.git_status.is_empty() {
        lines.push(Line::from(Span::styled(
            "  Changes",
            Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
        )));
        targets.push(None);
        for f in &app.git_status {
            let color = match f.status.as_str() {
                s if s.contains('M') => Color::Yellow,
                s if s.contains('A') => Color::Green,
                s if s.contains('D') => Color::Red,
                s if s.contains('?') => Color::DarkGray,
                _ => Color::White,
            };
            lines.push(Line::from(vec![
                Span::styled(format!("  {:3} ", f.status), Style::default().fg(color)),
                Span::styled(f.path.clone(), Style::default().fg(color)),
            ]));
            targets.push(Some(GitRowKind::StatusFile(targets_status_idx)));
            targets_status_idx += 1;
        }
        lines.push(Line::raw(""));
        targets.push(None);
    }

    // History section
    lines.push(Line::from(Span::styled(
        "  History",
        Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
    )));
    targets.push(None);

    for (i, commit) in app.git_commits.iter().enumerate() {
        let is_selected = i == app.git_commit_selected;
        let expand_arrow = if commit.expanded { "\u{25be}" } else { "\u{25b8}" };
        let msg_style = if is_selected {
            Style::default()
                .fg(app.agent_mode.accent_color())
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::White)
        };
        lines.push(Line::from(vec![
            Span::styled(format!("  {expand_arrow} "), Style::default().fg(Color::DarkGray)),
            Span::styled(format!("{} ", commit.short_hash), Style::default().fg(Color::Yellow)),
            Span::styled(commit.message.chars().take(40).collect::<String>(), msg_style),
            Span::styled(format!("  {}", commit.date), Style::default().fg(Color::DarkGray)),
        ]));
        targets.push(Some(GitRowKind::Commit(i)));

        if commit.expanded {
            for file in &commit.files {
                lines.push(Line::from(vec![
                    Span::styled("      \u{f0214} ", Style::default().fg(Color::DarkGray)),
                    Span::styled(file.clone(), Style::default().fg(Color::Cyan)),
                ]));
                targets.push(Some(GitRowKind::CommitFile(i, file.clone())));
            }
        }
    }

    app.git_row_targets = targets;
    let para = Paragraph::new(lines).scroll((app.git_scroll, 0));
    frame.render_widget(para, area);
}

fn draw_middle_pane(frame: &mut Frame, app: &mut App, area: Rect) {
    let tab_titles: Vec<Line> = app
        .middle_tabs
        .iter()
        .enumerate()
        .map(|(idx, t)| {
            let title = t.title();
            let close = if t.closeable() { " \u{00d7}" } else { "" };
            let is_active = idx == app.middle_tab_idx;
            // No active dot — activity is shown via color/bold only.
            let label = format!("  {title}{close} ");
            let mut style = if is_active {
                Style::default()
                    .fg(app.agent_mode.accent_color())
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::DarkGray)
            };
            if app.hovered_tab.as_deref() == Some(format!("middle_{idx}").as_str()) {
                style = style.add_modifier(Modifier::UNDERLINED);
            }
            Line::from(Span::styled(label, style))
        })
        .collect();

    let layout = Layout::vertical([Constraint::Length(1), Constraint::Min(0)]).split(area);

    // Record middle tab hit-test areas, advancing x by each rendered title width.
    // Also record a separate `middle_close_N` area over the `\u{00d7}` glyph.
    if let Some(ref mut areas) = app.tab_click_areas {
        let mut x = layout[0].x;
        for (idx, line) in tab_titles.iter().enumerate() {
            let w = line.width() as u16;
            // Push the close-button area first so it wins hit-testing over the tab.
            if app
                .middle_tabs
                .get(idx)
                .map(|t| t.closeable())
                .unwrap_or(false)
                && w >= 2
            {
                // Layout is "  {title}{close} ": close = " \u{00d7}", so the
                // \u{00d7} sits at w-2 and a trailing space at w-1. Cover both
                // columns so the click reliably lands on the close button.
                areas.push((
                    format!("middle_close_{idx}"),
                    Rect { x: x + w - 2, y: layout[0].y, width: 2, height: 1 },
                ));
            }
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
        )
        .divider("\u{258f}");
    frame.render_widget(tabs, layout[0]);

    let content_area = layout[1];
    let block = Block::bordered()
        .border_type(border_type_for_pane(app, FocusedPane::Conversation))
        .border_style(Style::default().fg(border_color(app, FocusedPane::Conversation)));
    let inner = block.inner(content_area);
    frame.render_widget(block, content_area);

    // Render the active FileView's editor widget directly (full editing).
    if let Some(TabContent::FileView { editor, .. }) = app.middle_tabs.get(app.middle_tab_idx) {
        frame.render_widget(editor, inner);
        return;
    }

    match app.middle_tabs.get(app.middle_tab_idx).cloned() {
        Some(TabContent::Conversation) => draw_conversation_content(frame, app, inner),
        Some(TabContent::FileView { .. }) => {}
        Some(TabContent::DiffView(_, diff)) => draw_side_by_side_diff(frame, diff, inner),
        None => {}
    }
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
    // If user is browsing git commits, show commit details instead of normal tools.
    if matches!(app.left_tab, LeftTab::Git) {
        if let Some(detail) = app.selected_commit_detail.clone() {
            draw_commit_detail(frame, app, &detail, area);
            return;
        }
    }

    let tools_dot = if app.tools_activity { "\u{25cf} " } else { "" };
    let tasks_dot = if app.tasks_activity { "\u{25cf} " } else { "" };
    let labels: [(String, &str, bool); 3] = [
        (
            format!("{tools_dot}\u{e28f}  Tools "),
            "right_tools",
            matches!(app.right_tab, RightTab::Tools),
        ),
        (
            format!("{tasks_dot}\u{f0ae}  Tasks "),
            "right_tasks",
            matches!(app.right_tab, RightTab::Tasks),
        ),
        (" \u{f007}  Subagents ".to_string(), "right_agents", matches!(app.right_tab, RightTab::Subagents)),
    ];
    let tab_titles: Vec<Line> = labels
        .iter()
        .map(|(label, id, active)| styled_tab(app, label, id, *active))
        .collect();
    let selected = match app.right_tab {
        RightTab::Tools => 0,
        RightTab::Tasks => 1,
        RightTab::Subagents => 2,
    };

    let layout = Layout::vertical([Constraint::Length(1), Constraint::Min(0)]).split(area);

    if let Some(ref mut areas) = app.tab_click_areas {
        let mut x = layout[0].x;
        for (i, (label, id, _)) in labels.iter().enumerate() {
            let w = label.chars().count() as u16 + 1;
            areas.push((id.to_string(), Rect { x, y: layout[0].y, width: w.max(1), height: 1 }));
            x += w;
            if i < labels.len() - 1 {
                x += 1; // account for the default 1-char divider between tabs
            }
        }
    }

    let tabs = Tabs::new(tab_titles)
        .select(selected)
        .style(Style::default().fg(Color::DarkGray))
        .highlight_style(
            Style::default()
                .fg(app.agent_mode.accent_color())
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(tabs, layout[0]);

    let block = Block::bordered()
        .border_type(border_type_for_pane(app, FocusedPane::Tools))
        .border_style(Style::default().fg(border_color(app, FocusedPane::Tools)));
    let inner = block.inner(layout[1]);
    frame.render_widget(block, layout[1]);

    match app.right_tab {
        RightTab::Tools => draw_tools_content(frame, app, inner),
        RightTab::Tasks => draw_tasks_content(frame, app, inner),
        RightTab::Subagents => draw_subagents_content(frame, app, inner),
    }
}

fn draw_commit_detail(frame: &mut Frame, app: &App, detail: &str, area: Rect) {
    let lines: Vec<Line> = detail
        .lines()
        .map(|l| {
            if l.starts_with('+') && !l.starts_with("+++") {
                Line::from(Span::styled(l.to_string(), Style::default().fg(Color::Green)))
            } else if l.starts_with('-') && !l.starts_with("---") {
                Line::from(Span::styled(l.to_string(), Style::default().fg(Color::Red)))
            } else if l.starts_with("commit ") {
                Line::from(Span::styled(
                    l.to_string(),
                    Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
                ))
            } else {
                Line::from(Span::raw(l.to_string()))
            }
        })
        .collect();

    let block = Block::bordered()
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(app.agent_mode.accent_color()))
        .title(Span::styled(
            " Commit Details ",
            Style::default().fg(app.agent_mode.accent_color()),
        ));
    frame.render_widget(
        Paragraph::new(lines).block(block).wrap(Wrap { trim: false }),
        area,
    );
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
            Span::raw("In input: cycle agent mode  │  Outside input: cycle pane focus"),
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
        Line::from(vec![
            Span::styled("  Alt+h  Alt+l ", Style::default().fg(Color::Cyan)),
            Span::raw("Hide/show left and right panes"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+P       ", Style::default().fg(Color::Cyan)),
            Span::raw("Fuzzy file finder"),
        ]),
        Line::from(vec![
            Span::styled("  Ctrl+S       ", Style::default().fg(Color::Cyan)),
            Span::raw("Save current file (when FileView tab)"),
        ]),
        Line::from(vec![
            Span::styled("  Right-click  ", Style::default().fg(Color::Cyan)),
            Span::raw("Context menu (open, copy, diff, edit...)"),
        ]),
        Line::from(vec![
            Span::styled("  Scroll wheel ", Style::default().fg(Color::Cyan)),
            Span::raw("Scroll focused pane"),
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
        Line::from(vec![
            Span::styled("  Shift+drag   ", Style::default().fg(Color::Cyan)),
            Span::raw("Select text (Shift bypasses TUI mouse in xterm/iTerm2/kitty)"),
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
                    Span::styled("\u{258c} ", Style::default().fg(Color::Green)),
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
                        Span::styled("\u{258c} ", Style::default().fg(Color::Green)),
                        Span::styled(line.to_string(), Style::default().fg(Color::White)),
                    ]));
                }
                all_lines.push(Line::raw(""));
            }
            Role::Assistant => {
                let accent = app.agent_mode.accent_color();
                all_lines.push(Line::from(vec![
                    Span::styled("\u{258c} ", Style::default().fg(accent)),
                    Span::styled(
                        "Atelier",
                        match_marker.unwrap_or_else(|| {
                            Style::default().fg(accent).add_modifier(Modifier::BOLD)
                        }),
                    ),
                ]));
                for mut hl_line in render_markdown_lines(&entry.text) {
                    let mut spans = vec![Span::styled("\u{258c} ", Style::default().fg(accent))];
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
            Span::styled("\u{258c} ", Style::default().fg(accent)),
            Span::styled(
                "Atelier",
                Style::default().fg(accent).add_modifier(Modifier::BOLD),
            ),
        ]));
        for mut hl_line in render_markdown_lines(&app.streaming_text) {
            let mut spans = vec![Span::styled("\u{258c} ", Style::default().fg(accent))];
            spans.extend(hl_line.spans.drain(..));
            all_lines.push(Line::from(spans));
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

fn draw_sessions_content(frame: &mut Frame, app: &mut App, area: Rect) {
    // If viewing a file, show its code outline instead of the sessions list.
    if !app.file_outline.is_empty() {
        let mut lines = vec![Line::from(Span::styled(
            "  Outline",
            Style::default().fg(Color::DarkGray),
        ))];
        for item in &app.file_outline {
            let color = match item.kind.as_str() {
                "fn" | "def" | "async def" => Color::Cyan,
                "struct" | "class" => Color::Yellow,
                "impl" | "trait" => Color::Magenta,
                _ => Color::White,
            };
            lines.push(Line::from(vec![
                Span::styled(
                    format!("  {:4} ", item.line),
                    Style::default().fg(Color::DarkGray),
                ),
                Span::styled(format!("{} ", item.kind), Style::default().fg(Color::DarkGray)),
                Span::styled(item.name.clone(), Style::default().fg(color)),
            ]));
        }
        frame.render_widget(Paragraph::new(lines), area);
        return;
    }

    let accent = app.agent_mode.accent_color();
    let mut lines: Vec<Line> = Vec::new();
    // (session index, display row) for each clickable session card.
    let mut click_rows: Vec<(usize, usize)> = Vec::new();

    for (idx, s) in app.sessions_list.iter().take(12).enumerate() {
        let row = lines.len();
        let id: String = s.id.chars().take(14).collect();
        // Row 1: ● id  (current)
        let dot_color = if s.is_current { Color::Green } else { accent };
        let mut header = vec![
            Span::styled("  \u{25cf}  ", Style::default().fg(dot_color)),
            Span::styled(id, Style::default().add_modifier(Modifier::BOLD)),
        ];
        if s.is_current {
            header.push(Span::styled(
                "  (current)",
                Style::default().fg(Color::DarkGray),
            ));
        }
        lines.push(Line::from(header));
        // Row 2: label (first message), only if present and distinct from id.
        if !s.label.is_empty() {
            let label: String = s.label.chars().take(28).collect();
            lines.push(Line::from(Span::styled(
                format!("     {label}"),
                Style::default().fg(Color::Gray),
            )));
        }
        // Row 3: $cost  saved $savings  N turns
        let mut stats = vec![Span::styled(
            format!("     ${:.4}", s.cost_usd),
            Style::default().fg(Color::DarkGray),
        )];
        if s.savings_usd > 0.0 {
            stats.push(Span::styled(
                format!("  saved ${:.4}", s.savings_usd),
                Style::default().fg(Color::Green),
            ));
        }
        if s.turns > 0 {
            stats.push(Span::styled(
                format!("  {} turns", s.turns),
                Style::default().fg(Color::DarkGray),
            ));
        }
        if s.tool_calls > 0 {
            stats.push(Span::styled(
                format!("  {} tools", s.tool_calls),
                Style::default().fg(Color::DarkGray),
            ));
        }
        lines.push(Line::from(stats));
        // Row 4: modified time
        if !s.modified.is_empty() {
            lines.push(Line::from(Span::styled(
                format!("     {}", s.modified),
                Style::default().fg(Color::DarkGray),
            )));
        }
        lines.push(Line::from(""));
        click_rows.push((idx, row));
    }

    if app.sessions_list.is_empty() {
        lines.push(Line::from(Span::styled(
            "  No past sessions",
            Style::default().fg(Color::DarkGray),
        )));
    }

    // Register clickable hit areas for each session card (id row + body).
    if let Some(ref mut areas) = app.tab_click_areas {
        for (idx, row) in &click_rows {
            let y = area.y.saturating_add(*row as u16);
            if y < area.y + area.height {
                areas.push((
                    format!("session_{idx}"),
                    Rect { x: area.x, y, width: area.width, height: 4 },
                ));
            }
        }
    }

    frame.render_widget(Paragraph::new(lines), area);
}

fn draw_context_pane(frame: &mut Frame, app: &App, area: Rect) {
    let stats = &app.context_stats;
    let accent = app.agent_mode.accent_color();

    let model_short = if stats.model.is_empty() {
        app.current_model
            .split('/')
            .next_back()
            .filter(|s| !s.is_empty())
            .unwrap_or("no model")
    } else {
        stats.model.split('/').next_back().unwrap_or(&stats.model)
    };

    let mut lines: Vec<Line> = vec![
        Line::raw(""),
        Line::from(vec![
            Span::styled("  \u{25c6} ", Style::default().fg(accent)),
            Span::styled(
                model_short.to_string(),
                Style::default().fg(Color::White).add_modifier(Modifier::BOLD),
            ),
        ]),
    ];

    if !stats.provider.is_empty() {
        lines.push(Line::from(Span::styled(
            format!("    {}", stats.provider),
            Style::default().fg(Color::DarkGray),
        )));
    }
    lines.push(Line::raw(""));

    // Cache bar
    let eff = stats.cache_efficiency;
    let bar_w = 10usize;
    let filled = ((eff / 100.0) * bar_w as f64).clamp(0.0, bar_w as f64) as usize;
    let bar: String = "\u{2588}".repeat(filled) + &"\u{2591}".repeat(bar_w - filled);
    let eff_color = if eff > 60.0 {
        Color::Green
    } else if eff > 30.0 {
        Color::Yellow
    } else {
        Color::Red
    };
    lines.push(Line::from(vec![
        Span::styled("  Cache  ", Style::default().fg(Color::DarkGray)),
        Span::styled(bar, Style::default().fg(eff_color)),
        Span::styled(format!("  {eff:.0}%"), Style::default().fg(eff_color)),
    ]));

    if app.total_cost_usd > 0.0 {
        lines.push(Line::from(vec![
            Span::styled("  Cost   ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                format!("${:.4}", app.total_cost_usd),
                Style::default().fg(Color::White),
            ),
        ]));
    }
    if app.total_savings_usd > 0.001 {
        lines.push(Line::from(vec![
            Span::styled("  Saved  ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                format!("${:.4}", app.total_savings_usd),
                Style::default().fg(Color::Green),
            ),
        ]));
    }

    let used_k = (stats.input_tokens + stats.cache_read_tokens) as f64 / 1000.0;
    lines.push(Line::from(vec![
        Span::styled("  Tokens ", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format!("{used_k:.0}k ({:.0}%)", stats.estimated_context_pct),
            Style::default().fg(Color::White),
        ),
    ]));

    if !stats.memory_hits.is_empty() {
        lines.push(Line::raw(""));
        lines.push(Line::from(Span::styled(
            "  Memory:",
            Style::default().fg(Color::DarkGray),
        )));
        for hit in stats.memory_hits.iter().take(4) {
            lines.push(Line::from(vec![
                Span::styled("  \u{21aa} ", Style::default().fg(Color::DarkGray)),
                Span::styled(
                    hit.chars().take(25).collect::<String>(),
                    Style::default().fg(Color::White),
                ),
            ]));
        }
    }

    let block = Block::bordered()
        .border_type(border_type_for_pane(app, FocusedPane::Context))
        .border_style(Style::default().fg(border_color(app, FocusedPane::Context)))
        .title(Span::styled(
            " Context ",
            Style::default().fg(border_color(app, FocusedPane::Context)),
        ));
    frame.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }).block(block), area);
}

fn draw_tools_content(frame: &mut Frame, app: &App, area: Rect) {
    let items: Vec<ListItem> = app
        .tools
        .iter()
        .map(|tool| {
            let (icon, icon_color) = match tool.status {
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
            ListItem::new(Line::from(vec![
                Span::styled(format!("  {icon} "), Style::default().fg(icon_color)),
                Span::styled(
                    tool.name.clone(),
                    Style::default().fg(Color::White).add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    if detail.is_empty() {
                        String::new()
                    } else {
                        format!(" {detail}")
                    },
                    Style::default().fg(Color::DarkGray),
                ),
            ]))
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
