//! Browser bridge for atelier-tui (SSE-based, no external HTTP crates).
//!
//! When `--web [PORT]` is passed, this starts a tiny HTTP server using only
//! `tokio::net::TcpListener` + manual HTTP parsing that:
//!   1. Serves the xterm.js terminal on `GET /` (auto-resumes current session)
//!   2. Upgrades `GET /ws/terminal` to WebSocket → PTY bridge (same port as HTTP,
//!      so cloudflare tunnels and reverse proxies work without separate port setup)
//!   3. Streams backend events to browsers via Server-Sent Events on `GET /events`
//!   4. Accepts browser commands on `POST /command` and forwards them to the backend
//!   5. `/chat` keeps the legacy SSE chat UI

use std::pin::Pin;
use std::task::{Context, Poll};

use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt, ReadBuf};
use tokio::net::TcpListener;
use tokio::sync::{broadcast, mpsc};

#[allow(dead_code)]
pub const DEFAULT_WEB_PORT: u16 = 7777;

/// Start the SSE bridge server. `event_tx` carries serialized backend event
/// lines (one JSON object per message); `cmd_tx` receives serialized frontend
/// command lines from the browser. `current_session_id` is updated by the main
/// loop whenever a session starts — the web terminal auto-resumes it.
pub async fn start_web_server(
    port: u16,
    event_tx: broadcast::Sender<String>,
    cmd_tx: mpsc::Sender<String>,
    current_session_id: std::sync::Arc<std::sync::Mutex<String>>,
) -> anyhow::Result<()> {
    // Bind to 0.0.0.0 (not just 127.0.0.1) so cloudflared and other
    // bridges (Docker, VMs) can connect to the origin server.
    let listener = TcpListener::bind(format!("0.0.0.0:{port}")).await?;
    eprintln!("  \u{25c6} Web server listening on port {port}");

    loop {
        match listener.accept().await {
            Ok((stream, _addr)) => {
                let event_tx = event_tx.clone();
                let cmd_tx = cmd_tx.clone();
                let session_id = current_session_id.clone();
                tokio::spawn(async move {
                    if let Err(e) = handle_connection(stream, port, event_tx, cmd_tx, session_id).await {
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

// ─── HeadedStream ────────────────────────────────────────────────────────────
// Wraps a TcpStream and prepends already-read header bytes back onto the read
// stream. Used so tokio-tungstenite can do its WebSocket handshake even though
// we already consumed the HTTP headers from the socket.

struct HeadedStream {
    head: Vec<u8>,
    pos: usize,
    inner: tokio::net::TcpStream,
}

impl AsyncRead for HeadedStream {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<std::io::Result<()>> {
        if self.pos < self.head.len() {
            let available = &self.head[self.pos..];
            let to_copy = available.len().min(buf.remaining());
            buf.put_slice(&available[..to_copy]);
            self.pos += to_copy;
            return Poll::Ready(Ok(()));
        }
        Pin::new(&mut self.inner).poll_read(cx, buf)
    }
}

impl AsyncWrite for HeadedStream {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        data: &[u8],
    ) -> Poll<std::io::Result<usize>> {
        Pin::new(&mut self.inner).poll_write(cx, data)
    }
    fn poll_flush(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<std::io::Result<()>> {
        Pin::new(&mut self.inner).poll_flush(cx)
    }
    fn poll_shutdown(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<std::io::Result<()>> {
        Pin::new(&mut self.inner).poll_shutdown(cx)
    }
}

impl Unpin for HeadedStream {}

// ─── Inline WS PTY handler (same port as HTTP) ───────────────────────────────

async fn handle_ws_pty_inline(
    stream: HeadedStream,
    session_id: Option<String>,
    tui_binary: String,
) -> anyhow::Result<()> {
    use futures_util::{SinkExt, StreamExt};
    use portable_pty::{CommandBuilder, NativePtySystem, PtySize, PtySystem};
    use std::io::{Read, Write};
    use std::sync::Arc;
    use tokio::sync::Mutex;
    use tokio_tungstenite::{accept_hdr_async, tungstenite::Message};
    use tokio_tungstenite::tungstenite::handshake::server::{Request, Response};

    let mut resolved_session_id = session_id;
    let ws_stream = accept_hdr_async(stream, |req: &Request, resp: Response| {
        if let Some(query) = req.uri().query() {
            for kv in query.split('&') {
                if let Some(id) = kv.strip_prefix("s=") {
                    if !id.is_empty() {
                        resolved_session_id = Some(id.to_string());
                    }
                }
            }
        }
        Ok(resp)
    })
    .await?;

    let (mut ws_sender, mut ws_receiver) = ws_stream.split();

    let pty_system = NativePtySystem::default();
    let pair = pty_system.openpty(PtySize {
        rows: 40,
        cols: 120,
        pixel_width: 0,
        pixel_height: 0,
    })?;

    let mut cmd_args = vec!["--no-web".to_string()];
    if let Some(ref id) = resolved_session_id {
        cmd_args.push("--resume".to_string());
        cmd_args.push(id.clone());
    }
    let mut cmd = CommandBuilder::new(&tui_binary);
    for arg in &cmd_args {
        cmd.arg(arg);
    }
    let _child = pair.slave.spawn_command(cmd)?;

    let master = pair.master;
    let mut master_reader = master.try_clone_reader()?;
    let master_writer = Arc::new(Mutex::new(master.take_writer()?));

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

    while let Some(Ok(msg)) = ws_receiver.next().await {
        match msg {
            Message::Binary(data) => {
                let mut w = master_writer.lock().await;
                let _ = w.write_all(&data);
                let _ = w.flush();
            }
            Message::Text(text) => {
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

async fn handle_connection(
    mut stream: tokio::net::TcpStream,
    port: u16,
    event_tx: broadcast::Sender<String>,
    cmd_tx: mpsc::Sender<String>,
    current_session_id: std::sync::Arc<std::sync::Mutex<String>>,
) -> anyhow::Result<()> {
    // Read the request headers (and any already-buffered body bytes).
    let mut buf = vec![0u8; 8192];
    let mut filled = 0usize;
    loop {
        let n = stream.read(&mut buf[filled..]).await?;
        if n == 0 {
            break;
        }
        filled += n;
        if buf[..filled].windows(4).any(|w| w == b"\r\n\r\n") {
            break;
        }
        if filled >= buf.len() {
            break;
        }
    }
    let raw = String::from_utf8_lossy(&buf[..filled]).to_string();
    let mut head = raw.splitn(2, "\r\n\r\n");
    let header_part = head.next().unwrap_or("");
    let body_start = head.next().unwrap_or("");

    let request_line = header_part.lines().next().unwrap_or("");
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("");

    // Detect WebSocket upgrade requests — handle on the SAME port as HTTP
    // so cloudflare tunnels and reverse proxies (single port) work correctly.
    let is_ws_upgrade = header_part
        .lines()
        .any(|l| l.to_ascii_lowercase().starts_with("upgrade:") && l.to_ascii_lowercase().contains("websocket"));
    if method == "GET" && is_ws_upgrade && (path == "/ws/terminal" || path.starts_with("/ws/terminal?")) {
        let query = path.split_once('?').map(|(_, q)| q).unwrap_or("");
        let session_id: Option<String> = query
            .split('&')
            .find(|kv| kv.starts_with("s="))
            .map(|kv| kv[2..].to_string())
            .or_else(|| {
                current_session_id.lock().ok().and_then(|g| {
                    let s = g.clone();
                    if s.is_empty() { None } else { Some(s) }
                })
            });
        let tui_binary = std::env::current_exe()
            .unwrap_or_else(|_| std::path::PathBuf::from("atelier-tui"))
            .to_string_lossy()
            .to_string();
        let headed = HeadedStream { head: buf[..filled].to_vec(), pos: 0, inner: stream };
        return handle_ws_pty_inline(headed, session_id, tui_binary).await;
    }

    if method == "GET" && (path == "/" || path.starts_with("/?") || path.starts_with("/share/")) {
        // Default: serve the xterm.js terminal auto-resumed to the current session.
        let session_id = current_session_id.lock().ok().and_then(|g| {
            let s = g.clone();
            if s.is_empty() { None } else { Some(s) }
        });
        let html = xterm_html(port + 1, session_id);
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            html.len(),
            html,
        );
        stream.write_all(response.as_bytes()).await?;
        stream.flush().await?;
    } else if method == "GET" && (path == "/chat" || path.starts_with("/chat?")) {
        // Legacy chat web UI (SSE-based)
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            WEB_UI_HTML.len(),
            WEB_UI_HTML,
        );
        stream.write_all(response.as_bytes()).await?;
        stream.flush().await?;
    } else if method == "GET" && (path == "/terminal" || path.starts_with("/terminal?")) {
        // Real terminal page: xterm.js connects to the WS PTY bridge on web_port+1.
        // Extract an optional `s=<session_id>` from the query string to resume a session.
        let query = path.split_once('?').map(|(_, q)| q).unwrap_or("");
        let session_id: Option<String> = query
            .split('&')
            .find(|kv| kv.starts_with("s="))
            .map(|kv| kv[2..].to_string());
        let html = xterm_html(port + 1, session_id);
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            html.len(),
            html,
        );
        stream.write_all(response.as_bytes()).await?;
        stream.flush().await?;
    } else if method == "GET" && path == "/events" {
        // Server-Sent Events stream.
        stream
            .write_all(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: keep-alive\r\n\r\n",
            )
            .await?;
        stream.flush().await?;
        let mut rx = event_tx.subscribe();
        loop {
            match rx.recv().await {
                Ok(line) => {
                    // SSE frames must not contain raw newlines; backend lines are single JSON objects.
                    let frame = format!("data: {}\n\n", line.replace('\n', " "));
                    if stream.write_all(frame.as_bytes()).await.is_err() {
                        break;
                    }
                    if stream.flush().await.is_err() {
                        break;
                    }
                }
                Err(broadcast::error::RecvError::Lagged(_)) => continue,
                Err(broadcast::error::RecvError::Closed) => break,
            }
        }
    } else if method == "POST" && path == "/command" {
        // Determine the body length from Content-Length, then read the remainder.
        let content_length = header_part
            .lines()
            .find_map(|l| {
                let l = l.to_ascii_lowercase();
                l.strip_prefix("content-length:")
                    .map(|v| v.trim().parse::<usize>().unwrap_or(0))
            })
            .unwrap_or(0);
        let mut body = body_start.as_bytes().to_vec();
        while body.len() < content_length {
            let n = stream.read(&mut buf).await?;
            if n == 0 {
                break;
            }
            body.extend_from_slice(&buf[..n]);
        }
        if let Ok(cmd) = String::from_utf8(body) {
            let cmd = cmd.trim().to_string();
            if !cmd.is_empty() {
                let _ = cmd_tx.send(cmd).await;
            }
        }
        stream
            .write_all(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            .await?;
        stream.flush().await?;
    } else {
        stream
            .write_all(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")
            .await?;
        stream.flush().await?;
    }
    Ok(())
}

/// Embedded single-page HTML app (uses EventSource for events, fetch for commands).
pub const WEB_UI_HTML: &str = r#"<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Atelier</title>
<style>
  :root { --bg:#0d1117; --fg:#c9d1d9; --accent:#58a6ff; --green:#3fb950; --yellow:#d29922; --red:#f85149; --purple:#bc8cff; --muted:#484f58; --border:#21262d; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:'SF Mono','Fira Code',monospace; background:var(--bg); color:var(--fg); height:100vh; display:flex; flex-direction:column; }
  #header { padding:12px 20px; border-bottom:1px solid var(--border); display:flex; align-items:center; gap:12px; background:#010409; }
  #header h1 { color:var(--accent); font-size:14px; font-weight:600; }
  #status { font-size:11px; color:var(--muted); margin-left:auto; }
  #model-badge { font-size:11px; color:var(--purple); padding:2px 8px; border:1px solid var(--purple); border-radius:12px; }
  #conversation { flex:1; overflow-y:auto; padding:20px; display:flex; flex-direction:column; gap:16px; }
  .msg { display:flex; flex-direction:column; gap:4px; }
  .msg-header { font-size:11px; color:var(--muted); }
  .msg.user .msg-header { color:var(--green); }
  .msg.assistant .msg-header { color:var(--accent); }
  .msg-body { white-space:pre-wrap; word-break:break-word; line-height:1.6; font-size:13px; }
  .msg.user .msg-body { color:var(--green); }
  .tool-line { font-size:11px; color:var(--yellow); padding:2px 8px; background:rgba(210,153,34,0.08); border-radius:4px; display:inline-block; }
  .tool-line.done { color:var(--green); background:rgba(63,185,80,0.08); }
  .tool-line.failed { color:var(--red); background:rgba(248,81,73,0.08); }
  .system-line { font-size:11px; color:var(--muted); font-style:italic; }
  .error-line { color:var(--red); font-size:12px; }
  .streaming { border-left:2px solid var(--accent); padding-left:8px; }
  #input-area { padding:16px 20px; border-top:1px solid var(--border); background:#010409; display:flex; gap:8px; align-items:flex-end; }
  #input { flex:1; background:#21262d; color:var(--fg); border:1px solid var(--border); border-radius:8px; padding:10px 14px; font-family:inherit; font-size:13px; resize:none; min-height:42px; max-height:160px; outline:none; }
  #input:focus { border-color:var(--accent); }
  #send-btn { background:var(--accent); color:#0d1117; border:none; border-radius:8px; padding:10px 16px; cursor:pointer; font-weight:600; font-size:13px; white-space:nowrap; }
  .permission-bar { background:rgba(210,153,34,0.15); border:1px solid var(--yellow); border-radius:8px; padding:12px 16px; display:flex; align-items:center; gap:12px; }
  .permission-bar .question { flex:1; font-size:13px; color:var(--yellow); }
  .perm-btn { padding:6px 16px; border-radius:6px; cursor:pointer; font-size:12px; border:1px solid; }
  .perm-approve { background:rgba(63,185,80,0.15); color:var(--green); border-color:var(--green); }
  .perm-deny { background:rgba(248,81,73,0.1); color:var(--red); border-color:var(--red); }
  .choice-bar { background:rgba(88,166,255,0.08); border:1px solid var(--accent); border-radius:8px; padding:16px; display:flex; flex-direction:column; gap:10px; }
  .choice-question { font-size:13px; color:var(--accent); font-weight:600; }
  .choice-options { display:flex; flex-wrap:wrap; gap:8px; }
  .choice-btn { padding:8px 16px; background:#21262d; border:1px solid var(--border); border-radius:6px; cursor:pointer; font-size:12px; font-family:inherit; color:var(--fg); }
  .choice-btn:hover { border-color:var(--accent); color:var(--accent); }
  .readonly-banner { background:rgba(188,140,255,0.12); border-bottom:1px solid var(--purple); color:var(--purple); font-size:12px; padding:10px 20px; text-align:center; }
</style>
</head>
<body>
<div id="header">
  <h1>◆ ATELIER</h1>
  <span id="model-badge">connecting...</span>
  <span id="status">●</span>
</div>
<div id="conversation"></div>
<div id="input-area">
  <textarea id="input" placeholder="Type a message or /command..." rows="1" onkeydown="onKey(event)"></textarea>
  <button id="send-btn" onclick="send()">Send</button>
</div>
<script>
const conv = document.getElementById('conversation');
const input = document.getElementById('input');
const status = document.getElementById('status');
const modelBadge = document.getElementById('model-badge');
let streamEl = null;

function connect() {
  const es = new EventSource('/events');
  es.onopen = () => { status.style.color = '#3fb950'; status.textContent = 'connected'; };
  es.onerror = () => { status.style.color = '#d29922'; status.textContent = 'reconnecting'; };
  es.onmessage = (e) => { try { handleEvent(JSON.parse(e.data)); } catch (_) {} };
}

function handleEvent(ev) {
  switch (ev.type) {
    case 'route.selected':
      if (ev.model) modelBadge.textContent = (ev.provider || '') + '/' + (ev.model || '');
      addSystemLine('\u25c6 ' + (ev.provider || '') + '/' + (ev.model || '') + (ev.reason ? ' \u2014 ' + ev.reason : ''));
      break;
    case 'assistant.delta':
      if (!streamEl) { const m = addMsg('assistant', '\u25c9 Atelier'); streamEl = m.querySelector('.msg-body'); streamEl.className = 'msg-body streaming'; }
      streamEl.textContent += ev.text; scrollBottom(); break;
    case 'assistant.message':
      streamEl = null; addMsg('assistant', '\u25c9 Atelier', ev.text); break;
    case 'tool.requested':
      addToolLine('\u27f3 ' + ev.name + ' ' + JSON.stringify(ev.args || {}).slice(0, 60), ''); break;
    case 'tool.finished':
      addToolLine((ev.ok ? '\u2713' : '\u2717') + ' ' + ev.name, ev.ok ? 'done' : 'failed'); break;
    case 'permission.requested':
      addPermissionBar(ev.id, ev.action, ev.risk); break;
    case 'choice.requested':
      addChoiceBar(ev.id, ev.question, ev.choices || [], ev.allow_freeform !== false); break;
    case 'error':
      addErrorLine(ev.message); break;
    case 'session.started':
      if (ev.model) modelBadge.textContent = (ev.provider || 'auto') + '/' + ev.model;
      addSystemLine('Session: ' + ev.session_id + (ev.git_branch ? ' [' + ev.git_branch + ']' : '')); break;
  }
}

function addMsg(role, header, body) {
  const d = document.createElement('div'); d.className = 'msg ' + role;
  d.innerHTML = '<div class="msg-header">' + esc(header) + '</div><div class="msg-body">' + esc(body || '') + '</div>';
  conv.appendChild(d); scrollBottom(); return d;
}
function addToolLine(text, cls) { const d = document.createElement('div'); d.className = 'tool-line ' + cls; d.textContent = text; conv.appendChild(d); scrollBottom(); }
function addSystemLine(text) { const d = document.createElement('div'); d.className = 'system-line'; d.textContent = text; conv.appendChild(d); }
function addErrorLine(text) { const d = document.createElement('div'); d.className = 'error-line'; d.textContent = '\u26a0 ' + text; conv.appendChild(d); scrollBottom(); }
function addPermissionBar(id, action, risk) {
  const d = document.createElement('div'); d.className = 'permission-bar'; d.id = 'perm-' + id;
  d.innerHTML = '<span class="question">\u26a0 ' + esc(action) + '</span>' +
    '<button class="perm-btn perm-approve" onclick="approvePermission(\'' + id + '\', true)">Approve</button>' +
    '<button class="perm-btn perm-deny" onclick="approvePermission(\'' + id + '\', false)">Deny</button>';
  conv.appendChild(d); scrollBottom();
}
function addChoiceBar(id, question, choices, allowFreeform) {
  const d = document.createElement('div'); d.className = 'choice-bar'; d.id = 'choice-' + id;
  let btns = choices.map((c, i) => '<button class="choice-btn" onclick="sendChoice(\'' + id + '\', \'' + esc(c) + '\')">' + (i+1) + '. ' + esc(c) + '</button>').join('');
  if (allowFreeform) btns += '<button class="choice-btn" onclick="customChoice(\'' + id + '\')">Other...</button>';
  d.innerHTML = '<div class="choice-question">? ' + esc(question) + '</div><div class="choice-options">' + btns + '</div>';
  conv.appendChild(d); scrollBottom();
}
function post(cmd) { fetch('/command', { method: 'POST', body: JSON.stringify(cmd), headers: { 'Content-Type': 'application/json' } }); }
function approvePermission(id, approved) { post({ type: 'permission.response', id, approved, scope: 'once' }); const e = document.getElementById('perm-' + id); if (e) e.remove(); }
function sendChoice(id, response) { post({ type: 'choice.response', id, response }); const e = document.getElementById('choice-' + id); if (e) e.remove(); }
function customChoice(id) { const r = prompt('Enter your response:'); if (r) sendChoice(id, r); }
function scrollBottom() { conv.scrollTop = conv.scrollHeight; }
function esc(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 160) + 'px';
}
function send() {
  const text = input.value.trim(); if (!text) return;
  addMsg('user', '\u25b6 You', text);
  const cmd = text.startsWith('/')
    ? { type: 'user.command', name: text.slice(1).split(' ')[0], args: text.slice(1).split(' ').slice(1).filter(Boolean) }
    : { type: 'user.message', text };
  post(cmd); input.value = ''; input.style.height = '42px';
}
// If URL contains /share/, disable input and show banner (read-only observer).
const isReadOnly = window.location.pathname.startsWith('/share/');
if (isReadOnly) {
  document.getElementById('input-area').style.display = 'none';
  const banner = document.createElement('div');
  banner.className = 'readonly-banner';
  banner.innerHTML = '\u{1F441} Read-only session \u2014 observing live';
  document.body.insertBefore(banner, document.getElementById('conversation'));
}
connect();
</script>
</body>
</html>"#;

/// xterm.js terminal page. Connects to the WS PTY bridge on the SAME port via
/// `/ws/terminal` so cloudflare tunnels and reverse proxies work with a single port.
/// When `session_id` is set, the WebSocket URL carries `?s=<id>` to resume that session.
fn xterm_html(_ws_port: u16, session_id: Option<String>) -> String {
    let ws_query = match session_id {
        Some(ref id) if !id.is_empty() => format!("?s={id}"),
        _ => String::new(),
    };
    format!(
        r#"<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Atelier Terminal</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css"/>
<style>
  html, body {{ background: #0d1117; margin: 0; padding: 0; height: 100%; overflow: hidden; }}
  #terminal {{ height: 100vh; padding: 8px; }}
</style>
</head>
<body>
<div id="terminal"></div>
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
<script>
const term = new Terminal({{
  cursorBlink: true,
  fontSize: 14,
  fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
  theme: {{
    background: '#0d1117',
    foreground: '#c9d1d9',
    cursor: '#58a6ff',
    cursorAccent: '#0d1117',
    black: '#484f58', red: '#ff7b72', green: '#3fb950', yellow: '#d29922',
    blue: '#58a6ff', magenta: '#bc8cff', cyan: '#39c5cf', white: '#b1bac4',
    brightBlack: '#6e7681', brightRed: '#ffa198', brightGreen: '#56d364',
    brightYellow: '#e3b341', brightBlue: '#79c0ff', brightMagenta: '#d2a8ff',
    brightCyan: '#56d4dd', brightWhite: '#f0f6fc',
  }},
  allowProposedApi: true,
}});
const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.open(document.getElementById('terminal'));
fitAddon.fit();

// Use same origin for WebSocket — works with cloudflare tunnels (single port)
const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = wsProto + '//' + location.host + '/ws/terminal{ws_query}';
const ws = new WebSocket(wsUrl);
ws.binaryType = 'arraybuffer';

ws.onopen = () => {{
  term.write('\r\n  \x1b[36m◆\x1b[0m Connecting to Atelier session...\r\n');
  ws.send(JSON.stringify({{ type: 'resize', cols: term.cols, rows: term.rows }}));
}};

ws.onmessage = (e) => {{
  if (e.data instanceof ArrayBuffer) {{
    term.write(new Uint8Array(e.data));
  }}
}};

ws.onclose = () => {{
  term.write('\r\n\r\n  \x1b[33m[Session ended — close this tab or reconnect]\x1b[0m\r\n');
}};

ws.onerror = () => {{
  term.write('\r\n  \x1b[31m[WebSocket error — is atelier-tui running?]\x1b[0m\r\n  Tried: ' + wsUrl + '\r\n');
}};

term.onData((data) => {{
  if (ws.readyState === WebSocket.OPEN) {{
    ws.send(new TextEncoder().encode(data));
  }}
}});

term.onResize(( cols, rows ) => {{
  if (ws.readyState === WebSocket.OPEN) {{
    ws.send(JSON.stringify({{ type: 'resize', cols, rows }}));
  }}
}});

window.addEventListener('resize', () => {{ fitAddon.fit(); }});
</script>
</body>
</html>"#,
        ws_query = ws_query
    )
}
