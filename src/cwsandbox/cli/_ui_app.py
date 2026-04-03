# SPDX-FileCopyrightText: 2025 CoreWeave, Inc.
# SPDX-License-Identifier: Apache-2.0
# SPDX-PackageName: cwsandbox-client

"""Textual application backing `cwsandbox ui`."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import click
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Log, Static

from cwsandbox import Sandbox
from cwsandbox.cli.shell import run_shell_session


@dataclass(frozen=True)
class _Filters:
    status: str | None
    tags: tuple[str, ...]
    runway_ids: tuple[str, ...]
    tower_ids: tuple[str, ...]
    include_stopped: bool


@dataclass(frozen=True)
class _SandboxRow:
    sandbox_id: str
    status: str
    tower_id: str
    runway_id: str
    started_at: str


def _format_started_at(started_at: datetime | None) -> str:
    if started_at is None:
        return "-"
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return started_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _to_row(sandbox: Sandbox) -> _SandboxRow:
    sandbox_id = sandbox.sandbox_id or "-"
    status = sandbox.status.value if sandbox.status is not None else "-"
    return _SandboxRow(
        sandbox_id=sandbox_id,
        status=status,
        tower_id=sandbox.tower_id or "-",
        runway_id=sandbox.runway_id or "-",
        started_at=_format_started_at(sandbox.started_at),
    )


class CWSandboxUIApp(App[None]):
    """Interactive Textual app for browsing sandboxes."""

    TITLE = "CWSandbox UI"
    CSS = """
    Screen {
        layout: vertical;
    }

    #summary {
        height: auto;
        min-height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }

    #body {
        height: 1fr;
    }

    #table-pane {
        width: 3fr;
        border-right: wide $surface-darken-1;
    }

    #log-pane {
        width: 4fr;
    }

    .pane-title {
        height: auto;
        padding: 0 1;
        background: $panel;
        color: $text;
        text-style: bold;
    }

    DataTable,
    Log {
        height: 1fr;
    }
    """
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("s", "open_shell", "Shell"),
        Binding("question_mark", "show_help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        status: str | None,
        tags: tuple[str, ...],
        runway_ids: tuple[str, ...],
        tower_ids: tuple[str, ...],
        refresh_seconds: float,
        tail_lines: int,
        include_stopped: bool,
    ) -> None:
        super().__init__()
        self._sandbox_filters = _Filters(
            status=status,
            tags=tags,
            runway_ids=runway_ids,
            tower_ids=tower_ids,
            include_stopped=include_stopped,
        )
        self._refresh_seconds = refresh_seconds
        self._tail_lines = tail_lines
        self._follow_logs = True
        self._loading = False
        self._rows: list[_SandboxRow] = []
        self._selected_sandbox_id: str | None = None
        self._last_error: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Loading sandboxes...", id="summary")
        with Horizontal(id="body"):
            with Vertical(id="table-pane"):
                yield Static("Sandboxes", classes="pane-title")
                yield DataTable(
                    id="sandboxes",
                    cursor_type="row",
                    zebra_stripes=True,
                )
            with Vertical(id="log-pane"):
                yield Static("Entrypoint logs", id="log-title", classes="pane-title")
                yield Log(id="logs", auto_scroll=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#sandboxes", DataTable)
        table.add_columns("SANDBOX ID", "STATUS", "TOWER", "RUNWAY", "STARTED AT")
        table.focus()
        self._write_log_message("Loading sandboxes...")
        self._update_summary()
        self.set_interval(self._refresh_seconds, self.action_refresh)
        self.action_refresh()

    @property
    def _table(self) -> DataTable:
        return self.query_one("#sandboxes", DataTable)

    @property
    def _logs(self) -> Log:
        return self.query_one("#logs", Log)

    def _write_log_message(self, message: str) -> None:
        self._logs.clear()
        self._logs.write_line(message)

    def _update_log_title(self) -> None:
        follow_label = "follow" if self._follow_logs else "snapshot"
        if self._selected_sandbox_id is None:
            title = f"Entrypoint logs ({follow_label})"
        else:
            title = f"Entrypoint logs ({follow_label}) — {self._selected_sandbox_id}"
        self.query_one("#log-title", Static).update(title)

    def _filter_summary(self) -> str:
        filters: list[str] = []
        if self._sandbox_filters.status is not None:
            filters.append(f"status={self._sandbox_filters.status}")
        if self._sandbox_filters.tags:
            filters.append(f"tags={','.join(self._sandbox_filters.tags)}")
        if self._sandbox_filters.runway_ids:
            filters.append(f"runways={','.join(self._sandbox_filters.runway_ids)}")
        if self._sandbox_filters.tower_ids:
            filters.append(f"towers={','.join(self._sandbox_filters.tower_ids)}")
        if self._sandbox_filters.include_stopped:
            filters.append("include_stopped=true")
        return "; ".join(filters) if filters else "none"

    def _update_summary(self) -> None:
        state = "Refreshing" if self._loading else "Ready"
        if self._last_error is not None:
            state = f"Error: {self._last_error}"
        selected = self._selected_sandbox_id or "none"
        summary = (
            f"{state} | sandboxes={len(self._rows)} | selected={selected} | "
            f"follow={'on' if self._follow_logs else 'off'} | "
            f"refresh={self._refresh_seconds:.1f}s | filters={self._filter_summary()}"
        )
        self.query_one("#summary", Static).update(summary)
        self.sub_title = summary
        self._update_log_title()

    def _set_selected_sandbox(self, sandbox_id: str | None, *, clear_logs: bool = True) -> None:
        if sandbox_id == self._selected_sandbox_id and not clear_logs:
            return

        self._selected_sandbox_id = sandbox_id
        self._update_summary()
        if sandbox_id is None:
            self.workers.cancel_group(self, "logs")
            self._write_log_message("No sandbox selected.")
            return

        self._restart_logs(clear=clear_logs)

    def _apply_rows(self, rows: list[_SandboxRow]) -> None:
        self._rows = rows
        table = self._table
        table.clear()

        for row in rows:
            table.add_row(
                row.sandbox_id,
                row.status,
                row.tower_id,
                row.runway_id,
                row.started_at,
                key=row.sandbox_id,
            )

        if not rows:
            self._set_selected_sandbox(None)
            self._write_log_message("No sandboxes match the current filters.")
            self._update_summary()
            return

        previous_selected_id = self._selected_sandbox_id
        selected_id = previous_selected_id
        row_keys = {row.sandbox_id for row in rows}
        if selected_id not in row_keys:
            selected_id = rows[0].sandbox_id

        assert selected_id is not None
        self._selected_sandbox_id = selected_id
        selected_index = next(
            index for index, row in enumerate(rows) if row.sandbox_id == selected_id
        )
        table.move_cursor(row=selected_index, column=0, animate=False)
        self._update_summary()
        if selected_id != previous_selected_id:
            self._restart_logs(clear=False)

    def _restart_logs(self, *, clear: bool) -> None:
        sandbox_id = self._selected_sandbox_id
        if sandbox_id is None:
            return

        if clear:
            self._write_log_message(f"Loading entrypoint logs for {sandbox_id}...")
        self._stream_selected_logs(sandbox_id, self._follow_logs)

    @work(group="sandboxes", exclusive=True, exit_on_error=False)
    async def _refresh_sandboxes(self) -> None:
        self._loading = True
        self._last_error = None
        self._update_summary()

        try:
            sandboxes = await Sandbox.list(
                tags=list(self._sandbox_filters.tags) if self._sandbox_filters.tags else None,
                status=self._sandbox_filters.status,
                runway_ids=(
                    list(self._sandbox_filters.runway_ids)
                    if self._sandbox_filters.runway_ids
                    else None
                ),
                tower_ids=(
                    list(self._sandbox_filters.tower_ids)
                    if self._sandbox_filters.tower_ids
                    else None
                ),
                include_stopped=self._sandbox_filters.include_stopped,
            )
        except asyncio.CancelledError:
            self._loading = False
            self._update_summary()
            raise
        except Exception as exc:
            self._loading = False
            self._last_error = str(exc)
            self._update_summary()
            self.notify(str(exc), title="Sandbox refresh failed", severity="error")
            return

        self._loading = False
        self._last_error = None
        self._apply_rows([_to_row(sandbox) for sandbox in sandboxes])
        self._update_summary()

    @work(group="logs", exclusive=True, exit_on_error=False)
    async def _stream_selected_logs(self, sandbox_id: str, follow: bool) -> None:
        try:
            sandbox = await Sandbox.from_id(sandbox_id)
            reader = sandbox.stream_logs(
                follow=follow,
                tail_lines=self._tail_lines,
                timestamps=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if sandbox_id == self._selected_sandbox_id:
                self._write_log_message(f"Failed to load logs for {sandbox_id}: {exc}")
                self.notify(str(exc), title="Log stream failed", severity="error")
            return

        line_count = 0
        try:
            async for line in reader:
                if sandbox_id != self._selected_sandbox_id:
                    break
                if line_count == 0:
                    self._logs.clear()
                self._logs.write(line)
                line_count += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if sandbox_id == self._selected_sandbox_id:
                self._write_log_message(f"Failed to stream logs for {sandbox_id}: {exc}")
                self.notify(str(exc), title="Log stream failed", severity="error")
        finally:
            reader.close()

        if line_count == 0 and sandbox_id == self._selected_sandbox_id:
            self._write_log_message(
                f"No entrypoint logs available for {sandbox_id}."
                if not follow
                else f"Waiting for entrypoint logs from {sandbox_id}..."
            )

    @on(DataTable.RowHighlighted, "#sandboxes")
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        sandbox_id = str(event.row_key.value)
        if sandbox_id == self._selected_sandbox_id:
            return
        self._set_selected_sandbox(sandbox_id)

    def action_refresh(self) -> None:
        self._refresh_sandboxes()

    def action_toggle_follow(self) -> None:
        self._follow_logs = not self._follow_logs
        self._update_summary()
        if self._selected_sandbox_id is not None:
            self._restart_logs(clear=True)

    def action_show_help(self) -> None:
        self.notify(
            "Use Up/Down to change the selected sandbox. Press r to refresh, "
            "f to toggle live log following, s to open a shell, and q to quit.",
            title="CWSandbox UI",
            severity="information",
        )

    def action_open_shell(self) -> None:
        sandbox_id = self._selected_sandbox_id
        if sandbox_id is None:
            self.notify("Select a sandbox first.", title="No selection", severity="warning")
            return

        try:
            with self.suspend():
                exit_code = run_shell_session(sandbox_id, "/bin/bash")
        except click.ClickException as exc:
            self.notify(str(exc), title="Shell failed", severity="error")
            return

        if exit_code not in (0, 130):
            self.notify(
                f"Shell exited with code {exit_code}.",
                title="Shell exited",
                severity="warning",
            )
        self.action_refresh()
        self._restart_logs(clear=False)
