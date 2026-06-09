//! Application state for the Atelier TUI.

use crate::protocol::BackendEvent;
use ratatui::layout::Rect;
use ratatui::style::Color;
use ratatui_textarea::TextArea;
use serde_json::Value;
use std::path::Path;

/// A single row in the manual file tree (flat, with depth + expand state).
pub struct TreeNode {
    pub path: String,
    pub name: String,
    pub is_dir: bool,
    pub depth: usize,
    pub expanded: bool,
    pub gitignored: bool,
}

/// Read `.gitignore` patterns from the project root (one per non-comment line).
pub fn load_gitignore_patterns(root: &str) -> Vec<String> {
    let gitignore = Path::new(root).join(".gitignore");
    if !gitignore.exists() {
        return vec![];
    }
    std::fs::read_to_string(gitignore)
        .unwrap_or_default()
        .lines()
        .filter(|l| !l.starts_with('#') && !l.trim().is_empty())
        .map(|l| l.trim().to_string())
        .collect()
}

/// Coarse gitignore match against a relative path (substring/prefix heuristic).
pub fn is_gitignored(rel_path: &str, patterns: &[String]) -> bool {
    let path_lower = rel_path.to_lowercase();
    patterns.iter().any(|p| {
        let p_lower = p.to_lowercase().trim_end_matches('/').trim_start_matches('/').to_string();
        if p_lower.is_empty() {
            return false;
        }
        path_lower == p_lower
            || path_lower.starts_with(&format!("{p_lower}/"))
            || path_lower
                .split('/')
                .any(|seg| seg == p_lower)
    })
}

/// Read one directory level into sorted tree nodes (dirs first, then files).
/// Skips `.git`. Marks gitignored entries so the UI can render them greyed.
fn read_dir_nodes(dir: &Path, depth: usize, root: &Path, patterns: &[String]) -> Vec<TreeNode> {
    let mut entries: Vec<std::fs::DirEntry> =
        std::fs::read_dir(dir).into_iter().flatten().flatten().collect();
    entries.sort_by_key(|e| {
        let is_dir = e.path().is_dir();
        (!is_dir, e.file_name().to_string_lossy().to_lowercase())
    });
    entries
        .into_iter()
        .filter(|e| e.file_name().to_string_lossy() != ".git")
        .map(|e| {
            let path = e.path();
            let is_dir = path.is_dir();
            let name = e.file_name().to_string_lossy().to_string();
            let rel = path
                .strip_prefix(root)
                .unwrap_or(&path)
                .to_string_lossy()
                .to_string();
            TreeNode {
                gitignored: is_gitignored(&rel, patterns),
                path: path.to_string_lossy().to_string(),
                name,
                is_dir,
                depth,
                expanded: false,
            }
        })
        .collect()
}

/// Parse `/sessions` markdown output into session list entries.
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

#[derive(Debug, Clone, PartialEq)]
pub enum TabContent {
    Conversation,             // permanent, can't close
    FileView(String),         // path to file
    DiffView(String, String), // (filename, diff_text) side-by-side
}

impl TabContent {
    pub fn title(&self) -> String {
        match self {
            Self::Conversation => "Conversation".to_string(),
            Self::FileView(p) => std::path::Path::new(p)
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| p.clone()),
            Self::DiffView(f, _) => format!(
                "\u{0394} {}",
                std::path::Path::new(f)
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_else(|| f.clone())
            ),
        }
    }
    pub fn closeable(&self) -> bool {
        !matches!(self, Self::Conversation)
    }
}

#[derive(Debug, Clone, PartialEq, Copy)]
pub enum LeftTab {
    Sessions,
    Files,
    Git,
}

#[derive(Debug, Clone, PartialEq, Copy)]
pub enum RightTab {
    Tools,
    Tasks,
    Subagents,
}

#[derive(Debug, Clone)]
pub struct GitFile {
    pub status: String,
    pub path: String,
}

