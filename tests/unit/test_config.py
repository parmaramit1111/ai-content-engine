"""Unit tests for the configuration system.

Covers:
- AppSettings: env var loading, defaults, validation
- load_budget_yaml: file loading, YAML parsing
- validate_budget_config: percentage bounds, period validation, paid_fallback type checking
- get_budget_settings: end-to-end YAML loading + validation
- Integration: config -> load_budgets_from_config -> BudgetTracker
"""

import os

import pytest
from pydantic import ValidationError

from content_engine.budgets.models import BudgetPeriod, BudgetStatus
from content_engine.budgets.tracker import BudgetTracker, load_budgets_from_config
from content_engine.config import (
    AppSettings,
    BudgetConfigError,
    get_budget_settings,
    load_budget_yaml,
    validate_budget_config,
)

# --- AppSettings tests ---


class TestAppSettings:
    def test_defaults(self):
        settings = AppSettings()
        assert settings.env == "development"
        assert settings.gemini_api_key is None
        assert settings.asset_root == "./assets"
        assert settings.config_root == "./config"
        assert settings.budget_config == "./config/budgets.yaml"

    def test_env_var_override(self):
        old = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "test-key-123"
        try:
            settings = AppSettings()
            assert settings.gemini_api_key == "test-key-123"
        finally:
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old
            else:
                os.environ.pop("GEMINI_API_KEY", None)

    def test_invalid_env_rejected(self):
        with pytest.raises(ValidationError):
            AppSettings(env="invalid_env")

    def test_valid_env_values(self):
        for valid in ("development", "staging", "production"):
            settings = AppSettings(env=valid)
            assert settings.env == valid


# --- load_budget_yaml tests ---


class TestLoadBudgetYaml:
    def test_loads_valid_yaml(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text("budgets:\n  flow:\n    period: daily\n    local_budget: 50\n")
        data = load_budget_yaml(config_file)
        assert "budgets" in data
        assert "flow" in data["budgets"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(BudgetConfigError, match="not found"):
            load_budget_yaml(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text("budgets:\n  - invalid: [unclosed")

        with pytest.raises(BudgetConfigError, match="Failed to parse YAML"):
            load_budget_yaml(config_file)

    def test_empty_file_returns_empty_budgets(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text("")
        data = load_budget_yaml(config_file)
        assert data == {"budgets": {}}

    def test_non_dict_yaml_raises(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text("- just\n- a\n- list")

        with pytest.raises(BudgetConfigError, match="must be a YAML mapping"):
            load_budget_yaml(config_file)


# --- validate_budget_config tests ---


class TestValidateBudgetConfig:
    def test_valid_config_passes(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "warning_percent": 80,
                    "hard_stop_percent": 100,
                    "reserve_percent": 20,
                }
            }
        }
        result = validate_budget_config(config)
        assert result is config

    def test_empty_budgets_passes(self):
        result = validate_budget_config({"budgets": {}})
        assert result == {"budgets": {}}

    def test_none_budgets_passes(self):
        result = validate_budget_config({"budgets": None})
        assert result == {"budgets": None}

    def test_missing_budgets_key_passes(self):
        result = validate_budget_config({"other": "stuff"})
        assert "budgets" not in result

    def test_budgets_not_dict_raises(self):
        with pytest.raises(BudgetConfigError, match="must be a mapping"):
            validate_budget_config({"budgets": [1, 2, 3]})

    def test_provider_entry_not_dict_raises(self):
        with pytest.raises(BudgetConfigError, match="must be a mapping"):
            validate_budget_config({"budgets": {"flow": "not a dict"}})

    def test_invalid_period_raises(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "weekly",
                    "local_budget": 50,
                }
            }
        }
        with pytest.raises(BudgetConfigError, match="Invalid period"):
            validate_budget_config(config)

    def test_default_period_is_valid(self):
        config = {"budgets": {"flow": {"local_budget": 50}}}
        result = validate_budget_config(config)
        assert result is config

    def test_warning_percent_out_of_range(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "warning_percent": 101,
                }
            }
        }
        with pytest.raises(BudgetConfigError, match=r"must be in \[0, 100\]"):
            validate_budget_config(config)

    def test_warning_percent_negative(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "warning_percent": -1,
                }
            }
        }
        with pytest.raises(BudgetConfigError, match=r"must be in \[0, 100\]"):
            validate_budget_config(config)

    def test_hard_stop_percent_out_of_range(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "hard_stop_percent": 150,
                }
            }
        }
        with pytest.raises(BudgetConfigError, match=r"must be in \[0, 100\]"):
            validate_budget_config(config)

    def test_reserve_percent_out_of_range(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "reserve_percent": -5,
                }
            }
        }
        with pytest.raises(BudgetConfigError, match=r"must be in \[0, 100\]"):
            validate_budget_config(config)

    def test_warning_percent_boundary_values(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "warning_percent": 0,
                    "hard_stop_percent": 100,
                    "reserve_percent": 100,
                }
            }
        }
        result = validate_budget_config(config)
        assert result is config

    def test_paid_fallback_must_be_bool(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "paid_fallback": "yes",
                }
            }
        }
        with pytest.raises(BudgetConfigError, match="must be a boolean"):
            validate_budget_config(config)

    def test_warning_percent_must_be_int(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "warning_percent": "80",
                }
            }
        }
        with pytest.raises(BudgetConfigError, match="must be an integer"):
            validate_budget_config(config)

    def test_bool_rejected_as_percent(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 50,
                    "warning_percent": True,
                }
            }
        }
        with pytest.raises(BudgetConfigError, match="must be an integer"):
            validate_budget_config(config)


