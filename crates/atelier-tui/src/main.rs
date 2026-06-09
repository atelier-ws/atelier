//! Atelier TUI entry point: spawns the Python NDJSON backend and runs the UI loop.

mod app;
mod highlight;
mod protocol;
mod ui;
mod web;

use anyhow::Result;
use app::{App, CompletionMode, FocusedPane, PendingPermission, SearchState};
use crossterm::event::{
    DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind, KeyModifiers,
};
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use protocol::{BackendEvent, FrontendCommand};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;
use ratatui_textarea::TextArea;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader, BufWriter};
use tokio::process::{ChildStdin, ChildStdout};

fn backend_command() -> (String, Vec<String>) {
    let resume_id = {
        let args: Vec<String> = std::env::args().collect();
        args.windows(2)
            .find(|w| w[0] == "--resume")
            .map(|w| w[1].clone())
    };

    if let Ok(raw) = std::env::var("ATELIER_TUI_BACKEND") {
        let mut parts = raw.split_whitespace().map(String::from);
        if let Some(program) = parts.next() {
            let mut args: Vec<String> = parts.collect();
            if let Some(id) = &resume_id {
                args.push("--session-id".to_string());
                args.push(id.clone());
            }
            return (program, args);
        }
    }
    let mut args = vec!["tui-backend".to_string()];
    if let Some(id) = &resume_id {
        args.push("--session-id".to_string());
        args.push(id.clone());
    }
    ("atelier".to_string(), args)
}

#[tokio::main]
async fn main() -> Result<()> {
    if std::env::args().any(|a| a == "--mitm") {
        std::env::set_var("ATELIER_MITM", "1");
    }

    let (program, args) = backend_command();

    let mut child = tokio::process::Command::new(&program)
        .args(&args)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::inherit())
        .spawn()?;

    let child_stdin = child.stdin.take().expect("backend stdin missing");
    let child_stdout = child.stdout.take().expect("backend stdout missing");

    enable_raw_mode()?;
    let mut stdout = std::io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let result = run_app(&mut terminal, child_stdin, child_stdout).await;

    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )?;

    child.kill().await.ok();

    result
}

async fn run_app(
    terminal: &mut Terminal<CrosstermBackend<std::io::Stdout>>,
    child_stdin: ChildStdin,
    child_stdout: ChildStdout,
) -> Result<()> {
    let project_root = std::env::current_dir()?.to_string_lossy().to_string();
    let mut app = App::new(project_root);

    let args: Vec<String> = std::env::args().collect();
    let web_port: Option<u16> = args
        .iter()
        .position(|a| a == "--web")
        .map(|pos| {
            args.get(pos + 1)
                .and_then(|p| p.parse().ok())
                .unwrap_or(web::DEFAULT_WEB_PORT)
        });
    let resume_id: Option<String> = args
        .iter()
        .position(|a| a == "--resume")
        .and_then(|pos| args.get(pos + 1).filter(|a| !a.starts_with("--")).cloned());
    let show_resume_picker = args.iter().any(|a| a == "--resume") && resume_id.is_none();

    let (tx, mut rx) = tokio::sync::mpsc::channel::<BackendEvent>(100);

    // Broadcast channel for the web bridge (raw serialized event lines).
    let event_bcast = tokio::sync::broadcast::channel::<String>(256).0;
    // mpsc channel for commands arriving from browser clients (raw JSON lines).
    let (web_cmd_tx, mut web_cmd_rx) = tokio::sync::mpsc::channel::<String>(100);

    if let Some(port) = web_port {
        let event_tx = event_bcast.clone();
        tokio::spawn(async move {
            let _ = web::start_web_server(port, event_tx, web_cmd_tx).await;
        });
    }

    let reader_bcast = event_bcast.clone();
    let web_enabled = web_port.is_some();
    tokio::spawn(async move {
        let reader = BufReader::new(child_stdout);
        let mut lines = reader.lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if line.trim().is_empty() {
                continue;
            }
            if web_enabled {
                let _ = reader_bcast.send(line.clone());
            }
            if let Ok(event) = serde_json::from_str::<BackendEvent>(&line) {
                if tx.send(event).await.is_err() {
                    break;
                }
            }
        }
    });

    let mut writer = BufWriter::new(child_stdin);

    if show_resume_picker {
        app.show_session_picker = true;
        send_command(
            &mut writer,
            &FrontendCommand::UserCommand {
                name: "sessions".to_string(),
                args: vec![],
            },
        )
        .await?;
    }

    terminal.draw(|f| ui::draw(f, &mut app))?;

    loop {
        if crossterm::event::poll(std::time::Duration::from_millis(16))? {
            if let Event::Key(key) = crossterm::event::read()? {
                if key.kind == KeyEventKind::Press {
                    handle_key(&mut app, key, &mut writer).await?;
                }
            }
        }

        while let Ok(event) = rx.try_recv() {
            app.handle_event(event);
        }

        // Forward commands from browser clients to the backend.
        while let Ok(raw) = web_cmd_rx.try_recv() {
            let line = raw + "\n";
            writer.write_all(line.as_bytes()).await?;
            writer.flush().await?;
        }

        if app.should_quit {
            break;
        }

        terminal.draw(|f| ui::draw(f, &mut app))?;
    }

    Ok(())
}