/// A single commit in the Git history (file list loaded lazily on expand).
#[derive(Debug, Clone)]
pub struct GitCommit {
    pub hash: String,
    pub short_hash: String,
    pub message: String,
    pub author: String,
    pub date: String,
    pub expanded: bool,
    pub files: Vec<String>,
}

/// What a clickable row in the Git tab maps to (rebuilt each frame).
#[derive(Debug, Clone)]
pub enum GitRowKind {
    Commit(usize),
    CommitFile(usize, String),
}

/// Stored layout rectangles for mouse hit-testing (rebuilt each frame).
#[derive(Debug, Clone, Default)]
pub struct PaneRects {
    pub left: Rect,
    pub middle: Rect,
    pub right_top: Rect,
    pub right_bottom: Rect,
    pub input: Rect,
}

#[derive(Debug, Clone, PartialEq)]
pub enum FocusedPane {
    Input,
    Conversation,
    Tools,
    Context,  // context/memory/route
    Sessions, // sessions/agents
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
    ModelPicker { selected: usize, models: Vec<(String, String)> },
    AuthPicker { selected: usize, providers: Vec<String> },
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

#[derive(Debug, Clone)]
pub struct SessionSummary {
    pub id: String,
    pub label: String, // truncated first message or timestamp
    pub is_current: bool,
    pub cost_usd: f64,
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

#[derive(Debug, Clone)]
pub struct DragState {
    pub border: DragBorder,
    pub start_col: u16,
    pub start_pct: u16,
}

#[derive(Debug, Clone, PartialEq)]
pub enum DragBorder {
    /// Right edge of the left pane.
    LeftBorder,
    /// Left edge of the right pane.
    RightBorder,
}

pub struct App<'a> {
    pub conversation: Vec<ConversationEntry>,
    pub tools: Vec<ToolEntry>,
    pub pending_permission: Option<PendingPermission>,
    pub input: TextArea<'a>,
    pub scroll: u16,
    pub tool_scroll: u16,
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
    pub sessions_list: Vec<SessionSummary>,
    pub background_tasks: Vec<BackgroundTask>,
    pub reverse_search: Option<ReverseSearch>,
    pub prompt_suggestions: Vec<String>,
    // Left pane
    pub left_tab: LeftTab,
    pub left_hidden: bool,
    pub git_status: Vec<GitFile>,
    pub git_commits: Vec<GitCommit>,
    pub git_commit_selected: usize,
    /// Maps each rendered Git-tab row (before scroll) to a clickable target.
    pub git_row_targets: Vec<Option<GitRowKind>>,
    // Middle pane (tabbed)
    pub middle_tabs: Vec<TabContent>,
    pub middle_tab_idx: usize,
    pub middle_tab_scroll: Vec<u16>,
    // Right pane
    pub right_tab: RightTab,
    pub right_hidden: bool,
    // Draggable pane sizing (percentages of terminal width)
    pub left_pane_pct: u16,
    pub right_pane_pct: u16,
    pub drag_state: Option<DragState>,
    pub term_width: u16,
    // URL/QR header
    pub local_url: Option<String>,
    pub pinned_header: Option<String>,
    // Left-pane file/git browser scrolling + filtering
    pub files_scroll: u16,
    pub git_scroll: u16,
    pub file_filter: String,
    // Mouse hit-test areas for clickable tabs (rebuilt each frame)
    pub tab_click_areas: Option<Vec<(String, Rect)>>,
    // Manual file tree (devicons-style colors, gitignored shown greyed).
    pub file_tree: Vec<TreeNode>,
    pub file_tree_selected: usize,
    pub gitignore_patterns: Vec<String>,
    // Mouse hit-testing
    pub pane_rects: Option<PaneRects>,
    pub hovered_file_idx: Option<usize>,
    /// First file-tree index rendered in the Files tab (set each frame for hit-testing).
    pub files_view_offset: usize,
}

impl<'a> App<'a> {
    pub fn new(project_root: String) -> Self {
        let gitignore_patterns = load_gitignore_patterns(&project_root);
        let root = Path::new(&project_root);
        let file_tree = read_dir_nodes(root, 0, root, &gitignore_patterns);
        let mut app = App {
            conversation: Vec::new(),
            tools: Vec::new(),
            pending_permission: None,
            input: TextArea::default(),
            scroll: 0,
            tool_scroll: 0,
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
            sessions_list: Vec::new(),
            background_tasks: Vec::new(),
            reverse_search: None,
            prompt_suggestions: Vec::new(),
            left_tab: LeftTab::Sessions,
            left_hidden: false,
            git_status: Vec::new(),
            git_commits: Vec::new(),
            git_commit_selected: 0,
            git_row_targets: Vec::new(),
            middle_tabs: vec![TabContent::Conversation],
            middle_tab_idx: 0,
            middle_tab_scroll: vec![0],
            right_tab: RightTab::Tools,
            right_hidden: false,
            left_pane_pct: 22,
            right_pane_pct: 22,
            drag_state: None,
            term_width: 200,
            local_url: None,
            pinned_header: None,
            files_scroll: 0,
            git_scroll: 0,
            file_filter: String::new(),
            tab_click_areas: None,
            file_tree,
            file_tree_selected: 0,
            gitignore_patterns,
            pane_rects: None,
            hovered_file_idx: None,
            files_view_offset: 0,
        };
        app.refresh_git_status();
        app
    }

