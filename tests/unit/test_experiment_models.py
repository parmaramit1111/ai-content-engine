"""Unit tests for ExperimentRecord and QualityScores (Phase 12C).

Covers: minimal/full construction, required fields, quality score 1-5
bounds, audience-metric non-negative bounds, JSON round-trip, and that
nothing on these models computes/derives a value (they only validate what
is explicitly given).
"""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.enums import Category
from content_engine.domain.experiment import ExperimentRecord, QualityScores


def _make_record(**overrides) -> ExperimentRecord:
    defaults: dict = {
        "topic_id": uuid4(),
        "title": "Why Database Indexes Make Queries Faster",
        "category": Category.BACKEND_ENGINEERING,
    }
    defaults.update(overrides)
    return ExperimentRecord(**defaults)


class TestQualityScores:
    def test_defaults_to_all_none(self):
        scores = QualityScores()
        assert scores.accuracy is None
        assert scores.overall is None

    @pytest.mark.parametrize(
        "field",
        ["accuracy", "clarity", "hook", "visual_quality", "pacing", "originality", "overall"],
    )
    def test_accepts_1_to_5(self, field):
        scores = QualityScores(**{field: 3})
        assert getattr(scores, field) == 3

    @pytest.mark.parametrize("value", [0, 6, -1])
    def test_rejects_out_of_range(self, value):
        with pytest.raises(ValidationError):
            QualityScores(accuracy=value)


class TestExperimentRecordCreation:
    def test_minimal_creation_defaults(self):
        record = _make_record()

        assert record.production_id is None
        assert record.production_time_minutes is None
        assert record.regeneration_count == 0
        assert record.gemini_requests_used == 0
        assert record.gemini_tokens_used == 0
        assert record.flow_credits_used == 0
        assert record.incremental_ai_cost_notes is None
        assert record.publish_date is None
        assert record.views is None
        assert record.quality == QualityScores()
        assert record.notes is None

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            ExperimentRecord(topic_id=uuid4(), title="", category=Category.AI_ENGINEERING)

    def test_missing_topic_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            ExperimentRecord(title="x", category=Category.AI_ENGINEERING)

    def test_full_creation(self):
        record = _make_record(
            production_id=uuid4(),
            review_id=uuid4(),
            package_id=uuid4(),
            production_time_minutes=45.5,
            regeneration_count=3,
            gemini_requests_used=12,
            gemini_tokens_used=8000,
            flow_credits_used=90,
            incremental_ai_cost_notes="₹0 — free tier",
            publish_date=date(2026, 9, 20),
            views=1200,
            average_view_duration_seconds=18.4,
            percent_viewed=61.2,
            likes=80,
            comments=5,
            shares=3,
            subscribers_gained=-2,
            quality=QualityScores(accuracy=5, clarity=4, hook=5),
            notes="Hook landed well; pacing dragged mid-video",
        )
        assert record.production_time_minutes == 45.5
        assert record.subscribers_gained == -2
        assert record.quality.accuracy == 5


class TestExperimentRecordValidation:
    def test_negative_views_rejected(self):
        with pytest.raises(ValidationError):
            _make_record(views=-1)

    def test_percent_viewed_over_100_rejected(self):
        with pytest.raises(ValidationError):
            _make_record(percent_viewed=101)

    def test_negative_production_time_rejected(self):
        with pytest.raises(ValidationError):
            _make_record(production_time_minutes=-5)

    def test_subscribers_gained_may_be_negative(self):
        record = _make_record(subscribers_gained=-3)
        assert record.subscribers_gained == -3

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            ExperimentRecord(topic_id=uuid4(), title="x", category="not_a_category")


class TestExperimentRecordJSON:
    def test_json_round_trip(self):
        record = _make_record(
            production_time_minutes=30.0,
            publish_date=date(2026, 9, 20),
            quality=QualityScores(overall=4),
        )
        data = record.model_dump_json()
        restored = ExperimentRecord.model_validate_json(data)

        assert restored == record
        assert restored.publish_date == date(2026, 9, 20)
        assert restored.quality.overall == 4
