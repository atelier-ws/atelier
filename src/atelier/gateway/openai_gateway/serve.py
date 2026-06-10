"""Entry point for ``atelier serve-openai``.

Starts the Atelier OpenAI-compatible HTTP server via uvicorn.
"""
from __future__ import annotations


def serve(
    port: int = 8790,
    host: str = "0.0.0.0",
    project_root: str | None = None,
    yolo: bool = True,
    reload: bool = False,
) -> None:
    """Start the OpenAI-compatible gateway server.

    Args:
        port: TCP port to bind (default 8787).
        host: Bind address (default 0.0.0.0 — all interfaces).
        project_root: Working directory passed to the Atelier runtime.
        yolo: Auto-approve all tool permission prompts (default True for
            gateway mode — the TUI cannot respond to interactive prompts).
        reload: Enable uvicorn hot-reload (development only).
    """
    import uvicorn

    from .app import create_app

    app = create_app(project_root=project_root, yolo=yolo)
    uvicorn.run(app, host=host, port=port, log_level="info", reload=reload)
