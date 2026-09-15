"""CLI tests for ``content budget status``.

Covers reading the real default ``config/budgets.yaml`` shape, a
configured Flow budget showing usage, an unconfigured Gemini budget
showing NO_BUDGET, missing/invalid config files, and — critically — that
GEMINI_API_KEY is never printed even when it's set to something
recognizable in the environment.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from content_engine.cli import app

runner = CliRunner()

_FLOW_AND_GEMINI_YAML = """
budgets:
  flow:
    period: daily
    official_limit: 50
    local_budget: 50
    warning_percent: 80
    hard_stop_percent: 100
    reserve_percent: 20
    reset: first_generation_plus_24h
  gemini:
    model: null
    period: provider-defined
    official_limit:
      requests_per_day: null
      tokens_per_day: null
    local_budget:
      requests_per_day: null
      tokens_per_day: null
    warning_percent: 80
    hard_stop_percent: 100
    reserve_percent: 20
    paid_fallback: false
"""


def _write_budget_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "budgets.yaml"
    path.write_text(text)
    return path


class TestBudgetStatus:
    def test_shows_flow_ok_and_gemini_no_budget(self, tmp_path, monkeypatch):
        config_path = _write_budget_config(tmp_path, _FLOW_AND_GEMINI_YAML)

        result = runner.invoke(app, ["budget", "status", "--budget-config", str(config_path)])

        assert result.exit_code == 0, result.output
        assert "flow[requests] status=ok" in result.output
        assert "local_budget=50" in result.output
        # Gemini's default null local_budget means no automated dimension is
        # configured — only the always-checked "requests" dimension appears,
        # and it must report NO_BUDGET (PRD §8.2's safe default).
        assert "gemini[requests] status=no_budget" in result.output
        assert "gemini[tokens]" not in result.output

    def test_shows_configured_gemini_token_dimension(self, tmp_path, monkeypatch):
        config_path = _write_budget_config(
            tmp_path,
            """
budgets:
  gemini:
    model: gemini-2.0-flash
    period: provider-defined
    official_limit:
      requests_per_day: null
      tokens_per_day: null
    local_budget:
      requests_per_day: 100
      tokens_per_day: 50000
    warning_percent: 80
    hard_stop_percent: 100
    reserve_percent: 20
    paid_fallback: false
""",
        )

        result = runner.invoke(app, ["budget", "status", "--budget-config", str(config_path)])

        assert result.exit_code == 0, result.output
        assert "gemini[requests] status=ok" in result.output
        assert "gemini[tokens] status=ok" in result.output
        assert "local_budget=50000" in result.output

    def test_no_budgets_configured(self, tmp_path, monkeypatch):
        config_path = _write_budget_config(tmp_path, "budgets: {}\n")

        result = runner.invoke(app, ["budget", "status", "--budget-config", str(config_path)])

        assert result.exit_code == 0, result.output
        assert "No budgets configured." in result.output

    def test_missing_config_file_fails_clearly(self, tmp_path, monkeypatch):
        result = runner.invoke(
            app, ["budget", "status", "--budget-config", str(tmp_path / "does-not-exist.yaml")]
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_invalid_config_fails_clearly(self, tmp_path, monkeypatch):
        config_path = _write_budget_config(
            tmp_path,
            "budgets:\n"
            "  flow:\n"
            "    period: daily\n"
            "    local_budget: 50\n"
            "    warning_percent: 150\n",
        )
        result = runner.invoke(app, ["budget", "status", "--budget-config", str(config_path)])
        assert result.exit_code == 1
        assert "must be in [0, 100]" in result.output

    def test_never_prints_gemini_api_key(self, tmp_path, monkeypatch):
        config_path = _write_budget_config(tmp_path, _FLOW_AND_GEMINI_YAML)
        monkeypatch.setenv("GEMINI_API_KEY", "sk-super-secret-value-should-never-leak")

        result = runner.invoke(app, ["budget", "status", "--budget-config", str(config_path)])

        assert result.exit_code == 0, result.output
        assert "sk-super-secret-value-should-never-leak" not in result.output
        assert "GEMINI_API_KEY" not in result.output
