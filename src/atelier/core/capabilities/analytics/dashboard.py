"""Simple web analytics dashboard served via HTTP."""
from __future__ import annotations

import json

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Atelier Analytics</title>
<style>
  :root { --bg: #0d1117; --fg: #c9d1d9; --accent: #58a6ff; --green: #3fb950; --yellow: #d29922; --red: #f85149; --border: #21262d; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'SF Mono', monospace; background: var(--bg); color: var(--fg); padding: 24px; }
  h1 { color: var(--accent); margin-bottom: 24px; font-size: 20px; }
  h2 { color: var(--fg); margin: 20px 0 12px; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .stat-card { background: #161b22; border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
  .stat-label { font-size: 11px; color: #8b949e; text-transform: uppercase; margin-bottom: 8px; }
  .stat-value { font-size: 24px; font-weight: bold; color: var(--accent); }
  .stat-sub { font-size: 11px; color: #8b949e; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); color: #8b949e; font-weight: normal; }
  td { padding: 8px 12px; border-bottom: 1px solid #0d1117; }
  tr:hover { background: #161b22; }
  .efficiency-bar { background: #21262d; border-radius: 4px; height: 6px; margin-top: 4px; }
  .efficiency-fill { background: var(--green); border-radius: 4px; height: 6px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
  .badge-green { background: rgba(63,185,80,0.15); color: var(--green); }
  .badge-yellow { background: rgba(210,153,34,0.15); color: var(--yellow); }
</style>
</head>
<body>
<h1>\u25c6 Atelier Analytics</h1>

<div class="stats-grid" id="stats"></div>

<h2>Recent Sessions</h2>
<table>
  <thead><tr><th>Session</th><th>Model</th><th>Mode</th><th>Cache</th><th>Cost</th><th>Saved</th><th>Turns</th><th>Time</th></tr></thead>
  <tbody id="sessions"></tbody>
</table>

<script>
fetch('/api/analytics').then(r => r.json()).then(data => {
  const s = data.summary;
  document.getElementById('stats').innerHTML = `
    <div class="stat-card"><div class="stat-label">Total Sessions</div><div class="stat-value">${s.total_sessions || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Total Cost</div><div class="stat-value">$${(s.total_cost_usd || 0).toFixed(4)}</div></div>
    <div class="stat-card"><div class="stat-label">Total Savings</div><div class="stat-value" style="color:var(--green)">$${(s.total_savings_usd || 0).toFixed(4)}</div><div class="stat-sub">vs naive baseline</div></div>
    <div class="stat-card"><div class="stat-label">Avg Cache Efficiency</div><div class="stat-value">${(s.avg_cache_efficiency_pct || 0).toFixed(1)}%</div><div class="efficiency-bar"><div class="efficiency-fill" style="width:${s.avg_cache_efficiency_pct || 0}%"></div></div></div>
    <div class="stat-card"><div class="stat-label">Total Turns</div><div class="stat-value">${s.total_turns || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Tool Calls</div><div class="stat-value">${s.total_tool_calls || 0}</div></div>
  `;
  const tbody = document.getElementById('sessions');
  (data.sessions || []).forEach(s => {
    const eff = (s.cache_efficiency_pct || 0).toFixed(0);
    const badge = eff > 60 ? 'badge-green' : 'badge-yellow';
    tbody.innerHTML += `<tr>
      <td style="font-family:monospace;color:#58a6ff">${s.session_id.slice(0,20)}</td>
      <td>${(s.model || '').split('/').pop() || '-'}</td>
      <td>${s.mode || '-'}</td>
      <td><span class="badge ${badge}">${eff}%</span></td>
      <td>$${(s.total_cost_usd || 0).toFixed(4)}</td>
      <td style="color:var(--green)">$${(s.total_savings_usd || 0).toFixed(4)}</td>
      <td>${s.turns || 0}</td>
      <td>${s.started_at ? s.started_at.slice(0,16) : '-'}</td>
    </tr>`;
  });
});
</script>
</body>
</html>"""


def serve_dashboard(port: int = 8799) -> None:
    """Serve the analytics dashboard on a local HTTP server."""
    import http.server
    import threading
    import webbrowser

    from atelier.core.capabilities.analytics.store import AnalyticsStore

    class DashboardHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML_TEMPLATE.encode())
            elif self.path == "/api/analytics":
                store = AnalyticsStore()
                data = {
                    "summary": store.summary_stats(),
                    "sessions": [
                        {
                            "session_id": s.session_id,
                            "model": s.model,
                            "mode": s.mode,
                            "cache_efficiency_pct": s.cache_efficiency_pct,
                            "total_cost_usd": s.total_cost_usd,
                            "total_savings_usd": s.total_savings_usd,
                            "turns": s.turns,
                            "started_at": s.started_at,
                        }
                        for s in store.recent_sessions(50)
                    ],
                }
                store.close()
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass  # suppress access logs

    server = http.server.HTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://localhost:{port}"
    print(f"  \u25c6 Atelier Analytics Dashboard: {url}")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()


__all__ = ["serve_dashboard"]
