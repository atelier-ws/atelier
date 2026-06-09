//! Application state for the Atelier TUI.

use crate::protocol::BackendEvent;
use ratatui_textarea::TextArea;

#[derive(Debug, Clone, PartialEq)]
pub enum FocusedPane {
    Input,
    Conversation,
    Tools,
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
    ("sessions", "List saved sessions"),
    ("session", "Switch session: /session <id>"),
    ("approve", "Approve pending permission request"),
    ("deny", "Deny pending permission request"),
    ("diff", "Show pending diff"),
    ("verify", "Run verification"),
    ("context", "Run context capability"),
    ("background", "Show background service status"),
    ("clear", "Clear conversation"),
    ("exit", "Exit Atelier"),
];

#[derive(Debug, Clone, PartialEq)]
pub enum PendingPermission {
    Waiting {
        id: String,
        action: String,
        risk: String,
    },
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
}

impl<'a> App<'a> {
    pub fn new(project_root: String) -> Self {
        App {
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
        }
    }

    fn push_system(&mut self, text: String) {
        self.conversation.push(ConversationEntry {
            role: Role::System,
            text,
        });
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
                let r = reason.map(|r| format!(" ({r})")).unwrap_or_default();
                self.push_system(format!("route: {p}/{m}{r}"));
            }
            BackendEvent::MemoryHit { key, summary } => {
                let s = summary.unwrap_or_default();
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
            BackendEvent::ToolFinished { id, ok, .. } => {
                if let Some(t) = self.tools.iter_mut().find(|t| t.id == id) {
                    t.status = if ok { ToolStatus::Done } else { ToolStatus::Failed };
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
            BackendEvent::VerificationResult { ok, rubric, details } => {
                let status = if ok { "ok" } else { "failed" };
                let r = rubric.unwrap_or_default();
                let d = details.unwrap_or_default();
                self.push_system(format!("verification {status}: {r} {d}"));
            }
            BackendEvent::Error { message, details } => {
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
            FocusedPane::Tools => FocusedPane::Input,
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
            let f = filter.to_lowercase();
            files
                .iter()
                .filter(|p| f.is_empty() || p.to_lowercase().contains(&f))
                .cloned()
                .collect()
        } else {
            vec![]
        }
    }

    pub fn completion_select_up(&mut self) {
        match &mut self.completion_mode {
            CompletionMode::SlashCommand { selected, filter } => {
                let count = SLASH_COMMANDS
                    .iter()
                    .filter(|(name, _)| filter.is_empty() || name.contains(filter.to_lowercase().as_str()))
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
                let f = filter.to_lowercase();
                let count = files
                    .iter()
                    .filter(|p| f.is_empty() || p.to_lowercase().contains(&f))
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
                    .filter(|(name, _)| filter.is_empty() || name.contains(filter.to_lowercase().as_str()))
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
                let f = filter.to_lowercase();
                let count = files
                    .iter()
                    .filter(|p| f.is_empty() || p.to_lowercase().contains(&f))
                    .count();
                if count > 0 && *selected + 1 < count {
                    *selected += 1;
                }
            }
            CompletionMode::None => {}
        }
    }
}
