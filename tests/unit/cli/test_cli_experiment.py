"""CLI tests for `content experiment record/list/export-csv` (Phase 12C).

Covers: creation/update (upsert) semantics, production-side fields always
pulled fresh from WorkflowState, human-entered production time (never
derived from any timestamp), quality scores via flags and via a metrics
file, invalid quality scores rejected, CSV export as a derived-only
output, and no secret leakage.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from uuid import UUID, uuid4

from typer.testing import CliRunner

from content_engine.cli import app
from content_engine.storage import ContentStore

runner = CliRunner()


def _env(monkeypatch, tmp_path: Path) -> Path:
    content_root = tmp_path / "content"
    monkeypatch.setenv("CONTENT_ROOT", str(content_root))
    return content_root


def _extract(output: str, key: str) -> str:
    for line in output.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{key}= not found in output:\n{output}")


def _create_topic(content_root: Path) -> str:
    result = runner.invoke(
        app,
        [
            "topic",
            "create",
            "--title",
            "Why Database Indexes Make Queries Faster",
            "--category",
            "backend_engineering",
            "--audience",
            "backend engineers",
            "--difficulty",
            "intermediate",
            "--hook",
            "Why does one line of SQL make queries 100x faster?",
            "--content-root",
            str(content_root),
        ],
    )
    assert result.exit_code == 0, result.output
    return _extract(result.output, "topic_id")


class TestExperimentRecordCreate:
    def test_creates_record_with_defaults_from_topic_and_workflow(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        result = runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.title == "Why Database Indexes Make Queries Faster"
        assert record.category.value == "backend_engineering"
        assert record.regeneration_count == 0
        assert record.production_time_minutes is None

    def test_missing_topic_fails_clearly(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                str(uuid4()),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 1
        assert "Topic artifact not found" in result.output


class TestHumanEnteredProductionTime:
    def test_production_time_only_set_when_explicitly_given(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        no_time = runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )
        assert no_time.exit_code == 0, no_time.output
        store = ContentStore(content_root)
        assert store.load_experiment_record(UUID(topic_id)).production_time_minutes is None

        with_time = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--production-time-minutes",
                "42.5",
                "--content-root",
                str(content_root),
            ],
        )
        assert with_time.exit_code == 0, with_time.output
        record = store.load_experiment_record(UUID(topic_id))
        assert record.production_time_minutes == 42.5

    def test_production_time_never_derived_from_workflow_timestamps(self, tmp_path, monkeypatch):
        """Regardless of how much wall-clock time passes, nothing sets
        production_time_minutes unless a human explicitly supplies it."""
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        # Simulate a "completed" workflow (package create would normally set
        # completed_at) by directly manipulating WorkflowState the way the
        # CLI does internally, then confirm experiment record still leaves
        # production_time_minutes unset.
        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        from datetime import UTC, datetime, timedelta

        completed = state.model_copy(
            update={
                "started_at": datetime.now(UTC) - timedelta(hours=5),
                "completed_at": datetime.now(UTC),
            }
        )
        store.save_workflow_state(completed)

        result = runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )
        assert result.exit_code == 0, result.output

        record = store.load_experiment_record(UUID(topic_id))
        assert record.production_time_minutes is None


class TestExperimentRecordUpsert:
    def test_rerunning_updates_rather_than_duplicates(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--views",
                "100",
                "--content-root",
                str(content_root),
            ],
        )
        runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--likes",
                "10",
                "--content-root",
                str(content_root),
            ],
        )

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        # Both calls' fields persist — an update, not an overwrite/duplicate.
        assert record.views == 100
        assert record.likes == 10
        assert len(store.list_experiment_records()) == 1

    def test_production_fields_always_refreshed_from_workflow_state(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        updated_state = state.model_copy(
            update={"gemini_requests_used": 7, "flow_credits_used": 55, "brief_regenerations": 2}
        )
        store.save_workflow_state(updated_state)

        runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )

        record = store.load_experiment_record(UUID(topic_id))
        assert record.gemini_requests_used == 7
        assert record.flow_credits_used == 55
        assert record.regeneration_count == 2


class TestQualityScores:
    def test_quality_scores_via_flags(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--quality-accuracy",
                "5",
                "--quality-hook",
                "4",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.quality.accuracy == 5
        assert record.quality.hook == 4
        assert record.quality.clarity is None

    def test_quality_score_out_of_range_rejected(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--quality-accuracy",
                "9",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code != 0

    def test_metrics_file_sets_quality_and_audience_fields(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(
            json.dumps(
                {
                    "views": 500,
                    "likes": 40,
                    "quality": {"overall": 4, "pacing": 3},
                }
            )
        )

        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--metrics-file",
                str(metrics_file),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.views == 500
        assert record.likes == 40
        assert record.quality.overall == 4
        assert record.quality.pacing == 3

    def test_explicit_flag_overrides_metrics_file(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps({"views": 500}))

        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--metrics-file",
                str(metrics_file),
                "--views",
                "999",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.views == 999


class TestMetricsFileNullHandling:
    """Regression tests for the metrics-file None-overwrite fix.

    A metrics file is a partial update: an explicit ``null`` for a field
    means "not supplied here," not "clear this field." Previously,
    ``file_overrides``/``file_quality`` were merged without the same
    None-filtering already applied to ``flag_overrides``, so a metrics
    file listing an untouched field as ``null`` (e.g. from a hand-edited
    template) would silently wipe a previously-recorded value.
    """

    def test_top_level_null_does_not_overwrite_existing_value(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--views",
                "500",
                "--content-root",
                str(content_root),
            ],
        )

        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps({"likes": 10, "views": None}))
        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--metrics-file",
                str(metrics_file),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.views == 500
        assert record.likes == 10

    def test_nested_quality_null_does_not_overwrite_existing_value(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--quality-overall",
                "4",
                "--content-root",
                str(content_root),
            ],
        )

        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps({"quality": {"pacing": 3, "overall": None}}))
        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--metrics-file",
                str(metrics_file),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.quality.overall == 4
        assert record.quality.pacing == 3

    def test_non_null_metrics_file_values_still_update(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--views",
                "500",
                "--content-root",
                str(content_root),
            ],
        )

        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps({"views": 750, "quality": {"hook": 5}}))
        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--metrics-file",
                str(metrics_file),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.views == 750
        assert record.quality.hook == 5

    def test_explicit_flag_overrides_null_bearing_metrics_file(self, tmp_path, monkeypatch):
        """Explicit non-null flags still win, even when the metrics file
        lists that same field as null alongside other real values."""
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps({"views": None, "likes": 10}))
        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--metrics-file",
                str(metrics_file),
                "--views",
                "999",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.views == 999
        assert record.likes == 10


class TestIncrementalAiCostNotes:
    def test_no_monetary_cost_by_default(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.incremental_ai_cost_notes is None

    def test_cost_notes_are_free_text_not_a_number(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        result = runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--incremental-ai-cost-notes",
                "₹0 — free tier",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.incremental_ai_cost_notes == "₹0 — free tier"


class TestExperimentList:
    def test_lists_all_records(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )

        result = runner.invoke(app, ["experiment", "list", "--content-root", str(content_root)])
        assert result.exit_code == 0, result.output
        assert "Why Database Indexes Make Queries Faster" in result.output

    def test_empty_list(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        result = runner.invoke(app, ["experiment", "list", "--content-root", str(content_root)])
        assert result.exit_code == 0, result.output
        assert "No experiment records found." in result.output


class TestExperimentExportCsv:
    def test_export_writes_derived_csv(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        runner.invoke(
            app,
            [
                "experiment",
                "record",
                "--topic-id",
                topic_id,
                "--views",
                "321",
                "--quality-overall",
                "4",
                "--content-root",
                str(content_root),
            ],
        )

        output_csv = tmp_path / "export.csv"
        result = runner.invoke(
            app,
            [
                "experiment",
                "export-csv",
                "--output",
                str(output_csv),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "records_exported=1" in result.output

        with output_csv.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["topic_id"] == topic_id
        assert rows[0]["views"] == "321"
        assert rows[0]["quality_overall"] == "4"

    def test_export_is_derived_and_regenerable_not_source_of_truth(self, tmp_path, monkeypatch):
        """Deleting/corrupting the CSV must never affect the JSON records."""
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )

        output_csv = tmp_path / "export.csv"
        runner.invoke(
            app,
            [
                "experiment",
                "export-csv",
                "--output",
                str(output_csv),
                "--content-root",
                str(content_root),
            ],
        )
        output_csv.write_text("garbage, not a valid csv export at all")

        store = ContentStore(content_root)
        record = store.load_experiment_record(UUID(topic_id))
        assert record.title == "Why Database Indexes Make Queries Faster"

        # Re-exporting overwrites the corrupted file from the JSON source of truth.
        second = runner.invoke(
            app,
            [
                "experiment",
                "export-csv",
                "--output",
                str(output_csv),
                "--content-root",
                str(content_root),
            ],
        )
        assert second.exit_code == 0, second.output
        with output_csv.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["topic_id"] == topic_id


class TestNoSecretLeakage:
    def test_experiment_record_never_prints_gemini_api_key(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        monkeypatch.setenv("GEMINI_API_KEY", "sk-super-secret-value-should-never-leak")

        result = runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )
        assert result.exit_code == 0, result.output
        assert "sk-super-secret-value-should-never-leak" not in result.output

    def test_experiment_list_never_prints_gemini_api_key(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        runner.invoke(
            app,
            ["experiment", "record", "--topic-id", topic_id, "--content-root", str(content_root)],
        )
        monkeypatch.setenv("GEMINI_API_KEY", "sk-super-secret-value-should-never-leak")

        result = runner.invoke(app, ["experiment", "list", "--content-root", str(content_root)])
        assert result.exit_code == 0, result.output
        assert "sk-super-secret-value-should-never-leak" not in result.output
