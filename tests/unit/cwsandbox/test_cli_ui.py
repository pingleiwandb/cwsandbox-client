# SPDX-FileCopyrightText: 2025 CoreWeave, Inc.
# SPDX-License-Identifier: Apache-2.0
# SPDX-PackageName: cwsandbox-client

"""Tests for the cwsandbox ui CLI command."""

from __future__ import annotations

from types import ModuleType
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from cwsandbox.cli import cli


class _FakeApp:
    """Simple stand-in for the Textual app."""

    init_kwargs: dict[str, Any] | None = None
    run_called = False

    def __init__(self, **kwargs: Any) -> None:
        type(self).init_kwargs = kwargs
        type(self).run_called = False

    def run(self) -> None:
        type(self).run_called = True


class TestUICommand:
    """Tests for the cwsandbox ui CLI command."""

    def test_ui_registered(self) -> None:
        """UI command is registered on the CLI group."""
        runner = CliRunner()
        result = runner.invoke(cli, ["ui", "--help"])
        assert result.exit_code == 0
        assert "--refresh-seconds" in result.output
        assert "--include-stopped" in result.output

    def test_ui_missing_textual_dependency(self) -> None:
        """cwsandbox ui shows a focused install hint when Textual is unavailable."""

        def _raise_import_error(name: str) -> ModuleType:
            raise ModuleNotFoundError("No module named 'textual'", name="textual")

        with patch("cwsandbox.cli.ui.importlib.import_module", side_effect=_raise_import_error):
            runner = CliRunner()
            result = runner.invoke(cli, ["ui"])

        assert result.exit_code == 1
        assert "cwsandbox[tui]" in result.output

    def test_ui_runs_textual_app_with_expected_options(self) -> None:
        """cwsandbox ui passes parsed CLI options through to the Textual app."""
        fake_module = ModuleType("cwsandbox.cli._ui_app")
        fake_module.CWSandboxUIApp = _FakeApp

        with patch("cwsandbox.cli.ui.importlib.import_module", return_value=fake_module):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "ui",
                    "--status",
                    "running",
                    "--tag",
                    "batch",
                    "--runway-id",
                    "default",
                    "--tower-id",
                    "t-1",
                    "--refresh-seconds",
                    "5",
                    "--tail",
                    "50",
                    "--include-stopped",
                ],
            )

        assert result.exit_code == 0
        assert _FakeApp.run_called is True
        assert _FakeApp.init_kwargs == {
            "status": "running",
            "tags": ("batch",),
            "runway_ids": ("default",),
            "tower_ids": ("t-1",),
            "refresh_seconds": 5.0,
            "tail_lines": 50,
            "include_stopped": True,
        }
