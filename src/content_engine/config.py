"""Application configuration — settings, secrets, and budget YAML loading/validation.

ARCHITECTURE §5 (Quota, Budget & Threshold Architecture), §5.4 (YAML config file).

Secrets and environment configuration come from environment variables via
pydantic-settings. Budget policy overrides live in a YAML file whose path is
configurable via the ``BUDGET_CONFIG`` env var (default: ``./config/budgets.yaml``).
"""

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from content_engine.budgets.models import BudgetPeriod


class AppSettings(BaseSettings):
    """Application settings loaded from environment variables.

    All secrets (API keys) come from the environment — never committed.
    Paths are configurable for different deployment targets.

    Env var mapping uses UPPER_CASE names as documented in .env.example:
        CONTENT_ENGINE_ENV, GEMINI_API_KEY, ASSET_ROOT,
        CONFIG_ROOT, BUDGET_CONFIG.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(
        default="development",
        description="Application environment (development, staging, production)",
    )
    gemini_api_key: str | None = Field(
        default=None, description="Google Gemini API key — never commit to VCS"
    )
    gemini_model: str | None = Field(
        default=None, description="Gemini model name for text generation (e.g. gemini-2.0-flash)"
    )
    asset_root: str = Field(default="./assets", description="Root directory for generated assets")
    config_root: str = Field(
        default="./config", description="Root directory for configuration files"
    )
    budget_config: str = Field(
        default="./config/budgets.yaml", description="Path to budget YAML config file"
    )

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"env must be one of {allowed}, got '{v}'")
        return v


class BudgetConfigError(Exception):
    """Raised when the budget YAML config is invalid."""


def load_budget_yaml(config_path: str | Path) -> dict[str, Any]:
    """Load and parse the budget YAML config file.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Parsed config dict with a ``budgets`` top-level key.

    Raises:
        BudgetConfigError: If the file cannot be read or parsed.
    """
    path = Path(config_path)
    if not path.is_file():
        raise BudgetConfigError(f"Budget config file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise BudgetConfigError(f"Failed to parse YAML config {path}: {exc}") from exc

    if data is None:
        return {"budgets": {}}

    if not isinstance(data, dict):
        raise BudgetConfigError(
            f"Budget config must be a YAML mapping at {path}, got {type(data).__name__}"
        )

    return data


def validate_budget_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate the parsed budget config structure and values.

    Checks:
        - Top-level ``budgets`` key is a dict.
        - Each provider entry is a dict.
        - ``period`` is a valid ``BudgetPeriod`` value.
        - Percentage fields (``warning_percent``, ``hard_stop_percent``,
          ``reserve_percent``) are integers in [0, 100].
        - ``paid_fallback`` is a bool (must be False per PRD §9).

    Args:
        config: Parsed config dict (with top-level ``budgets`` key).

    Returns:
        The validated config dict (unchanged if valid).

    Raises:
        BudgetConfigError: If any validation constraint is violated.
    """
    budgets = config.get("budgets", {})

    if budgets is None:
        return config

    if not isinstance(budgets, dict):
        raise BudgetConfigError(f"'budgets' must be a mapping, got {type(budgets).__name__}")

    for name, entry in budgets.items():
        if not isinstance(entry, dict):
            raise BudgetConfigError(
                f"Budget entry for '{name}' must be a mapping, got {type(entry).__name__}"
            )

        period = entry.get("period", "provider-defined")
        if period not in {bp.value for bp in BudgetPeriod}:
            valid_periods = [bp.value for bp in BudgetPeriod]
            raise BudgetConfigError(
                f"Invalid period '{period}' for provider '{name}'. Must be one of: {valid_periods}"
            )

        for pct_field in ("warning_percent", "hard_stop_percent", "reserve_percent"):
            if pct_field in entry:
                value = entry[pct_field]
                if not isinstance(value, int) or isinstance(value, bool):
                    raise BudgetConfigError(
                        f"'{pct_field}' for provider '{name}' must be an integer, "
                        f"got {type(value).__name__}"
                    )
                if value < 0 or value > 100:
                    raise BudgetConfigError(
                        f"'{pct_field}' for provider '{name}' must be in [0, 100], got {value}"
                    )

        if "paid_fallback" in entry:
            value = entry["paid_fallback"]
            if not isinstance(value, bool):
                raise BudgetConfigError(
                    f"'paid_fallback' for provider '{name}' must be a boolean, "
                    f"got {type(value).__name__}"
                )

    return config


def get_budget_settings(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the budget config from a YAML file.

    Convenience function that loads the YAML, validates it, and returns
    the parsed dict ready for ``load_budgets_from_config``.

    Args:
        config_path: Optional path override; defaults to ``AppSettings.budget_config``.

    Returns:
        Validated config dict with ``budgets`` key.
    """
    if config_path is None:
        settings = AppSettings()
        config_path = settings.budget_config

    config = load_budget_yaml(config_path)
    return validate_budget_config(config)


def get_settings() -> AppSettings:
    """Load application settings from environment variables.

    Returns a cached-style singleton per process (pydantic-settings itself
    reads env at instantiation).
    """
    return AppSettings()
