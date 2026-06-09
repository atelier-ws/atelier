//! Atelier TUI entry point: spawns the Python NDJSON backend and runs the UI loop.

mod app;
mod highlight;
mod protocol;
mod ui;

use anyhow::Result;
use app::{App, FocusedPane, PendingPermission};
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

    let (tx, mut rx) = tokio::sync::mpsc::channel::<BackendEvent>(100);

    tokio::spawn(async move {
        let reader = BufReader::new(child_stdout);
        let mut lines = reader.lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if line.trim().is_empty() {
                continue;
            }
            if let Ok(event) = serde_json::from_str::<BackendEvent>(&line) {
                if tx.send(event).await.is_err() {
                    break;
                }
            }
        }
    });

    let mut writer = BufWriter::new(child_stdin);

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

    match key.code {
        KeyCode::Char('d') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.should_quit = true;
        }
        KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            send_command(writer, &FrontendCommand::Interrupt {}).await?;
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
            app.input = TextArea::default();

            let cmd = if let Some(rest) = text.strip_prefix('/') {
                let mut parts = rest.splitn(2, ' ');
                let name = parts.next().unwrap_or("").to_string();
                let args = parts
                    .next()
                    .map(|s| vec![s.to_string()])
                    .unwrap_or_default();
                FrontendCommand::UserCommand { name, args }
            } else {
                FrontendCommand::UserMessage { text: text.clone() }
            };

            app.conversation.push(app::ConversationEntry {
                role: app::Role::User,
                text,
            });

            send_command(writer, &cmd).await?;
        }
        KeyCode::Up => match app.focused_pane {
            FocusedPane::Tools => app.tool_scroll_up(),
            _ => app.scroll_up(),
        },
        KeyCode::Down => match app.focused_pane {
            FocusedPane::Tools => app.tool_scroll_down(),
            _ => app.scroll_down(),
        },
        KeyCode::PageUp => {
            for _ in 0..10 {
                app.scroll_up();
            }
        }
        KeyCode::PageDown => {
            for _ in 0..10 {
                app.scroll_down();
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
