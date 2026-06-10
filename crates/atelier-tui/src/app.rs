//! Application state for the Atelier TUI.

use crate::protocol::BackendEvent;
use ratatui::layout::Rect;
use ratatui::style::Color;
use ratatui_textarea::TextArea;
use serde_json::Value;

/// Expected line format: `- ``<id>`` — <date time> (<size>KB)`
pub fn parse_session_list(text: &str) -> Vec<SessionListEntry> {
    let mut out = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if !line.starts_with("- `") {
            continue;
        }
        // id is between the first pair of backticks
        let after = &line[3..];
        let Some(end) = after.find('`') else { continue };
        let id = after[..end].to_string();
        let rest = &after[end + 1..];
        // size: look for "(<n>KB)"
        let size_kb = rest
            .rfind('(')
            .and_then(|i| rest[i + 1..].split("KB").next())
            .and_then(|s| s.trim().parse::<f32>().ok())
            .unwrap_or(0.0);
        // timestamp: text between "— " and " ("
        let timestamp = rest
            .split('—')
            .nth(1)
            .map(|s| s.split('(').next().unwrap_or("").trim().to_string())
            .unwrap_or_default();
        out.push(SessionListEntry {
            id,
            timestamp,
            size_kb,
        });
    }
    out
}

/// Extract a file path from a tool result payload (read/edit return `{"path": ...}` or similar).
fn extract_path_from_result(result: &Option<Value>) -> Option<String> {
    let v = result.as_ref()?;
    if let Some(obj) = v.as_object() {
        for key in ["path", "file", "file_path", "filename"] {
            if let Some(Value::String(s)) = obj.get(key) {
                if !s.is_empty() {
                    return Some(s.clone());
                }
            }
        }
    }
    None
}

/// Fuzzy-match *path* against *query*, returning a higher score for better matches.
pub fn fuzzy_score(path: &str, query: &str) -> i32 {
    if query.is_empty() {
        return 0;
    }
    let p = path.to_lowercase();
    let q = query.to_lowercase();
    // Exact match
    if p == q {
        return 100;
    }
    // Filename matches (give bonus to filename vs full path)
    let filename = p.split('/').next_back().unwrap_or(&p);
    if filename == q {
        return 95;
    }
    if filename.starts_with(&q) {
        return 85;
    }
    // Prefix match on full path
    if p.starts_with(&q) {
        return 80;
    }
    // Substring in filename
    if filename.contains(&q) {
        return 70;
    }
    // Substring in path
    if p.contains(&q) {
        return 60;
    }
    // Sequential character match (all chars of query appear in order in path)
    let mut pi = p.chars();
    let mut score = 0i32;
    let mut matched = 0;
    for qc in q.chars() {
        loop {
            match pi.next() {
                Some(pc) if pc == qc => {
                    matched += 1;
                    score += 1;
                    break;
                }
                Some(_) => {
                    score -= 1;
                }
                None => return -1, // query char not found
            }
        }
    }
    if matched == q.chars().count() {
        score.max(1)
    } else {
        -1
    }
}

/// Provider prefix of a model id (`anthropic/claude-…` → `anthropic`).
pub fn model_provider(model_id: &str) -> &str {
    model_id.split('/').next().unwrap_or(model_id)
}

/// Filter *models* by a case-insensitive substring (matched against id + description)
/// and return them ordered by provider so groups are contiguous. The returned flat
/// list is the single source of truth for the picker's selection index — both the
/// renderer and the key handler iterate it identically.
pub fn filter_grouped_models(
    models: &[(String, String)],
    filter: &str,
) -> Vec<(String, String)> {
    let f = filter.to_lowercase();
    let mut filtered: Vec<(String, String)> = models
        .iter()
        .filter(|(id, desc)| {
            f.is_empty() || id.to_lowercase().contains(&f) || desc.to_lowercase().contains(&f)
        })
        .cloned()
        .collect();
    // Stable sort keeps original order within each provider group.
    filtered.sort_by(|a, b| model_provider(&a.0).cmp(model_provider(&b.0)));
    filtered
}

