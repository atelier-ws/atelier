//! NDJSON wire protocol shared with the Python `atelier tui-backend` server.

use serde_json::Value;

/// Events emitted by the Python backend (one JSON object per line on stdout).
#[derive(Debug, Clone, serde::Deserialize)]
#[serde(tag = "type")]
pub enum BackendEvent {
    #[serde(rename = "session.started")]
    SessionStarted {
        session_id: String,
        #[serde(default)]
        project_root: Option<String>,
    },
    #[serde(rename = "route.selected")]
    RouteSelected {
        #[serde(default)]
        provider: Option<String>,
        #[serde(default)]
        model: Option<String>,
        #[serde(default)]
        reason: Option<String>,
    },
    #[serde(rename = "memory.hit")]
    MemoryHit {
        key: String,
        #[serde(default)]
        summary: Option<String>,
    },
    #[serde(rename = "assistant.delta")]
    AssistantDelta { text: String },
    #[serde(rename = "assistant.message")]
    AssistantMessage { text: String },
    #[serde(rename = "tool.requested")]
    ToolRequested {
        id: String,
        name: String,
        #[serde(default)]
        args: Value,
    },
    #[serde(rename = "tool.started")]
    ToolStarted { id: String, name: String },
    #[serde(rename = "tool.output")]
    ToolOutput { id: String, chunk: String },
    #[serde(rename = "tool.finished")]
    ToolFinished { id: String, name: String, ok: bool },
    #[serde(rename = "patch.proposed")]
    PatchProposed {
        id: String,
        files: Vec<String>,
        diff: String,
    },
    #[serde(rename = "permission.requested")]
    PermissionRequested {
        id: String,
        action: String,
        #[serde(default)]
        risk: Option<String>,
    },
    #[serde(rename = "verification.result")]
    VerificationResult {
        ok: bool,
        #[serde(default)]
        rubric: Option<String>,
        #[serde(default)]
        details: Option<String>,
    },
    #[serde(rename = "error")]
    Error {
        message: String,
        #[serde(default)]
        details: Option<String>,
    },
}

/// Commands sent to the Python backend (one JSON object per line on stdin).
#[derive(Debug, Clone, serde::Serialize)]
#[serde(tag = "type")]
pub enum FrontendCommand {
    #[serde(rename = "user.message")]
    UserMessage { text: String },
    #[serde(rename = "user.command")]
    UserCommand { name: String, args: Vec<String> },
    #[serde(rename = "permission.response")]
    PermissionResponse {
        id: String,
        approved: bool,
        scope: String,
    },
    #[serde(rename = "interrupt")]
    Interrupt {},
}
