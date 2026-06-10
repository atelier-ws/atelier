//! WebSocket PTY bridge: spawns atelier-tui's backend in a PTY and connects it
//! to a browser via WebSocket. The browser runs xterm.js and sees the exact
//! terminal output — identical to SSH but over HTTP.
//!
//! Architecture:
//!   Browser (xterm.js) <--WebSocket binary--> this bridge <--PTY--> backend
//!
//! Runs on a dedicated port (`web_port + 1`). The xterm.js HTML page is served
//! from the existing SSE web server (`/terminal` route in `web.rs`).

use std::io::{Read, Write};
use std::sync::Arc;

use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use portable_pty::{CommandBuilder, NativePtySystem, PtySize, PtySystem};
use tokio::net::TcpListener;
use tokio::sync::Mutex;
use tokio_tungstenite::tungstenite::handshake::server::{Request, Response};
use tokio_tungstenite::{accept_hdr_async, tungstenite::Message};

/// Start the WebSocket PTY server on `ws_port`. Each connection gets its own PTY
/// running `tui_backend_cmd` (e.g. `atelier tui-backend`).
pub async fn start_ws_pty_server(ws_port: u16, tui_backend_cmd: Vec<String>) -> Result<()> {
    let listener = TcpListener::bind(format!("0.0.0.0:{ws_port}")).await?;

    loop {
        match listener.accept().await {
            Ok((stream, _addr)) => {
                let cmd = tui_backend_cmd.clone();
                tokio::spawn(async move {
                    if let Err(e) = handle_ws_pty(stream, cmd).await {
                        let _ = e;
                    }
                });
            }
            Err(_) => {
                tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            }
        }
    }
}

async fn handle_ws_pty(stream: tokio::net::TcpStream, tui_cmd: Vec<String>) -> Result<()> {
    // Inspect the WebSocket Upgrade request to extract an optional `s=<session_id>`
    // from the query string; if present we resume that session in the PTY.
    let mut session_id: Option<String> = None;
    let ws_stream = accept_hdr_async(stream, |req: &Request, resp: Response| {
        if let Some(query) = req.uri().query() {
            for kv in query.split('&') {
                if let Some(id) = kv.strip_prefix("s=") {
                    if !id.is_empty() {
                        session_id = Some(id.to_string());
                    }
                }
            }
        }
        Ok(resp)
    })
    .await?;
    let (mut ws_sender, mut ws_receiver) = ws_stream.split();

    // Allocate a PTY.
    let pty_system = NativePtySystem::default();
    let pair = pty_system.openpty(PtySize {
        rows: 40,
        cols: 120,
        pixel_width: 0,
        pixel_height: 0,
    })?;

    // Build the command and spawn it in the PTY slave.
    let mut tui_cmd_final = tui_cmd.clone();
    if let Some(ref id) = session_id {
        tui_cmd_final.push("--resume".to_string());
        tui_cmd_final.push(id.clone());
    }
    let mut cmd = CommandBuilder::new(&tui_cmd_final[0]);
    for arg in &tui_cmd_final[1..] {
        cmd.arg(arg);
    }
    let _child = pair.slave.spawn_command(cmd)?;

    let master = pair.master;
    let mut master_reader = master.try_clone_reader()?;
    let master_writer = Arc::new(Mutex::new(master.take_writer()?));

    // PTY output → WebSocket (blocking PTY read, async WS send).
    let rt = tokio::runtime::Handle::current();
    let sender_task = tokio::task::spawn_blocking(move || {
        let mut buf = vec![0u8; 4096];
        loop {
            let n = match master_reader.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => n,
            };
            let bytes = buf[..n].to_vec();
            if rt
                .block_on(ws_sender.send(Message::Binary(bytes.into())))
                .is_err()
            {
                break;
            }
        }
    });

    // WebSocket input → PTY stdin.
    while let Some(Ok(msg)) = ws_receiver.next().await {
        match msg {
            Message::Binary(data) => {
                let mut w = master_writer.lock().await;
                let _ = w.write_all(&data);
                let _ = w.flush();
            }
            Message::Text(text) => {
                // JSON resize message: {"type":"resize","cols":N,"rows":M}
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(text.as_str()) {
                    if v["type"] == "resize" {
                        let cols = v["cols"].as_u64().unwrap_or(120) as u16;
                        let rows = v["rows"].as_u64().unwrap_or(40) as u16;
                        let _ = master.resize(PtySize {
                            rows,
                            cols,
                            pixel_width: 0,
                            pixel_height: 0,
                        });
                    }
                }
            }
            Message::Close(_) => break,
            _ => {}
        }
    }

    sender_task.abort();
    Ok(())
}