/// A right-click context menu anchored at a terminal cell.
#[derive(Debug, Clone)]
pub struct ContextMenu {
    pub x: u16,
    pub y: u16,
    pub items: Vec<ContextItem>,
    pub selected: usize,
}

#[derive(Debug, Clone)]
pub struct ContextItem {
    pub label: String,
    pub key: char, // keyboard shortcut shown in menu
    pub action: ContextAction,
}

#[derive(Debug, Clone)]
pub enum ContextAction {
    CopyLastMessage,
    SearchInConversation,
    ClearConversation,
    NewTask,
}

#[derive(Debug, Clone, PartialEq)]
pub enum FocusedPane {
    Input,
    #[allow(dead_code)]
    Conversation,
}

#[derive(Debug, Clone, PartialEq)]
pub enum CompletionMode {
    None,
    SlashCommand {
        selected: usize,
        filter: String,
    },
    FileRef {
        selected: usize,
        filter: String,
        files: Vec<String>,
    },
}

pub const SLASH_COMMANDS: &[(&str, &str)] = &[
    ("help", "Show available commands"),
    ("tools", "List available tools"),
    ("memory", "Search Atelier memory: /memory <query>"),
    ("route", "Show routing decision: /route <task>"),
    ("approve", "Approve pending permission request"),
    ("deny", "Deny pending permission request"),
    ("auth", "Configure provider authentication: /auth [provider]"),
    ("share", "Share read-only session link: /share"),
    ("export", "Export conversation to Markdown file"),
    ("diff", "Show pending diff"),
    ("verify", "Run verification"),
    ("model", "Switch model: /model <provider/model-string>"),
    ("edit", "Open a file in $EDITOR: /edit <file>"),
    (
        "context",
        "Show context stats (turns, tokens, tool results)",
    ),
    ("usage", "Detailed token/context usage breakdown"),
    ("permissions", "Show/manage tool permissions: /permissions"),
    ("yolo", "Toggle auto-approve all tool calls: /yolo"),
    (
        "analytics",
        "Show session analytics (turns, tools, tokens, mode)",
    ),
    (
        "agents",
        "Switch agent mode: /agents <code|explore|research|plan>",
    ),
    ("background", "Background the current session"),
    ("tasks", "List background tasks: /tasks"),
    ("plan", "Read-only exploration mode: /plan <task>"),
    ("btw", "Ephemeral side question (not added to history): /btw <question>"),
    ("mcp", "List MCP servers"),
    ("compact", "Compact/summarize conversation to free context"),
    ("cost", "Show session cost"),
    ("doctor", "System health check"),
    ("allowed-tools", "List available tools (alias: /tools)"),
    ("version", "Show Atelier version"),
    ("newtask", "Clear conversation, start fresh"),
    (
        "checkpoint",
        "Save conversation checkpoint: /checkpoint [label]",
    ),
    ("rewind", "Restore to checkpoint: /rewind [id]"),
    ("resume", "Resume a saved session (alias: /sessions)"),
    ("timeline", "Browse sessions in a navigable timeline overlay"),
    (
        "shell",
        "Run a shell command directly: !<cmd> or /shell <cmd>",
    ),
    ("clear", "Clear conversation"),
    ("exit", "Exit Atelier"),
];

#[derive(Debug, Clone)]
pub struct ReverseSearch {
    pub query: String,
    pub matches: Vec<usize>, // indices into message_history
    pub current: usize,
}

#[derive(Debug, Clone, PartialEq)]
pub enum PendingPermission {
    Waiting {
        id: String,
        action: String,
        risk: String,
    },
}

#[derive(Debug, Clone)]
pub struct PendingChoice {
    pub id: String,
    pub question: String,
    pub choices: Vec<String>,
    pub selected: usize,
    pub allow_freeform: bool,
    pub custom_input: String, // for freeform
    pub input_mode: bool,     // true = typing custom response
}

#[derive(Debug, Clone, PartialEq, Copy)]
pub enum AgentMode {
    Code,     // default — full tools, blue accent
    Explore,  // read-only — read/grep/symbols, green
    Research, // research — read/grep/web, purple
    Plan,     // planning — read/grep only, orange
}

