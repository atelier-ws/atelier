//! Tunnel detection and spawning for remote web access.
use std::process::Stdio;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

/// Try to start a tunnel to the given local port.
/// Returns the public URL if successful, or None.
pub async fn try_start_tunnel(port: u16) -> Option<(String, tokio::process::Child)> {
    // Try bore first (simpler, no ToS friction)
    if which_available("bore").await {
        if let Some(result) = start_bore(port).await {
            return Some(result);
        }
    }
    // Try cloudflared
    if which_available("cloudflared").await {
        if let Some(result) = start_cloudflared(port).await {
            return Some(result);
        }
    }
    // Try localtunnel (lt)
    if which_available("lt").await {
        if let Some(result) = start_localtunnel(port).await {
            return Some(result);
        }
    }
    None
}

async fn which_available(cmd: &str) -> bool {
    tokio::process::Command::new("which")
        .arg(cmd)
        .output()
        .await
        .map(|o| o.status.success())
        .unwrap_or(false)
}

async fn start_cloudflared(port: u16) -> Option<(String, tokio::process::Child)> {
    let mut child = Command::new("cloudflared")
        .args(["tunnel", "--url", &format!("http://localhost:{port}")])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    // Spawn two tasks to read stdout and stderr concurrently — cloudflared may
    // print the URL to either depending on version.
    let stdout = child.stdout.take()?;
    let stderr = child.stderr.take()?;

    let (url_tx, url_rx) = tokio::sync::oneshot::channel::<String>();
    let url_tx = std::sync::Arc::new(std::sync::Mutex::new(Some(url_tx)));

    let tx1 = url_tx.clone();
    tokio::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if let Some(url) = extract_url(&line) {
                if let Some(tx) = tx1.lock().unwrap().take() {
                    let _ = tx.send(url);
                }
                return;
            }
        }
    });

    let tx2 = url_tx.clone();
    tokio::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if let Some(url) = extract_url(&line) {
                if let Some(tx) = tx2.lock().unwrap().take() {
                    let _ = tx.send(url);
                }
                return;
            }
        }
    });

    match tokio::time::timeout(Duration::from_secs(20), url_rx).await {
        Ok(Ok(url)) => Some((url, child)),
        _ => {
            child.kill().await.ok();
            None
        }
    }
}

async fn start_bore(port: u16) -> Option<(String, tokio::process::Child)> {
    let mut child = Command::new("bore")
        .args(["local", &port.to_string(), "--to", "bore.pub"])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    let stdout = child.stdout.take()?;
    let mut lines = BufReader::new(stdout).lines();

    let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
    while tokio::time::Instant::now() < deadline {
        match tokio::time::timeout(Duration::from_secs(2), lines.next_line()).await {
            Ok(Ok(Some(line))) => {
                if let Some(url) = extract_url(&line) {
                    return Some((url, child));
                }
                // bore format: "listening at bore.pub:PORT"
                if line.contains("bore.pub:") {
                    if let Some(port_str) = line.split("bore.pub:").nth(1) {
                        let bore_port = port_str.trim();
                        return Some((format!("http://bore.pub:{bore_port}"), child));
                    }
                }
            }
            _ => break,
        }
    }
    child.kill().await.ok();
    None
}

async fn start_localtunnel(port: u16) -> Option<(String, tokio::process::Child)> {
    let mut child = Command::new("lt")
        .args(["--port", &port.to_string()])
        .stdout(Stdio::piped())
        .spawn()
        .ok()?;

    let stdout = child.stdout.take()?;
    let mut lines = BufReader::new(stdout).lines();

    if let Ok(Ok(Some(line))) =
        tokio::time::timeout(Duration::from_secs(5), lines.next_line()).await
    {
        if let Some(url) = extract_url(&line) {
            return Some((url, child));
        }
    }
    child.kill().await.ok();
    None
}

fn extract_url(line: &str) -> Option<String> {
    let prefixes = ["https://", "http://"];
    for prefix in prefixes {
        if let Some(start) = line.find(prefix) {
            let rest = &line[start..];
            let end = rest
                .find(|c: char| c.is_whitespace() || c == '"' || c == '\'')
                .unwrap_or(rest.len());
            let url = &rest[..end];
            if url.len() <= prefix.len() + 3 {
                continue;
            }
            // Only accept real tunnel URLs — filter out cloudflare marketing/terms pages
            let is_tunnel = url.contains("trycloudflare.com")
                || url.contains("bore.pub")
                || url.contains("loca.lt")
                || url.contains("ngrok")
                || url.contains("serveo.net");
            let is_junk = url.contains("/terms") || url.contains("/tos") || url.contains("cloudflare.com/");
            if is_tunnel && !is_junk {
                return Some(url.to_string());
            }
        }
    }
    None
}