async fn send_command(
    writer: &mut BufWriter<ChildStdin>,
    cmd: &FrontendCommand,
) -> Result<()> {
    let line = serde_json::to_string(cmd)? + "\n";
    writer.write_all(line.as_bytes()).await?;
    writer.flush().await?;
    Ok(())
}

async fn handle_key(
    app: &mut App<'_>,
    key: crossterm::event::KeyEvent,
    writer: &mut BufWriter<ChildStdin>,
) -> Result<()> {
    // Session picker overlay takes top priority.
    if app.show_session_picker {
        match key.code {
            KeyCode::Up => {
                app.session_picker_selected = app.session_picker_selected.saturating_sub(1);
                return Ok(());
            }
            KeyCode::Down => {
                if app.session_picker_selected + 1 < app.session_list.len() {
                    app.session_picker_selected += 1;
                }
                return Ok(());
            }
            KeyCode::Esc => {
                app.show_session_picker = false;
                return Ok(());
            }
            KeyCode::Enter => {
                if let Some(entry) = app.session_list.get(app.session_picker_selected) {
                    let id = entry.id.clone();
                    app.show_session_picker = false;
                    app.push_system_pub(format!("resuming session {id}"));
                    send_command(
                        writer,
                        &FrontendCommand::UserMessage {
                            text: format!("Resume session {id}"),
                        },
                    )
                    .await?;
                }
                return Ok(());
            }
            _ => return Ok(()),
        }
    }

    // Choice overlay takes priority next.
    if let Some(choice) = app.pending_choice.clone() {
        if choice.input_mode {
            match key.code {
                KeyCode::Enter => {
                    let response = choice.custom_input.clone();
                    app.pending_choice = None;
                    send_command(
                        writer,
                        &FrontendCommand::ChoiceResponse {
                            id: choice.id,
                            response,
                        },
                    )
                    .await?;
                }
                KeyCode::Esc => {
                    if let Some(c) = app.pending_choice.as_mut() {
                        c.input_mode = false;
                        c.custom_input.clear();
                    }
                }
                KeyCode::Backspace => {
                    if let Some(c) = app.pending_choice.as_mut() {
                        c.custom_input.pop();
                    }
                }
                KeyCode::Char(ch) => {
                    if let Some(c) = app.pending_choice.as_mut() {
                        c.custom_input.push(ch);
                    }
                }
                _ => {}
            }
            return Ok(());
        }
        match key.code {
            KeyCode::Up => {
                if let Some(c) = app.pending_choice.as_mut() {
                    c.selected = c.selected.saturating_sub(1);
                }
                return Ok(());
            }
            KeyCode::Down => {
                if let Some(c) = app.pending_choice.as_mut() {
                    if c.selected + 1 < c.choices.len() {
                        c.selected += 1;
                    }
                }
                return Ok(());
            }
            KeyCode::Enter => {
                let response = choice
                    .choices
                    .get(choice.selected)
                    .cloned()
                    .unwrap_or_default();
                app.pending_choice = None;
                send_command(
                    writer,
                    &FrontendCommand::ChoiceResponse {
                        id: choice.id,
                        response,
                    },
                )
                .await?;
                return Ok(());
            }
            KeyCode::Char(ch) if choice.allow_freeform => {
                if let Some(c) = app.pending_choice.as_mut() {
                    c.input_mode = true;
                    c.custom_input.push(ch);
                }
                return Ok(());
            }
            KeyCode::Esc => {
                app.pending_choice = None;
                return Ok(());
            }
            _ => return Ok(()),
        }
    }

    // Permission prompt takes priority.
    if let Some(PendingPermission::Waiting { id, .. }) = app.pending_permission.clone() {
        match key.code {
            KeyCode::Char('y') => {
                app.pending_permission = None;
                send_command(
                    writer,
                    &FrontendCommand::PermissionResponse {
                        id,
                        approved: true,
                        scope: "once".to_string(),
                    },
                )
                .await?;
                return Ok(());
            }
            KeyCode::Char('a') => {
                app.pending_permission = None;
                send_command(
                    writer,
                    &FrontendCommand::PermissionResponse {
                        id,
                        approved: true,
                        scope: "always".to_string(),
                    },
                )
                .await?;
                return Ok(());
            }
            KeyCode::Char('n') => {
                app.pending_permission = None;
                send_command(
                    writer,
                    &FrontendCommand::PermissionResponse {
                        id,
                        approved: false,
                        scope: "once".to_string(),
                    },
                )
                .await?;
                return Ok(());
            }
            _ => return Ok(()),
        }
    }

    // Diff overlay takes priority next.
    if app.pending_diff.is_some() {
        match key.code {
            KeyCode::Char('a') => {
                app.pending_diff = None;
                send_command(
                    writer,
                    &FrontendCommand::PermissionResponse {
                        id: String::new(),
                        approved: true,
                        scope: "once".to_string(),
                    },
                )
                .await?;
                return Ok(());
            }
            KeyCode::Char('d') => {
                app.pending_diff = None;
                return Ok(());
            }
            _ => return Ok(()),
        }
    }

    // --- Search mode handling (Ctrl+F) ---
    if app.search.is_some() {
        match key.code {
            KeyCode::Esc => {
                app.search = None;
                return Ok(());
            }
            KeyCode::Enter | KeyCode::Down => {
                app.search_next();
                return Ok(());
            }
            KeyCode::Up => {
                app.search_prev();
                return Ok(());
            }
            KeyCode::Backspace => {
                let mut q = app.search.as_ref().map(|s| s.query.clone()).unwrap_or_default();
                q.pop();
                app.search_conversation(&q);
                return Ok(());
            }
            KeyCode::Char(c) => {
                let mut q = app.search.as_ref().map(|s| s.query.clone()).unwrap_or_default();
                q.push(c);
                app.search_conversation(&q);
                return Ok(());
            }
            _ => return Ok(()),
        }
    }

    // --- Completion mode handling (slash commands / file refs) ---
    if app.completion_mode != CompletionMode::None {
        match key.code {
            KeyCode::Esc => {
                app.completion_mode = CompletionMode::None;
                return Ok(());
            }
            KeyCode::Up => {
                app.completion_select_up();
                return Ok(());
            }
            KeyCode::Down => {
                app.completion_select_down();
                return Ok(());
            }
            KeyCode::Enter => {
                match app.completion_mode.clone() {
                    CompletionMode::SlashCommand { selected, filter } => {
                        let commands = app.filtered_slash_commands(&filter);
                        if let Some((name, _)) = commands.get(selected) {
                            app.input = TextArea::default();
                            for ch in format!("/{name} ").chars() {
                                app.input.input(Event::Key(crossterm::event::KeyEvent::new(
                                    KeyCode::Char(ch),
                                    KeyModifiers::NONE,
                                )));
                            }
                            app.completion_mode = CompletionMode::None;
                        }
                    }
                    CompletionMode::FileRef { selected, filter, .. } => {
                        let files = app.filtered_files(&filter);
                        if let Some(file_path) = files.get(selected) {
                            let current = app.input.lines().join("\n");
                            let at_pos = current.rfind('@').unwrap_or(current.len());
                            let before_at = current[..at_pos].to_string();
                            app.input = TextArea::default();
                            for ch in format!("{before_at}@{file_path}").chars() {
                                app.input.input(Event::Key(crossterm::event::KeyEvent::new(
                                    KeyCode::Char(ch),
                                    KeyModifiers::NONE,
                                )));
                            }
                            app.completion_mode = CompletionMode::None;
                        }
                    }
                    CompletionMode::None => {}
                }
                return Ok(());
            }
            KeyCode::Char(c) => {
                match &mut app.completion_mode {
                    CompletionMode::SlashCommand { filter, selected } => {
                        filter.push(c);
                        *selected = 0;
                    }
                    CompletionMode::FileRef { filter, selected, .. } => {
                        filter.push(c);
                        *selected = 0;
                    }
                    CompletionMode::None => {}
                }
                app.input.input(Event::Key(key));
                return Ok(());
            }
            KeyCode::Backspace => {
                let still_active = match &mut app.completion_mode {
                    CompletionMode::SlashCommand { filter, selected } => {
                        filter.pop();
                        *selected = 0;
                        true
                    }
                    CompletionMode::FileRef { filter, selected, .. } => {
                        filter.pop();
                        *selected = 0;
                        true
                    }
                    CompletionMode::None => false,
                };
                app.input.input(Event::Key(key));
                if !still_active {
                    app.completion_mode = CompletionMode::None;
                }
                return Ok(());
            }
            _ => {}
        }
    }

    match key.code {
        KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            send_command(writer, &FrontendCommand::Interrupt {}).await?;
        }
        KeyCode::Char('m') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.agent_mode = app.agent_mode.next();
            send_command(
                writer,
                &FrontendCommand::UserCommand {
                    name: "mode".to_string(),
                    args: vec![app.agent_mode.name().to_lowercase()],
                },
            )
            .await?;
        }
        KeyCode::Char('f') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.search = Some(SearchState {
                query: String::new(),
                matches: vec![],
                current_match: 0,
            });
        }
        KeyCode::Tab => {
            app.cycle_focus();
        }
        KeyCode::Enter if key.modifiers.contains(KeyModifiers::SHIFT) => {
            app.input.insert_newline();
        }
        KeyCode::Enter => {
            let text = app.input.lines().join("\n").trim().to_string();
            if text.is_empty() {
                return Ok(());
            }

            // API-key setup mode: treat input as a model string override.
            if app.needs_api_key {
                app.current_model = text.clone();
                app.needs_api_key = false;
                app.input = TextArea::default();
                send_command(
                    writer,
                    &FrontendCommand::UserCommand {
                        name: "set-model".to_string(),
                        args: vec![text],
                    },
                )
                .await?;
                return Ok(());
            }

            app.input = TextArea::default();
            app.auto_scroll = true;

            if let Some(rest) = text.strip_prefix('/') {
                let mut parts = rest.splitn(2, ' ');
                let name = parts.next().unwrap_or("").to_string();
                let args = parts
                    .next()
                    .map(|s| vec![s.to_string()])
                    .unwrap_or_default();
                app.conversation.push(app::ConversationEntry {
                    role: app::Role::System,
                    text: format!("/{name} {}", args.join(" ")).trim_end().to_string(),
                });
                send_command(writer, &FrontendCommand::UserCommand { name, args }).await?;
            } else {
                app.conversation.push(app::ConversationEntry {
                    role: app::Role::User,
                    text: text.clone(),
                });
                if !text.is_empty() {
                    if app.message_history.last() != Some(&text) {
                        app.message_history.push(text.clone());
                        if app.message_history.len() > 50 {
                            app.message_history.remove(0);
                        }
                    }
                    app.history_cursor = None;
                }
                send_command(writer, &FrontendCommand::UserMessage { text }).await?;
            }
        }
        KeyCode::Up if key.modifiers.contains(KeyModifiers::ALT) => {
            if let Some(text) = app.history_up() {
                app.input = TextArea::default();
                for line in text.lines() {
                    for ch in line.chars() {
                        app.input.input(Event::Key(crossterm::event::KeyEvent::new(
                            KeyCode::Char(ch),
                            KeyModifiers::NONE,
                        )));
                    }
                }
            }
        }
        KeyCode::Down if key.modifiers.contains(KeyModifiers::ALT) => {
            if let Some(text) = app.history_down() {
                app.input = TextArea::default();
                if !text.is_empty() {
                    for ch in text.chars() {
                        app.input.input(Event::Key(crossterm::event::KeyEvent::new(
                            KeyCode::Char(ch),
                            KeyModifiers::NONE,
                        )));
                    }
                }
            }
        }
        KeyCode::End => {
            app.auto_scroll = true;
            app.scroll = u16::MAX;
        }
        KeyCode::Up => {
            app.auto_scroll = false;
            match app.focused_pane {
                FocusedPane::Tools => app.tool_scroll_up(),
                _ => app.scroll_up(),
            }
        }
        KeyCode::Down => match app.focused_pane {
            FocusedPane::Tools => app.tool_scroll_down(),
            _ => app.scroll_down(),
        },
        KeyCode::PageUp => {
            app.auto_scroll = false;
            for _ in 0..10 {
                app.scroll_up();
            }
        }
        KeyCode::PageDown => {
            for _ in 0..10 {
                app.scroll_down();
            }
        }
        KeyCode::Char('/') => {
            let current = app.input.lines().join("");
            if current.trim().is_empty() {
                app.completion_mode = CompletionMode::SlashCommand {
                    selected: 0,
                    filter: String::new(),
                };
            }
            if app.focused_pane == FocusedPane::Input {
                app.input.input(Event::Key(key));
            }
        }
        KeyCode::Char('@') => {
            let files = collect_repo_files(&app.project_root);
            app.completion_mode = CompletionMode::FileRef {
                selected: 0,
                filter: String::new(),
                files,
            };
            if app.focused_pane == FocusedPane::Input {
                app.input.input(Event::Key(key));
            }
        }
        _ => {
            if app.focused_pane == FocusedPane::Input {
                app.input.input(Event::Key(key));
            }
        }
    }

    Ok(())
}

fn collect_repo_files(root: &str) -> Vec<String> {
    let mut files = Vec::new();
    let base = std::path::Path::new(root);
    collect_files_recursive(base, base, &mut files, 0);
    files.sort();
    files.truncate(200);
    files
}

fn collect_files_recursive(
    base: &std::path::Path,
    dir: &std::path::Path,
    files: &mut Vec<String>,
    depth: usize,
) {
    if depth > 3 || files.len() >= 200 {
        return;
    }
    let skip = ["target", ".git", "node_modules", "__pycache__", ".venv", "dist"];
    if let Ok(entries) = std::fs::read_dir(dir) {
        for entry in entries.flatten() {
            if files.len() >= 200 {
                return;
            }
            let path = entry.path();
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with('.') && name != ".env" {
                continue;
            }
            if skip.contains(&name.as_str()) {
                continue;
            }
            if path.is_dir() {
                collect_files_recursive(base, &path, files, depth + 1);
            } else if path.is_file() {
                if let Ok(rel) = path.strip_prefix(base) {
                    files.push(rel.to_string_lossy().to_string());
                }
            }
        }
    }
}
