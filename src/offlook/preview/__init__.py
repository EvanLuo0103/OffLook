"""Public entry point for a single local preview window."""
from pathlib import Path


def launch_preview(path: str | Path, *, context=None, renderers=None,
                   always_on_top: bool | None = None) -> int:
    """Show one preview and return its exit code; call on the main thread."""
    from offlook.core.context import create_context
    from offlook.gui import PreviewApplication

    app = PreviewApplication(context or create_context(), renderers=renderers,
                             always_on_top=always_on_top)
    app.open(path)
    return app.run()