    /// Move the file-tree selection up one row.
    pub fn file_tree_up(&mut self) {
        self.file_tree_selected = self.file_tree_selected.saturating_sub(1);
    }

    /// Move the file-tree selection down one row.
    pub fn file_tree_down(&mut self) {
        if self.file_tree_selected + 1 < self.file_tree.len() {
            self.file_tree_selected += 1;
        }
    }

    /// Path + is_dir of the currently selected tree node, if any.
    pub fn file_tree_selected_path(&self) -> Option<(String, bool)> {
        self.file_tree
            .get(self.file_tree_selected)
            .map(|n| (n.path.clone(), n.is_dir))
    }

    /// Expand or collapse the selected directory. No-op on files.
    pub fn file_tree_toggle(&mut self) {
        let i = self.file_tree_selected;
        let Some(node) = self.file_tree.get(i) else {
            return;
        };
        if !node.is_dir {
            return;
        }
        let depth = node.depth;
        if node.expanded {
            self.file_tree[i].expanded = false;
            let mut j = i + 1;
            while j < self.file_tree.len() && self.file_tree[j].depth > depth {
                j += 1;
            }
            self.file_tree.drain(i + 1..j);
        } else {
            let path = node.path.clone();
            let root = Path::new(&self.project_root).to_path_buf();
            let children =
                read_dir_nodes(Path::new(&path), depth + 1, &root, &self.gitignore_patterns);
            self.file_tree[i].expanded = true;
            for (k, child) in children.into_iter().enumerate() {
                self.file_tree.insert(i + 1 + k, child);
            }
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

    pub fn open_file_tab(&mut self, path: String) {
        if !self
            .middle_tabs
            .iter()
            .any(|t| matches!(t, TabContent::FileView(p) if *p == path))
        {
            self.middle_tabs.push(TabContent::FileView(path));
            self.middle_tab_scroll.push(0);
        }
        self.middle_tab_idx = self.middle_tabs.len() - 1;
    }

    pub fn open_diff_tab(&mut self, filename: String, diff: String) {
        self.middle_tabs.push(TabContent::DiffView(filename, diff));
        self.middle_tab_scroll.push(0);
        self.middle_tab_idx = self.middle_tabs.len() - 1;
    }

    pub fn close_tab(&mut self, idx: usize) {
        if idx < self.middle_tabs.len() && self.middle_tabs[idx].closeable() {
            self.middle_tabs.remove(idx);
            if idx < self.middle_tab_scroll.len() {
                self.middle_tab_scroll.remove(idx);
            }
            self.middle_tab_idx = self
                .middle_tab_idx
                .saturating_sub(1)
                .min(self.middle_tabs.len().saturating_sub(1));
        }
    }

    pub fn refresh_git_status(&mut self) {
        let output = std::process::Command::new("git")
            .args(["status", "--porcelain"])
            .current_dir(&self.project_root)
            .output();
        if let Ok(out) = output {
            let text = String::from_utf8_lossy(&out.stdout);
            self.git_status = text
                .lines()
                .filter_map(|l| {
                    if l.len() >= 4 {
                        Some(GitFile {
                            status: l[0..2].trim().to_string(),
                            path: l[3..].to_string(),
                        })
                    } else {
                        None
                    }
                })
                .collect();
        }
        let log_output = std::process::Command::new("git")
            .args(["log", "--pretty=format:%H|%h|%s|%an|%ar", "-15", "--no-color"])
            .current_dir(&self.project_root)
            .output();
        if let Ok(out) = log_output {
            let text = String::from_utf8_lossy(&out.stdout);
            self.git_commits = text
                .lines()
                .filter_map(|line| {
                    let parts: Vec<&str> = line.splitn(5, '|').collect();
                    if parts.len() >= 5 {
                        Some(GitCommit {
                            hash: parts[0].to_string(),
                            short_hash: parts[1].to_string(),
                            message: parts[2].to_string(),
                            author: parts[3].to_string(),
                            date: parts[4].to_string(),
                            expanded: false,
                            files: Vec::new(),
                        })
                    } else {
                        None
                    }
                })
                .collect();
            self.git_commit_selected = self
                .git_commit_selected
                .min(self.git_commits.len().saturating_sub(1));
        }
    }

    /// Expand/collapse a commit, lazily loading its changed-file list on expand.
    pub fn git_commit_toggle(&mut self, idx: usize) {
        let Some(commit) = self.git_commits.get_mut(idx) else {
            return;
        };
        commit.expanded = !commit.expanded;
        if !commit.expanded || !commit.files.is_empty() {
            return;
        }
        let hash = commit.hash.clone();
        let files = if let Ok(output) = std::process::Command::new("git")
            .args(["show", "--name-only", "--pretty=format:", &hash])
            .current_dir(&self.project_root)
            .output()
        {
            let text = String::from_utf8_lossy(&output.stdout);
            text.lines()
                .filter(|l| !l.trim().is_empty())
                .map(|l| l.to_string())
                .collect()
        } else {
            Vec::new()
        };
        if let Some(commit) = self.git_commits.get_mut(idx) {
            commit.files = files;
        }
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
                self.is_streaming = true;
                self.auto_scroll = true;
                self.streaming_text.push_str(&text);
            }
            BackendEvent::AssistantMessage { text } => {
                self.is_streaming = false;
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
                self.conversation.push(ConversationEntry {
                    role: Role::Assistant,
                    text,
                });
            }
            BackendEvent::ToolRequested { id, name, .. } => {
                self.tools.push(ToolEntry {
                    id,
                    name,
                    status: ToolStatus::Requested,
                    output_preview: None,
                });
            }
            BackendEvent::ToolStarted { id, name } => {
                if let Some(t) = self.tools.iter_mut().find(|t| t.id == id) {
                    t.status = ToolStatus::Running;
                } else {
                    self.tools.push(ToolEntry {
                        id,
                        name,
                        status: ToolStatus::Running,
                        output_preview: None,
                    });
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
                });
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

    pub fn cycle_focus(&mut self) {
        self.focused_pane = match self.focused_pane {
            FocusedPane::Input => FocusedPane::Conversation,
            FocusedPane::Conversation => FocusedPane::Tools,
            FocusedPane::Tools => FocusedPane::Context,
            FocusedPane::Context => FocusedPane::Sessions,
            FocusedPane::Sessions => FocusedPane::Input,
        };
    }

    pub fn tool_scroll_up(&mut self) {
        self.tool_scroll = self.tool_scroll.saturating_sub(1);
    }

    pub fn tool_scroll_down(&mut self) {
        self.tool_scroll = self.tool_scroll.saturating_add(1);
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
