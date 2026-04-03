# SPDX-FileCopyrightText: 2025 CoreWeave, Inc.
# SPDX-License-Identifier: Apache-2.0
# SPDX-PackageName: cwsandbox-client

"""cwsandbox ui — interactive Textual interface for sandboxes."""

from __future__ import annotations

import importlib

import click

from cwsandbox import SandboxStatus

_STATUS_CHOICES = [s.value for s in SandboxStatus if s != SandboxStatus.UNSPECIFIED]
_TUI_DEPENDENCY_ROOTS = {
    "linkify_it",
    "markdown_it",
    "mdit_py_plugins",
    "platformdirs",
    "pygments",
    "rich",
    "textual",
}


def _load_ui_app() -> type[object]:
    """Import the Textual app lazily so the base CLI doesn't require Textual."""
    try:
        module = importlib.import_module("cwsandbox.cli._ui_app")
    except ModuleNotFoundError as exc:
        missing = (getattr(exc, "name", "") or "").split(".", 1)[0]
        if missing in _TUI_DEPENDENCY_ROOTS:
            raise click.ClickException(
                "cwsandbox ui requires the 'tui' extra.\n"
                "Install it with: pip install cwsandbox[tui]"
            ) from None
        raise

    app_class = getattr(module, "CWSandboxUIApp", None)
    if not isinstance(app_class, type):
        raise click.ClickException("Failed to load the CWSandbox Textual app.")
    return app_class


@click.command("ui")
@click.option(
    "--status",
    "-s",
    default=None,
    type=click.Choice(_STATUS_CHOICES, case_sensitive=False),
    help="Filter by status.",
)
@click.option("--tag", "-t", "tags", multiple=True, help="Filter by tag (repeatable).")
@click.option(
    "--runway-id", "-r", "runway_ids", multiple=True, help="Filter by runway ID (repeatable)."
)
@click.option(
    "--tower-id", "-T", "tower_ids", multiple=True, help="Filter by tower ID (repeatable)."
)
@click.option(
    "--refresh-seconds",
    default=3.0,
    type=click.FloatRange(min=0.2, min_open=False),
    show_default=True,
    help="Automatic list refresh interval in seconds.",
)
@click.option(
    "--tail",
    "tail_lines",
    default=200,
    type=click.IntRange(min=0),
    show_default=True,
    help="Initial number of log lines to show for the selected sandbox.",
)
@click.option(
    "--include-stopped",
    is_flag=True,
    default=False,
    help="Include terminal sandboxes in the list.",
)
def ui(
    status: str | None,
    tags: tuple[str, ...],
    runway_ids: tuple[str, ...],
    tower_ids: tuple[str, ...],
    refresh_seconds: float,
    tail_lines: int,
    include_stopped: bool,
) -> None:
    """Open an interactive Textual UI for browsing sandboxes."""
    app_class = _load_ui_app()
    app = app_class(
        status=status,
        tags=tags,
        runway_ids=runway_ids,
        tower_ids=tower_ids,
        refresh_seconds=refresh_seconds,
        tail_lines=tail_lines,
        include_stopped=include_stopped,
    )
    app.run()
