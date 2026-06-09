//! Browser bridge for atelier-tui (SSE-based, no external HTTP crates).
//!
//! When `--web [PORT]` is passed, this starts a tiny HTTP server using only
//! `tokio::net::TcpListener` + manual HTTP parsing that:
//!   1. Serves an embedded single-page HTML client on `GET /`
//!   2. Streams backend events to browsers via Server-Sent Events on `GET /events`
//!   3. Accepts browser commands on `POST /command` and forwards them to the backend
//!
//! The HTML client uses the `EventSource` API for events and `fetch` for commands.

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::sync::{broadcast, mpsc};

pub const DEFAULT_WEB_PORT: u16 = 7777;

/// Start the SSE bridge server. `event_tx` carries serialized backend event
/// lines (one JSON object per message); `cmd_tx` receives serialized frontend
/// command lines from the browser.
pub async fn start_web_server(
    port: u16,
    event_tx: broadcast::Sender<String>,
    cmd_tx: mpsc::Sender<String>,
) -> anyhow::Result<()> {
    let listener = TcpListener::bind(format!("127.0.0.1:{port}")).await?;
    eprintln!("\n  \u{25c6} Atelier web interface: http://localhost:{port}\n");

    loop {
        let (stream, _) = listener.accept().await?;
        let event_tx = event_tx.clone();
        let cmd_tx = cmd_tx.clone();
        tokio::spawn(async move {
            let _ = handle_connection(stream, event_tx, cmd_tx).await;
        });
    }
}

async fn handle_connection(
    mut stream: tokio::net::TcpStream,
    event_tx: broadcast::Sender<String>,
    cmd_tx: mpsc::Sender<String>,
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

    if method == "GET" && (path == "/" || path.starts_with("/?")) {
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            WEB_UI_HTML.len(),
            WEB_UI_HTML,
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
connect();
</script>
</body>
</html>"#;