impl AgentMode {
    pub fn name(&self) -> &'static str {
        match self {
            Self::Code => "CODE",
            Self::Explore => "EXPLORE",
            Self::Research => "RESEARCH",
            Self::Plan => "PLAN",
        }
    }
    pub fn accent_color(&self) -> Color {
        match self {
            Self::Code => Color::Cyan,
            Self::Explore => Color::Green,
            Self::Research => Color::Magenta,
            Self::Plan => Color::Yellow,
        }
    }
    #[allow(dead_code)]
    pub fn tools(&self) -> &'static [&'static str] {
        match self {
            Self::Code => &["read", "edit", "shell", "grep", "explore"],
            Self::Explore => &["read", "grep", "explore"],
            Self::Research => &["read", "grep", "explore"],
            Self::Plan => &["read", "grep"],
        }
    }
    pub fn next(&self) -> Self {
        match self {
            Self::Code => Self::Explore,
            Self::Explore => Self::Research,
            Self::Research => Self::Plan,
            Self::Plan => Self::Code,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum ActiveOverlay {
    None,
    Help,
    AgentPicker { selected: usize },
    ModelPicker { selected: usize, models: Vec<(String, String)>, filter: String },
    AuthPicker { selected: usize, providers: Vec<String> },
    CommandPalette { query: String, selected: usize },
    SessionTimeline { entries: Vec<SessionTimelineEntry>, selected: usize },
    WhichKey { leader_pressed: bool, pending_keys: Vec<char> },
}

#[derive(Debug, Clone, PartialEq)]
pub struct SessionTimelineEntry {
    pub id: String,
    pub timestamp: String,
    pub message_count: usize,
    pub size_kb: f32,
    pub summary: String, // first 60 chars of first message
}

/// Convert a parsed session-list entry into a richer timeline entry.
/// The flat session-list text only carries id/timestamp/size, so the message
/// count is estimated from the on-disk size and the summary is left empty until
/// the backend supplies one.
fn session_entry_to_timeline(e: SessionListEntry) -> SessionTimelineEntry {
    let message_count = (e.size_kb.round() as usize).max(1);
    SessionTimelineEntry {
        id: e.id,
        timestamp: e.timestamp,
        message_count,
        size_kb: e.size_kb,
        summary: String::new(),
    }
}

#[derive(Debug, Clone)]
pub struct SearchState {
    pub query: String,
    pub matches: Vec<usize>,  // indices into conversation
    pub current_match: usize, // index into matches
}

#[derive(Debug, Clone)]
pub struct SessionListEntry {
    pub id: String,
    pub timestamp: String,
    pub size_kb: f32,
}

#[derive(Debug, Clone)]
pub enum Role {
    User,
    Assistant,
    System,
}

#[derive(Debug, Clone)]
pub struct ConversationEntry {
    pub role: Role,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum ToolStatus {
    Requested,
    Running,
    Done,
    Failed,
}

#[derive(Debug, Clone)]
pub struct ToolEntry {
    pub id: String,
    pub name: String,
    pub status: ToolStatus,
    pub output_preview: Option<String>,
    pub elapsed_ms: Option<u64>,
    pub started_at: Option<std::time::Instant>,
}

#[derive(Debug, Clone, Default)]
pub struct ContextStats {
    pub model: String,
    pub provider: String,
    pub cache_efficiency: f64,
    pub total_cost_usd: f64,
    pub total_savings_usd: f64,
    pub input_tokens: u64,
    pub cache_read_tokens: u64,
    pub cache_write_tokens: u64,
    pub estimated_context_pct: f64, // used context as % of model's window
    pub memory_hits: Vec<String>,   // recent memory hits
}

#[derive(Debug, Clone, PartialEq)]
pub enum TaskStatus {
    Running,
    Done,
    Failed,
}

#[derive(Debug, Clone)]
pub struct BackgroundTask {
    pub id: String,
    pub name: String,
    pub status: TaskStatus,
}

pub struct App<'a> {
    pub conversation: Vec<ConversationEntry>,
    pub tools: Vec<ToolEntry>,
    pub pending_permission: Option<PendingPermission>,
    pub input: TextArea<'a>,
    pub scroll: u16,
    pub focused_pane: FocusedPane,
    pub should_quit: bool,
    pub session_id: String,
    pub project_root: String,
    pub current_model: String,
    pub git_branch: String,
    pub streaming_text: String,
    pub is_streaming: bool,
    pub pending_diff: Option<String>,
    pub cache_efficiency: Option<f64>,
    pub cost_usd: f64,
    pub savings_usd: f64,
    pub auto_scroll: bool,
    pub needs_api_key: bool,
    pub completion_mode: CompletionMode,
    pub recent_files: Vec<String>,
    pub message_history: Vec<String>,
    pub history_cursor: Option<usize>,
    pub total_cost_usd: f64,
    pub total_savings_usd: f64,
    pub pending_choice: Option<PendingChoice>,
    pub agent_mode: AgentMode,
    pub search: Option<SearchState>,
    pub session_list: Vec<SessionListEntry>,
    pub show_session_picker: bool,
    pub session_picker_selected: usize,
    pub last_ctrl_c: Option<std::time::Instant>,
    pub web_port: Option<u16>,
    pub tunnel_url: Option<String>,
    pub qr_lines: Vec<String>,
    pub open_editor: Option<String>,
    pub active_overlay: ActiveOverlay,
    pub context_stats: ContextStats,
    pub background_tasks: Vec<BackgroundTask>,
    pub reverse_search: Option<ReverseSearch>,
    pub prompt_suggestions: Vec<String>,
    pub local_url: Option<String>,
    pub term_width: u16,
    pub conv_rect: Rect,
    pub input_rect: Rect,
    pub context_menu: Option<ContextMenu>,
    pub pending_context_action: Option<ContextAction>,
    // Professional grade additions
    pub show_side_panel: bool,
    pub spinner_tick: u8,
    pub streaming_start: Option<std::time::Instant>,
    pub tool_count: usize,
    pub selection_mode: bool,         // when true, mouse capture is OFF — native terminal selection works
    pub pending_mouse_toggle: Option<bool>,
    pub pending_esc: Option<std::time::Instant>, // for ESC+Enter → Alt+Enter detection // Some(true)=enable capture, Some(false)=disable it
    pub tool_expanded: std::collections::HashSet<String>, // ids of tools whose output is expanded inline
    // Desktop-notification bookkeeping
    pub last_activity_time: std::time::Instant, // updated on every keypress
    pub notification_pending: Option<String>,   // set when agent finishes while user is idle
}

impl<'a> App<'a> {
    pub fn new(project_root: String) -> Self {
        App {
            conversation: Vec::new(),
            tools: Vec::new(),
            pending_permission: None,
            input: TextArea::default(),
            scroll: 0,
            focused_pane: FocusedPane::Input,
            should_quit: false,
            session_id: String::new(),
            project_root,
            current_model: String::new(),
            git_branch: String::new(),
            streaming_text: String::new(),
            is_streaming: false,
            pending_diff: None,
            cache_efficiency: None,
            cost_usd: 0.0,
            savings_usd: 0.0,
            auto_scroll: true,
            needs_api_key: false,
            completion_mode: CompletionMode::None,
            recent_files: Vec::new(),
            message_history: Vec::new(),
            history_cursor: None,
            total_cost_usd: 0.0,
            total_savings_usd: 0.0,
            pending_choice: None,
            agent_mode: AgentMode::Code,
            search: None,
            session_list: Vec::new(),
            show_session_picker: false,
            session_picker_selected: 0,
            last_ctrl_c: None,
            web_port: None,
            tunnel_url: None,
            qr_lines: Vec::new(),
            open_editor: None,
            active_overlay: ActiveOverlay::None,
            context_stats: ContextStats::default(),
            background_tasks: Vec::new(),
            reverse_search: None,
            prompt_suggestions: Vec::new(),
            local_url: None,
            term_width: 200,
            conv_rect: Rect::default(),
            input_rect: Rect::default(),
            context_menu: None,
            pending_context_action: None,
            show_side_panel: true,
            spinner_tick: 0,
            streaming_start: None,
            tool_count: 0,
            selection_mode: false,
            pending_mouse_toggle: None,
            pending_esc: None,
            tool_expanded: std::collections::HashSet::new(),
            last_activity_time: std::time::Instant::now(),
            notification_pending: None,
        }
    }

    fn push_system(&mut self, text: String) {
        self.conversation.push(ConversationEntry {
            role: Role::System,
            text,
        });
    }

    pub fn push_system_pub(&mut self, text: String) {
        self.push_system(text);
    }

    /// Apply an incoming backend event to the app state.
    pub fn handle_event(&mut self, event: BackendEvent) {
        match event {
            BackendEvent::SessionStarted {
                session_id,
                project_root,
                model,
                git_branch,
                has_api_key,
                ..
            } => {
                self.session_id = session_id.clone();
                if let Some(root) = project_root {
                    self.project_root = root;
                }
                if let Some(m) = model {
                    self.current_model = m;
                }
                if let Some(b) = git_branch {
                    self.git_branch = b;
                }
                self.needs_api_key = !has_api_key.unwrap_or(true);
                self.push_system(format!("session started: {session_id}"));
                if let Some(port) = self.web_port {
                    self.push_system(format!(
                        "\u{25c6} Web interface: http://localhost:{port}  (use --tunnel for remote access)"
                    ));
                }
            }
            BackendEvent::RouteSelected {
                provider,
                model,
                reason,
            } => {
                if let Some(m) = model.clone() {
                    self.current_model = m;
                }
                let p = provider.unwrap_or_default();
                let m = model.unwrap_or_default();
                if !p.is_empty() {
                    self.context_stats.provider = p.clone();
                }
                if !m.is_empty() {
                    self.context_stats.model = m.clone();
                }
                let r = reason.map(|r| format!(" ({r})")).unwrap_or_default();
                self.push_system(format!("route: {p}/{m}{r}"));
            }
            BackendEvent::MemoryHit { key, summary } => {
                let s = summary.unwrap_or_default();
                let label = if s.is_empty() {
                    key.clone()
                } else {
                    format!("{key}: {s}")
                };
                let preview: String = label.chars().take(60).collect();
                self.context_stats.memory_hits.push(preview);
                while self.context_stats.memory_hits.len() > 5 {
                    self.context_stats.memory_hits.remove(0);
                }
                self.push_system(format!("memory[{key}]: {s}"));
            }
            BackendEvent::AssistantDelta { text } => {
                if !self.is_streaming {
                    self.streaming_start = Some(std::time::Instant::now());
                }
                self.is_streaming = true;
                self.auto_scroll = true;
                self.streaming_text.push_str(&text);
            }
            BackendEvent::AssistantMessage { text } => {
                self.is_streaming = false;
                self.streaming_start = None;
                self.auto_scroll = true;
                self.streaming_text.clear();
                if self.show_session_picker {
                    let parsed = parse_session_list(&text);
                    if !parsed.is_empty() {
                        self.session_list = parsed;
                        self.session_picker_selected = 0;
                        return;
                    }
                }
                if let ActiveOverlay::SessionTimeline { entries, selected } = &mut self.active_overlay {
                    let parsed = parse_session_list(&text);
                    if !parsed.is_empty() {
                        *entries = parsed.into_iter().map(session_entry_to_timeline).collect();
                        *selected = 0;
                        return;
                    }
                }
                self.conversation.push(ConversationEntry {
                    role: Role::Assistant,
                    text,
                });
                // If the user has been idle for >3s the terminal is likely blurred —
                // queue a desktop notification (sent from the main loop where async
                // process spawning is available).
                if self.last_activity_time.elapsed().as_secs() >= 3 {
                    self.notification_pending =
                        Some("Atelier: Agent response ready".to_string());
                }
            }
            BackendEvent::ToolRequested { id, name, .. } => {
                self.tools.push(ToolEntry {
                    id,
                    name,
                    status: ToolStatus::Requested,
                    output_preview: None,
                    elapsed_ms: None,
                    started_at: None,
                });
                self.tool_count += 1;
            }
            BackendEvent::ToolStarted { id, name } => {
                if let Some(t) = self.tools.iter_mut().find(|t| t.id == id) {
                    t.status = ToolStatus::Running;
                    t.started_at = Some(std::time::Instant::now());
                } else {
                    self.tools.push(ToolEntry {
                        id,
                        name,
                        status: ToolStatus::Running,
                        output_preview: None,
                        elapsed_ms: None,
                        started_at: Some(std::time::Instant::now()),
                    });
                    self.tool_count += 1;
                }
            }
            BackendEvent::ToolOutput { id, chunk } => {
                if let Some(t) = self.tools.iter_mut().find(|t| t.id == id) {
                    let preview: String = chunk.chars().take(120).collect();
                    t.output_preview = Some(preview);
                }
            }
            BackendEvent::ToolFinished {
                id,
                name,
                ok,
                result,
            } => {
                if let Some(t) = self.tools.iter_mut().find(|t| t.id == id) {
                    t.status = if ok {
                        ToolStatus::Done
                    } else {
                        ToolStatus::Failed
                    };
                    if let Some(start) = t.started_at {
                        t.elapsed_ms = Some(start.elapsed().as_millis() as u64);
                    }
                }
                if ok && (name == "read" || name == "edit") {
                    if let Some(path) = extract_path_from_result(&result) {
                        if !self.recent_files.contains(&path) {
                            self.recent_files.push(path);
                        }
                    }
                }
            }
            BackendEvent::PatchProposed { files, diff, .. } => {
                self.pending_diff = Some(format!("Files: {}\n\n{}", files.join(", "), diff));
                self.push_system(format!("patch proposed: {}", files.join(", ")));
            }
            BackendEvent::PermissionRequested { id, action, risk } => {
                self.pending_permission = Some(PendingPermission::Waiting {
                    id,
                    action,
                    risk: risk.unwrap_or_else(|| "medium".to_string()),
                });
            }
            BackendEvent::ChoiceRequested {
                id,
                question,
                choices,
                allow_freeform,
            } => {
                self.pending_choice = Some(PendingChoice {
                    id,
                    question,
                    choices,
                    selected: 0,
                    allow_freeform: allow_freeform.unwrap_or(true),
                    custom_input: String::new(),
                    input_mode: false,
                });
            }
            BackendEvent::VerificationResult {
                ok,
                rubric,
                details,
            } => {
                let status = if ok { "ok" } else { "failed" };
                let r = rubric.unwrap_or_default();
                let d = details.unwrap_or_default();
                self.push_system(format!("verification {status}: {r} {d}"));
            }
            BackendEvent::Error { message, details } => {
                if message.contains("Loop detected") || message.contains("loop") {
                    self.tools.push(ToolEntry {
                        id: "supervision".to_string(),
                        name: format!("\u{26a0} {message}"),
                        status: ToolStatus::Failed,
                        output_preview: None,
                        elapsed_ms: None,
                        started_at: None,
                    });
                }
                let d = details.map(|d| format!(" — {d}")).unwrap_or_default();
                self.push_system(format!("error: {message}{d}"));
            }
            BackendEvent::CacheStats {
                cache_efficiency_pct,
                cost_usd,
                savings_usd,
                ..
            } => {
                self.cache_efficiency = Some(cache_efficiency_pct);
                self.cost_usd = cost_usd;
                self.savings_usd = savings_usd;
                self.total_cost_usd += cost_usd;
                self.total_savings_usd += savings_usd;
                self.context_stats.cache_efficiency = cache_efficiency_pct;
                self.context_stats.total_cost_usd = self.total_cost_usd;
                self.context_stats.total_savings_usd = self.total_savings_usd;
            }
            BackendEvent::ContextUsageUpdated {
                input_tokens,
                cache_read_tokens,
                cache_write_tokens,
                output_tokens,
                model_context_window,
                cache_efficiency_pct,
                cost_usd,
                ..
            } => {
                self.context_stats.input_tokens = input_tokens;
                self.context_stats.cache_read_tokens = cache_read_tokens;
                self.context_stats.cache_write_tokens = cache_write_tokens;
                if cache_efficiency_pct > 0.0 {
                    self.context_stats.cache_efficiency = cache_efficiency_pct;
                }
                if cost_usd > 0.0 {
                    self.context_stats.total_cost_usd = self.total_cost_usd;
                }
                if self.context_stats.model.is_empty() {
                    self.context_stats.model = self.current_model.clone();
                }
                let used = input_tokens + cache_read_tokens + output_tokens;
                let window = model_context_window.max(1);
                self.context_stats.estimated_context_pct =
                    (used as f64 / window as f64 * 100.0).min(100.0);
            }
            BackendEvent::ShellStarted { id, command } => {
                self.tools.push(ToolEntry {
                    id,
                    name: format!("shell: {command}"),
                    status: ToolStatus::Running,
                    output_preview: None,
                    elapsed_ms: None,
                    started_at: Some(std::time::Instant::now()),
                });
                self.tool_count += 1;
            }
            BackendEvent::ShellOutput { id, chunk } => {
                if let Some(t) = self.tools.iter_mut().find(|t| t.id == id) {
                    let preview: String = chunk.chars().take(120).collect();
                    t.output_preview = Some(preview);
                }
            }
            BackendEvent::ShellFinished { id, ok, .. } => {
                if let Some(t) = self.tools.iter_mut().find(|t| t.id == id) {
                    t.status = if ok {
                        ToolStatus::Done
                    } else {
                        ToolStatus::Failed
                    };
                    if let Some(start) = t.started_at {
                        t.elapsed_ms = Some(start.elapsed().as_millis() as u64);
                    }
                }
            }
            BackendEvent::TaskCreated { id, name } => {
                self.background_tasks.push(BackgroundTask {
                    id,
                    name,
                    status: TaskStatus::Running,
                });
            }
            BackendEvent::TaskUpdated { id, status } => {
                if let Some(t) = self.background_tasks.iter_mut().find(|t| t.id == id) {
                    t.status = match status.as_str() {
                        "done" => TaskStatus::Done,
                        "failed" => TaskStatus::Failed,
                        _ => TaskStatus::Running,
                    };
                }
            }
            BackendEvent::CheckpointCreated { label, .. } => {
                self.push_system(format!("checkpoint: {label}"));
            }
            BackendEvent::PromptSuggestion { text } => {
                self.prompt_suggestions.push(text);
                if self.prompt_suggestions.len() > 3 {
                    self.prompt_suggestions.remove(0);
                }
            }
        }
    }

    pub fn scroll_up(&mut self) {
        self.scroll = self.scroll.saturating_sub(3);
    }

    pub fn scroll_down(&mut self) {
        self.scroll = self.scroll.saturating_add(3);
    }

    #[allow(dead_code)]
    pub fn cycle_focus(&mut self) {
        self.focused_pane = match self.focused_pane {
            FocusedPane::Input => FocusedPane::Conversation,
            FocusedPane::Conversation => FocusedPane::Input,
        };
    }

    /// Expand/collapse the inline output of the most recent (last) tool call.
    pub fn toggle_last_tool_expanded(&mut self) {
        if let Some(tool) = self.tools.last() {
            let id = tool.id.clone();
            if !self.tool_expanded.remove(&id) {
                self.tool_expanded.insert(id);
            }
        }
    }

    pub fn filtered_slash_commands(&self, filter: &str) -> Vec<(&'static str, &'static str)> {
        let f = filter.to_lowercase();
        SLASH_COMMANDS
            .iter()
            .filter(|(name, _)| f.is_empty() || name.contains(f.as_str()))
            .copied()
            .collect()
    }

    pub fn filtered_files(&self, filter: &str) -> Vec<String> {
        if let CompletionMode::FileRef { files, .. } = &self.completion_mode {
            let mut scored: Vec<(i32, String)> = files
                .iter()
                .filter_map(|p| {
                    let s = fuzzy_score(p, filter);
                    if filter.is_empty() || s > 0 {
                        Some((s, p.clone()))
                    } else {
                        None
                    }
                })
                .collect();
            // Recent files at top, then by score desc
            scored.sort_by(|a, b| {
                let a_recent = self.recent_files.contains(&a.1);
                let b_recent = self.recent_files.contains(&b.1);
                match (a_recent, b_recent) {
                    (true, false) => std::cmp::Ordering::Less,
                    (false, true) => std::cmp::Ordering::Greater,
                    _ => b.0.cmp(&a.0),
                }
            });
            scored.into_iter().map(|(_, p)| p).take(50).collect()
        } else {
            vec![]
        }
    }

    pub fn history_up(&mut self) -> Option<String> {
        if self.message_history.is_empty() {
            return None;
        }
        let idx = match self.history_cursor {
            None => self.message_history.len() - 1,
            Some(0) => 0,
            Some(i) => i - 1,
        };
        self.history_cursor = Some(idx);
        self.message_history.get(idx).cloned()
    }

    pub fn history_down(&mut self) -> Option<String> {
        match self.history_cursor {
            None => None,
            Some(i) if i + 1 >= self.message_history.len() => {
                self.history_cursor = None;
                Some(String::new()) // clear input
            }
            Some(i) => {
                self.history_cursor = Some(i + 1);
                self.message_history.get(i + 1).cloned()
            }
        }
    }

    pub fn completion_select_up(&mut self) {
        match &mut self.completion_mode {
            CompletionMode::SlashCommand { selected, filter } => {
                let count = SLASH_COMMANDS
                    .iter()
                    .filter(|(name, _)| {
                        filter.is_empty() || name.contains(filter.to_lowercase().as_str())
                    })
                    .count();
                if count > 0 {
                    *selected = selected.saturating_sub(1);
                }
            }
            CompletionMode::FileRef {
                selected,
                filter,
                files,
            } => {
                let count = files
                    .iter()
                    .filter(|p| filter.is_empty() || fuzzy_score(p, filter) > 0)
                    .count();
                if count > 0 {
                    *selected = selected.saturating_sub(1);
                }
            }
            CompletionMode::None => {}
        }
    }

    pub fn completion_select_down(&mut self) {
        match &mut self.completion_mode {
            CompletionMode::SlashCommand { selected, filter } => {
                let count = SLASH_COMMANDS
                    .iter()
                    .filter(|(name, _)| {
                        filter.is_empty() || name.contains(filter.to_lowercase().as_str())
                    })
                    .count();
                if count > 0 && *selected + 1 < count {
                    *selected += 1;
                }
            }
            CompletionMode::FileRef {
                selected,
                filter,
                files,
            } => {
                let count = files
                    .iter()
                    .filter(|p| filter.is_empty() || fuzzy_score(p, filter) > 0)
                    .count();
                if count > 0 && *selected + 1 < count {
                    *selected += 1;
                }
            }
            CompletionMode::None => {}
        }
    }

    pub fn search_conversation(&mut self, query: &str) {
        let q = query.to_lowercase();
        let matches: Vec<usize> = self
            .conversation
            .iter()
            .enumerate()
            .filter(|(_, entry)| entry.text.to_lowercase().contains(&q))
            .map(|(i, _)| i)
            .collect();
        let current = 0;
        if !matches.is_empty() {
            // Scroll to first match
            self.auto_scroll = false;
            self.scroll = (matches[0] as u16).saturating_mul(3); // rough estimate
        }
        self.search = Some(SearchState {
            query: query.to_string(),
            matches,
            current_match: current,
        });
    }

    pub fn search_next(&mut self) {
        if let Some(ref mut s) = self.search {
            if s.matches.is_empty() {
                return;
            }
            s.current_match = (s.current_match + 1) % s.matches.len();
            let msg_idx = s.matches[s.current_match];
            self.auto_scroll = false;
            self.scroll = (msg_idx as u16).saturating_mul(3);
        }
    }

    pub fn search_prev(&mut self) {
        if let Some(ref mut s) = self.search {
            if s.matches.is_empty() {
                return;
            }
            if s.current_match == 0 {
                s.current_match = s.matches.len() - 1;
            } else {
                s.current_match -= 1;
            }
            let msg_idx = s.matches[s.current_match];
            self.auto_scroll = false;
            self.scroll = (msg_idx as u16).saturating_mul(3);
        }
    }
}
