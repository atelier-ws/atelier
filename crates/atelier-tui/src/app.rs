//! Application state for the Atelier TUI.

use crate::protocol::BackendEvent;
use ratatui_textarea::TextArea;

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
    pub should_quit: bool,
    pub session_id: String,
    pub project_root: String,
    pub current_model: String,
    pub streaming_text: String,
    pub is_streaming: bool,
}

impl<'a> App<'a> {
    pub fn new(project_root: String) -> Self {
        App {
            conversation: Vec::new(),
            tools: Vec::new(),
            pending_permission: None,
            input: TextArea::default(),
            scroll: 0,
            should_quit: false,
            session_id: String::new(),
            project_root,
            current_model: String::new(),
            streaming_text: String::new(),
            is_streaming: false,
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
            } => {
                self.session_id = session_id.clone();
                if let Some(root) = project_root {
                    self.project_root = root;
                }
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
                self.streaming_text.push_str(&text);
            }
            BackendEvent::AssistantMessage { text } => {
                self.is_streaming = false;
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
            BackendEvent::PatchProposed { files, .. } => {
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
        }
    }

    pub fn scroll_up(&mut self) {
        self.scroll = self.scroll.saturating_sub(3);
    }

    pub fn scroll_down(&mut self) {
        self.scroll = self.scroll.saturating_add(3);
    }
}
