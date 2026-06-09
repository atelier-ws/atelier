//! Atelier TUI entry point: spawns the Python NDJSON backend and runs the UI loop.

mod app;
mod highlight;
mod protocol;
mod qr;
mod terminal_bridge;
mod tunnel;
mod ui;
mod web;

use anyhow::Result;
use app::{ActiveOverlay, AgentMode, App, CompletionMode, ContextAction, ContextItem, ContextMenu, ConversationEntry, DragBorder, DragState, FocusedPane, FuzzyFinder, GitRowKind, LeftTab, PendingPermission, ReverseSearch, RightTab, Role, SearchState, TabContent};
use crossterm::event::{
    DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind, KeyModifiers,
    KeyboardEnhancementFlags, PopKeyboardEnhancementFlags, PushKeyboardEnhancementFlags,
};
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use protocol::{BackendEvent, FrontendCommand};
use ratatui::backend::CrosstermBackend;
use ratatui::layout::Rect;
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

    // --no-web: skip all web/tunnel/PTY servers (used when running inside PTY bridge)
    let no_web = std::env::args().any(|a| a == "--no-web");

    let (program, backend_args) = backend_command();

    let mut child = tokio::process::Command::new(&program)
        .args(&backend_args)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::inherit())
        .spawn()?;

    let child_stdin = child.stdin.take().expect("backend stdin missing");
    let child_stdout = child.stdout.take().expect("backend stdout missing");

    // Always start the web bridge on an available port (unless --no-web).
    let web_port = if no_web { 0u16 } else { find_available_port(7700).await };

    // Start the WebSocket PTY bridge on web_port + 1: serves a REAL terminal
    // (xterm.js) over WebSocket, spawning the TUI itself in a PTY like SSH.
    if !no_web {
        let ws_pty_port = web_port + 1;
        // Spawn the TUI binary (not the backend) in the PTY so the browser sees the full
        // visual Ratatui TUI — identical to SSH. Pass --no-web to avoid recursive web spawning.
        let tui_binary = std::env::current_exe()
            .unwrap_or_else(|_| std::path::PathBuf::from("atelier-tui"));
        let tui_cmd: Vec<String> = vec![
            tui_binary.to_string_lossy().to_string(),
            "--no-web".to_string(),
        ];
        tokio::spawn(async move {
            if let Err(e) = terminal_bridge::start_ws_pty_server(ws_pty_port, tui_cmd).await {
                eprintln!("WS PTY server error: {e}");
            }
        });
        eprintln!("  \u{25c6} Chat UI:     http://localhost:{web_port}");
        eprintln!("  \u{25c6} Terminal UI: http://localhost:{web_port}/terminal  (xterm.js \u{2014} like SSH)");
    }

    enable_raw_mode()?;
    let mut stdout = std::io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;

    // Enable the kitty keyboard protocol when the terminal is known to support it,
    // so Shift+Enter is reported as a distinct key event (not collapsed to plain Enter).
    let kitty_supported = std::env::var("TERM_PROGRAM")
        .map(|v| v == "WezTerm" || v == "kitty" || v == "iTerm.app")
        .unwrap_or(false)
        || std::env::var("COLORTERM")
            .map(|v| v == "truecolor")
            .unwrap_or(false);
    if kitty_supported {
        let _ = execute!(
            stdout,
            PushKeyboardEnhancementFlags(KeyboardEnhancementFlags::DISAMBIGUATE_ESCAPE_CODES)
        );
    }

    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let result = run_app(&mut terminal, child_stdin, child_stdout, web_port).await;

    if kitty_supported {
        let _ = execute!(terminal.backend_mut(), PopKeyboardEnhancementFlags);
    }
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture,
    )?;

    child.kill().await.ok();

    result
}

