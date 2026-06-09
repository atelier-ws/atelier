//! Tunnel detection and spawning for remote web access.
use std::process::Stdio;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

/// Try to start a tunnel to the given local port.
/// Returns the public URL if successful, or None.
pub async fn try_start_tunnel(port: u16) -> Option<(String, tokio::process::Child)> {
    // Try cloudflared first
    if which_available("cloudflared").await {
        if let Some(result) = start_cloudflared(port).await {
            return Some(result);
        }
    }
    // Try bore
    if which_available("bore").await {
        if let Some(result) = start_bore(port).await {
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
        .args([
            "tunnel",
            "--url",
            &format!("http://localhost:{port}"),
            "--no-autoupdate",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    let stderr = child.stderr.take()?;
    let mut lines = BufReader::new(stderr).lines();

    // cloudflared prints the URL to stderr
    let deadline = tokio::time::Instant::now() + Duration::from_secs(15);
    while tokio::time::Instant::now() < deadline {
        match tokio::time::timeout(Duration::from_secs(2), lines.next_line()).await {
            Ok(Ok(Some(line))) => {
                // Look for URL pattern: https://....trycloudflare.com
                if let Some(url) = extract_url(&line) {
                    return Some((url, child));
                }
            }
            _ => break,
        }
    }
    child.kill().await.ok();
    None
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
    // Find https?://[^\s]+ pattern
    let prefixes = ["https://", "http://"];
    for prefix in prefixes {
        if let Some(start) = line.find(prefix) {
            let rest = &line[start..];
            let end = rest
                .find(|c: char| c.is_whitespace() || c == '"' || c == '\'')
                .unwrap_or(rest.len());
            let url = &rest[..end];
            if url.len() > prefix.len() + 3 {
                return Some(url.to_string());
            }
        }
    }
    None
}