# --- get_budget_settings tests ---


class TestGetBudgetSettings:
    def test_loads_real_config(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text(
            "budgets:\n"
            "  flow:\n"
            "    period: daily\n"
            "    official_limit: 50\n"
            "    local_budget: 50\n"
            "    warning_percent: 80\n"
            "    hard_stop_percent: 100\n"
            "    reserve_percent: 20\n"
            "    reset: first_generation_plus_24h\n"
        )
        data = get_budget_settings(config_file)
        assert "flow" in data["budgets"]

    def test_validates_config(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text(
            "budgets:\n  flow:\n    period: daily\n    local_budget: 50\n    warning_percent: 150\n"
        )
        with pytest.raises(BudgetConfigError):
            get_budget_settings(config_file)


# --- Integration tests: config -> load_budgets_from_config -> BudgetTracker ---


class TestConfigIntegration:
    def test_config_yaml_loads_via_load_budgets_from_config(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text(
            "budgets:\n"
            "  flow:\n"
            "    period: daily\n"
            "    official_limit: 50\n"
            "    local_budget: 50\n"
            "    warning_percent: 80\n"
            "    hard_stop_percent: 100\n"
            "    reserve_percent: 20\n"
            "    reset: first_generation_plus_24h\n"
            "  notebooklm:\n"
            "    period: provider-defined\n"
            "    official_limit: null\n"
            "    local_budget: null\n"
            "    warning_percent: 80\n"
            "    hard_stop_percent: 100\n"
            "    reserve_percent: 20\n"
            "    paid_fallback: false\n"
        )
        config = get_budget_settings(config_file)
        budgets = load_budgets_from_config(config)
        assert "flow" in budgets
        assert "notebooklm" in budgets
        assert budgets["flow"].local_budget == 50
        assert budgets["notebooklm"].local_budget is None

    def test_config_yaml_with_tracker(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text(
            "budgets:\n"
            "  flow:\n"
            "    period: daily\n"
            "    official_limit: 50\n"
            "    local_budget: 50\n"
            "    warning_percent: 80\n"
            "    hard_stop_percent: 100\n"
            "    reserve_percent: 20\n"
            "    reset: first_generation_plus_24h\n"
        )
        config = get_budget_settings(config_file)
        budgets = load_budgets_from_config(config)
        tracker = BudgetTracker(budgets)

        result = tracker.check_allowance("flow", units=10)
        assert result.status == BudgetStatus.OK

        tracker.record_usage("flow", units=45, operation="generate")
        result = tracker.check_allowance("flow", units=10)
        assert result.status == BudgetStatus.HARD_STOP

    def test_gemini_dict_config_treated_as_manual(self, tmp_path):
        config_file = tmp_path / "budgets.yaml"
        config_file.write_text(
            "budgets:\n"
            "  gemini:\n"
            "    model: null\n"
            "    period: provider-defined\n"
            "    official_limit:\n"
            "      requests_per_day: null\n"
            "      tokens_per_day: null\n"
            "    local_budget:\n"
            "      requests_per_day: null\n"
            "      tokens_per_day: null\n"
            "    warning_percent: 80\n"
            "    hard_stop_percent: 100\n"
            "    reserve_percent: 20\n"
            "    paid_fallback: false\n"
        )
        config = get_budget_settings(config_file)
        budgets = load_budgets_from_config(config)
        gemini = budgets["gemini"]
        assert gemini.model is None
        assert gemini.period == BudgetPeriod.PROVIDER_DEFINED
        assert gemini.local_budget is None
        assert gemini.official_limit is None