async fn run_app(
    terminal: &mut Terminal<CrosstermBackend<std::io::Stdout>>,
    child_stdin: ChildStdin,
    child_stdout: ChildStdout,
    web_port: u16,
) -> Result<()> {
    let project_root = std::env::current_dir()?.to_string_lossy().to_string();
    let mut app = App::new(project_root);

    let args: Vec<String> = std::env::args().collect();
    let resume_id: Option<String> = args
        .iter()
        .position(|a| a == "--resume")
        .and_then(|pos| args.get(pos + 1).filter(|a| !a.starts_with("--")).cloned());
    let show_resume_picker = args.iter().any(|a| a == "--resume") && resume_id.is_none();

    app.web_port = if web_port > 0 { Some(web_port) } else { None };
    if web_port > 0 {
        app.local_url = Some(format!("http://localhost:{web_port}"));
    }

    let (tx, mut rx) = tokio::sync::mpsc::channel::<BackendEvent>(100);

    // Broadcast channel for the web bridge (raw serialized event lines).
    let event_bcast = tokio::sync::broadcast::channel::<String>(256).0;
    // mpsc channel for commands arriving from browser clients (raw JSON lines).
    let (web_cmd_tx, mut web_cmd_rx) = tokio::sync::mpsc::channel::<String>(100);

    // Only spawn web/tunnel if we have a valid port (not --no-web mode).
    if web_port > 0 {
        let event_tx = event_bcast.clone();
        tokio::spawn(async move {
            let _ = web::start_web_server(web_port, event_tx, web_cmd_tx).await;
        });
    }

    // Always try to start a tunnel; share the URL with the main loop.
    let tunnel_url_shared: std::sync::Arc<std::sync::Mutex<Option<String>>> =
        std::sync::Arc::new(std::sync::Mutex::new(None));
    if web_port > 0 {
        let tunnel_url_for_task = tunnel_url_shared.clone();
        tokio::spawn(async move {
            if let Some((url, mut child)) = tunnel::try_start_tunnel(web_port).await {
                *tunnel_url_for_task.lock().unwrap() = Some(url);
                let _ = child.wait().await;
            }
        });
    }

    let reader_bcast = event_bcast.clone();
    tokio::spawn(async move {
        let reader = BufReader::new(child_stdout);
        let mut lines = reader.lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if line.trim().is_empty() {
                continue;
            }
            let _ = reader_bcast.send(line.clone());
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
            match crossterm::event::read()? {
                Event::Key(key) if key.kind == KeyEventKind::Press => {
                    handle_key(&mut app, key, &mut writer).await?;
                }
                Event::Mouse(mouse) => {
                    handle_mouse(&mut app, mouse);
                    // Execute any context menu action that was queued by the mouse handler
                    if let Some(action) = app.pending_context_action.take() {
                        execute_context_action(&mut app, action, &mut writer).await?;
                    }
                }
                _ => {}
            }
        }

        // Open a file in $EDITOR if requested by a /edit command.
        if let Some(file) = app.open_editor.take() {
            let editor = std::env::var("EDITOR")
                .or_else(|_| std::env::var("VISUAL"))
                .unwrap_or_else(|_| "vi".to_string());
            disable_raw_mode()?;
            execute!(
                terminal.backend_mut(),
                LeaveAlternateScreen,
                DisableMouseCapture
            )?;
            let status = std::process::Command::new(&editor).arg(&file).status();
            enable_raw_mode()?;
            execute!(
                terminal.backend_mut(),
                EnterAlternateScreen,
                EnableMouseCapture
            )?;
            terminal.clear()?;
            let msg = match status {
                Ok(s) if s.success() => format!("\u{2713} Edited {file} in {editor}"),
                Ok(s) => format!("\u{26a0} {editor} exited with {s}"),
                Err(e) => format!("\u{2717} Failed to open {editor}: {e}"),
            };
            app.conversation.push(app::ConversationEntry {
                role: app::Role::System,
                text: msg,
            });
        }

        // Pick up the tunnel URL once it becomes available.
        if app.tunnel_url.is_none() {
            if let Ok(guard) = tunnel_url_shared.try_lock() {
                if let Some(ref url) = *guard {
                    app.tunnel_url = Some(url.clone());
                    app.qr_lines = qr::render_qr(url);
                    app.conversation.push(app::ConversationEntry {
                        role: app::Role::System,
                        text: format!("\u{25c6} {url}"),
                    });
                    app.auto_scroll = true;
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

/// Run `git diff` for a single file relative to the given repo root.
fn get_file_diff_in_root(path: &str, root: &str) -> String {
    std::process::Command::new("git")
        .args(["diff", "--no-color", "--", path])
        .current_dir(root)
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
        .unwrap_or_default()
}

async fn find_available_port(start: u16) -> u16 {
    for port in start..start.saturating_add(100) {
        if tokio::net::TcpListener::bind(format!("127.0.0.1:{port}"))
            .await
            .is_ok()
        {
            return port;
        }
    }
    start
}

async fn send_command(writer: &mut BufWriter<ChildStdin>, cmd: &FrontendCommand) -> Result<()> {
    let line = serde_json::to_string(cmd)? + "\n";
    writer.write_all(line.as_bytes()).await?;
    writer.flush().await?;
    Ok(())
}

/// Replace the entire textarea contents with the given string.
fn set_input_text(input: &mut TextArea<'_>, text: &str) {
    *input = TextArea::default();
    for ch in text.chars() {
        input.input(Event::Key(crossterm::event::KeyEvent::new(
            KeyCode::Char(ch),
            KeyModifiers::NONE,
        )));
    }
}

async fn handle_key(
    app: &mut App<'_>,
    key: crossterm::event::KeyEvent,
    writer: &mut BufWriter<ChildStdin>,
) -> Result<()> {
    // Support BOTH Shift+Enter and Alt+Enter for multiline input — checked first
    // so no other handler can swallow it. Alt+Enter reliably arrives as `ESC+\r`;
    // Shift+Enter works in terminals that report the SHIFT modifier on Enter.
    if key.code == KeyCode::Enter
        && (key.modifiers.contains(KeyModifiers::SHIFT)
            || key.modifiers.contains(KeyModifiers::ALT))
    {
        app.input.insert_newline();
        return Ok(());
    }

    // Right-click context menu captures keys while open.
    if let Some(menu) = app.context_menu.as_mut() {
        match key.code {
            KeyCode::Esc | KeyCode::Char('q') => {
                app.context_menu = None;
                return Ok(());
            }
            KeyCode::Up => {
                if menu.selected > 0 {
                    menu.selected -= 1;
                }
                return Ok(());
            }
            KeyCode::Down => {
                menu.selected = (menu.selected + 1).min(menu.items.len().saturating_sub(1));
                return Ok(());
            }
            KeyCode::Enter => {
                let action = menu.items[menu.selected].action.clone();
                app.context_menu = None;
                execute_context_action(app, action, writer).await?;
                return Ok(());
            }
            KeyCode::Char(c) => {
                if let Some(item) = menu.items.iter().find(|i| i.key == c) {
                    let action = item.action.clone();
                    app.context_menu = None;
                    execute_context_action(app, action, writer).await?;
                }
                return Ok(());
            }
            _ => return Ok(()),
        }
    }

    // Fuzzy file finder (Ctrl+P) captures keys while open.
    if let Some(ff) = app.fuzzy_finder.as_mut() {
        match key.code {
            KeyCode::Esc => {
                app.fuzzy_finder = None;
                return Ok(());
            }
            KeyCode::Enter => {
                if let Some(path) = ff.filtered.get(ff.selected).cloned() {
                    let abs = std::path::Path::new(&app.project_root)
                        .join(&path)
                        .to_string_lossy()
                        .to_string();
                    app.open_file_tab(abs);
                    app.focused_pane = FocusedPane::Conversation;
                }
                app.fuzzy_finder = None;
                return Ok(());
            }
            KeyCode::Up => {
                if ff.selected > 0 {
                    ff.selected -= 1;
                }
                return Ok(());
            }
            KeyCode::Down => {
                ff.selected = (ff.selected + 1).min(ff.filtered.len().saturating_sub(1));
                return Ok(());
            }
            KeyCode::Backspace => {
                ff.query.pop();
                ff.update_filter();
                return Ok(());
            }
            KeyCode::Char(c)
                if !key.modifiers.contains(KeyModifiers::CONTROL)
                    && !key.modifiers.contains(KeyModifiers::ALT) =>
            {
                ff.query.push(c);
                ff.update_filter();
                return Ok(());
            }
            _ => return Ok(()),
        }
    }

    // Interactive overlays (agent/model/auth pickers + help) capture keys first.
    match &app.active_overlay {
        ActiveOverlay::AgentPicker { .. }
        | ActiveOverlay::ModelPicker { .. }
        | ActiveOverlay::AuthPicker { .. } => {
            match key.code {
                KeyCode::Esc | KeyCode::Char('q') => {
                    app.active_overlay = ActiveOverlay::None;
                    return Ok(());
                }
                KeyCode::Up => {
                    match &mut app.active_overlay {
                        ActiveOverlay::AgentPicker { selected } => {
                            if *selected > 0 {
                                *selected -= 1;
                            }
                        }
                        ActiveOverlay::ModelPicker { selected, .. } => {
                            if *selected > 0 {
                                *selected -= 1;
                            }
                        }
                        ActiveOverlay::AuthPicker { selected, .. } => {
                            if *selected > 0 {
                                *selected -= 1;
                            }
                        }
                        _ => {}
                    }
                    return Ok(());
                }
                KeyCode::Down => {
                    match &mut app.active_overlay {
                        ActiveOverlay::AgentPicker { selected } => {
                            *selected = (*selected + 1).min(3);
                        }
                        ActiveOverlay::ModelPicker { selected, models } => {
                            *selected = (*selected + 1).min(models.len().saturating_sub(1));
                        }
                        ActiveOverlay::AuthPicker { selected, providers } => {
                            *selected = (*selected + 1).min(providers.len().saturating_sub(1));
                        }
                        _ => {}
                    }
                    return Ok(());
                }
                KeyCode::Enter => {
                    match app.active_overlay.clone() {
                        ActiveOverlay::AgentPicker { selected } => {
                            let modes = ["code", "explore", "research", "plan"];
                            if let Some(mode) = modes.get(selected) {
                                app.agent_mode = match *mode {
                                    "code" => AgentMode::Code,
                                    "explore" => AgentMode::Explore,
                                    "research" => AgentMode::Research,
                                    "plan" => AgentMode::Plan,
                                    _ => AgentMode::Code,
                                };
                                send_command(
                                    writer,
                                    &FrontendCommand::UserCommand {
                                        name: "mode".to_string(),
                                        args: vec![mode.to_string()],
                                    },
                                )
                                .await?;
                            }
                        }
                        ActiveOverlay::ModelPicker { selected, models } => {
                            if let Some((model_id, _)) = models.get(selected) {
                                app.current_model = model_id.clone();
                                send_command(
                                    writer,
                                    &FrontendCommand::UserCommand {
                                        name: "model".to_string(),
                                        args: vec![model_id.clone()],
                                    },
                                )
                                .await?;
                            }
                        }
                        ActiveOverlay::AuthPicker { selected, providers } => {
                            if let Some(provider) = providers.get(selected) {
                                send_command(
                                    writer,
                                    &FrontendCommand::UserCommand {
                                        name: "auth".to_string(),
                                        args: vec![provider.clone()],
                                    },
                                )
                                .await?;
                            }
                        }
                        _ => {}
                    }
                    app.active_overlay = ActiveOverlay::None;
                    return Ok(());
                }
                _ => return Ok(()),
            }
        }
        ActiveOverlay::Help => {
            match key.code {
                KeyCode::Esc | KeyCode::Char('?') | KeyCode::Char('q') => {
                    app.active_overlay = ActiveOverlay::None;
                }
                _ => {}
            }
            return Ok(());
        }
        ActiveOverlay::None => {}
    }

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
                let mut q = app
                    .search
                    .as_ref()
                    .map(|s| s.query.clone())
                    .unwrap_or_default();
                q.pop();
                app.search_conversation(&q);
                return Ok(());
            }
            KeyCode::Char(c) => {
                let mut q = app
                    .search
                    .as_ref()
                    .map(|s| s.query.clone())
                    .unwrap_or_default();
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
                    CompletionMode::FileRef {
                        selected, filter, ..
                    } => {
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
                    CompletionMode::FileRef {
                        filter, selected, ..
                    } => {
                        filter.push(c);
                        *selected = 0;
                    }
                    CompletionMode::None => {}
                }
                app.input.input(Event::Key(key));
                return Ok(());
            }
            KeyCode::Backspace => {
                app.input.input(Event::Key(key));
                // Re-sync completion mode against the resulting input text:
                // if the trigger char was deleted, exit completion mode.
                let current_text = app.input.lines().join("");
                match &app.completion_mode {
                    CompletionMode::SlashCommand { .. } => {
                        if !current_text.starts_with('/') {
                            app.completion_mode = CompletionMode::None;
                        } else {
                            let filter = current_text.trim_start_matches('/').to_string();
                            app.completion_mode = CompletionMode::SlashCommand {
                                selected: 0,
                                filter,
                            };
                        }
                    }
                    CompletionMode::FileRef { files, .. } => match current_text.rfind('@') {
                        None => app.completion_mode = CompletionMode::None,
                        Some(at_pos) => {
                            let filter = current_text[at_pos + 1..].to_string();
                            let files_clone = files.clone();
                            app.completion_mode = CompletionMode::FileRef {
                                selected: 0,
                                filter,
                                files: files_clone,
                            };
                        }
                    },
                    CompletionMode::None => {}
                }
                return Ok(());
            }
            _ => {}
        }
    }

    // Reverse search (Ctrl+R) takes priority over normal input handling.
    if app.reverse_search.is_some() {
        // Esc / Ctrl+G cancels.
        if matches!(key.code, KeyCode::Esc)
            || (matches!(key.code, KeyCode::Char('g'))
                && key.modifiers.contains(KeyModifiers::CONTROL))
        {
            app.reverse_search = None;
            app.input = TextArea::default();
            return Ok(());
        }
        // Ctrl+R advances to the next match.
        if matches!(key.code, KeyCode::Char('r'))
            && key.modifiers.contains(KeyModifiers::CONTROL)
        {
            if let Some(ref mut rs) = app.reverse_search {
                if !rs.matches.is_empty() {
                    rs.current = (rs.current + 1) % rs.matches.len();
                    let idx = rs.matches[rs.current];
                    let line = app.message_history[idx].clone();
                    set_input_text(&mut app.input, &line);
                }
            }
            return Ok(());
        }
        // Enter accepts the current input and falls through to normal Enter.
        if matches!(key.code, KeyCode::Enter) {
            app.reverse_search = None;
            // fall through to normal handling below
        } else if let KeyCode::Char(c) = key.code {
            if !key.modifiers.contains(KeyModifiers::CONTROL) {
                if let Some(ref mut rs) = app.reverse_search {
                    rs.query.push(c);
                    let q = rs.query.to_lowercase();
                    rs.matches = app
                        .message_history
                        .iter()
                        .enumerate()
                        .filter(|(_, m)| m.to_lowercase().contains(&q))
                        .map(|(i, _)| i)
                        .rev()
                        .collect();
                    rs.current = 0;
                    let first = rs.matches.first().copied();
                    if let Some(idx) = first {
                        let line = app.message_history[idx].clone();
                        set_input_text(&mut app.input, &line);
                    }
                }
                return Ok(());
            }
        } else if matches!(key.code, KeyCode::Backspace) {
            if let Some(ref mut rs) = app.reverse_search {
                rs.query.pop();
                let q = rs.query.to_lowercase();
                rs.matches = app
                    .message_history
                    .iter()
                    .enumerate()
                    .filter(|(_, m)| m.to_lowercase().contains(&q))
                    .map(|(i, _)| i)
                    .rev()
                    .collect();
                rs.current = 0;
                let first = rs.matches.first().copied();
                if let Some(idx) = first {
                    let line = app.message_history[idx].clone();
                    set_input_text(&mut app.input, &line);
                }
            }
            return Ok(());
        }
    }

    // File tree navigation: route keys to the manual tree when the Files tab
    // is focused (Tab/BackTab still cycle pane focus so the user can leave).
    if matches!(app.focused_pane, FocusedPane::Sessions)
        && matches!(app.left_tab, LeftTab::Files)
        && !matches!(key.code, KeyCode::Tab | KeyCode::BackTab)
        && !key.modifiers.contains(KeyModifiers::ALT)
    {
        match key.code {
            KeyCode::Enter => {
                if let Some((path, is_dir)) = app.file_tree_selected_path() {
                    if is_dir {
                        app.file_tree_toggle();
                    } else {
                        app.open_file_tab(path);
                    }
                }
            }
            KeyCode::Up | KeyCode::Char('k') => app.file_tree_up(),
            KeyCode::Down | KeyCode::Char('j') => app.file_tree_down(),
            KeyCode::Right | KeyCode::Char('l') => app.file_tree_toggle(),
            KeyCode::Left | KeyCode::Char('h') => app.file_tree_toggle(),
            KeyCode::PageUp => {
                for _ in 0..10 {
                    app.file_tree_up();
                }
            }
            KeyCode::PageDown => {
                for _ in 0..10 {
                    app.file_tree_down();
                }
            }
            _ => {}
        }
        return Ok(());
    }

    // When the middle pane is focused on a FileView tab, route editing keys to
    // its TextArea. Esc returns to the input; Ctrl/Alt combos and Tab fall
    // through to global shortcuts (save, tab switching, nav history).
    if matches!(app.focused_pane, FocusedPane::Conversation)
        && matches!(
            app.middle_tabs.get(app.middle_tab_idx),
            Some(TabContent::FileView { .. })
        )
    {
        if matches!(key.code, KeyCode::Esc) {
            app.focused_pane = FocusedPane::Input;
            return Ok(());
        }
        let is_global = matches!(key.code, KeyCode::Tab | KeyCode::BackTab)
            || key.modifiers.contains(KeyModifiers::CONTROL)
            || key.modifiers.contains(KeyModifiers::ALT);
        if !is_global {
            if let Some(TabContent::FileView { editor, dirty, .. }) =
                app.middle_tabs.get_mut(app.middle_tab_idx)
            {
                if editor.input(crossterm::event::Event::Key(key)) {
                    *dirty = true;
                }
            }
            return Ok(());
        }
    }

    match key.code {
        #[cfg(feature = "clipboard")]
        KeyCode::Char('c' | 'C')
            if key
                .modifiers
                .contains(KeyModifiers::CONTROL | KeyModifiers::SHIFT) =>
        {
            let last_text = app
                .conversation
                .iter()
                .rev()
                .find(|e| matches!(e.role, app::Role::Assistant))
                .map(|e| e.text.clone())
                .unwrap_or_default();
            if !last_text.is_empty() {
                use arboard::Clipboard;
                if let Ok(mut clipboard) = Clipboard::new() {
                    let _ = clipboard.set_text(&last_text);
                    app.conversation.push(app::ConversationEntry {
                        role: app::Role::System,
                        text: "\u{2713} Copied last response to clipboard".to_string(),
                    });
                }
            }
        }
        KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            // If there's a text selection, Ctrl+C copies it (editor behavior)
            if let Some(ref sel) = app.text_selection {
                if !sel.selected_text.is_empty() {
                    #[cfg(feature = "clipboard")]
                    {
                        use arboard::Clipboard;
                        if let Ok(mut cb) = Clipboard::new() {
                            let _ = cb.set_text(&sel.selected_text);
                            app.conversation.push(app::ConversationEntry {
                                role: app::Role::System,
                                text: format!("\u{1f4cb} Copied {} chars", sel.selected_text.len()),
                            });
                        }
                    }
                    app.text_selection = None;
                    return Ok(());
                }
            }
            let now = std::time::Instant::now();
            let double_press = app
                .last_ctrl_c
                .map(|t| now.duration_since(t).as_millis() < 1000)
                .unwrap_or(false);
            app.last_ctrl_c = Some(now);

            if double_press || !app.is_streaming {
                // Exit on double Ctrl+C or when nothing is running.
                app.should_quit = true;
            } else {
                // Single Ctrl+C while streaming: interrupt the agent.
                send_command(writer, &FrontendCommand::Interrupt {}).await?;
                app.conversation.push(app::ConversationEntry {
                    role: app::Role::System,
                    text: "\u{26a1} Interrupted".to_string(),
                });
                app.is_streaming = false;
                app.streaming_text.clear();
            }
        }
        KeyCode::Char('d') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.should_quit = true;
        }
        KeyCode::Char('l') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.conversation.clear();
            app.tools.clear();
            app.streaming_text.clear();
            app.is_streaming = false;
            app.search = None;
            app.conversation.push(app::ConversationEntry {
                role: app::Role::System,
                text: "Screen cleared.".to_string(),
            });
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
        KeyCode::Char('p') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            let files = collect_files_for_display(&app.project_root);
            app.fuzzy_finder = Some(FuzzyFinder::new(files));
        }
        KeyCode::Char('s') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            let path_clone = match app.middle_tabs.get(app.middle_tab_idx) {
                Some(TabContent::FileView { path, .. }) => Some(path.clone()),
                _ => None,
            };
            if let Some(path) = path_clone {
                if let Some(TabContent::FileView {
                    editor,
                    dirty,
                    content_cache,
                    ..
                }) = app.middle_tabs.get_mut(app.middle_tab_idx)
                {
                    let new_content = editor.lines().join("\n");
                    if let Err(e) = std::fs::write(&path, &new_content) {
                        app.conversation.push(ConversationEntry {
                            role: Role::System,
                            text: format!("\u{2717} Save failed: {e}"),
                        });
                    } else {
                        *dirty = false;
                        *content_cache = new_content;
                        app.conversation.push(ConversationEntry {
                            role: Role::System,
                            text: format!("\u{2713} Saved {path}"),
                        });
                    }
                }
            }
        }
        KeyCode::Char('r') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.reverse_search = Some(ReverseSearch {
                query: String::new(),
                matches: vec![],
                current: 0,
            });
        }
        KeyCode::Tab if key.modifiers.contains(KeyModifiers::CONTROL) => {
            if !app.middle_tabs.is_empty() {
                app.middle_tab_idx = (app.middle_tab_idx + 1) % app.middle_tabs.len();
                app.nav_push(app.middle_tab_idx);
                app.build_outline_for_current_file();
                if matches!(app.middle_tabs.get(app.middle_tab_idx), Some(TabContent::FileView { .. })) {
                    app.focused_pane = FocusedPane::Conversation;
                }
            }
        }
        KeyCode::BackTab if key.modifiers.contains(KeyModifiers::CONTROL) => {
            if !app.middle_tabs.is_empty() {
                app.middle_tab_idx = if app.middle_tab_idx == 0 {
                    app.middle_tabs.len() - 1
                } else {
                    app.middle_tab_idx - 1
                };
                app.nav_push(app.middle_tab_idx);
                app.build_outline_for_current_file();
                if matches!(app.middle_tabs.get(app.middle_tab_idx), Some(TabContent::FileView { .. })) {
                    app.focused_pane = FocusedPane::Conversation;
                }
            }
        }
        KeyCode::Char('w') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.close_tab(app.middle_tab_idx);
        }
        KeyCode::Char('1') if key.modifiers.contains(KeyModifiers::ALT) => {
            app.left_tab = LeftTab::Files;
        }
        KeyCode::Char('2') if key.modifiers.contains(KeyModifiers::ALT) => {
            app.left_tab = LeftTab::Git;
            app.refresh_git_status();
            app.load_commit_detail(app.git_commit_selected);
        }
        KeyCode::Char('3') if key.modifiers.contains(KeyModifiers::ALT) => {
            app.right_tab = RightTab::Tools;
            app.tools_activity = false;
        }
        KeyCode::Char('4') if key.modifiers.contains(KeyModifiers::ALT) => {
            app.right_tab = RightTab::Tasks;
            app.tasks_activity = false;
        }
        KeyCode::Char('5') if key.modifiers.contains(KeyModifiers::ALT) => {
            app.right_tab = RightTab::Subagents;
        }
        KeyCode::F(1) => {
            app.right_tab = RightTab::Tools;
            app.tools_activity = false;
        }
        KeyCode::F(2) => {
            app.right_tab = RightTab::Tasks;
            app.tasks_activity = false;
        }
        KeyCode::F(3) => {
            app.right_tab = RightTab::Subagents;
        }
        // Alt+h / Alt+l to hide/show panes (Alt+[ doesn't work — ESC [ is ANSI escape prefix)
        KeyCode::Char('h') if key.modifiers.contains(KeyModifiers::ALT) => {
            app.left_hidden = !app.left_hidden;
        }
        KeyCode::Char('l') if key.modifiers.contains(KeyModifiers::ALT) => {
            app.right_hidden = !app.right_hidden;
        }
        KeyCode::Tab if matches!(app.focused_pane, FocusedPane::Input) => {
            // Tab in input = cycle agent mode (code → explore → research → plan → code)
            app.agent_mode = app.agent_mode.next();
            send_command(writer, &FrontendCommand::UserCommand {
                name: "mode".to_string(),
                args: vec![app.agent_mode.name().to_lowercase()],
            }).await?;
        }
        KeyCode::Tab => {
            // Tab outside input = cycle pane focus
            app.cycle_focus();
        }
        // Alt+Tab = insert literal tab into input
        KeyCode::Tab if key.modifiers.contains(KeyModifiers::ALT) => {
            app.input.input(crossterm::event::Event::Key(crossterm::event::KeyEvent::new(
                KeyCode::Char('\t'), KeyModifiers::NONE
            )));
        }
        KeyCode::Enter
            if matches!(app.focused_pane, FocusedPane::Sessions)
                && matches!(app.left_tab, LeftTab::Files) =>
        {
            let files = collect_files_for_display(&app.project_root);
            if let Some(path) = files.get(app.files_scroll as usize) {
                let abs = std::path::Path::new(&app.project_root)
                    .join(path)
                    .to_string_lossy()
                    .to_string();
                app.open_file_tab(abs);
            }
        }
        KeyCode::Enter
            if matches!(app.focused_pane, FocusedPane::Sessions)
                && matches!(app.left_tab, LeftTab::Git) =>
        {
            app.git_commit_toggle(app.git_commit_selected);
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

            if let Some(shell_cmd) = text.strip_prefix('!') {
                let shell_cmd = shell_cmd.trim().to_string();
                if shell_cmd.is_empty() {
                    return Ok(());
                }
                app.conversation.push(app::ConversationEntry {
                    role: app::Role::System,
                    text: format!("$ {shell_cmd}"),
                });
                send_command(
                    writer,
                    &FrontendCommand::UserCommand {
                        name: "shell".to_string(),
                        args: vec![shell_cmd],
                    },
                )
                .await?;
                return Ok(());
            }

            if let Some(rest) = text.strip_prefix('/') {
                let mut parts = rest.splitn(2, ' ');
                let name = parts.next().unwrap_or("").to_string();
                let args = parts
                    .next()
                    .map(|s| vec![s.to_string()])
                    .unwrap_or_default();

                // Handle exit/quit locally — never send to backend.
                if name == "exit" || name == "quit" {
                    app.should_quit = true;
                    return Ok(());
                }

                // Interactive overlays handled locally — never sent to backend.
                if name == "?" || name == "help" {
                    app.active_overlay = ActiveOverlay::Help;
                    return Ok(());
                }
                if name == "agents" {
                    app.active_overlay = ActiveOverlay::AgentPicker { selected: 0 };
                    return Ok(());
                }
                if name == "model" {
                    let models = vec![
                        ("anthropic/claude-opus-4-8".to_string(), "Anthropic, frontier, $15/Mtok".to_string()),
                        ("anthropic/claude-sonnet-4-5".to_string(), "Anthropic, balanced, $3/Mtok".to_string()),
                        ("openai/gpt-4o".to_string(), "OpenAI, balanced, $2.5/Mtok".to_string()),
                        ("openai/gpt-4o-mini".to_string(), "OpenAI, cheap, $0.15/Mtok".to_string()),
                        ("groq/llama-3.3-70b-versatile".to_string(), "Groq, fast, $0.59/Mtok".to_string()),
                        ("ollama/llama3.2".to_string(), "Local, free, needs Ollama".to_string()),
                        ("openrouter/anthropic/claude-opus-4-8".to_string(), "OpenRouter \u{2192} Claude".to_string()),
                        ("bedrock/anthropic.claude-sonnet-4-5-v1:0".to_string(), "AWS Bedrock Claude".to_string()),
                    ];
                    app.active_overlay = ActiveOverlay::ModelPicker { selected: 0, models };
                    return Ok(());
                }
                if name == "auth" {
                    let providers = vec![
                        "anthropic".to_string(), "openai".to_string(), "google".to_string(),
                        "groq".to_string(), "mistral".to_string(), "openrouter".to_string(),
                        "ollama".to_string(), "bedrock".to_string(), "azure".to_string(),
                        "vertex".to_string(), "together".to_string(), "fireworks".to_string(),
                    ];
                    app.active_overlay = ActiveOverlay::AuthPicker { selected: 0, providers };
                    return Ok(());
                }

                // Handle clear locally.
                if name == "clear" {
                    app.conversation.clear();
                    app.tools.clear();
                    app.streaming_text.clear();
                    app.is_streaming = false;
                    app.search = None;
                    app.conversation.push(app::ConversationEntry {
                        role: app::Role::System,
                        text: "Screen cleared.".to_string(),
                    });
                    return Ok(());
                }

                // Handle edit locally: open the file in $EDITOR (done in run_app loop).
                if name == "edit" {
                    let file = args.first().cloned().unwrap_or_default();
                    if !file.is_empty() {
                        app.open_editor = Some(file);
                    } else {
                        app.conversation.push(app::ConversationEntry {
                            role: app::Role::System,
                            text: "Usage: /edit <file>".to_string(),
                        });
                    }
                    return Ok(());
                }

                // Switching sessions: clear the current conversation so the
                // backend's replayed/loaded session replaces it (not appends).
                if name == "session" && !args.is_empty() {
                    app.conversation.clear();
                    app.tools.clear();
                    app.streaming_text.clear();
                    app.is_streaming = false;
                    send_command(writer, &FrontendCommand::UserCommand { name, args }).await?;
                    return Ok(());
                }

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
        KeyCode::Left if key.modifiers.contains(KeyModifiers::ALT) => {
            if app.nav_pos > 0 {
                app.nav_pos -= 1;
                app.middle_tab_idx =
                    app.nav_history[app.nav_pos].min(app.middle_tabs.len().saturating_sub(1));
                app.build_outline_for_current_file();
            }
        }
        KeyCode::Right if key.modifiers.contains(KeyModifiers::ALT) => {
            if app.nav_pos + 1 < app.nav_history.len() {
                app.nav_pos += 1;
                app.middle_tab_idx =
                    app.nav_history[app.nav_pos].min(app.middle_tabs.len().saturating_sub(1));
                app.build_outline_for_current_file();
            }
        }
        KeyCode::Up if matches!(app.focused_pane, FocusedPane::Sessions)
            && matches!(app.left_tab, LeftTab::Files) =>
        {
            app.files_scroll = app.files_scroll.saturating_sub(1);
        }
        KeyCode::Down if matches!(app.focused_pane, FocusedPane::Sessions)
            && matches!(app.left_tab, LeftTab::Files) =>
        {
            app.files_scroll = app.files_scroll.saturating_add(1);
        }
        KeyCode::Up if matches!(app.focused_pane, FocusedPane::Sessions)
            && matches!(app.left_tab, LeftTab::Git) =>
        {
            app.git_commit_selected = app.git_commit_selected.saturating_sub(1);
            app.load_commit_detail(app.git_commit_selected);
        }
        KeyCode::Down if matches!(app.focused_pane, FocusedPane::Sessions)
            && matches!(app.left_tab, LeftTab::Git) =>
        {
            app.git_commit_selected =
                (app.git_commit_selected + 1).min(app.git_commits.len().saturating_sub(1));
            app.load_commit_detail(app.git_commit_selected);
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
        KeyCode::Char('?') => {
            let current = app.input.lines().join("");
            if current.trim().is_empty() {
                app.active_overlay = ActiveOverlay::Help;
            } else if app.focused_pane == FocusedPane::Input {
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

fn handle_mouse(app: &mut App<'_>, mouse: crossterm::event::MouseEvent) {
    use crossterm::event::{MouseButton, MouseEventKind};

    let (col, row) = (mouse.column, mouse.row);
    match mouse.kind {
        MouseEventKind::Down(MouseButton::Left) => {
            // Context menu: click on item executes it; click outside dismisses
            if let Some(menu) = app.context_menu.take() {
                let menu_w = menu.items.iter().map(|i| i.label.len() + 6).max().unwrap_or(20) as u16;
                let menu_h = menu.items.len() as u16 + 2;
                let in_menu = col >= menu.x && col < menu.x + menu_w
                    && row >= menu.y && row < menu.y + menu_h;
                if in_menu {
                    let item_row = row.saturating_sub(menu.y + 1); // skip border
                    let idx = item_row as usize;
                    if let Some(item) = menu.items.get(idx) {
                        // Store for async execution in the main loop (handle_mouse is sync)
                        app.pending_context_action = Some(item.action.clone());
                    }
                }
                // menu dropped (either action taken or click-outside)
                return;
            }
            // Clear text selection on any left click
            app.text_selection = None;
            // First, handle clickable tabs.
            let mut hit_tab = false;
            if let Some(areas) = app.tab_click_areas.clone() {
                // Allow a ±1 column tolerance so clicks on tab padding/divider
                // still land on the intended tab.
                let tab_hit = |r: &Rect| {
                    col + 1 >= r.x
                        && col <= r.x + r.width
                        && row >= r.y
                        && row < r.y + r.height
                };
                for (tab_id, rect) in &areas {
                    if tab_hit(rect) {
                        match tab_id.as_str() {
                            "left_files" => app.left_tab = LeftTab::Files,
                            "left_git" => {
                                app.left_tab = LeftTab::Git;
                                app.refresh_git_status();
                                app.load_commit_detail(app.git_commit_selected);
                            }
                            "right_tools" => {
                                app.right_tab = RightTab::Tools;
                                app.tools_activity = false;
                            }
                            "right_tasks" => {
                                app.right_tab = RightTab::Tasks;
                                app.tasks_activity = false;
                            }
                            "right_agents" => app.right_tab = RightTab::Subagents,
                            _ if tab_id.starts_with("middle_close_") => {
                                if let Ok(idx) =
                                    tab_id["middle_close_".len()..].parse::<usize>()
                                {
                                    app.close_tab(idx);
                                }
                            }
                            _ if tab_id.starts_with("middle_") => {
                                if let Ok(idx) = tab_id["middle_".len()..].parse::<usize>() {
                                    if idx < app.middle_tabs.len() {
                                        app.middle_tab_idx = idx;
                                        app.nav_push(idx);
                                        app.build_outline_for_current_file();
                                        if matches!(app.middle_tabs.get(idx), Some(TabContent::FileView { .. })) {
                                            app.focused_pane = FocusedPane::Conversation;
                                        }
                                    }
                                }
                            }
                            _ => {}
                        }
                        hit_tab = true;
                        break;
                    }
                }
            }
            if hit_tab {
                return;
            }
            // Detect a click near a pane border to start a drag-resize (takes priority).
            let term_width = app.term_width.max(1);
            let left_border_col = app.left_pane_pct * term_width / 100;
            let right_border_col = (100 - app.right_pane_pct) * term_width / 100;
            if !app.left_hidden && (col as i32 - left_border_col as i32).abs() <= 2 {
                app.drag_state = Some(DragState {
                    border: DragBorder::LeftBorder,
                    start_col: col,
                    start_pct: app.left_pane_pct,
                });
                return;
            } else if !app.right_hidden && (col as i32 - right_border_col as i32).abs() <= 2 {
                app.drag_state = Some(DragState {
                    border: DragBorder::RightBorder,
                    start_col: col,
                    start_pct: app.right_pane_pct,
                });
                return;
            }

            // Activate the clicked pane.
            if let Some(rects) = app.pane_rects.clone() {
                let in_rect = |r: &Rect| {
                    col >= r.x && col < r.x + r.width && row >= r.y && row < r.y + r.height
                };
                if in_rect(&rects.input) {
                    app.focused_pane = FocusedPane::Input;
                } else if in_rect(&rects.middle) {
                    app.focused_pane = FocusedPane::Conversation;
                    // Start a text selection when dragging over the conversation.
                    if matches!(app.middle_tabs.get(app.middle_tab_idx), Some(TabContent::Conversation)) {
                        let rel = row.saturating_sub(rects.middle.y);
                        app.text_selection = Some(app::TextSelection {
                            start_row: rel,
                            end_row: rel,
                            selected_text: String::new(),
                        });
                    }
                } else if !app.right_hidden && in_rect(&rects.right_top) {
                    app.focused_pane = FocusedPane::Tools;
                } else if !app.right_hidden && in_rect(&rects.right_bottom) {
                    app.focused_pane = FocusedPane::Context;
                } else if !app.left_hidden && in_rect(&rects.left) {
                    app.focused_pane = FocusedPane::Sessions;
                }

                // Left-pane content clicks: file tree open / git commit toggle.
                if !app.left_hidden && in_rect(&rects.left) {
                    let content_y = rects.left.y + 2; // skip tab bar + top border
                    match app.left_tab {
                        LeftTab::Files => {
                            let idx = (row as i32 - content_y as i32) as usize + app.files_view_offset;
                            if let Some(node) = app.file_tree.get(idx) {
                                if node.is_dir {
                                    app.file_tree_selected = idx;
                                    app.file_tree_toggle();
                                } else {
                                    app.file_tree_selected = idx;
                                    let path = node.path.clone();
                                    app.open_file_tab(path);
                                    app.focused_pane = FocusedPane::Conversation;
                                }
                            }
                        }
                        LeftTab::Git => {
                            if row >= content_y {
                                let line_idx =
                                    (row - content_y) as usize + app.git_scroll as usize;
                                if let Some(Some(target)) =
                                    app.git_row_targets.get(line_idx).cloned()
                                {
                                    match target {
                                        GitRowKind::StatusFile(i) => {
                                            if let Some(git_file) = app.git_status.get(i) {
                                                let path = git_file.path.clone();
                                                let diff = get_file_diff_in_root(
                                                    &path,
                                                    &app.project_root,
                                                );
                                                app.open_diff_tab(path, diff);
                                                app.focused_pane = FocusedPane::Conversation;
                                            }
                                        }
                                        GitRowKind::Commit(i) => {
                                            app.git_commit_selected = i;
                                            app.git_commit_toggle(i);
                                            app.load_commit_detail(i);
                                        }
                                        GitRowKind::CommitFile(i, file) => {
                                            if let Some(commit) = app.git_commits.get(i) {
                                                let hash = commit.hash.clone();
                                                let diff = std::process::Command::new("git")
                                                    .args(["show", "--no-color", &hash, "--", &file])
                                                    .current_dir(&app.project_root)
                                                    .output()
                                                    .map(|o| {
                                                        String::from_utf8_lossy(&o.stdout)
                                                            .to_string()
                                                    })
                                                    .unwrap_or_default();
                                                app.open_diff_tab(file.clone(), diff);
                                                app.focused_pane = FocusedPane::Conversation;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        MouseEventKind::ScrollUp => {
            if let Some(ref rects) = app.pane_rects {
                let in_rect = |r: &Rect| {
                    col >= r.x && col < r.x + r.width && row >= r.y && row < r.y + r.height
                };
                if in_rect(&rects.middle) {
                    if matches!(
                        app.middle_tabs.get(app.middle_tab_idx),
                        Some(TabContent::FileView { .. }) | Some(TabContent::DiffView(..))
                    ) {
                        if let Some(s) = app.middle_tab_scroll.get_mut(app.middle_tab_idx) {
                            *s = s.saturating_sub(3);
                        }
                    } else {
                        app.auto_scroll = false;
                        app.scroll = app.scroll.saturating_sub(3);
                    }
                } else if !app.right_hidden && in_rect(&rects.right_top) {
                    app.tool_scroll = app.tool_scroll.saturating_sub(2);
                } else if !app.left_hidden && in_rect(&rects.left) {
                    match app.left_tab {
                        LeftTab::Files => app.files_scroll = app.files_scroll.saturating_sub(2),
                        LeftTab::Git => app.git_scroll = app.git_scroll.saturating_sub(2),
                    }
                }
            }
        }
        MouseEventKind::ScrollDown => {
            if let Some(ref rects) = app.pane_rects {
                let in_rect = |r: &Rect| {
                    col >= r.x && col < r.x + r.width && row >= r.y && row < r.y + r.height
                };
                if in_rect(&rects.middle) {
                    if matches!(
                        app.middle_tabs.get(app.middle_tab_idx),
                        Some(TabContent::FileView { .. }) | Some(TabContent::DiffView(..))
                    ) {
                        if let Some(s) = app.middle_tab_scroll.get_mut(app.middle_tab_idx) {
                            *s = s.saturating_add(3);
                        }
                    } else {
                        app.auto_scroll = false;
                        app.scroll = app.scroll.saturating_add(3);
                    }
                } else if !app.right_hidden && in_rect(&rects.right_top) {
                    app.tool_scroll = app.tool_scroll.saturating_add(2);
                } else if !app.left_hidden && in_rect(&rects.left) {
                    match app.left_tab {
                        LeftTab::Files => app.files_scroll = app.files_scroll.saturating_add(2),
                        LeftTab::Git => app.git_scroll = app.git_scroll.saturating_add(2),
                    }
                }
            }
        }
        MouseEventKind::Down(MouseButton::Middle) => {
            // Middle click on a middle tab: close that tab.
            if let Some(areas) = app.tab_click_areas.clone() {
                for (id, rect) in &areas {
                    if id.starts_with("middle_")
                        && !id.starts_with("middle_close_")
                        && col >= rect.x
                        && col < rect.x + rect.width
                        && row >= rect.y
                        && row < rect.y + rect.height
                    {
                        if let Ok(idx) = id["middle_".len()..].parse::<usize>() {
                            app.close_tab(idx);
                        }
                        break;
                    }
                }
            }
        }
        MouseEventKind::Down(MouseButton::Right) => {
            let items = build_context_menu(app, col, row);
            if !items.is_empty() {
                app.context_menu = Some(ContextMenu {
                    x: col,
                    y: row,
                    items,
                    selected: 0,
                });
            }
        }
        MouseEventKind::Moved => {
            // Context menu hover — update selected item
            if let Some(ref mut menu) = app.context_menu {
                let menu_y = menu.y + 1; // skip border
                if row >= menu_y && (row - menu_y) < menu.items.len() as u16 {
                    menu.selected = (row - menu_y) as usize;
                }
            }
            // Track hover over tabs for underline highlighting.
            let mut found_tab = None;
            if let Some(ref areas) = app.tab_click_areas {
                for (id, rect) in areas {
                    if col >= rect.x
                        && col < rect.x + rect.width
                        && row >= rect.y
                        && row < rect.y + rect.height
                    {
                        found_tab = Some(id.clone());
                        break;
                    }
                }
            }
            app.hovered_tab = found_tab;
            // Track hover over the file tree for underline highlighting.
            app.hovered_file_idx = None;
            if !app.left_hidden && matches!(app.left_tab, LeftTab::Files) {
                if let Some(rects) = app.pane_rects.clone() {
                    let content_y = rects.left.y + 2;
                    if col >= rects.left.x
                        && col < rects.left.x + rects.left.width
                        && row >= content_y
                    {
                        let idx = (row - content_y) as usize + app.files_view_offset;
                        if idx < app.file_tree.len() {
                            app.hovered_file_idx = Some(idx);
                        }
                    }
                }
            }
        }
        MouseEventKind::Drag(MouseButton::Left) => {
            if let Some(ref drag) = app.drag_state {
                let term_width = app.term_width.max(1) as i32;
                let delta = col as i32 - drag.start_col as i32;
                let delta_pct = (delta * 100 / term_width) as i16;
                match drag.border {
                    DragBorder::LeftBorder => {
                        app.left_pane_pct =
                            (drag.start_pct as i16 + delta_pct).clamp(10, 40) as u16;
                    }
                    DragBorder::RightBorder => {
                        app.right_pane_pct =
                            (drag.start_pct as i16 - delta_pct).clamp(10, 40) as u16;
                    }
                }
            } else if app.text_selection.is_some() {
                // Extend the conversation text selection.
                let middle_y = app.pane_rects.as_ref().map(|r| r.middle.y).unwrap_or(0);
                let rel = row.saturating_sub(middle_y);
                let off = app.scroll as usize;
                let all_text = app
                    .conversation
                    .iter()
                    .map(|e| e.text.clone())
                    .collect::<Vec<_>>()
                    .join("\n");
                let lines: Vec<&str> = all_text.lines().collect();
                if let Some(ref mut sel) = app.text_selection {
                    sel.end_row = rel;
                    let min_row = sel.start_row.min(sel.end_row) as usize;
                    let max_row = sel.start_row.max(sel.end_row) as usize;
                    let start = (min_row + off).min(lines.len());
                    let end = (max_row + off + 1).min(lines.len());
                    sel.selected_text = if start < end {
                        lines[start..end].join("\n")
                    } else {
                        String::new()
                    };
                }
            }
        }
        MouseEventKind::Up(MouseButton::Left) => {
            app.drag_state = None;
            // Do NOT auto-copy on mouse up — keep selection visible for Ctrl+C
            // text_selection stays until user presses Ctrl+C, types something, or clicks elsewhere
        }
        _ => {}
    }
}

fn build_context_menu(app: &App, col: u16, row: u16) -> Vec<ContextItem> {
    use ContextAction::*;

    if let Some(ref rects) = app.pane_rects {
        let in_rect = |r: &Rect| {
            col >= r.x && col < r.x + r.width && row >= r.y && row < r.y + r.height
        };

        if in_rect(&rects.middle) {
            match app.middle_tabs.get(app.middle_tab_idx) {
                Some(TabContent::FileView { path, .. }) => {
                    return vec![
                        ContextItem {
                            label: "Open in $EDITOR".to_string(),
                            key: 'e',
                            action: OpenInEditor(path.clone()),
                        },
                        ContextItem {
                            label: "Copy path".to_string(),
                            key: 'c',
                            action: CopyPath(path.clone()),
                        },
                        ContextItem {
                            label: "Show git diff".to_string(),
                            key: 'd',
                            action: ShowDiff(path.clone()),
                        },
                    ];
                }
                Some(TabContent::Conversation) => {
                    return vec![
                        ContextItem {
                            label: "Copy last response".to_string(),
                            key: 'c',
                            action: CopyLastMessage,
                        },
                        ContextItem {
                            label: "Search conversation".to_string(),
                            key: 'f',
                            action: SearchInConversation,
                        },
                        ContextItem {
                            label: "Clear conversation".to_string(),
                            key: 'x',
                            action: ClearConversation,
                        },
                        ContextItem {
                            label: "New task".to_string(),
                            key: 'n',
                            action: NewTask,
                        },
                    ];
                }
                _ => {}
            }
        } else if !app.left_hidden && in_rect(&rects.left) && matches!(app.left_tab, LeftTab::Files)
        {
            if let Some(node) = app.file_tree.get(app.file_tree_selected) {
                let path = node.path.clone();
                if node.is_dir {
                    return vec![
                        ContextItem {
                            label: "Expand/collapse".to_string(),
                            key: 'e',
                            action: OpenFile(path.clone()),
                        },
                        ContextItem {
                            label: "Copy path".to_string(),
                            key: 'c',
                            action: CopyPath(path),
                        },
                    ];
                } else {
                    return vec![
                        ContextItem {
                            label: "Open in tab".to_string(),
                            key: 'o',
                            action: OpenFile(path.clone()),
                        },
                        ContextItem {
                            label: "Open in $EDITOR".to_string(),
                            key: 'e',
                            action: OpenInEditor(path.clone()),
                        },
                        ContextItem {
                            label: "Copy path".to_string(),
                            key: 'c',
                            action: CopyPath(path.clone()),
                        },
                        ContextItem {
                            label: "Show git diff".to_string(),
                            key: 'd',
                            action: ShowDiff(path),
                        },
                    ];
                }
            }
        }
    }
    vec![]
}

async fn execute_context_action(
    app: &mut App<'_>,
    action: ContextAction,
    writer: &mut BufWriter<ChildStdin>,
) -> Result<()> {
    match action {
        ContextAction::OpenFile(path) => {
            app.open_file_tab(path);
            app.focused_pane = FocusedPane::Conversation;
        }
        ContextAction::CopyPath(path) => {
            #[cfg(feature = "clipboard")]
            {
                use arboard::Clipboard;
                if let Ok(mut cb) = Clipboard::new() {
                    let _ = cb.set_text(&path);
                }
            }
            app.conversation.push(ConversationEntry {
                role: Role::System,
                text: format!("\u{1f4cb} Copied: {path}"),
            });
        }
        ContextAction::OpenInEditor(path) => {
            app.open_editor = Some(path);
        }
        ContextAction::ShowDiff(path) => {
            let diff = get_file_diff(&path);
            app.open_diff_tab(path, diff);
        }
        ContextAction::CopyLastMessage => {
            let last_text = app
                .conversation
                .iter()
                .rev()
                .find(|e| matches!(e.role, Role::Assistant))
                .map(|e| e.text.clone());
            if let Some(text) = last_text {
                #[cfg(feature = "clipboard")]
                {
                    use arboard::Clipboard;
                    if let Ok(mut cb) = Clipboard::new() {
                        let _ = cb.set_text(&text);
                    }
                }
                let _ = text;
                app.conversation.push(ConversationEntry {
                    role: Role::System,
                    text: "\u{1f4cb} Copied last response".to_string(),
                });
            }
        }
        ContextAction::SearchInConversation => {
            app.search = Some(SearchState {
                query: String::new(),
                matches: vec![],
                current_match: 0,
            });
        }
        ContextAction::ClearConversation => {
            app.conversation.clear();
            app.tools.clear();
            app.streaming_text.clear();
        }
        ContextAction::NewTask => {
            send_command(
                writer,
                &FrontendCommand::UserCommand {
                    name: "newtask".to_string(),
                    args: vec![],
                },
            )
            .await?;
        }
    }
    Ok(())
}

fn collect_files_for_display(root: &str) -> Vec<String> {
    collect_repo_files(root)
}

fn get_file_diff(path: &str) -> String {
    std::process::Command::new("git")
        .args(["diff", "--no-color", path])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
        .unwrap_or_default()
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
    let skip = [
        "target",
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "dist",
    ];
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
